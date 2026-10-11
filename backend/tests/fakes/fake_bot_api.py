"""A minimal Telegram/Bale Bot API server for tests (real HTTP, in a thread).

Tests queue updates with `push_message` / `push_callback`; the bot under test fetches them
with getUpdates. Everything the bot sends is recorded in `sent`.
"""

import json
import threading
import time
from email.parser import BytesParser
from email.policy import default as default_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "123456:TEST-bot-token-xyz"


class FakeBotApi:
    def __init__(self) -> None:
        self.updates: list[dict] = []
        self.sent: list[tuple[str, dict]] = []
        self.next_update_id = 1
        self.next_message_id = 100
        self.lock = threading.Lock()
        self.fail_send_to: set[int] = set()
        handler = self._handler()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> "FakeBotApi":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def reset(self) -> None:
        with self.lock:
            self.updates.clear()
            self.sent.clear()
            self.fail_send_to.clear()

    # --- test helpers ---

    def push_message(self, user_id: int, text: str, chat_type: str = "private") -> None:
        with self.lock:
            self.updates.append(
                {
                    "update_id": self.next_update_id,
                    "message": {
                        "message_id": self.next_message_id,
                        "from": {"id": user_id, "first_name": "T"},
                        "chat": {"id": user_id, "type": chat_type},
                        "text": text,
                    },
                }
            )
            self.next_update_id += 1
            self.next_message_id += 1

    def push_callback(self, user_id: int, data: str, message_id: int = 1) -> None:
        with self.lock:
            self.updates.append(
                {
                    "update_id": self.next_update_id,
                    "callback_query": {
                        "id": f"cb{self.next_update_id}",
                        "from": {"id": user_id},
                        "data": data,
                        "message": {
                            "message_id": message_id,
                            "chat": {"id": user_id, "type": "private"},
                        },
                    },
                }
            )
            self.next_update_id += 1

    def calls(self, method: str) -> list[dict]:
        with self.lock:
            return [body for name, body in self.sent if name == method]

    # --- HTTP ---

    def _handler(self):
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # keep test output quiet
                pass

            def _reply(self, status: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:
                prefix = f"/bot{TOKEN}/"
                if not self.path.startswith(prefix):
                    self._reply(
                        401, {"ok": False, "error_code": 401, "description": "Unauthorized"}
                    )
                    return
                method = self.path[len(prefix) :]
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                ctype = self.headers.get("Content-Type", "")
                if ctype.startswith("multipart/form-data"):
                    message = BytesParser(policy=default_policy).parsebytes(
                        f"Content-Type: {ctype}\r\n\r\n".encode() + raw
                    )
                    body = {}
                    for part in message.iter_parts():
                        name = part.get_param("name", header="content-disposition")
                        if part.get_filename():
                            body[name] = {
                                "filename": part.get_filename(),
                                "size": len(part.get_payload(decode=True)),
                            }
                        else:
                            body[name] = part.get_content()
                else:
                    body = json.loads(raw or b"{}")
                if method == "getMe":
                    self._reply(200, {"ok": True, "result": {"id": 1, "username": "mbp_test_bot"}})
                    return
                if method == "getUpdates":
                    offset = body.get("offset") or 0
                    for _ in range(2):  # a short "long poll" keeps the bot from spinning
                        with api.lock:
                            result = [u for u in api.updates if u["update_id"] >= offset]
                            api.updates = result[:]
                        if result:
                            break
                        time.sleep(0.1)
                    self._reply(200, {"ok": True, "result": result})
                    return
                with api.lock:
                    api.sent.append((method, body))
                chat = body.get("chat_id")
                if chat is not None and int(chat) in api.fail_send_to:
                    self._reply(403, {"ok": False, "error_code": 403, "description": "blocked"})
                    return
                if method == "sendMessage":
                    with api.lock:
                        api.next_message_id += 1
                        mid = api.next_message_id
                    self._reply(200, {"ok": True, "result": {"message_id": mid}})
                    return
                self._reply(200, {"ok": True, "result": True})

        return Handler
