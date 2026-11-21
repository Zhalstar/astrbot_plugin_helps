from collections import defaultdict

from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.command_group import CommandGroupFilter
from astrbot.core.star.star_handler import (
    EventType,
    StarHandlerMetadata,
    star_handlers_registry,
)

from ..models import EVENT_TYPE_MAP, PluginMetadata, RenderNode
from .base import BaseAnalyzer


class HookAnalyzer(BaseAnalyzer):
    """Analyze event hooks other than commands and function tools."""

    mode = "hook"
    title = "AstrBot 事件钩子"

    def _analyze_hierarchy(self) -> list[PluginMetadata]:
        """Group registered event handlers by event type.

        Returns:
            Normalized metadata for each event type containing its handlers.
        """
        results = []
        module_to_plugin = self._plugins_by_module()

        hook_groups = defaultdict(list)
        for handler in star_handlers_registry:
            if not isinstance(handler, StarHandlerMetadata):
                continue
            if self._is_command_handler(handler):
                continue
            if handler.event_type == EventType.OnCallingFuncToolEvent:
                continue

            plugin = module_to_plugin.get(handler.handler_module_path)
            if not plugin:
                continue
            if plugin.name in self.cfg.ignored_plugins:
                continue
            if not plugin.activated:
                continue
            hook_groups[handler.event_type].append(handler)

        for event_type, handlers in hook_groups.items():
            card_title = EVENT_TYPE_MAP.get(event_type, str(event_type.name))
            nodes = []
            for handler in handlers:
                plugin = module_to_plugin.get(handler.handler_module_path)
                plugin_name = plugin.name if plugin else "System"
                display_name = plugin.display_name if plugin else ""
                main_name = display_name if display_name else plugin_name

                raw_desc = self._get_handler_desc(handler)

                full_desc = f"@{plugin_name}" if display_name else ""
                if raw_desc:
                    full_desc = f"{full_desc} · {raw_desc}" if full_desc else raw_desc

                nodes.append(
                    RenderNode(
                        name=main_name,
                        desc=full_desc,
                        is_group=False,
                        tag="event_hook",
                        priority=handler.extras_configs.get("priority", 0),
                    )
                )

            nodes.sort(
                key=lambda node: (
                    -(node.priority if node.priority is not None else 0),
                    node.name,
                )
            )
            results.append(
                PluginMetadata(
                    name="hook_group",
                    display_name=card_title,
                    version="",
                    desc=f"共 {len(nodes)} 个钩子",
                    nodes=nodes,
                )
            )

        return results

    def _is_command_handler(self, handler: StarHandlerMetadata) -> bool:
        if not handler.event_filters:
            return False
        return any(
            isinstance(item, (CommandFilter, CommandGroupFilter))
            for item in handler.event_filters
        )
