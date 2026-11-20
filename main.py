from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star

from .core import HelpMode, HelpsService
from .core.config import PluginConfig


class HelpsPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.cfg = PluginConfig(config, context)
        self.service = HelpsService(self.cfg, context)

    async def initialize(self):
        pass

    async def _handle_request(
        self, event: AstrMessageEvent, mode: HelpMode, query: str = ""
    ):
        try:
            job = await self.service.render(mode, query)
        except Exception as exc:
            logger.error(f"[HelpTypst] Render Error: {exc}", exc_info=True)
            yield event.plain_result(f"渲染过程出错: {exc}")
            return
        if job.images:
            yield event.chain_result(
                [Image.fromFileSystem(path) for path in job.images]
            )

    @filter.command("helps", alias={"帮助", "菜单"})
    async def show_menu(self, event: AstrMessageEvent, query: str = ""):
        """显示指令菜单"""
        async for r in self._handle_request(event, "command", query):
            yield r

    @filter.command("events", alias={"事件"})
    async def show_events(self, event: AstrMessageEvent, query: str = ""):
        """显示事件监听列表"""
        async for r in self._handle_request(event, "event", query):
            yield r

    @filter.command("filters", alias={"过滤器"})
    async def show_filters(self, event: AstrMessageEvent, query: str = ""):
        """显示过滤器详情"""
        async for r in self._handle_request(event, "filter", query):
            yield r
