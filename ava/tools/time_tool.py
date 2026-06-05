from datetime import datetime
from typing import Any, Dict
from ava.tools.base_tool import BaseTool

class TimeTool(BaseTool):
    """Tool to get the current date and time."""

    @property
    def name(self) -> str:
        return "get_current_time"

    @property
    def description(self) -> str:
        return "Returns the current date and time."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": []
        }

    async def execute(self, **kwargs) -> Any:
        return datetime.now().isoformat()
