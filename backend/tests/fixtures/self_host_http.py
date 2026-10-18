"""Closed synthetic Telegram/OpenAI HTTP boundary for owned Docker acceptance.

No forwarding, real account, message content log, or persistence. The proof's
internal network and strict closed operations are mandatory containment.
"""

import json
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "999999999:closed_spec043_bot_token"
KEY = "CLOSED-SPEC043-PROVIDER-CANARY"
MODEL = "closed-schema-model"
BOT = {
    "id": 71000001,
    "is_bot": True,
    "first_name": "Closed bot",
    "username": "closed_self_host_bot",
    "can_join_groups": True,
    "can_read_all_group_messages": False,
}


def update(identifier: int = 7001) -> dict:
    return {
        "update_id": identifier,
        "message": {
            "message_id": identifier - 6300,
            "date": int(time.time()),
            "chat": {"id": 72000001, "type": "private", "first_name": "Closed"},
            "from": {"id": 73000001, "is_bot": False, "first_name": "Closed"},
            "text": "Closed private fixture message",
        },
    }


class Boundary:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.pending = False
        self.counts: Counter = Counter()
        self.last_offset: int | None = None
        self.offset_history: list[int | None] = []

    def snapshot(self) -> dict:
        with self.condition:
            return {
                "counts": dict(self.counts),
                "last_offset": self.last_offset,
                "offset_history": list(self.offset_history[-20:]),
            }

    def dispatch(
        self, path: str, body: dict, authorization: str | None
    ) -> tuple[int, dict]:
        if path == "/proof/arm":
            with self.condition:
                self.pending = True
                self.condition.notify_all()
            return 200, {"armed": True}
        if path == "/v1/chat/completions":
            with self.condition:
                if (
                    authorization != f"Bearer {KEY}"
                    or body.get("model") != MODEL
                    or body.get("response_format", {}).get("type") != "json_schema"
                ):
                    self.counts["unexpected"] += 1
                    return 400, {"error": "closed fixture contract mismatch"}
                self.counts["generation"] += 1
            plan = {
                "should_respond": True,
                "reason_code": "answer",
                "text": "Closed fixture answer",
                "confidence": 1.0,
                "language": "en",
                "interaction": {"kind": "neutral"},
            }
            return 200, {
                "choices": [
                    {"message": {"content": json.dumps(plan)}, "finish_reason": "stop"}
                ],
                "usage": {
                    "prompt_tokens": 30,
                    "completion_tokens": 10,
                    "total_tokens": 40,
                },
            }
        prefix = f"/bot{TOKEN}/"
        if not path.startswith(prefix):
            with self.condition:
                self.counts["unexpected"] += 1
            return 404, {"error": "closed fixture operation unavailable"}
        operation = path.removeprefix(prefix)
        with self.condition:
            self.counts[operation] += 1
            if operation == "getMe":
                result = BOT
            elif operation == "getWebhookInfo":
                result = {"url": "", "pending_update_count": 0, "allowed_updates": []}
            elif operation == "getUpdates":
                self.last_offset = body.get("offset")
                self.offset_history.append(self.last_offset)
                self.condition.wait_for(lambda: self.pending, timeout=2)
                result = [update()] if self.pending else []
                if self.pending:
                    self.counts["polling_returned"] += 1
                    self.pending = False
            elif operation == "sendMessage":
                reply = body.get("reply_parameters", {}).get("message_id")
                # Stock adapter serializes platform IDs as strings; preserve
                # exact reply-target checking for both wire representations.
                if str(body.get("chat_id")) != "72000001" or str(reply) not in {
                    "701",
                    "702",
                }:
                    self.counts["unexpected"] += 1
                    return 400, {"ok": False, "error_code": 400}
                self.counts["reply_checked"] += 1
                result = {
                    "message_id": 9000 + self.counts[operation],
                    "chat": {"id": 72000001},
                    "from": BOT,
                    "date": int(time.time()),
                }
            elif operation == "getChatMember":
                result = {
                    "status": "member",
                    "user": {
                        "id": int(body["user_id"]),
                        "is_bot": False,
                        "first_name": "Closed",
                    },
                }
            elif operation in {"sendChatAction", "setMessageReaction"}:
                result = True
            else:
                self.counts["unexpected"] += 1
                return 404, {"ok": False, "error_code": 404}
        return 200, {"ok": True, "result": result}


BOUNDARY = Boundary()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_: object) -> None:
        # Bot API request paths contain even the fixture token; never log them.
        return

    def respond(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if self.path == "/proof/state":
            self.respond(200, BOUNDARY.snapshot())
        else:
            self.respond(404, {"error": "closed fixture operation unavailable"})

    def do_POST(self) -> None:
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 65536:
            self.respond(400, {"error": "closed fixture body rejected"})
            return
        body = json.loads(self.rfile.read(size))
        if not isinstance(body, dict):
            self.respond(400, {"error": "closed fixture body rejected"})
            return
        status, result = BOUNDARY.dispatch(
            self.path, body, self.headers.get("Authorization")
        )
        self.respond(status, result)


if __name__ == "__main__":
    # Container-only listener on an unpublished, externally isolated network.
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
