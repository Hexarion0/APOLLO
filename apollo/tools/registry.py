import logging
from typing import Any, Dict, List, Optional
from apollo.tools.base import BaseTool

logger = logging.getLogger("apollo.tools.registry")

class ToolRegistry:
    """Registry managing available tools for APOLLO."""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        if tool.name in self._tools:
            logger.warning(f"Overwriting existing registered tool '{tool.name}'")
        self._tools[tool.name] = tool
        logger.info(f"Registered tool '{tool.name}'")

    def get(self, name: str) -> Optional[BaseTool]:
        """Retrieve tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[BaseTool]:
        """List all registered tools."""
        return list(self._tools.values())

    def get_openai_schemas(self) -> List[Dict[str, Any]]:
        """Export tool schemas formatted for LLM tool calling."""
        return [tool.to_openai_schema() for tool in self._tools.values()]

    async def execute_tool(self, name: str, **kwargs: Any) -> Any:
        """Execute tool by name."""
        tool = self.get(name)
        if not tool:
            raise KeyError(f"Tool '{name}' is not registered.")
        return await tool.execute(**kwargs)
