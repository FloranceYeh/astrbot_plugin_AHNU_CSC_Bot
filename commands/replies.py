from collections.abc import Iterable

from astrbot.api.event import AstrMessageEvent, MessageEventResult


def reply(
    event: AstrMessageEvent, text: str, markdown: bool, *, stop: bool = False
) -> MessageEventResult:
    result = event.plain_result(text).use_markdown(markdown)
    return result.stop_event() if stop else result


def format_fields(
    title: str, fields: Iterable[tuple[str, object]], markdown: bool
) -> str:
    if markdown:
        lines = "\n".join(f"- **{label}**：{value}" for label, value in fields)
        return f"## {title}\n\n{lines}"
    return "\n".join([title, *(f"{label}：{value}" for label, value in fields)])
