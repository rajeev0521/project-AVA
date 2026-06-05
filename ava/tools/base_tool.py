from abc import ABC, abstractmethod
from typing import Any, Dict

class BaseTool(ABC):
    """Abstract base class for all AVA tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """The name of the tool."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """The description of what the tool does."""
        pass

    @property
    @abstractmethod
    def parameters(self) -> Dict[str, Any]:
        """JSON schema for the parameters of the tool."""
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> Any:
        """Executes the tool with the given arguments."""
        pass
