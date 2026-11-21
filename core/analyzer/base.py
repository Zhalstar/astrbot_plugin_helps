from astrbot.api.star import Context
from astrbot.core.star.star_handler import StarHandlerMetadata

from ..config import PluginConfig
from ..models import HelpMode, PluginMetadata, RenderJob, RenderNode


class BaseAnalyzer:
    mode: HelpMode
    title: str

    def __init__(self, context: Context, config: PluginConfig):
        self.context = context
        self.cfg = config

    def analyze(self, query: str = "") -> RenderJob:
        """Analyze current framework data and build a render job.

        Args:
            query: Optional search text.

        Returns:
            Complete render job for this analyzer mode.
        """
        plugins = self._get_plugins(query)
        title = f'搜索结果: "{query}"' if query else self.title
        return RenderJob(
            mode=self.mode,
            plugins=plugins,
            title=title,
            query=query,
        )

    def _get_plugins(self, query: str | None = None) -> list[PluginMetadata]:
        """获取（经过搜索过滤的）插件列表"""
        structured_plugins = self._analyze_hierarchy()
        if not query:
            return structured_plugins

        q_lower = query.lower()
        filtered_plugins = []
        for plugin in structured_plugins:
            is_container_match = self._is_match(
                plugin.name,
                plugin.display_name,
                plugin.desc,
                q_lower,
            )
            if is_container_match:
                filtered_plugins.append(plugin)
                continue

            matched_nodes = self._filter_nodes_recursively(plugin.nodes, q_lower)
            if matched_nodes:
                plugin.nodes = matched_nodes
                filtered_plugins.append(plugin)
        return filtered_plugins

    def _is_match(
        self,
        name: str,
        display: str | None,
        desc: str,
        query: str,
    ) -> bool:
        """基础匹配检查"""
        if query in name.lower():
            return True
        if display and query in display.lower():
            return True
        if desc and query in desc.lower():
            return True
        return False

    def _filter_nodes_recursively(
        self,
        nodes: list[RenderNode],
        query: str,
    ) -> list[RenderNode]:
        """递归过滤节点树，返回一个新的包含匹配的节点的节点列表"""
        result = []
        for node in nodes:
            if self._is_match(node.name, None, node.desc, query):
                result.append(node)
                continue
            if node.children:
                filtered_children = self._filter_nodes_recursively(
                    node.children,
                    query,
                )
                if filtered_children:
                    node.children = filtered_children
                    result.append(node)
        return result

    def _analyze_hierarchy(self) -> list[PluginMetadata]:
        raise NotImplementedError

    def _plugins_by_module(self) -> dict[str, PluginMetadata]:
        """Build a module-path lookup for loaded plugins.

        Returns:
            Normalized plugin metadata keyed by module path.
        """
        plugins = {}
        for star in self.context.get_all_stars():
            if star.module_path:
                plugin = PluginMetadata.from_star(star)
                plugin.name = plugin.resolved_name
                plugins[plugin.module_path] = plugin
        return plugins

    def _get_handler_desc(self, handler: StarHandlerMetadata) -> str:
        """Return the first available description line for a Handler.

        Args:
            handler: Handler metadata to inspect.

        Returns:
            The first explicit description or docstring line.
        """
        desc = (handler.desc or "").split("\n")[0].strip()
        if not desc and handler.handler.__doc__:
            desc = handler.handler.__doc__.split("\n")[0].strip()
        return desc
