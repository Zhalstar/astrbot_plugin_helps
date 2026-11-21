from astrbot.core.agent.mcp_client import MCPTool

from ..models import PluginMetadata, RenderNode
from .base import BaseAnalyzer


class ToolAnalyzer(BaseAnalyzer):
    """Analyze plugin function tools and MCP tools."""

    mode = "tool"
    title = "AstrBot 函数工具"

    def _analyze_hierarchy(self) -> list[PluginMetadata]:
        """Group active tools by their plugin or MCP source.

        Returns:
            Normalized source metadata containing its function tools.
        """
        grouped: dict[tuple[str, str], PluginMetadata] = {}
        module_to_plugin = self._plugins_by_module()

        tool_manager = self.context.get_llm_tool_manager()
        for tool in tool_manager.func_list:
            if not tool.active:
                continue

            source = PluginMetadata(name="Unknown")
            source_key = ("unknown", "")
            tag = "tool"
            if isinstance(tool, MCPTool):
                source.name = f"MCP/{tool.mcp_server_name}"
                source.display_name = f"🔌 {tool.mcp_server_name}"
                source_key = ("mcp", tool.mcp_server_name)
                tag = "mcp"
            elif tool.handler_module_path:
                plugin = module_to_plugin.get(tool.handler_module_path)
                if plugin:
                    if plugin.name in self.cfg.ignored_plugins:
                        continue
                    source = plugin.model_copy(deep=True)
                    source_key = ("plugin", plugin.module_path)
                else:
                    source.name = "Core/Unknown"
                    source_key = ("module", tool.handler_module_path)

            desc = (tool.description or "").split("\n")[0].strip()
            node = RenderNode(name=tool.name, desc=desc, is_group=False, tag=tag)
            if source_key not in grouped:
                source.desc = ""
                source.nodes = []
                grouped[source_key] = source
            grouped[source_key].nodes.append(node)

        return list(grouped.values())
