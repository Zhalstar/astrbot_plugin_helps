from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star

from .core import HelpMode, HelpsService
from .core.config import PluginConfig
from .core.models import HELP_MODES


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

    @filter.llm_tool(name="show_help")
    async def llm_show_help(
        self,
        event: AstrMessageEvent,
        analyzer: str = "command",
        query: str = "",
    ) -> str:
        """显示 AstrBot 插件帮助菜单或指定分析页面。

        Args:
            analyzer(string): 分析器类型，可选 command、plugin、tool、hook、filter，默认为 command。
            query(string): 搜索关键词；使用 plugin 分析器时填写插件名称，默认为空。

        Returns:
            图片发送结果。
        """
        mode = analyzer.strip().lower()
        if mode not in HELP_MODES:
            return "不支持的分析器，可选：command、plugin、tool、hook、filter"
        if mode == "plugin" and not query:
            return "使用 plugin 分析器时必须提供插件名称"
        sent = False
        async for result in self._handle_request(event, mode, query):
            await event.send(result)
            sent = True
        return "帮助图片已发送" if sent else "未找到匹配的帮助内容"

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
