from collections import defaultdict

from astrbot.core.star.filter.event_message_type import (
    EventMessageType,
    EventMessageTypeFilter,
)
from astrbot.core.star.filter.platform_adapter_type import (
    PlatformAdapterType,
    PlatformAdapterTypeFilter,
)
from astrbot.core.star.filter.regex import RegexFilter
from astrbot.core.star.star_handler import StarHandlerMetadata, star_handlers_registry

from ..models import PluginMetadata, RenderNode
from .base import BaseAnalyzer


def format_flags(value, enum_cls) -> str:
    """Format the active members of a framework flag enum.

    Args:
        value: Flag value to inspect.
        enum_cls: Enum class that defines the available flags.

    Returns:
        Human-readable active member names.
    """
    if value is None:
        return "None"
    if hasattr(enum_cls, "ALL") and value == enum_cls.ALL:
        return "ALL"

    members = [
        member.name for member in enum_cls if member.name != "ALL" and member in value
    ]
    return " | ".join(members) if members else "None"


class FilterAnalyzer(BaseAnalyzer):
    """过滤器分析器"""

    mode = "filter"
    title = "AstrBot 过滤器分析"

    def _analyze_hierarchy(self) -> list[PluginMetadata]:
        results = []
        module_to_plugin = self._plugins_by_module()

        regex_data = defaultdict(list)
        platform_data = defaultdict(list)
        message_type_data = defaultdict(list)

        for handler in star_handlers_registry:
            if not isinstance(handler, StarHandlerMetadata):
                continue

            plugin = module_to_plugin.get(handler.handler_module_path)
            if not plugin:
                continue
            if plugin.name in self.cfg.ignored_plugins:
                continue
            if not plugin.activated or not handler.event_filters:
                continue

            for item in handler.event_filters:
                if isinstance(item, RegexFilter):
                    regex_data[handler.handler_module_path].append(
                        (item.regex_str, handler)
                    )
                elif isinstance(item, PlatformAdapterTypeFilter):
                    names = format_flags(
                        item.platform_type,
                        PlatformAdapterType,
                    )
                    platform_data[f"🌍 {names}"].append(handler)
                elif isinstance(item, EventMessageTypeFilter):
                    names = format_flags(
                        item.event_message_type,
                        EventMessageType,
                    )
                    message_type_data[f"📨 {names}"].append(handler)

        if regex_data:
            nodes = []
            for module_path, items in regex_data.items():
                plugin = module_to_plugin.get(module_path)
                plugin_name = plugin.name if plugin else "Unknown"
                display_name = plugin.display_name if plugin else ""
                children = []

                for regex, handler in sorted(items, key=lambda item: item[0]):
                    raw_desc = self._get_handler_desc(handler)

                    full_desc = f"#{handler.handler_name}"
                    if raw_desc:
                        full_desc += f" · {raw_desc}"
                    children.append(
                        RenderNode(
                            name=regex,
                            desc=full_desc,
                            is_group=False,
                            tag="regex_pattern",
                        )
                    )

                nodes.append(
                    RenderNode(
                        name=display_name if display_name else plugin_name,
                        desc=f"@{plugin_name}" if display_name else "",
                        is_group=True,
                        tag="plugin_container",
                        children=children,
                    )
                )

            nodes.sort(key=lambda node: node.name)
            results.append(
                PluginMetadata(
                    name="filter_regex",
                    display_name="正则触发器 (Regex)",
                    version="",
                    desc=f"共 {len(nodes)} 个插件使用了正则",
                    nodes=nodes,
                )
            )

        if platform_data:
            results.append(
                self._build_criteria_card(
                    "平台限制 (Platform)",
                    "platform",
                    platform_data,
                    module_to_plugin,
                )
            )

        if message_type_data:
            results.append(
                self._build_criteria_card(
                    "消息类型限制 (MsgType)",
                    "msg_type",
                    message_type_data,
                    module_to_plugin,
                )
            )

        return results

    def _build_criteria_card(
        self,
        title: str,
        tag_prefix: str,
        data: dict[str, list[StarHandlerMetadata]],
        module_to_plugin: dict[str, PluginMetadata],
    ) -> PluginMetadata:
        nodes = []
        for filter_name in sorted(data):
            children = []
            for handler in data[filter_name]:
                plugin = module_to_plugin.get(handler.handler_module_path)
                plugin_name = plugin.name if plugin else "Unknown"
                display_name = plugin.display_name if plugin else ""
                main_name = display_name if display_name else plugin_name

                raw_desc = self._get_handler_desc(handler)

                parts = []
                if display_name:
                    parts.append(f"@{plugin_name}")
                parts.append(f"#{handler.handler_name}")
                if raw_desc:
                    parts.append(raw_desc)

                children.append(
                    RenderNode(
                        name=main_name,
                        desc=" · ".join(parts),
                        is_group=False,
                        tag="event_hook",
                        priority=handler.extras_configs.get("priority", 0),
                    )
                )

            children.sort(
                key=lambda node: (
                    -(node.priority if node.priority is not None else 0),
                    node.name,
                )
            )
            nodes.append(
                RenderNode(
                    name=filter_name,
                    desc=f"{len(children)} 个监听点",
                    is_group=True,
                    tag="filter_criteria",
                    children=children,
                )
            )

        return PluginMetadata(
            name=f"filter_{tag_prefix}",
            display_name=title,
            version="",
            desc=f"共 {len(data)} 种过滤条件",
            nodes=nodes,
        )
