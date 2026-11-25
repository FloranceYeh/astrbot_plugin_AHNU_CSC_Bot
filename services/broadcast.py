import asyncio
import json
import time
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.star import Context

from ..api import Ret2ShellAPI
from .events import Announcement, parse_event
from .notifications import NotificationTracker
from .settings import Settings

RECONNECT_BASE_DELAY = 1.0
RECONNECT_MAX_DELAY = 60.0


class BroadcastService:
    def __init__(self, context: Context, api: Ret2ShellAPI, settings: Settings):
        self._context = context
        self._api = api
        self._settings = settings
        self.notifications = NotificationTracker(
            api, self._publish, settings.use_markdown
        )
        self.running = False
        self._ws_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._timers: set[asyncio.Task] = set()
        self.game_start: float | None = None
        self.game_end: float | None = None

    def start(self, state_path: Path | None) -> None:
        if self.running:
            return
        self.running = True
        self.notifications.state_path = state_path
        if self.notifications.enabled:
            self.notifications.load()
        self._ws_task = asyncio.create_task(self._run())
        if self.notifications.enabled:
            self._watchdog_task = asyncio.create_task(self._watchdog())

    async def _publish(self, announcement: Announcement) -> None:
        if announcement.key not in self._settings.enabled_events:
            return
        for target in self._settings.targets[announcement.audience]:
            chain = (
                MessageChain()
                .message(announcement.text)
                .use_markdown(self._settings.use_markdown)
            )
            try:
                await self._context.send_message(target, chain)
            except Exception as exc:
                logger.error(
                    "Ret2Shell announcement to %s failed (%s).",
                    target,
                    type(exc).__name__,
                )

    async def _schedule_game_times(self) -> None:
        data, status = await self._api.game()
        if not self.running or status != 200 or not isinstance(data, dict):
            return
        game_name = data.get("name")
        game_name = (
            game_name if isinstance(game_name, str) and game_name else "Ret2Shell 赛事"
        )
        for key, verb in (("start_at", "比赛已开始"), ("end_at", "比赛已结束")):
            timestamp = data.get(key)
            if not isinstance(timestamp, (int, float)):
                continue
            if key == "start_at":
                self.game_start = timestamp
            else:
                self.game_end = timestamp
            delay = timestamp - time.time()
            if delay <= 0:
                continue
            task = asyncio.create_task(
                self._delayed_announcement(delay, game_name, verb)
            )
            self._timers.add(task)
            task.add_done_callback(self._timers.discard)

    async def _delayed_announcement(
        self, delay: float, game_name: str, text: str
    ) -> None:
        await asyncio.sleep(delay)
        if self.running:
            await self._publish(
                Announcement(
                    text,
                    "public",
                    f"**{game_name} {text}**"
                    if self._settings.use_markdown
                    else f"{game_name} {text}",
                )
            )

    async def _run(self) -> None:
        backoff = RECONNECT_BASE_DELAY
        first_connection = True
        if self.notifications.enabled and not self.notifications.baseline_ready:
            await self.notifications.establish_baseline()
        elif self.notifications.enabled:
            await self.notifications.reconcile(startup=True)
        await self._schedule_game_times()
        while self.running:
            try:
                logger.info("Connecting to Ret2Shell WebSocket.")
                async with self._api.websocket() as websocket:
                    logger.info("Ret2Shell WebSocket connected.")
                    backoff = RECONNECT_BASE_DELAY
                    if not first_connection and self.notifications.enabled:
                        await self.notifications.reconcile()
                    first_connection = False
                    async for raw_message in websocket:
                        await self._handle_message(raw_message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Ret2Shell WebSocket disconnected (%s).", type(exc).__name__
                )
            if not self.running:
                return
            logger.info("Retrying the Ret2Shell WebSocket in %.0f seconds.", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, RECONNECT_MAX_DELAY)

    async def _handle_message(self, raw_message: str) -> None:
        try:
            envelope = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Ignoring an invalid Ret2Shell WebSocket event.")
            return

        announcement = parse_event(envelope)
        if announcement is None:
            return
        if announcement.key == "new_notification" and self.notifications.enabled:
            await self.notifications.reconcile()
            return
        if self._settings.use_markdown:
            announcement = Announcement(
                announcement.key,
                announcement.audience,
                f"**{announcement.text}**",
            )
        await self._publish(announcement)

    async def _watchdog(self) -> None:
        while self.running:
            await asyncio.sleep(60)
            if self.running:
                await self.notifications.reconcile()

    async def stop(self) -> None:
        self.running = False
        tasks = [
            task
            for task in (self._ws_task, self._watchdog_task, *self._timers)
            if task is not None and not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
