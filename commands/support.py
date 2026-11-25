from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.event.filter import (
    CustomFilter,
    command,
    custom_filter,
)
from astrbot.api.platform import MessageType
from astrbot.core.star import star_map

from ..services.support import FORM_DURATION_MINUTES, FORM_FIELD, FORM_TEMPLATE


class SupportFormReplyFilter(CustomFilter):
    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        if not event.is_private_chat():
            return False
        text = event.get_message_str()
        if FORM_FIELD.search(text):
            return True
        if len(text.strip().splitlines()) < 2:
            return False

        metadata = star_map.get(receive_support_form.__module__)
        plugin = metadata.star_cls if metadata else None
        sender = (event.get_platform_id(), event.get_sender_id())
        return plugin is not None and plugin.support.has_pending_reply(sender)


def register_support(module_name: str) -> None:
    # AstrBot binds handlers to the Star instance by their registered module.
    start_support.__module__ = module_name
    receive_support_form.__module__ = module_name
    command("support", desc="私聊提交工单")(start_support)
    custom_filter(SupportFormReplyFilter, priority=10)(receive_support_form)


async def start_support(plugin: Any, event: AstrMessageEvent):
    markdown = plugin.settings.use_markdown
    private = event.is_private_chat()
    platform_name = event.get_platform_name()
    if not private and platform_name not in ("aiocqhttp", "qq_official"):
        yield (
            event.plain_result("请在与机器人的私聊中发送 /support 获取工单表单。")
            .use_markdown(markdown)
            .stop_event()
        )
        return

    sender_id = event.get_sender_id()
    reply_sender_id = sender_id
    if not private and platform_name == "qq_official":
        raw_message = event.message_obj.raw_message
        author = getattr(raw_message, "author", None)
        reply_sender_id = getattr(author, "user_openid", None)
    if not sender_id or plugin.support.directory is None:
        yield (
            event.plain_result("工单服务暂时不可用，请稍后重试。")
            .use_markdown(markdown)
            .stop_event()
        )
        return
    if not isinstance(reply_sender_id, str) or not reply_sender_id:
        yield (
            event.plain_result("请打开与机器人的私聊，发送 /support 获取工单表单。")
            .use_markdown(markdown)
            .stop_event()
        )
        return

    title = "**赛事工单**"
    delivery_note = (
        "提交后会转交人工处理并返回工单id。\n\n" if plugin.settings.support_umo else ""
    )
    form = (
        f"{title}\n\n请在 {FORM_DURATION_MINUTES} 分钟内私聊发回表格，"
        "或直接回复两行（第一行标题，第二行描述）。队伍 ID、平台 ID 和学号可选填。"
        "表格内换行可用 `<br>`。\n\n"
        f"{delivery_note}{FORM_TEMPLATE}"
    )
    reply_sender = (event.get_platform_id(), reply_sender_id)
    pending = plugin.support.expect_reply(reply_sender)
    if private:
        yield event.plain_result(form).use_markdown(True).stop_event()
        return

    sent = False
    try:
        if platform_name == "qq_official":
            sent = await plugin.support.reply_to_qq_group_message(
                event, reply_sender_id, form
            )
        else:
            private_umo = f"{event.get_platform_id()}:{MessageType.FRIEND_MESSAGE.value}:{sender_id}"
            sent = await plugin.context.send_message(
                private_umo, MessageChain().message(form).use_markdown(True)
            )
    except Exception as exc:
        logger.warning("Support form DM failed (%s).", type(exc).__name__)
    finally:
        if not sent:
            plugin.support.discard_reply(reply_sender, pending)

    message = (
        "工单表单已私聊发送，请在私聊中填写并回复。"
        if sent
        else "私聊发送失败，请在与机器人的私聊中发送 /support 获取工单表单。"
    )
    yield event.plain_result(message).use_markdown(markdown).stop_event()


async def receive_support_form(plugin: Any, event: AstrMessageEvent):
    sender = (event.get_platform_id(), event.get_sender_id())
    platform_name = event.get_platform_name()
    sender_name = event.get_sender_name().strip()
    if not sender_name and platform_name in ("qq_official", "qq_official_webhook"):
        # Some SDK versions expose only the OpenID on the parsed C2C author.
        raw_data = getattr(event.message_obj.raw_message, "raw_data", None)
        author = raw_data.get("author") if isinstance(raw_data, dict) else None
        username = author.get("username") if isinstance(author, dict) else None
        if isinstance(username, str):
            sender_name = username.strip()

    reply = await plugin.support.submit(
        sender,
        event.get_message_str(),
        platform_name=platform_name,
        sender_name=sender_name,
    )
    yield (
        event.plain_result(reply)
        .use_markdown(plugin.settings.use_markdown or FORM_TEMPLATE in reply)
        .stop_event()
    )
