from astrbot.api import AstrBotConfig, logger
from astrbot.api.star import Context, Star, StarTools

from .api import Ret2ShellAPI
from .commands import register_commands
from .services.broadcast import BroadcastService
from .services.settings import Settings
from .services.support import SupportService


class Ret2ShellPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.settings = Settings.from_config(config or {})
        self.api = Ret2ShellAPI(self.settings)
        self.broadcast = BroadcastService(context, self.api, self.settings)
        self.support = SupportService(context, self.settings.support_umo)

    async def initialize(self) -> None:
        data_dir = None
        try:
            data_dir = StarTools.get_data_dir()
        except (RuntimeError, ValueError) as exc:
            logger.warning("Ret2Shell plugin data directory is unavailable: %s", exc)
        if data_dir is not None:
            self.support.directory = data_dir / "support_tickets"

        if not self.api.ready:
            logger.info("Ret2Shell needs a WebSocket URL with a valid game_id.")
            return

        state_path = None
        if data_dir is not None and self.broadcast.notifications.enabled:
            state_path = data_dir / "notification_state.json"
        self.broadcast.start(state_path)

    async def terminate(self) -> None:
        self.support.stop()
        await self.broadcast.stop()
        await self.api.close()


register_commands(__name__)
