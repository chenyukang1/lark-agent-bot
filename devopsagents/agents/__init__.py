from .cursor import CursorAgent
from .claude_code import ClaudeCoodeAgent
from .base import BaseSubAgent
from devopsagents.config import DEFAULT_CONFIG


class SubAgentFactory:
    _agent_mapping = {
        "cursor": CursorAgent,
        "claude": ClaudeCoodeAgent,
    }

    _agent_instances = {}

    @classmethod
    def get_sub_agent(cls) -> BaseSubAgent:
        agent_type = DEFAULT_CONFIG["sub_agent"] or "cursor"
        if agent_type not in cls._agent_instances:
            agent_class = cls._agent_mapping.get(agent_type)
            if not agent_class:
                raise ValueError(f"Unsupported agent type: {agent_type}")
            cls._agent_instances[agent_type] = agent_class()

        return cls._agent_instances[agent_type]
