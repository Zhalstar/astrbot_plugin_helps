"""Business orchestration for help data and image rendering."""

import asyncio

from astrbot.core.star.context import Context

from .analyzer import BaseAnalyzer, CommandAnalyzer, EventAnalyzer, FilterAnalyzer
from .cache import RenderCache
from .config import PluginConfig
from .layout import TypstLayout
from .models import HelpMode, PluginMetadata
from .renderer import RenderOutcome, TypstRenderer


class HelpsService:
    """Coordinate analyzers, layout generation, and rendering."""

    def __init__(self, config: PluginConfig, context: Context):
        self.cfg = config
        # 布局
        self.layout = TypstLayout(self.cfg)
        # 缓存
        self.cache = RenderCache(self.cfg)
        # 渲染器
        self.renderer = TypstRenderer(self.cfg, self.cache)
        # 分析器
        self.command_analyzer = CommandAnalyzer(context, self.cfg)
        self.event_analyzer = EventAnalyzer(context, self.cfg)
        self.filter_analyzer = FilterAnalyzer(context, self.cfg)
        self._analyzers: dict[HelpMode, BaseAnalyzer] = {
            "command": self.command_analyzer,
            "event": self.event_analyzer,
            "filter": self.filter_analyzer,
        }
        self._titles: dict[HelpMode, str] = {
            "command": "AstrBot 指令菜单",
            "event": "AstrBot 事件监听",
            "filter": "AstrBot 过滤器分析",
        }

    def get_plugins(
        self,
        mode: HelpMode,
        query: str = "",
    ) -> list[PluginMetadata]:
        """Return plugin information for a command or API consumer.

        Args:
            mode: Information category to analyze.
            query: Optional search query.

        Returns:
            Matching normalized plugin metadata.
        """
        return self._analyzers[mode].get_plugins(query)

    async def render(self, mode: HelpMode, query: str = "") -> RenderOutcome:
        """Analyze current data and render the requested help view.

        Args:
            mode: Information category to render.
            query: Optional search query.

        Returns:
            Rendered image result and an optional error message.
        """

        plugins = await asyncio.to_thread(self.get_plugins, mode, query)

        if not plugins:
            return None, "empty"

        title = f'搜索结果: "{query}"' if query else self._titles[mode]
        content = self.layout.build_json(plugins, title, mode)
        return await self.renderer.render(content, mode, query)

    async def close(self) -> None:
        """Close rendering resources owned by the injected renderer."""
        await self.renderer.close()
