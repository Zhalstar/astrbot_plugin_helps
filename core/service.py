import asyncio

from astrbot.core.star.context import Context

from .analyzer import (
    BaseAnalyzer,
    CommandAnalyzer,
    FilterAnalyzer,
    HookAnalyzer,
    PluginAnalyzer,
    ToolAnalyzer,
)
from .cache import RenderCache
from .config import PluginConfig
from .models import HelpMode, RenderJob
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
            "plugin": PluginAnalyzer(context, self.cfg),
            "tool": ToolAnalyzer(context, self.cfg),
            "hook": HookAnalyzer(context, self.cfg),
            "filter": FilterAnalyzer(context, self.cfg),
        }

    async def render(self, mode: HelpMode, query: str = "") -> RenderJob:
        """Analyze current data and render the requested help view.

        Args:
            mode: Information category to render.
            query: Optional search query.

        Returns:
            Render job containing the request data and rendered image paths.
        """

        job = await asyncio.to_thread(self._analyzers[mode].analyze, query)
        if not job.plugins:
            return job
        return await self.renderer.render(job)
