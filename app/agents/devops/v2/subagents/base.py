from abc import ABC, abstractmethod
from typing import ClassVar

from app.config import get_config

from .claude import ClaudeCodeAgent
from .cursor import CursorAgent


class BaseSubAgent(ABC):
    @abstractmethod
    async def run(self, work_dir: str, prompt: str) -> str:
        pass


class SubAgentFactory:
    __agent_mapping: ClassVar[dict[str, type[BaseSubAgent]]] = {
        "cursor": CursorAgent,
        "claude": ClaudeCodeAgent,
    }
    _agent_instances: ClassVar[dict[str, BaseSubAgent]] = {}

    @classmethod
    def get_sub_agent(cls) -> BaseSubAgent:
        agent_type = get_config()["sub_agent"] or "cursor"
        if agent_type not in cls._agent_instances:
            agent_class = cls.__agent_mapping.get(agent_type)
            if not agent_class:
                raise ValueError(f"Unsupported agent type: {agent_type}")
            cls._agent_instances[agent_type] = agent_class()

        return cls._agent_instances[agent_type]
