from collections import defaultdict
from typing import Any, TypeVar

from astrbot.api import logger
from astrbot.core.star.filter import HandlerFilter
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.command_group import CommandGroupFilter
from astrbot.core.star.filter.permission import PermissionTypeFilter
from astrbot.core.star.star_handler import StarHandlerMetadata, star_handlers_registry

from ..models import PluginMetadata, RenderNode
from .base import BaseAnalyzer

FilterT = TypeVar("FilterT", bound=HandlerFilter)


class CommandAnalyzer(BaseAnalyzer):
    """指令分析器：处理 CommandFilter / CommandGroupFilter"""

    mode = "command"
    title = "AstrBot 指令菜单"

    def _analyze_hierarchy(self) -> list[PluginMetadata]:
        handlers_map = self._group_handlers_by_module()
        results = []
        all_stars = self.context.get_all_stars()

        logger.info(f"开始分析指令。共扫描到 {len(all_stars)} 个已加载插件。")

        for star_meta in all_stars:
            if not star_meta.activated:
                continue

            plugin = PluginMetadata.from_star(star_meta)
            plugin_name = plugin.resolved_name
            raw_module = plugin.module_path

            if plugin_name in self.cfg.ignored_plugins:
                continue

            if not raw_module:
                logger.debug(
                    f"插件 {plugin_name} 缺失 module_path，无法关联指令，已跳过。"
                )
                continue

            handlers = handlers_map.get(raw_module, [])
            if not handlers:
                handlers = [
                    handler
                    for module, module_handlers in handlers_map.items()
                    if module.startswith(raw_module + ".")
                    or raw_module.startswith(module + ".")
                    for handler in module_handlers
                ]

            if not handlers:
                logger.debug(
                    f"插件 {plugin_name} ({raw_module}) 未注册任何指令 Handler。"
                )
                continue

            try:
                nodes = self.build_command_tree(handlers)
                if nodes:
                    plugin.nodes = nodes
                    results.append(plugin)
                else:
                    logger.debug(f"插件 {plugin_name} 指令树构建结果为空。")
            except Exception as exc:
                logger.warning(f"处理插件 {plugin_name} 时发生异常: {exc}")
                continue

        results.sort(key=lambda item: (not item.display_name, item.name))
        logger.info(f"指令分析完成。找到 {len(results)} 个有指令的插件。")
        return results

    def build_command_tree(
        self,
        handlers: list[StarHandlerMetadata],
    ) -> list[RenderNode]:
        """Build a command tree while preserving framework registration order.

        Args:
            handlers: Registered handlers associated with one plugin.

        Returns:
            Top-level command and command-group nodes.
        """
        nodes = []
        child_handlers_blacklist = self._scan_all_children(handlers)

        for handler in handlers:
            if handler.handler_name in child_handlers_blacklist:
                continue

            group_filter = self._get_filter(handler, CommandGroupFilter)
            if group_filter:
                try:
                    node = self._parse_group(handler, group_filter)
                    if node:
                        nodes.append(node)
                except Exception as exc:
                    logger.warning(f"解析指令组 {handler.handler_name} 失败: {exc}")
                continue

            command_filter = self._get_filter(handler, CommandFilter)
            if command_filter:
                try:
                    node = self._parse_command_node(handler, command_filter)
                    if node:
                        nodes.append(node)
                except Exception as exc:
                    logger.warning(f"解析指令 {handler.handler_name} 失败: {exc}")

        return nodes

    def _group_handlers_by_module(self) -> dict[str, list[StarHandlerMetadata]]:
        mapping = defaultdict(list)
        for handler in star_handlers_registry:
            if isinstance(handler, StarHandlerMetadata) and handler.handler_module_path:
                mapping[handler.handler_module_path].append(handler)
        return mapping

    def _scan_all_children(self, handlers: list[StarHandlerMetadata]) -> set[str]:
        blacklist: set[str] = set()
        groups_map: dict[str, str] = {}
        for handler in handlers:
            group_filter = self._get_filter(handler, CommandGroupFilter)
            if group_filter:
                groups_map[group_filter.group_name] = handler.handler_name

        def _scan_recursive(
            filter_obj: CommandFilter | CommandGroupFilter,
        ) -> None:
            handler_metadata = getattr(filter_obj, "handler_md", None)
            if handler_metadata and hasattr(handler_metadata, "handler_name"):
                blacklist.add(handler_metadata.handler_name)

            if isinstance(filter_obj, CommandGroupFilter):
                if filter_obj.group_name in groups_map:
                    blacklist.add(groups_map[filter_obj.group_name])
                for sub_filter in filter_obj.sub_command_filters:
                    _scan_recursive(sub_filter)

        for handler in handlers:
            group_filter = self._get_filter(handler, CommandGroupFilter)
            if group_filter:
                for sub_filter in group_filter.sub_command_filters:
                    _scan_recursive(sub_filter)
        return blacklist

    def _parse_group(
        self,
        handler: StarHandlerMetadata,
        group_filter: CommandGroupFilter,
    ) -> RenderNode:
        desc = (handler.desc or "").split("\n")[0].strip()
        children = []
        for sub_filter in group_filter.sub_command_filters:
            child = self._process_sub_filter(sub_filter)
            if child:
                children.append(child)

        return RenderNode(
            name=group_filter.group_name,
            desc=desc or "指令组",
            is_group=True,
            tag=self._check_permission(handler),
            children=children,
        )

    def _process_sub_filter(self, filter_obj: Any) -> RenderNode | None:
        handler = getattr(filter_obj, "handler_md", None)
        desc = (getattr(handler, "desc", "") or "").split("\n")[0].strip()
        tag = self._check_permission(handler) if handler else "normal"

        if isinstance(filter_obj, CommandFilter):
            return RenderNode(
                name=filter_obj.command_name,
                desc=desc,
                is_group=False,
                tag=tag,
            )

        if isinstance(filter_obj, CommandGroupFilter):
            children = []
            for sub_filter in filter_obj.sub_command_filters:
                child = self._process_sub_filter(sub_filter)
                if child:
                    children.append(child)
            return RenderNode(
                name=filter_obj.group_name,
                desc=desc or "子指令组",
                is_group=True,
                tag=tag,
                children=children,
            )
        return None

    def _parse_command_node(
        self,
        handler: StarHandlerMetadata,
        command_filter: CommandFilter,
    ) -> RenderNode:
        desc = (handler.desc or "").split("\n")[0].strip()
        return RenderNode(
            name=command_filter.command_name,
            desc=desc,
            is_group=False,
            tag=self._check_permission(handler),
        )

    def _check_permission(self, handler: Any) -> str:
        if not handler or not hasattr(handler, "event_filters"):
            return "normal"
        for item in handler.event_filters:
            if isinstance(item, PermissionTypeFilter):
                return "admin"
        return "normal"

    def _get_filter(
        self,
        handler: StarHandlerMetadata,
        filter_type: type[FilterT],
    ) -> FilterT | None:
        if not hasattr(handler, "event_filters"):
            return None
        for item in handler.event_filters:
            if isinstance(item, filter_type):
                return item
        return None
