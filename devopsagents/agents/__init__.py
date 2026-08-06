from typing import ClassVar

from devopsagents.config import DEFAULT_CONFIG

from .base import BaseSubAgent
from .claude_code import ClaudeCoodeAgent
from .cursor import CursorAgent


class SubAgentFactory:
    __agent_mapping: ClassVar[dict[str, type[BaseSubAgent]]] = {
        "cursor": CursorAgent,
        "claude": ClaudeCoodeAgent,
    }
    _agent_instances: ClassVar[dict[str, BaseSubAgent]] = {}

    @classmethod
    def get_sub_agent(cls) -> BaseSubAgent:
        agent_type = DEFAULT_CONFIG["sub_agent"] or "cursor"
        if agent_type not in cls._agent_instances:
            agent_class = cls.__agent_mapping.get(agent_type)
            if not agent_class:
                raise ValueError(f"Unsupported agent type: {agent_type}")
            cls._agent_instances[agent_type] = agent_class()

        return cls._agent_instances[agent_type]
