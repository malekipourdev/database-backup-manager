"""A small client for the Telegram Bot API, which Bale's bot API also implements."""

import logging
from pathlib import Path
from typing import Any

import httpx

from mbp.logging import register_secret

logger = logging.getLogger(__name__)

DEFAULT_BASE_URLS = {
    "bale": "https://tapi.bale.ai",
    "telegram": "https://api.telegram.org",
}
# Long polling: the server holds getUpdates open this long when there is nothing new.
POLL_TIMEOUT_SECONDS = 25
MAX_DETAIL = 300

# Every request URL contains the token; keep httpx's per-request INFO logs out of the logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

Keyboard = list[list[dict[str, str]]]


class BotApiError(Exception):
    """A Bot API call failed. `message` never contains the token."""

    def __init__(self, code: str, message: str | None = None, status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.status = status


class BotApi:
    def __init__(
        self,
        platform: str,
        token: str,
        *,
        base_url: str = "",
        proxy: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.platform = platform
        self._token = token
        register_secret(token)
        base = (base_url or DEFAULT_BASE_URLS[platform]).rstrip("/")
        self._base = f"{base}/bot{token}/"
        self._client = httpx.Client(
            timeout=httpx.Timeout(30.0, read=POLL_TIMEOUT_SECONDS + 15),
            proxy=proxy or None,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _sanitize(self, text: str) -> str:
        return text.replace(self._token, "***")[:MAX_DETAIL]

    def call(self, method: str, data: dict[str, Any] | None = None, files=None) -> Any:
        try:
            if files:
                response = self._client.post(self._base + method, data=data, files=files)
            else:
                response = self._client.post(self._base + method, json=data or {})
        except httpx.TimeoutException as exc:
            raise BotApiError("timeout", self._sanitize(type(exc).__name__)) from None
        except httpx.HTTPError as exc:
            raise BotApiError(
                "unreachable", self._sanitize(f"{type(exc).__name__}: {exc}")
            ) from None
        try:
            body = response.json()
        except ValueError:
            raise BotApiError(
                "bad_response", f"HTTP {response.status_code}", response.status_code
            ) from None
        if not body.get("ok"):
            status = body.get("error_code") or response.status_code
            description = self._sanitize(str(body.get("description") or ""))
            code = "unauthorized" if status in (401, 404) else "api_error"
            raise BotApiError(code, description, status)
        return body.get("result")

    # --- methods ---

    def get_me(self) -> dict:
        return self.call("getMe")

    def get_updates(self, offset: int | None, timeout: int = POLL_TIMEOUT_SECONDS) -> list[dict]:
        data: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            data["offset"] = offset
        return self.call("getUpdates", data) or []

    def send_message(self, chat_id: int, text: str, keyboard: Keyboard | None = None) -> dict:
        data: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if keyboard is not None:
            data["reply_markup"] = {"inline_keyboard": keyboard}
        return self.call("sendMessage", data)

    def edit_message(
        self, chat_id: int, message_id: int, text: str, keyboard: Keyboard | None = None
    ) -> None:
        data: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if keyboard is not None:
            data["reply_markup"] = {"inline_keyboard": keyboard}
        try:
            self.call("editMessageText", data)
        except BotApiError as exc:
            # Editing to identical content is an error on Telegram; nothing to do then.
            if "not modified" not in (exc.message or ""):
                raise

    def set_commands(self, commands: list[tuple[str, str]], language: str | None = None) -> None:
        """The command menu shown next to the message box; `language`: for users of it only."""
        data: dict[str, Any] = {
            "commands": [{"command": name, "description": text} for name, text in commands]
        }
        if language:
            data["language_code"] = language
        self.call("setMyCommands", data)

    def answer_callback(self, callback_id: str, text: str | None = None) -> None:
        data: dict[str, Any] = {"callback_query_id": callback_id}
        if text:
            data["text"] = text
        try:
            self.call("answerCallbackQuery", data)
        except BotApiError:
            # Only removes the button's loading state; never worth failing an action for.
            logger.debug("answerCallbackQuery failed", exc_info=True)

    def send_document(self, chat_id: int, path: Path, filename: str, caption: str) -> None:
        # httpx streams the file object in chunks while building the multipart body.
        with open(path, "rb") as handle:
            self.call(
                "sendDocument",
                data={"chat_id": str(chat_id), "caption": caption},
                files={"document": (filename, handle, "application/octet-stream")},
            )
