import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.platform import MessageType
from astrbot.api.star import Context

FORM_DURATION_MINUTES = 15
TICKET_ID = re.compile(r"[0-9a-f]{32}", re.ASCII)
OPTIONAL_FIELDS = {
    "team_id": "队伍 ID",
    "ret2shell_platform_id": "平台 ID",
    "student_id": "学号",
}
FORM_LABELS = {"title": "工单标题", "description": "问题描述", **OPTIONAL_FIELDS}
FORM_KEYS = {label.replace(" ", ""): key for key, label in FORM_LABELS.items()}
FORM_TEMPLATE = "\n".join(
    [
        "| 字段 | 内容 |",
        "| --- | --- |",
        *[f"| {label} | |" for label in FORM_LABELS.values()],
    ]
)
PLAIN_FORM_TEMPLATE = "\n".join(f"{label}：" for label in FORM_LABELS.values())
FORM_FIELD = re.compile(
    r"^[^\S\r\n]*(?:[|｜][^\S\r\n]*)?"
    r"(工单标题|问题描述|队伍[^\S\r\n]*(?ai:ID)|平台[^\S\r\n]*(?ai:ID)|学号)"
    r"(?:[^\S\r\n]*(?P<separator>[:：|｜])[^\S\r\n]*|[^\S\r\n]+|(?=\r?$))",
    re.MULTILINE,
)
TABLE_CELL_END = re.compile(r"(?<!\\)((?:\\\\)*)[|｜]$")
TABLE_LINE_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)
MARKDOWN_SPECIAL = re.compile(r"([\\*_\x60~\[\]<>!&])")


def form_template(markdown: bool) -> str:
    return FORM_TEMPLATE if markdown else PLAIN_FORM_TEMPLATE


class SupportService:
    def __init__(self, context: Context, target_umos: tuple[str, ...]) -> None:
        self._context = context
        self._target_umos = target_umos
        self.directory: Path | None = None
        self._pending: dict[tuple[str, str], asyncio.TimerHandle] = {}
        self._sending_results: set[str] = set()

    def expect_reply(self, sender: tuple[str, str]) -> asyncio.TimerHandle:
        previous = self._pending.pop(sender, None)
        if previous is not None:
            previous.cancel()
        pending = asyncio.get_running_loop().call_later(
            FORM_DURATION_MINUTES * 60, self._pending.pop, sender, None
        )
        self._pending[sender] = pending
        return pending

    async def reply_to_qq_group_message(
        self, event: AstrMessageEvent, user_openid: str, text: str, *, markdown: bool
    ) -> bool:
        message_id = event.message_obj.message_id
        if not message_id:
            return False

        sdk = getattr(getattr(event, "bot", None), "api", None)
        send_c2c = getattr(sdk, "post_c2c_message", None)
        if send_c2c is None:
            return False

        response = await send_c2c(
            openid=user_openid,
            msg_id=message_id,
            msg_type=2 if markdown else 0,
            markdown={"content": text} if markdown else None,
            content=None if markdown else text,
        )
        return bool(
            response.get("id")
            if isinstance(response, dict)
            else getattr(response, "id", None)
        )

    def discard_reply(
        self, sender: tuple[str, str], pending: asyncio.TimerHandle
    ) -> None:
        if self._pending.get(sender) is pending:
            del self._pending[sender]
            pending.cancel()

    def has_pending_reply(self, sender: tuple[str, str]) -> bool:
        return sender in self._pending

    async def submit(
        self,
        sender: tuple[str, str],
        text: str,
        *,
        platform_name: str = "",
        sender_name: str = "",
        markdown: bool = False,
        origin_umo: str = "",
    ) -> str:
        pending = self._pending.get(sender)
        if pending is None:
            return "当前没有待填写的工单。请发送 /support 获取新表单。"
        if self.directory is None:
            return "工单服务暂时不可用，请稍后重试。"

        form = _parse_form(text)
        if form is None:
            return (
                "请一次发回工单标题和问题描述。可以填写表格、保留字段名，"
                "或直接发送两行（第一行标题，第二行描述）。"
                f"队伍 ID、平台 ID 和学号可选填。\n\n{form_template(markdown)}"
            )
        ticket_id = uuid4().hex
        ticket = {
            "id": ticket_id,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "platform_id": sender[0],
            "platform_name": platform_name,
            "sender_id": sender[1],
            "sender_name": sender_name,
            "origin_umo": origin_umo,
            **form,
        }
        try:
            self._save_ticket(self.directory / f"{ticket_id}.json", ticket)
        except OSError as exc:
            logger.error("Could not save support ticket (%s).", type(exc).__name__)
            return "暂时无法保存工单，请稍后重新发送表单。"

        self.discard_reply(sender, pending)
        if self._target_umos:
            await self._forward(ticket, markdown)
        return f"工单已收到\n工单编号：{ticket_id}"

    def list_tickets(self) -> list[dict]:
        if self.directory is None:
            raise OSError("Support ticket directory is unavailable")
        tickets = []
        for path in self.directory.glob("*.json"):
            try:
                if (ticket := self.get_ticket(path.stem)) is not None:
                    tickets.append(ticket)
            except OSError as exc:
                logger.warning(
                    "Could not read support ticket %s (%s).",
                    path.stem,
                    type(exc).__name__,
                )
        return sorted(
            tickets,
            key=lambda ticket: (ticket["created_at"], ticket["id"]),
            reverse=True,
        )

    def get_ticket(self, ticket_id: str) -> dict | None:
        if self.directory is None:
            raise OSError("Support ticket directory is unavailable")
        if not TICKET_ID.fullmatch(ticket_id):
            return None
        try:
            ticket = json.loads(
                (self.directory / f"{ticket_id}.json").read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            return None
        except ValueError as exc:
            raise OSError("Invalid support ticket JSON") from exc
        if (
            not isinstance(ticket, dict)
            or ticket.get("id") != ticket_id
            or not all(
                isinstance(ticket.get(key), str)
                for key in ("title", "description", "created_at")
            )
        ):
            raise OSError("Invalid support ticket record")
        return ticket

    @staticmethod
    def _save_ticket(path: Path, ticket: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(ticket, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary_path.replace(path)

    async def resolve_ticket(
        self, ticket_id: str, result: str, *, resolved_by: str, markdown: bool
    ) -> str:
        if self.directory is None:
            raise OSError("Support ticket directory is unavailable")
        if ticket_id in self._sending_results:
            return "该工单的处理结果正在发送，请稍后查看状态。"
        ticket = self.get_ticket(ticket_id)
        if ticket is None:
            return "未找到该工单。"
        if ticket.get("notified_at"):
            return "该工单已处理，结果已发送。"
        path = self.directory / f"{ticket_id}.json"
        if ticket.get("resolution"):
            if result and result != ticket["resolution"]:
                return "该工单已有处理结果。请仅发送 /support_resolve 工单编号，重发已保存的结果。"
        else:
            if not result:
                return "用法：/support_resolve 工单编号 处理结果"
            ticket.update(
                resolution=result,
                resolved_by=resolved_by,
                resolved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            self._save_ticket(path, ticket)

        origin = ticket.get("origin_umo")
        if not origin and ticket.get("platform_name") in (
            "aiocqhttp",
            "qq_official",
            "qq_official_webhook",
        ):
            if ticket.get("platform_id") and ticket.get("sender_id"):
                origin = f"{ticket['platform_id']}:{MessageType.FRIEND_MESSAGE.value}:{ticket['sender_id']}"
        if not origin:
            return "处理结果已保存。该工单缺少原会话地址。"

        self._sending_results.add(ticket_id)
        try:
            sent = await self._send_resolution(origin, ticket, markdown)
            if not sent:
                return (
                    "处理结果已保存，但发送失败。可用 /support_resolve 工单编号 重试。"
                )

            ticket["notified_at"] = datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            try:
                self._save_ticket(path, ticket)
            except OSError:
                logger.exception(
                    "Could not record delivery of support ticket %s.", ticket_id
                )
                return "处理结果已发送，通知状态写入失败。"
            return "工单已处理，结果已发送到提交会话。"
        finally:
            self._sending_results.discard(ticket_id)

    async def _send_resolution(self, origin: str, ticket: dict, markdown: bool) -> bool:
        result = ticket["resolution"]
        if markdown:
            result = MARKDOWN_SPECIAL.sub(r"\\\1", result)
            message = f"## 工单处理结果\n\n**工单编号**：{ticket['id']}\n\n{result}"
        else:
            message = f"工单处理结果\n工单编号：{ticket['id']}\n{result}"
        try:
            return await self._context.send_message(
                origin, MessageChain().message(message).use_markdown(markdown)
            )
        except Exception as exc:
            logger.warning(
                "Could not send result for support ticket %s (%s).",
                ticket["id"],
                type(exc).__name__,
            )
            return False

    async def _forward(self, ticket: dict[str, str], markdown: bool) -> None:
        id_label = {
            "aiocqhttp": "QQ 号",
            "qq_official": "QQ OpenID",
            "qq_official_webhook": "QQ OpenID",
        }.get(ticket.get("platform_name", ""), "用户 ID")
        nickname = " ".join(ticket.get("sender_name", "").split())
        fields = [
            ("工单编号", ticket["id"]),
            ("处理方式", "引用本条通知发送 /support_resolve 处理结果"),
            ("提交者昵称", nickname or "未提供"),
            (id_label, f"{ticket['sender_id']}（{ticket['platform_id']}）"),
            ("工单标题", ticket["title"]),
            *(
                (label, " ".join(ticket[key].split()))
                for key, label in OPTIONAL_FIELDS.items()
                if ticket.get(key)
            ),
            ("问题描述", ticket["description"]),
        ]
        lines = ["## 收到新工单\n" if markdown else "收到新工单"]
        for label, value in fields:
            if markdown:
                value = MARKDOWN_SPECIAL.sub(r"\\\1", value).replace("\n", "\n  ")
                lines.append(f"- **{label}**：{value}")
            else:
                lines.append(f"{label}：{value}")
        message = "\n".join(lines)
        results = await asyncio.gather(
            *(
                self._context.send_message(
                    target_umo, MessageChain().message(message).use_markdown(markdown)
                )
                for target_umo in self._target_umos
            ),
            return_exceptions=True,
        )
        for target_umo, result in zip(self._target_umos, results, strict=True):
            if result is not True:
                reason = (
                    type(result).__name__
                    if isinstance(result, BaseException)
                    else "no matching destination"
                )
                logger.warning(
                    "Could not forward support ticket %s to %s (%s).",
                    ticket["id"],
                    target_umo,
                    reason,
                )

    def stop(self) -> None:
        for pending in self._pending.values():
            pending.cancel()
        self._pending.clear()


def _parse_form(text: str) -> dict[str, str] | None:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    fields = list(FORM_FIELD.finditer(text))
    if not fields:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) == 2:
            return {"title": lines[0], "description": lines[1]}
        return None

    table_form = fields[0].group("separator") in ("|", "｜")
    fields = [
        field
        for field in fields
        if (field.group("separator") in ("|", "｜")) == table_form
    ]
    values = {}
    for index, field in enumerate(fields):
        key = FORM_KEYS["".join(field.group(1).split()).upper()]
        if key in values:
            return None
        end = fields[index + 1].start() if index + 1 < len(fields) else len(text)
        value = text[field.end() : end].strip()
        if table_form:
            lines = []
            # Keep pasted line breaks within a cell until its closing pipe.
            for line in value.split("\n"):
                if line.strip() in ("```", "~~~"):
                    break
                line, closed = TABLE_CELL_END.subn(r"\1", line.rstrip())
                lines.append(line)
                if closed:
                    break
            value = "\n".join(lines).replace(r"\|", "|")
            value = TABLE_LINE_BREAK.sub("\n", value)
        values[key] = value.strip()
    if not values.get("title") or not values.get("description"):
        return None
    return {key: value for key, value in values.items() if value}
