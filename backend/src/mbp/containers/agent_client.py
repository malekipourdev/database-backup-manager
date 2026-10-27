"""The panel's client for an agent (see mbp.agent): the local one or another server's."""

import contextlib
import logging
import ssl
from collections.abc import Iterator

import httpx

from mbp.agent.tls import pinned_context
from mbp.api.errors import ApiError
from mbp.config import Settings
from mbp.security import agent_auth
from mbp.security.agent_token import agent_token

logger = logging.getLogger(__name__)

# Agent status codes that the panel passes on as they are; anything else becomes 502.
PASSED_ON = {403, 404, 503, 504}
# 401 codes an agent explains itself; any other 401 means the token is wrong.
UNAUTHORIZED_CODES = {"agent_clock_skew"}
# A dump may pause while the server works on a big table.
DUMP_READ_TIMEOUT = 600.0


class SignedAuth(httpx.Auth):
    """Signs every request for a remote agent (mbp.security.agent_auth)."""

    def __init__(self, token: str, cert_fp: str) -> None:
        self.token = token
        self.cert_fp = cert_fp

    def auth_flow(self, request: httpx.Request):
        request.headers["Authorization"] = agent_auth.sign(
            self.token, request.method, request.url.path, self.cert_fp
        )
        yield request


def url_host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def _transport_error(exc: httpx.TransportError) -> ApiError:
    if isinstance(exc, httpx.TimeoutException):
        return ApiError(504, "agent_timeout")
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, ssl.SSLCertVerificationError):
            # Another certificate than the pinned one: reinstalled agent, or someone between.
            return ApiError(502, "agent_cert_mismatch")
        cause = cause.__cause__ or cause.__context__
    if "CERTIFICATE_VERIFY_FAILED" in str(exc):
        return ApiError(502, "agent_cert_mismatch")
    return ApiError(503, "agent_unreachable")


class AgentClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        auth: httpx.Auth | None = None,
        verify: ssl.SSLContext | bool = True,
        timeout: float = 40.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout, verify=verify)
        self._auth = auth
        self._headers = {"Authorization": f"Bearer {token}"} if token and auth is None else {}

    @classmethod
    def from_settings(cls, settings: Settings) -> "AgentClient":
        return cls(
            settings.agent_url,
            agent_token(settings.encryption_key.get_secret_value()),
            timeout=settings.agent_timeout_seconds,
        )

    @classmethod
    def remote(
        cls, host: str, port: int, token: str, cert_pem: str, *, timeout: float = 40.0
    ) -> "AgentClient":
        """A client for another server's agent that trusts only its pinned certificate."""
        fp = agent_auth.fingerprint(ssl.PEM_cert_to_DER_cert(cert_pem))
        return cls(
            f"https://{url_host(host)}:{port}",
            auth=SignedAuth(token, fp),
            verify=pinned_context(cert_pem),
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _error(response: httpx.Response) -> ApiError:
        try:
            body = response.json()
        except ValueError:
            body = {}
        code = str(body.get("code") or "agent_error")
        if response.status_code == 401:
            # Never a 401 to the browser: that would look like the admin's session ended.
            logger.error("An agent refused the panel's token (%s)", code)
            return ApiError(502, code if code in UNAUTHORIZED_CODES else "agent_unauthorized")
        status = response.status_code if response.status_code in PASSED_ON else 502
        return ApiError(status, code, body.get("detail"))

    def _call(self, method: str, path: str, **kwargs) -> dict:
        if self._auth is not None:
            kwargs["auth"] = self._auth
        try:
            response = self._client.request(method, path, headers=self._headers, **kwargs)
        except httpx.TransportError as exc:
            raise _transport_error(exc) from exc
        if response.status_code < 400:
            return response.json()
        raise self._error(response)

    def hello(self, nonce: str) -> dict:
        return self._call("POST", "/v1/hello", json={"nonce": nonce})

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

    # --- deploys ---

    def deploy(self, payload: dict) -> str:
        return self._call("POST", "/v1/deploy", json=payload)["job_id"]

    def deploy_job(self, job_id: str, offset: int) -> dict:
        return self._call("GET", f"/v1/deploy/{job_id}", params={"offset": offset})

    def project_state(self, name: str) -> dict:
        return self._call("GET", f"/v1/projects/{name}/state")

    def project_remove(self, name: str, compose_file: str, down: bool) -> dict:
        return self._call(
            "POST",
            f"/v1/projects/{name}/remove",
            json={"compose_file": compose_file, "down": down},
        )

    # --- web servers ---

    def webservers(self) -> dict:
        try:
            return self._call("GET", "/v1/webservers")
        except ApiError as exc:
            # An agent from before web servers has no such route.
            if exc.status == 404 and exc.code == "agent_error":
                raise ApiError(409, "agent_outdated") from exc
            raise

    # --- databases on the agent's server ---

    def mysql_test(self, target: dict) -> dict:
        return self._call("POST", "/v1/mysql/test", json=target)

    def mysql_databases(self, target: dict) -> dict:
        return self._call("POST", "/v1/mysql/databases", json=target)

    @contextlib.contextmanager
    def dump_stream(self, payload: dict) -> Iterator[httpx.Response]:
        """The agent's framed dump stream (mbp.backups.frames); closing it stops the dump."""
        kwargs: dict = {"json": payload, "headers": self._headers}
        if self._auth is not None:
            kwargs["auth"] = self._auth
        timeout = httpx.Timeout(40.0, read=DUMP_READ_TIMEOUT)
        try:
            with self._client.stream(
                "POST", "/v1/mysql/dump", timeout=timeout, **kwargs
            ) as response:
                if response.status_code >= 400:
                    response.read()
                    raise self._error(response)
                yield response
        except httpx.TransportError as exc:
            raise _transport_error(exc) from exc
