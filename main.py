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

    async def terminate(self):
        pass

    async def _handle_request(
        self, event: AstrMessageEvent, mode: HelpMode, query: str = ""
    ):
        try:
            job = await self.service.render(mode, query)
        except Exception as exc:
            logger.error(f"Render Error: {exc}", exc_info=True)
            return
        if job.images:
            yield event.chain_result(
                [Image.fromFileSystem(path) for path in job.images]
            )

    @filter.command("帮助", alias={"helps", "菜单"})
    async def show_menu(self, event: AstrMessageEvent, query: str = ""):
        """显示指令菜单"""
        async for r in self._handle_request(event, "command", query):
            yield r

    @filter.command("插件", alias={"plugin"})
    async def show_plugin(self, event: AstrMessageEvent, plugin_name: str):
        """显示插件完整分析"""
        async for r in self._handle_request(event, "plugin", plugin_name):
            yield r

    @filter.command("工具", alias={"tools"})
    async def show_tools(self, event: AstrMessageEvent, query: str = ""):
        """显示工具列表"""
        async for r in self._handle_request(event, "tool", query):
            yield r

    @filter.command("钩子", alias={"hooks", "事件", "监听器", "events"})
    async def show_hooks(self, event: AstrMessageEvent, query: str = ""):
        """显示事件钩子列表"""
        async for r in self._handle_request(event, "hook", query):
            yield r

    @filter.command("过滤器", alias={"filters"})
    async def show_filters(self, event: AstrMessageEvent, query: str = ""):
        """显示过滤器详情"""
        async for r in self._handle_request(event, "filter", query):
            yield r
