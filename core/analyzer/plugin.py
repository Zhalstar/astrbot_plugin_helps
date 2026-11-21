from collections import defaultdict

from astrbot.api.star import Context
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.command_group import CommandGroupFilter
from astrbot.core.star.filter.event_message_type import (
    EventMessageType,
    EventMessageTypeFilter,
)
from astrbot.core.star.filter.platform_adapter_type import (
    PlatformAdapterType,
    PlatformAdapterTypeFilter,
)
from astrbot.core.star.filter.regex import RegexFilter
from astrbot.core.star.star_handler import (
    EventType,
    StarHandlerMetadata,
    star_handlers_registry,
)

from ..config import PluginConfig
from ..models import EVENT_TYPE_MAP, PluginMetadata, RenderJob, RenderNode
from .base import BaseAnalyzer
from .command import CommandAnalyzer
from .filter import format_flags


class PluginAnalyzer(BaseAnalyzer):
    """Combine all registered capabilities of one plugin."""

    mode = "plugin"
    title = "AstrBot 插件分析"

    def __init__(self, context: Context, config: PluginConfig):
        super().__init__(context, config)
        self.command_analyzer = CommandAnalyzer(context, config)

    def analyze(self, query: str = "") -> RenderJob:
        """Analyze one selected plugin and build its render job.

        Args:
            query: Plugin ID, directory name, or display name.

        Returns:
            Complete plugin-analysis render job.
        """
        plugins = self._get_plugins(query)
        title = (
            f"{plugins[0].display_name or plugins[0].name} · 插件分析"
            if plugins
            else self.title
        )
        return RenderJob(
            mode=self.mode,
            plugins=plugins,
            title=title,
        )

    def _get_plugins(self, query: str | None = None) -> list[PluginMetadata]:
        """Find one plugin and return its complete analysis.

        Args:
            query: Plugin ID, directory name, or display name.

        Returns:
            A single analyzed plugin, or an empty list when no plugin matches.
        """
        target = (query or "").strip().casefold()
        if not target:
            return []

        partial_match = None
        for star in self.context.get_all_stars():
            plugin = PluginMetadata.from_star(star)
            plugin.name = plugin.resolved_name
            if not plugin.activated or plugin.name in self.cfg.ignored_plugins:
                continue

            names = {
                value.casefold()
                for value in (plugin.name, plugin.root_dir_name, plugin.display_name)
                if value
            }
            if target in names:
                return [self._analyze_plugin(plugin)]
            if partial_match is None and any(target in name for name in names):
                partial_match = plugin

        return [self._analyze_plugin(partial_match)] if partial_match else []

    def _analyze_hierarchy(self) -> list[PluginMetadata]:
        """Analyze every active plugin.

        Returns:
            Complete metadata and registered capabilities for active plugins.
        """
        results = []
        for star in self.context.get_all_stars():
            plugin = PluginMetadata.from_star(star)
            plugin.name = plugin.resolved_name
            if plugin.activated and plugin.name not in self.cfg.ignored_plugins:
                results.append(self._analyze_plugin(plugin))
        return results

    def _analyze_plugin(self, plugin: PluginMetadata) -> PluginMetadata:
        """Collect metadata, commands, tools, hooks, and filters for a plugin.

        Args:
            plugin: Normalized metadata for the target plugin.

        Returns:
            The plugin metadata populated with grouped render nodes.
        """
        module_path = plugin.module_path
        handlers = [
            handler
            for handler in star_handlers_registry
            if isinstance(handler, StarHandlerMetadata)
            and module_path
            and (
                handler.handler_module_path == module_path
                or handler.handler_module_path.startswith(module_path + ".")
                or module_path.startswith(handler.handler_module_path + ".")
            )
        ]
        sections = []

        info_nodes = []
        if plugin.author:
            info_nodes.append(RenderNode(name="作者", desc=plugin.author))
        description = plugin.short_desc or plugin.desc
        if description:
            info_nodes.append(
                RenderNode(name="简介", desc=description.split("\n")[0].strip())
            )
        if plugin.repo:
            info_nodes.append(RenderNode(name="仓库", desc=plugin.repo))
        if plugin.astrbot_version:
            info_nodes.append(
                RenderNode(name="AstrBot 版本", desc=plugin.astrbot_version)
            )
        if plugin.support_platforms:
            info_nodes.append(
                RenderNode(
                    name="支持平台",
                    desc="、".join(plugin.support_platforms),
                )
            )
        if info_nodes:
            sections.append(
                RenderNode(name="插件信息", is_group=True, children=info_nodes)
            )

        command_nodes = self.command_analyzer.build_command_tree(handlers)
        if command_nodes:
            sections.append(
                RenderNode(name="指令", is_group=True, children=command_nodes)
            )

        tool_nodes = []
        for tool in self.context.get_llm_tool_manager().func_list:
            tool_module = tool.handler_module_path
            if (
                not tool.active
                or not tool_module
                or not module_path
                or not (
                    tool_module == module_path
                    or tool_module.startswith(module_path + ".")
                    or module_path.startswith(tool_module + ".")
                )
            ):
                continue
            tool_nodes.append(
                RenderNode(
                    name=tool.name,
                    desc=(tool.description or "").split("\n")[0].strip(),
                    tag="tool",
                )
            )
        if tool_nodes:
            sections.append(
                RenderNode(name="函数工具", is_group=True, children=tool_nodes)
            )

        hook_groups: dict[EventType, list[RenderNode]] = defaultdict(list)
        filter_nodes = []
        for handler in handlers:
            raw_desc = self._get_handler_desc(handler)
            detail = f"#{handler.handler_name}"
            if raw_desc:
                detail += f" · {raw_desc}"

            is_command = any(
                isinstance(item, (CommandFilter, CommandGroupFilter))
                for item in handler.event_filters
            )
            if (
                not is_command
                and handler.event_type != EventType.OnCallingFuncToolEvent
            ):
                hook_groups[handler.event_type].append(
                    RenderNode(
                        name=handler.handler_name,
                        desc=raw_desc,
                        tag="event_hook",
                        priority=handler.extras_configs.get("priority", 0),
                    )
                )

            for item in handler.event_filters:
                if isinstance(item, RegexFilter):
                    filter_nodes.append(
                        RenderNode(
                            name=item.regex_str,
                            desc=detail,
                            tag="regex_pattern",
                        )
                    )
                elif isinstance(item, PlatformAdapterTypeFilter):
                    names = format_flags(
                        item.platform_type,
                        PlatformAdapterType,
                    )
                    filter_nodes.append(
                        RenderNode(
                            name=f"平台 · {names}",
                            desc=detail,
                            tag="filter_criteria",
                        )
                    )
                elif isinstance(item, EventMessageTypeFilter):
                    names = format_flags(
                        item.event_message_type,
                        EventMessageType,
                    )
                    filter_nodes.append(
                        RenderNode(
                            name=f"消息类型 · {names}",
                            desc=detail,
                            tag="filter_criteria",
                        )
                    )

        if hook_groups:
            hook_nodes = [
                RenderNode(
                    name=EVENT_TYPE_MAP.get(event_type, event_type.name),
                    desc=f"{len(nodes)} 个钩子",
                    is_group=True,
                    tag="event_hook",
                    children=nodes,
                )
                for event_type, nodes in hook_groups.items()
            ]
            sections.append(
                RenderNode(name="事件钩子", is_group=True, children=hook_nodes)
            )

        if filter_nodes:
            sections.append(
                RenderNode(name="过滤器", is_group=True, children=filter_nodes)
            )

        plugin.nodes = sections
        return plugin
