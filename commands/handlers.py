from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.event.filter import PermissionType, command, permission_type

from ..api import UNAVAILABLE
from ..services.events import BLOODS, local_time, tag_name
from ..services.settings import Settings
from .replies import format_fields, reply
from .support import register_support

COMMANDS = {
    "query_game": "game",
    "query_rank": "rank",
    "query_challenge": "challenge",
    "query_team": "team",
    "query_status": "ret2shell_status",
}


def register_commands(module_name: str) -> None:
    for method_name, name in COMMANDS.items():
        handler = globals()[method_name]
        handler.__module__ = module_name
        command(name, alias={f"/{name}"})(handler)
        if method_name == "query_status":
            permission_type(PermissionType.ADMIN)(handler)
    register_support(module_name)


async def query_game(plugin: Any, event: AstrMessageEvent):
    markdown = plugin.settings.use_markdown
    data, status = await plugin.api.game()
    if status != 200 or not isinstance(data, dict):
        yield reply(event, _http_error(status), markdown)
        return
    start = local_time(data.get("start_at"))
    end = local_time(data.get("end_at"))
    start_text = start.strftime("%Y/%m/%d %H:%M") if start else "未知"
    end_text = end.strftime("%Y/%m/%d %H:%M") if end else "未知"
    message = format_fields(
        data.get("name") or "未知赛事",
        [
            ("简介", data.get("brief") or "暂无"),
            ("比赛时间", f"{start_text} - {end_text}"),
        ],
        markdown,
    )
    yield reply(event, message, markdown)


async def query_rank(plugin: Any, event: AstrMessageEvent):
    markdown = plugin.settings.use_markdown
    data, status = await plugin.api.ranking()
    if status != 200 or not isinstance(data, list):
        yield reply(event, _http_error(status), markdown)
        return
    teams = data[0] if data and isinstance(data[0], list) else []
    if not teams:
        yield reply(event, "暂无队伍得分", markdown)
        return
    lines = []
    for position, team in enumerate(teams, start=1):
        if not isinstance(team, dict):
            continue
        place = BLOODS.get(position, f"第 {position} 名")
        lines.append(
            (place, f"{team.get('name') or '未知队伍'} · {team.get('score', 0)} pts")
        )
    yield reply(event, format_fields("积分排行", lines, markdown), markdown)


async def query_challenge(plugin: Any, event: AstrMessageEvent, challenge_id: str = ""):
    markdown = plugin.settings.use_markdown
    if not plugin.api.has_credentials:
        yield reply(event, "题目详情查询需要先配置 Ret2Shell 办赛账号。", markdown)
        return
    try:
        parsed_id = int(challenge_id)
    except ValueError:
        yield reply(event, "用法：/challenge 题目ID", markdown)
        return
    if parsed_id <= 0:
        yield reply(event, "题目 ID 必须为正整数。", markdown)
        return
    data, status = await plugin.api.challenge(parsed_id)
    if status != 200 or not isinstance(data, dict):
        yield reply(event, _http_error(status), markdown)
        return
    if data.get("hidden"):
        yield reply(event, "该题目尚未公开。", markdown)
        return
    submissions, submission_status = await plugin.api.challenge_submissions(parsed_id)
    solves = (
        submissions.get("solves", "未知")
        if submission_status == 200 and isinstance(submissions, dict)
        else "未知"
    )
    message = format_fields(
        data.get("name") or "未知题目",
        [
            ("方向", tag_name(data)),
            ("当前分数", f"{data.get('score', 0)} pts"),
            ("已解出", solves),
        ],
        markdown,
    )
    yield reply(event, message, markdown)


async def query_team(plugin: Any, event: AstrMessageEvent, team_id: str = ""):
    markdown = plugin.settings.use_markdown
    try:
        parsed_id = int(team_id)
    except ValueError:
        yield reply(event, "用法：/team 队伍ID", markdown)
        return
    if parsed_id <= 0:
        yield reply(event, "队伍 ID 必须为正整数。", markdown)
        return
    data, status = await plugin.api.team(parsed_id)
    if status != 200 or not isinstance(data, dict):
        yield reply(event, _http_error(status), markdown)
        return
    rank_data, rank_status = await plugin.api.team_rank(parsed_id)
    rank = rank_data if rank_status == 200 else "未知"
    fields = []
    if data.get("tag") is not None:
        fields.append(("标签", data["tag"]))
    fields.extend((("积分", f"{data.get('score', 0)} pts"), ("排名", rank)))
    yield reply(
        event, format_fields(data.get("name") or "未知队伍", fields, markdown), markdown
    )


async def query_status(plugin: Any, event: AstrMessageEvent):
    settings: Settings = plugin.settings
    ws_status = "运行中" if plugin.broadcast.running else "已停止"
    game_start = _time_text(plugin.broadcast.game_start)
    game_end = _time_text(plugin.broadcast.game_end)
    state = plugin.broadcast.notifications.state_path
    state_status = "已持久化" if state else "仅保存在内存中"
    url_text = _safe_ws_url(settings.ws_url)
    targets = " · ".join(
        f"{label} {len(settings.targets[key])} 个"
        for key, label in (("public", "公开"), ("admin", "管理"), ("ops", "运维"))
    )
    fields = [
        ("WebSocket", ws_status),
        ("赛事 ID", plugin.api.game_id or "未解析"),
        ("WebSocket 地址", url_text),
        ("平台账号", "已配置" if plugin.api.has_credentials else "匿名访问"),
        ("通知补偿", "已启用" if plugin.api.has_credentials else "未配置账号"),
        ("通知记录", state_status),
        ("播报目标", targets),
        ("Markdown 回复", "启用" if settings.use_markdown else "纯文本"),
        ("比赛时间", f"{game_start} - {game_end}"),
    ]
    yield reply(
        event,
        format_fields("Ret2Shell 播报状态", fields, settings.use_markdown),
        settings.use_markdown,
    )


def _safe_ws_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if parsed.query:
            query = urlencode(
                [
                    (key, value if key == "game_id" else "***")
                    for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                ],
                doseq=True,
            )
            return urlunsplit(parsed._replace(query=query))
    except ValueError:
        logger.debug("Ret2Shell WebSocket URL could not be displayed.")
    return url or "未配置"


def _time_text(timestamp: float | None) -> str:
    return (
        datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
        if timestamp
        else "未获取"
    )


def _http_error(status: int) -> str:
    return {
        UNAVAILABLE: "Ret2Shell API 暂时不可用，请检查 WebSocket 地址。",
        401: "平台登录失败，请检查 Ret2Shell 办赛账号和密码。",
        403: "权限不足，或赛事当前不允许访问该信息。",
        412: "比赛尚未开始。",
        404: "未找到该比赛、题目或队伍。",
        429: "请求过于频繁，请稍后重试。",
    }.get(status, f"Ret2Shell API 请求失败（HTTP {status}）。")
