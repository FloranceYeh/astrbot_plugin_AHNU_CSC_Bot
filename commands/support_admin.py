import re
from typing import Any

from astrbot.api.event import AstrMessageEvent
from astrbot.api.event.filter import PermissionType, command, permission_type
from astrbot.api.message_components import Plain, Reply

from ..services.support import FORM_LABELS, MARKDOWN_SPECIAL, TICKET_ID
from .replies import format_fields, reply

PAGE_SIZE = 10
QUOTED_TICKET = re.compile(
    rf"^(?:##[ \t]+)?收到新工单\s+(?:-[ \t]+)?(?:\*\*)?工单编号"
    rf"(?:\*\*)?[：:]\s*({TICKET_ID.pattern})(?=\s|$)",
    re.IGNORECASE,
)


async def list_support_tickets(plugin: Any, event: AstrMessageEvent, page: str = "1"):
    markdown = plugin.settings.use_markdown
    try:
        page_number = int(page)
        if page_number < 1:
            raise ValueError
    except ValueError:
        yield reply(
            event, "用法：/support_list [页码]，页码从 1 开始。", markdown, stop=True
        )
        return

    try:
        tickets = plugin.support.list_tickets()
    except OSError:
        yield reply(event, "暂时无法读取工单。", markdown, stop=True)
        return
    if not tickets:
        yield reply(event, "暂无工单。", markdown, stop=True)
        return

    page_count = (len(tickets) + PAGE_SIZE - 1) // PAGE_SIZE
    if page_number > page_count:
        yield reply(event, f"页码超出范围，共 {page_count} 页。", markdown, stop=True)
        return
    start = (page_number - 1) * PAGE_SIZE
    fields = []
    for ticket in tickets[start : start + PAGE_SIZE]:
        title = " ".join(ticket["title"].split())
        if len(title) > 60:
            title = title[:59] + "…"
        if markdown:
            title = MARKDOWN_SPECIAL.sub(r"\\\1", title)
        fields.append((ticket["id"], f"[{_status(ticket)}] {title}"))
    heading = f"工单列表 · 第 {page_number}/{page_count} 页 · 共 {len(tickets)} 张"
    yield reply(event, format_fields(heading, fields, markdown), markdown, stop=True)


async def show_support_ticket(
    plugin: Any, event: AstrMessageEvent, ticket_id: str = ""
):
    markdown = plugin.settings.use_markdown
    if not ticket_id:
        yield reply(event, "用法：/support_show 工单编号", markdown, stop=True)
        return
    try:
        ticket = plugin.support.get_ticket(ticket_id.lower())
    except OSError:
        yield reply(event, "暂时无法读取该工单。", markdown, stop=True)
        return
    if ticket is None:
        yield reply(event, "未找到该工单。", markdown, stop=True)
        return

    fields = [
        ("状态", _status(ticket)),
        ("提交时间", ticket["created_at"]),
        ("提交者", ticket.get("sender_name") or ticket.get("sender_id") or "未提供"),
        *(
            (label, ticket[key])
            for key, label in FORM_LABELS.items()
            if ticket.get(key)
        ),
    ]
    if ticket.get("resolution"):
        fields.extend(
            (
                ("处理时间", ticket.get("resolved_at", "")),
                ("处理结果", ticket["resolution"]),
            )
        )
    if markdown:
        fields = [
            (label, MARKDOWN_SPECIAL.sub(r"\\\1", value).replace("\n", "\n  "))
            for label, value in fields
        ]
    yield reply(
        event,
        format_fields(f"工单 {ticket['id']}", fields, markdown),
        markdown,
        stop=True,
    )


async def resolve_support_ticket(plugin: Any, event: AstrMessageEvent):
    markdown = plugin.settings.use_markdown
    command_parts = event.get_message_str().split(maxsplit=1)
    arguments = command_parts[1].strip() if len(command_parts) == 2 else ""
    result_parts = arguments.split(maxsplit=1)
    explicit_id = result_parts[0].lower() if result_parts else ""
    quoted_ids = set()
    for component in event.get_messages():
        if not isinstance(component, Reply):
            continue
        if component.sender_id not in (0, "0", None, "") and str(
            component.sender_id
        ) != str(event.get_self_id()):
            continue
        quoted_text = (
            component.message_str
            or component.text
            or "\n".join(
                part.text for part in (component.chain or ()) if isinstance(part, Plain)
            )
        )
        if match := QUOTED_TICKET.match(quoted_text.strip()):
            quoted_ids.add(match[1].lower())

    if len(quoted_ids) > 1:
        yield reply(event, "请只引用一条工单通知。", markdown, stop=True)
        return
    if quoted_ids:
        ticket_id = quoted_ids.pop()
        if TICKET_ID.fullmatch(explicit_id):
            if explicit_id != ticket_id:
                yield reply(
                    event, "命令中的工单编号与引用的通知不一致。", markdown, stop=True
                )
                return
            result = result_parts[1] if len(result_parts) == 2 else ""
        else:
            result = arguments
    elif TICKET_ID.fullmatch(explicit_id):
        ticket_id = explicit_id
        result = result_parts[1] if len(result_parts) == 2 else ""
    else:
        yield reply(
            event,
            "请引用工单通知并发送 /support_resolve 处理结果，"
            "或发送 /support_resolve 工单编号 处理结果。",
            markdown,
            stop=True,
        )
        return
    try:
        message = await plugin.support.resolve_ticket(
            ticket_id, result, resolved_by=event.get_sender_id(), markdown=markdown
        )
    except OSError:
        message = "暂时无法读取或保存工单，请稍后重试。"
    yield reply(event, message, markdown, stop=True)


def _status(ticket: dict) -> str:
    if ticket.get("notified_at"):
        return "已处理"
    if ticket.get("resolution"):
        return "待通知"
    return "待处理"


ADMIN_COMMANDS = {
    "support_list": (list_support_tickets, "分页查看工单"),
    "support_show": (show_support_ticket, "查看工单详情"),
    "support_resolve": (resolve_support_ticket, "引用工单通知或按编号处理工单"),
}


def register_support_admin(module_name: str) -> None:
    for name, (handler, description) in ADMIN_COMMANDS.items():
        handler.__module__ = module_name
        command(name, alias={f"/{name}"}, desc=description)(handler)
        permission_type(PermissionType.ADMIN)(handler)
