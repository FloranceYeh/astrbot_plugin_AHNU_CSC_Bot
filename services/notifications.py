import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from astrbot.api import logger

from ..api import Ret2ShellAPI
from .events import Announcement

MAX_STARTUP_COMPENSATION = 10


class NotificationTracker:
    def __init__(
        self,
        api: Ret2ShellAPI,
        publish: Callable[[Announcement], Awaitable[None]],
        use_markdown: bool,
    ):
        self._api = api
        self._publish = publish
        self._use_markdown = use_markdown
        self.enabled = api.has_credentials
        self.state_path: Path | None = None
        self._seen_ids: set[int | str] = set()
        self._lock = asyncio.Lock()
        self._baseline_ready = False

    @property
    def baseline_ready(self) -> bool:
        return self._baseline_ready

    def load(self) -> None:
        if self.state_path is None:
            return
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "Ret2Shell notification state could not be read (%s).",
                type(exc).__name__,
            )
            return
        if (
            not isinstance(state, dict)
            or str(state.get("game_id")) != self._api.game_id
        ):
            return
        ids = state.get("seen_ids")
        if not isinstance(ids, list):
            return
        self._seen_ids = {
            item for item in ids if type(item) is int or isinstance(item, str)
        }
        self._baseline_ready = True

    async def _fetch(self) -> list[dict] | None:
        data, status = await self._api.notifications()
        if status != 200 or not isinstance(data, list):
            logger.warning(
                "Ret2Shell notification reconciliation failed (HTTP %s).", status
            )
            return None
        return [
            item
            for item in data
            if isinstance(item, dict) and type(item.get("id")) in (int, str)
        ]

    async def establish_baseline(self) -> bool:
        for delay in (0, 2, 5):
            if delay:
                await asyncio.sleep(delay)
            items = await self._fetch()
            if items is not None:
                self._seen_ids.update(item["id"] for item in items)
                self._baseline_ready = True
                self._save()
                logger.info("Ret2Shell notification baseline established.")
                return True
        logger.warning("Ret2Shell notification baseline is unavailable.")
        return False

    async def reconcile(self, startup: bool = False) -> None:
        if not self.enabled:
            return
        async with self._lock:
            items = await self._fetch()
            if items is None:
                return
            if not self._baseline_ready:
                self._seen_ids.update(item["id"] for item in items)
                self._baseline_ready = True
                self._save()
                return

            pending = [item for item in items if item["id"] not in self._seen_ids]
            pending.sort(
                key=lambda item: (
                    item.get("published_at")
                    if isinstance(item.get("published_at"), (int, float))
                    else 0
                )
            )
            if startup and len(pending) > MAX_STARTUP_COMPENSATION:
                logger.warning(
                    "Skipping %s missed Ret2Shell notifications after startup.",
                    len(pending),
                )
                self._seen_ids.update(item["id"] for item in items)
                self._save()
                return
            for item in pending:
                self._seen_ids.add(item["id"])
                title = item.get("title")
                if isinstance(title, str) and title:
                    name_data, name_status = await self._api.game()
                    name = (
                        name_data.get("name")
                        if name_status == 200 and isinstance(name_data, dict)
                        else "Ret2Shell 赛事"
                    )
                    await self._publish(
                        Announcement(
                            "new_notification",
                            "public",
                            f"**【{name}】**\n\n新通知：{title}"
                            if self._use_markdown
                            else f"【{name}】\n新通知：{title}",
                        )
                    )
            if pending:
                self._save()

    def _save(self) -> None:
        if self.state_path is None:
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.state_path.with_suffix(".tmp")
            temporary_path.write_text(
                json.dumps(
                    {
                        "game_id": self._api.game_id,
                        "saved_at": datetime.now().isoformat(timespec="seconds"),
                        "seen_ids": sorted(self._seen_ids, key=str),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            os.replace(temporary_path, self.state_path)
        except OSError as exc:
            logger.error(
                "Ret2Shell notification state could not be saved (%s).",
                type(exc).__name__,
            )
