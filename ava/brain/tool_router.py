from typing import Any, Dict, List
from ava.tools.base_tool import BaseTool


def _convert_schema_for_genai(schema: dict) -> dict:
    """
    Convert standard JSON Schema dicts to the format expected by
    google-generativeai SDK's protobuf FunctionDeclaration.

    Changes:
      - "type" key  →  "type_" key
      - type values uppercased: "object" → "OBJECT", "string" → "STRING", etc.
      - Recursively converts nested properties and items.
    """
    if not isinstance(schema, dict):
        return schema

    result = {}
    for key, value in schema.items():
        if key == "type":
            result["type_"] = value.upper()
        elif key == "properties" and isinstance(value, dict):
            result["properties"] = {
                prop_name: _convert_schema_for_genai(prop_schema)
                for prop_name, prop_schema in value.items()
            }
        elif key == "items" and isinstance(value, dict):
            result["items"] = _convert_schema_for_genai(value)
        else:
            result[key] = value
    return result


class ToolRouter:
    """Maps Gemini function call decisions to tool instances."""

    def __init__(self, tools: List[BaseTool]):
        self.tools = {tool.name: tool for tool in tools}

    def get_tool(self, name: str) -> BaseTool:
        return self.tools.get(name)

    def get_all_tool_schemas(self) -> List[Dict[str, Any]]:
        schemas = []
        for tool in self.tools.values():
            schemas.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": _convert_schema_for_genai(tool.parameters),
            })
        return schemas

    async def execute_tool(self, name: str, session: Any, kwargs: Dict[str, Any]) -> Any:
        tool = self.get_tool(name)
        if not tool:
            raise ValueError(f"Tool {name} not found")
        return await tool.execute(session=session, **kwargs)
