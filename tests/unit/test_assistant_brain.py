import pytest
from typing import Any, Dict
from unittest.mock import MagicMock
from ava.brain.tool_router import ToolRouter
from ava.tools.base_tool import BaseTool

class MockTimeTool(BaseTool):
    @property
    def name(self) -> str:
        return "get_current_time"
        
    @property
    def description(self) -> str:
        return "Returns current time."
        
    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> Any:
        return "2026-06-03T10:00:00"

@pytest.mark.asyncio
async def test_tool_router_executes_tool():
    tool = MockTimeTool()
    router = ToolRouter([tool])
    
    # Test execution
    session = MagicMock()
    result = await router.execute_tool("get_current_time", session, {})
    assert result == "2026-06-03T10:00:00"
    
    # Test schemas
    schemas = router.get_all_tool_schemas()
    assert len(schemas) == 1
    assert schemas[0]["name"] == "get_current_time"
