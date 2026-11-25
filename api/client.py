from urllib.parse import parse_qs, urlsplit

import httpx
from websockets.asyncio.client import connect

from astrbot.api import logger

from ..services.settings import Settings

UNAVAILABLE = 0


class Ret2ShellAPI:
    def __init__(self, settings: Settings):
        self._ws_url = settings.ws_url
        self._client: httpx.AsyncClient | None = None
        self.game_id = ""
        self.origin = ""
        self.has_credentials = False

        try:
            url = urlsplit(self._ws_url)
            game_id = parse_qs(url.query).get("game_id", [""])[0]
            url.port
        except ValueError:
            return
        if (
            url.scheme not in ("ws", "wss")
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or not (game_id.isascii() and game_id.isdecimal())
        ):
            return

        self.game_id = game_id
        scheme = "https" if url.scheme == "wss" else "http"
        self.origin = f"{scheme}://{url.netloc}"
        self.has_credentials = bool(settings.account and settings.password)
        if bool(settings.account) != bool(settings.password):
            logger.warning(
                "Ret2Shell requires both account and password for authenticated requests."
            )
        self._client = httpx.AsyncClient(
            base_url=f"{self.origin}/api/",
            auth=(settings.account, settings.password)
            if self.has_credentials
            else None,
            headers={"User-Agent": "astrbot-plugin-ahnu-csc-bot"},
            timeout=10.0,
        )

    @property
    def ready(self) -> bool:
        return self._client is not None

    def websocket(self) -> connect:
        return connect(self._ws_url)

    async def _get(
        self, path: str = "", *, params: dict[str, str | int] | None = None
    ) -> tuple[object, int]:
        if self._client is None:
            return None, UNAVAILABLE
        try:
            response = await self._client.get(
                f"game/{self.game_id}{path}", params=params
            )
            if response.status_code != 200:
                return None, response.status_code
            return response.json(), 200
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Ret2Shell API request failed (%s).", type(exc).__name__)
            return None, UNAVAILABLE

    async def game(self) -> tuple[object, int]:
        return await self._get()

    async def ranking(self) -> tuple[object, int]:
        return await self._get(
            "/team",
            params={
                "page": 1,
                "page_size": 10,
                "order": "score",
                "asc": "false",
                "min_state": 3,
            },
        )

    async def challenge(self, challenge_id: int) -> tuple[object, int]:
        return await self._get(f"/challenge/{challenge_id}")

    async def challenge_submissions(self, challenge_id: int) -> tuple[object, int]:
        return await self._get(f"/challenge/{challenge_id}/submit")

    async def team(self, team_id: int) -> tuple[object, int]:
        return await self._get(f"/team/{team_id}")

    async def team_rank(self, team_id: int) -> tuple[object, int]:
        return await self._get(f"/team/{team_id}/rank")

    async def notifications(self) -> tuple[object, int]:
        return await self._get("/notification")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
