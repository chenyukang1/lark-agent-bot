from abc import ABC, abstractmethod


class BaseSubAgent(ABC):
    @abstractmethod
    async def run(self, work_dir: str, prompt: str) -> str:
        pass
