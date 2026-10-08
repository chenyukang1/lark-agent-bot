"""Lark Agent Bot application modules."""

from threading import Lock

from app.lark.client import LarkClient

_client: LarkClient | None = None
_lock = Lock()


def get_lark_client() -> LarkClient:
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                _client = LarkClient()
    return _client
