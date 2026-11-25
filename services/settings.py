from collections.abc import Mapping
from dataclasses import dataclass, field

from .events import EVENT_KEYS, Audience


@dataclass(frozen=True)
class Settings:
    ws_url: str
    account: str
    password: str = field(repr=False)
    targets: dict[Audience, tuple[str, ...]]
    enabled_events: frozenset[str]
    use_markdown: bool
    support_umo: tuple[str, ...] = ()

    @classmethod
    def from_config(cls, config: Mapping) -> "Settings":
        targets = {}
        for audience in ("public", "admin", "ops"):
            value = config.get(f"{audience}_umo", [])
            if isinstance(value, str):
                value = value.split(",")
            if not isinstance(value, (list, tuple)):
                value = []
            targets[audience] = tuple(
                dict.fromkeys(
                    item.strip()
                    for item in value
                    if isinstance(item, str) and item.strip()
                )
            )

        enabled = config.get("enabled_events")
        ws_url = config.get("ret2shell_ws_link")
        account = config.get("ret2shell_account")
        password = config.get("ret2shell_password")
        support_umo = config.get("support_umo")
        if isinstance(support_umo, str):
            support_umo = support_umo.split(",")
        if not isinstance(support_umo, (list, tuple)):
            support_umo = []
        return cls(
            ws_url=ws_url.strip() if isinstance(ws_url, str) else "",
            account=account.strip() if isinstance(account, str) else "",
            password=password if isinstance(password, str) else "",
            targets=targets,
            enabled_events=EVENT_KEYS.intersection(
                item for item in enabled if isinstance(item, str)
            )
            if isinstance(enabled, (list, tuple))
            else EVENT_KEYS,
            use_markdown=config.get("use_markdown") is True,
            support_umo=tuple(
                dict.fromkeys(
                    item.strip()
                    for item in support_umo
                    if isinstance(item, str) and item.strip()
                )
            ),
        )
