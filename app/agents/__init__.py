"""Lark Agent Bot application modules."""

from collections.abc import Callable
from threading import Lock

from app.agents.code_review.ddl_notice import DDLNoticeAgent
from app.agents.devops.v1.agent import DevopsAgentV1
from app.agents.devops.v2.agent import DevopsAgentV2


class _LazyAgent:
    """Delay service configuration and client setup until an agent is used."""

    def __init__(self, factory: Callable[[], object]) -> None:
        self._factory = factory
        self._instance: object | None = None
        self._lock = Lock()

    def __getattr__(self, name: str):
        if self._instance is None:
            with self._lock:
                if self._instance is None:
                    self._instance = self._factory()
        return getattr(self._instance, name)


devopsAgentV1 = _LazyAgent(DevopsAgentV1)
devopsAgentV2 = _LazyAgent(DevopsAgentV2)
ddl_notice_agent = _LazyAgent(DDLNoticeAgent)
