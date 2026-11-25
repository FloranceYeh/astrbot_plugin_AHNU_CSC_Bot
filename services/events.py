from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Audience = Literal["public", "admin", "ops"]

CHALLENGE_EVENTS = {
    "up": ("challenge_up", "新题目上线"),
    "down": ("challenge_down", "题目下线"),
    "new_hint": ("new_hint", "发布新提示"),
}
BLOODS = {1: "一血", 2: "二血", 3: "三血"}
GAME_EVENTS = {"freeze": "比赛已冻结", "unfreeze": "比赛已解冻"}
OPS_EVENTS = {
    "cluster_overloaded": "集群超载",
    "cluster_recovered": "集群恢复",
    "server_panic": "服务崩溃",
}
EVENT_KEYS = frozenset(
    (
        *(key for key, _ in CHALLENGE_EVENTS.values()),
        *(f"blood_{place}" for place in BLOODS),
        "correct",
        "cheated",
        "too_quick",
        "chat_message",
        "new_notification",
        *GAME_EVENTS,
        *OPS_EVENTS,
    )
)


@dataclass(frozen=True)
class Announcement:
    key: str
    audience: Audience
    text: str


def tag_name(challenge: dict) -> str:
    tags = challenge.get("tag")
    if isinstance(tags, list) and tags and isinstance(tags[0], dict):
        return tags[0].get("name") or "未知"
    return "未知"


def local_time(timestamp: object) -> datetime | None:
    if not isinstance(timestamp, (int, float)) or not timestamp:
        return None
    try:
        return datetime.fromtimestamp(timestamp)
    except (ValueError, OverflowError, OSError):
        return None


def parse_event(envelope: object) -> Announcement | None:
    if not isinstance(envelope, dict):
        return None
    for kind in ("challenge", "submission", "game", "chat", "devops"):
        if kind in envelope:
            break
    else:
        return None
    data = envelope[kind]
    if not isinstance(data, dict) or not isinstance(
        event_type := data.get("event_type"), str
    ):
        return None

    if kind == "game":
        if event_type in GAME_EVENTS:
            return Announcement(event_type, "public", GAME_EVENTS[event_type])
        if event_type == "new_notification" and data.get("message"):
            return Announcement(event_type, "public", f"新通知：{data['message']}")
        return None
    if kind == "devops":
        if event_type in OPS_EVENTS:
            return Announcement(event_type, "ops", OPS_EVENTS[event_type])
        return None

    challenge = data.get("challenge")
    if not isinstance(challenge, dict):
        challenge = {}
    subject = f"[{tag_name(challenge)}] {challenge.get('name') or '未知题目'}"
    if kind == "challenge":
        if event_type in CHALLENGE_EVENTS:
            key, label = CHALLENGE_EVENTS[event_type]
            return Announcement(key, "public", f"{label}：{subject}")
        return None

    team = data.get("team")
    team_name = team.get("name") if isinstance(team, dict) else None
    team_name = team_name or "未知队伍"
    if kind == "chat":
        if event_type == "message":
            content = str(data.get("content") or "")[:200]
            return Announcement(
                "chat_message",
                "admin",
                f"{team_name} 对 {subject} 的反馈：\n{content}",
            )
        return None
    if event_type == "correct":
        blood = data.get("blood_state")
        if type(blood) is int and blood in BLOODS:
            key, audience = f"blood_{blood}", "public"
            text = f"恭喜 {team_name} 获得 {subject} {BLOODS[blood]}！"
        else:
            key, audience = "correct", "admin"
            text = f"{team_name} 解出了 {subject}"
        milestones = data.get("milestones")
        if isinstance(milestones, list):
            for item in milestones:
                if isinstance(item, dict) and item.get("name"):
                    text += f"\n{team_name} 达成里程碑：{item['name']}"
        return Announcement(key, audience, text)
    if event_type == "cheated":
        peer = data.get("peer_team")
        peer_name = peer.get("name") if isinstance(peer, dict) else None
        return Announcement(
            "cheated",
            "admin",
            f"检测到作弊：{team_name} 提交了 {peer_name or '其他队伍'} 的 {subject} Flag",
        )
    if event_type == "too_quick":
        return Announcement("too_quick", "admin", f"{team_name} 提交 {subject} 过快")
    return None
