from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.event.filter import PermissionType, command, permission_type

from ..api import UNAVAILABLE
from ..services.events import BLOODS, local_time, tag_name
from ..services.settings import Settings

COMMANDS: dict[str, tuple[str, ...]] = {
    "query_game": ("game",),
    "query_rank": ("rank",),
    "query_challenge": ("challenge",),
    "query_team": ("team",),
    "query_status": ("ret2shell_status",),
}


def register_commands(module_name: str) -> None:
    for method_name, names in COMMANDS.items():
        handler = globals()[method_name]
        handler.__module__ = module_name
        if method_name == "query_status":
            permission_type(PermissionType.ADMIN)(handler)
        for name in names:
            command(name)(handler)


def _result(
    event: AstrMessageEvent, text: str, settings: Settings
) -> MessageEventResult:
    result = event.plain_result(text)
    result.use_markdown(settings.use_markdown)
    return result


async def query_game(plugin: Any, event: AstrMessageEvent):
    data, status = await plugin.api.game()
    if status != 200 or not isinstance(data, dict):
        yield _result(event, _http_error(status), plugin.settings)
        return
    start = local_time(data.get("start_at"))
    end = local_time(data.get("end_at"))
    start_text = start.strftime("%Y/%m/%d %H:%M") if start else "未知"
    end_text = end.strftime("%Y/%m/%d %H:%M") if end else "未知"
    message = (
        f"## {data.get('name') or '未知赛事'}\n\n"
        f"**简介**：{data.get('brief') or '暂无'}  \n"
        f"**比赛时间**：{start_text} - {end_text}"
    )
    yield _result(event, message, plugin.settings)


async def query_rank(plugin: Any, event: AstrMessageEvent):
    data, status = await plugin.api.ranking()
    if status != 200 or not isinstance(data, list):
        yield _result(event, _http_error(status), plugin.settings)
        return
    teams = data[0] if data and isinstance(data[0], list) else []
    if not teams:
        yield _result(event, "暂无队伍得分", plugin.settings)
        return
    lines = ["## 积分排行"]
    for position, team in enumerate(teams, start=1):
        if not isinstance(team, dict):
            continue
        place = BLOODS.get(position)
        label = f"**{place}**" if place else f"**{position}.**"
        lines.append(
            f"{label} {team.get('name') or '未知队伍'} · {team.get('score', 0)} pts"
        )
    yield _result(event, "\n\n".join(lines), plugin.settings)


async def query_challenge(plugin: Any, event: AstrMessageEvent):
    if not plugin.api.has_credentials:
        yield _result(
            event, "题目详情查询需要先配置 Ret2Shell 办赛账号。", plugin.settings
        )
        return
    try:
        challenge_id = int(event.message_str.split()[1])
    except (IndexError, ValueError):
        yield _result(event, "用法：/challenge 题目ID", plugin.settings)
        return
    if challenge_id <= 0:
        yield _result(event, "题目 ID 必须为正整数。", plugin.settings)
        return
    data, status = await plugin.api.challenge(challenge_id)
    if status != 200 or not isinstance(data, dict):
        yield _result(event, _http_error(status), plugin.settings)
        return
    if data.get("hidden"):
        yield _result(event, "该题目尚未公开。", plugin.settings)
        return
    submissions, submission_status = await plugin.api.challenge_submissions(
        challenge_id
    )
    solves = (
        submissions.get("solves", "未知")
        if submission_status == 200 and isinstance(submissions, dict)
        else "未知"
    )
    message = (
        f"## {data.get('name') or '未知题目'}\n\n"
        f"**方向**：{tag_name(data)}  \n"
        f"**当前分数**：{data.get('score', 0)} pts  \n"
        f"**已解出**：{solves}"
    )
    yield _result(event, message, plugin.settings)


async def query_team(plugin: Any, event: AstrMessageEvent):
    try:
        team_id = int(event.message_str.split()[1])
    except (IndexError, ValueError):
        yield _result(event, "用法：/team 队伍ID", plugin.settings)
        return
    if team_id <= 0:
        yield _result(event, "队伍 ID 必须为正整数。", plugin.settings)
        return
    data, status = await plugin.api.team(team_id)
    if status != 200 or not isinstance(data, dict):
        yield _result(event, _http_error(status), plugin.settings)
        return
    rank_data, rank_status = await plugin.api.team_rank(team_id)
    rank = rank_data if rank_status == 200 else "未知"
    fields = [f"## {data.get('name') or '未知队伍'}"]
    if data.get("tag") is not None:
        fields.append(f"**标签**：{data['tag']}")
    fields.extend((f"**积分**：{data.get('score', 0)} pts", f"**排名**：{rank}"))
    yield _result(event, "\n\n".join(fields), plugin.settings)


async def query_status(plugin: Any, event: AstrMessageEvent):
    settings: Settings = plugin.settings
    ws_status = "运行中" if plugin.broadcast.running else "已停止"
    game_start = _time_text(plugin.broadcast.game_start)
    game_end = _time_text(plugin.broadcast.game_end)
    state = plugin.broadcast.notifications.state_path
    state_status = "已持久化" if state else "仅保存在内存中"
    url_text = _safe_ws_url(settings.ws_url)
    lines = [
        "## Ret2Shell 播报状态",
        f"**WebSocket**：{ws_status}",
        f"**赛事 ID**：{plugin.api.game_id or '未解析'}",
        f"**WebSocket 地址**：{url_text}",
        f"**平台账号**：{'已配置' if plugin.api.has_credentials else '匿名访问'}",
        f"**通知补偿**：{'已启用' if plugin.api.has_credentials else '未配置账号'}",
        f"**通知记录**：{state_status}",
        f"**播报目标**：公开 {len(settings.targets['public'])} 个 · 管理 {len(settings.targets['admin'])} 个 · 运维 {len(settings.targets['ops'])} 个",
        f"**Markdown 回复**：{'启用' if settings.use_markdown else '纯文本'}",
        f"**比赛时间**：{game_start} - {game_end}",
    ]
    yield _result(event, "\n\n".join(lines), settings)


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
