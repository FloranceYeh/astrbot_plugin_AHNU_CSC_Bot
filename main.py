from astrbot.api import AstrBotConfig, logger
from astrbot.api.star import Context, Star, StarTools

from .api import Ret2ShellAPI
from .commands import register_commands
from .services.broadcast import BroadcastService
from .services.settings import Settings


class Ret2ShellPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.settings = Settings.from_config(config or {})
        self.api = Ret2ShellAPI(self.settings)
        self.broadcast = BroadcastService(context, self.api, self.settings)

    async def initialize(self) -> None:
        if not self.api.ready:
            logger.info("Ret2Shell needs a WebSocket URL with a valid game_id.")
            return

        state_path = None
        if self.broadcast.notifications.enabled:
            try:
                state_path = StarTools.get_data_dir() / "notification_state.json"
            except (RuntimeError, ValueError) as exc:
                logger.warning("Ret2Shell notification state is in-memory: %s", exc)
        self.broadcast.start(state_path)

    async def terminate(self) -> None:
        await self.broadcast.stop()
        await self.api.close()


register_commands(__name__)
