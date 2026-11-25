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

from ..services.support import FORM_DURATION_MINUTES, FORM_FIELD, form_template
from .replies import reply
from .support_admin import ADMIN_COMMANDS, register_support_admin


class SupportFormReplyFilter(CustomFilter):
    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        if not event.is_private_chat():
            return False
        text = event.get_message_str()
        first_word = text.lstrip().split(maxsplit=1)
        if first_word and first_word[0].removeprefix("/") in ADMIN_COMMANDS:
            return False
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
    command(
        "support",
        alias={"/support"},
        desc="私聊提交工单",
    )(start_support)
    custom_filter(SupportFormReplyFilter, priority=10)(receive_support_form)
    register_support_admin(module_name)


async def start_support(plugin: Any, event: AstrMessageEvent):
    markdown = plugin.settings.use_markdown
    private = event.is_private_chat()
    platform_name = event.get_platform_name()
    if not private and platform_name not in ("aiocqhttp", "qq_official"):
        yield reply(
            event,
            "请在与机器人的私聊中发送 /support 获取工单表单。",
            markdown,
            stop=True,
        )
        return

    sender_id = event.get_sender_id()
    reply_sender_id = sender_id
    if not private and platform_name == "qq_official":
        raw_message = event.message_obj.raw_message
        author = getattr(raw_message, "author", None)
        reply_sender_id = getattr(author, "user_openid", None)
    if not sender_id or plugin.support.directory is None:
        yield reply(event, "工单服务暂时不可用，请稍后重试。", markdown, stop=True)
        return
    if not isinstance(reply_sender_id, str) or not reply_sender_id:
        yield reply(
            event,
            "请打开与机器人的私聊，发送 /support 获取工单表单。",
            markdown,
            stop=True,
        )
        return

    title = "**赛事工单**" if markdown else "赛事工单"
    instructions = (
        "填写表格后一次发回。表格内换行可用 `<br>`。"
        if markdown
        else "在冒号后填写内容，然后一次发回。"
    )
    delivery_note = (
        "提交后会转交人工处理并返回工单id。\n\n" if plugin.settings.support_umo else ""
    )
    form = (
        f"{title}\n\n请在 {FORM_DURATION_MINUTES} 分钟内通过私聊提交。{instructions}\n"
        "也可以回复两行，第一行为标题，第二行为描述。队伍 ID、平台 ID 和学号可选填。\n\n"
        f"{delivery_note}{form_template(markdown)}"
    )
    reply_sender = (event.get_platform_id(), reply_sender_id)
    pending = plugin.support.expect_reply(reply_sender)
    if private:
        yield reply(event, form, markdown, stop=True)
        return

    sent = False
    try:
        if platform_name == "qq_official":
            sent = await plugin.support.reply_to_qq_group_message(
                event, reply_sender_id, form, markdown=markdown
            )
        else:
            private_umo = f"{event.get_platform_id()}:{MessageType.FRIEND_MESSAGE.value}:{sender_id}"
            sent = await plugin.context.send_message(
                private_umo, MessageChain().message(form).use_markdown(markdown)
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
    yield reply(event, message, markdown, stop=True)


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

    markdown = plugin.settings.use_markdown
    message = await plugin.support.submit(
        sender,
        event.get_message_str(),
        platform_name=platform_name,
        sender_name=sender_name,
        markdown=markdown,
        origin_umo=event.unified_msg_origin,
    )
    yield reply(event, message, markdown, stop=True)
