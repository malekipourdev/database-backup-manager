"""The backend's client for the Docker agent (see mbp.agent)."""

import logging

import httpx

from mbp.api.errors import ApiError
from mbp.config import Settings
from mbp.security.agent_token import agent_token

logger = logging.getLogger(__name__)

# Agent status codes that the panel passes on as they are; anything else becomes 502.
PASSED_ON = {403, 404, 503, 504}


class AgentClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 40.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)
        self._headers = {"Authorization": f"Bearer {token}"}

    @classmethod
    def from_settings(cls, settings: Settings) -> "AgentClient":
        return cls(
            settings.agent_url,
            agent_token(settings.encryption_key.get_secret_value()),
            timeout=settings.agent_timeout_seconds,
        )

    def close(self) -> None:
        self._client.close()

    def _call(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self._client.request(method, path, headers=self._headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise ApiError(504, "agent_timeout") from exc
        except httpx.TransportError as exc:
            raise ApiError(503, "agent_unreachable") from exc
        if response.status_code < 400:
            return response.json()
        try:
            body = response.json()
        except ValueError:
            body = {}
        code = str(body.get("code") or "agent_error")
        if response.status_code == 401:
            # Never a 401 to the browser: that would look like the admin's session ended.
            logger.error("The Docker agent refused the backend's token")
            raise ApiError(502, "agent_unauthorized")
        status = response.status_code if response.status_code in PASSED_ON else 502
        raise ApiError(status, code, body.get("detail"))

    def info(self) -> dict:
        return self._call("GET", "/v1/info")

    def containers(self) -> list[dict]:
        return self._call("GET", "/v1/containers")["containers"]

    def container(self, ref: str) -> dict:
        return self._call("GET", f"/v1/containers/{ref}")

    def container_stats(self, ref: str) -> dict | None:
        return self._call("GET", f"/v1/containers/{ref}/stats")["stats"]

    def stats(self) -> dict[str, dict | None]:
        return self._call("GET", "/v1/stats")["stats"]

    def logs(self, ref: str, tail: int) -> dict:
        return self._call("GET", f"/v1/containers/{ref}/logs", params={"tail": tail})

    def action(self, ref: str, action: str) -> dict:
        return self._call("POST", f"/v1/containers/{ref}/{action}")["container"]
