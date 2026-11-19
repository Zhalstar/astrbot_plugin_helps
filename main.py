from astrbot.api import AstrBotConfig
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

    async def terminate(self):
        await self.service.close()

    async def _handle_request(
        self, event: AstrMessageEvent, mode: HelpMode, query: str = ""
    ):
        result, error = await self.service.render(mode, query)
        if result:
            yield event.chain_result([Image.fromFileSystem(p) for p in result.images])
        elif error != "empty":
            yield event.plain_result(error)

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
