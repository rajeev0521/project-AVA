from typing import Any, Dict, List
from ava.tools.base_tool import BaseTool

class ToolRouter:
    """Maps Gemini function call decisions to tool instances."""
    
    def __init__(self, tools: List[BaseTool]):
        self.tools = {tool.name: tool for tool in tools}

    def get_tool(self, name: str) -> BaseTool:
        return self.tools.get(name)
        
    def get_all_tool_schemas(self) -> List[Dict[str, Any]]:
        schemas = []
        for tool in self.tools.values():
            # Create the schema expected by google-generativeai SDK
            schemas.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters
            })
        return schemas

    async def execute_tool(self, name: str, kwargs: Dict[str, Any]) -> Any:
        tool = self.get_tool(name)
        if not tool:
            raise ValueError(f"Tool {name} not found")
        return await tool.execute(**kwargs)
