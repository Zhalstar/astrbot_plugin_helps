import asyncio

from astrbot.core.star.context import Context

from .analyzer import BaseAnalyzer, CommandAnalyzer, EventAnalyzer, FilterAnalyzer
from .cache import RenderCache
from .config import PluginConfig
from .models import HelpMode, PluginMetadata, RenderJob
from .renderer import TypstRenderer


class HelpsService:
    """Coordinate analyzers, layout generation, and rendering."""

    def __init__(self, config: PluginConfig, context: Context):
        self.cfg = config
        # 缓存
        self.cache = RenderCache(self.cfg)
        # 渲染器
        self.renderer = TypstRenderer(self.cfg, self.cache)
        # 分析器
        self._analyzers: dict[HelpMode, BaseAnalyzer] = {
            "command": CommandAnalyzer(context, self.cfg),
            "event": EventAnalyzer(context, self.cfg),
            "filter": FilterAnalyzer(context, self.cfg),
        }
        self._titles: dict[HelpMode, str] = {
            "command": "AstrBot 指令菜单",
            "event": "AstrBot 事件监听",
            "filter": "AstrBot 过滤器分析",
        }

    def get_plugins(self, mode: HelpMode, query: str = "") -> list[PluginMetadata]:
        """Return plugin information for a command or API consumer.

        Args:
            mode: Information category to analyze.
            query: Optional search query.

        Returns:
            Matching normalized plugin metadata.
        """
        return self._analyzers[mode].get_plugins(query)

    async def render(self, mode: HelpMode, query: str = "") -> RenderJob:
        """Analyze current data and render the requested help view.

        Args:
            mode: Information category to render.
            query: Optional search query.

        Returns:
            Render job containing the request data and rendered image paths.
        """

        plugins = await asyncio.to_thread(self.get_plugins, mode, query)

        title = f'搜索结果: "{query}"' if query else self._titles[mode]
        job = RenderJob(mode=mode, plugins=plugins, title=title, query=query)
        if not plugins:
            return job
        return await self.renderer.render(job)
