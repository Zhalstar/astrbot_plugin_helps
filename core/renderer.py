import asyncio
import json
import math
import re
import uuid
from pathlib import Path
from typing import Any

import typst
from PIL import Image

from astrbot.api import logger

from .cache import RenderCache
from .config import PluginConfig
from .models import HelpMode, PluginMetadata, RenderJob, RenderNode


class TypstRenderer:
    def __init__(self, config: PluginConfig, cache: RenderCache):
        self.temp_dir = config.temp_dir
        self.cfg = config
        self.cache = cache
        self._render_lock = asyncio.Lock()

    def _generate_balanced_payload(
        self,
        plugins: list[PluginMetadata],
        title: str,
        mode: HelpMode,
    ) -> dict[str, Any]:
        """Distribute plugin cards across the rendered columns.

        Args:
            plugins: Normalized plugin metadata to render.
            title: Title displayed at the top of the image.
            mode: Help data category being rendered.

        Returns:
            Layout data consumed by the Typst template.
        """
        giants = []
        complex_plugins = []
        tool_plugins = []

        for plugin in plugins:
            nodes = plugin.nodes
            is_tool = len(nodes) > 0 and nodes[0].tag in ("tool", "mcp")
            if is_tool:
                tool_plugins.append(plugin.model_dump())
                continue

            height = self._estimate_height(nodes)
            if (
                mode in ("event", "filter")
                and height > self.cfg.rendering.giant_threshold
            ):
                giants.append(plugin.model_dump())
                continue
            complex_plugins.append(plugin)

        plugins_with_height = [
            (plugin, self._estimate_height(plugin.nodes) + 80)
            for plugin in complex_plugins
        ]
        sorted_plugins = sorted(
            plugins_with_height, key=lambda item: item[1], reverse=True
        )
        columns = [[] for _ in range(3)]
        column_heights = [0] * 3
        for plugin, height in sorted_plugins:
            index = column_heights.index(min(column_heights))
            columns[index].append(plugin.model_dump())
            column_heights[index] += height

        return {
            "title": title,
            "mode": mode,
            "prefixes": self.cfg.prefixes,
            "font_families": self.cfg.font_families,
            "plugin_count": len(plugins),
            "giants": giants,
            "columns": columns,
            "tools": tool_plugins,
        }

    def _estimate_height(self, nodes: list[RenderNode]) -> int:
        """Estimate card height for greedy column balancing.

        Args:
            nodes: Render nodes contained in a plugin card.

        Returns:
            Estimated card content height in Typst points.
        """
        total_height = 0
        complex_nodes = [node for node in nodes if node.is_group or node.desc]
        simple_nodes = [node for node in nodes if not node.is_group and not node.desc]

        for node in complex_nodes:
            if node.is_group:
                total_height += 60 + self._estimate_height(node.children)
            else:
                total_height += 60

        if simple_nodes:
            total_height += math.ceil(len(simple_nodes) / 3) * 30 + 10
        return total_height

    def _execute_render_task(
        self,
        json_str: str,
        output_png_path: Path,
        query: str | None,
        ppi: float,
    ) -> Path:
        """Compile the Typst template and convert its PNG output to WebP.

        Args:
            json_str: Serialized layout data passed to Typst.
            output_png_path: Intermediate PNG path.
            query: Optional search query used for highlighting.
            ppi: Typst rasterization resolution.

        Returns:
            Generated WebP image path.
        """
        sys_inputs = {"json_string": json_str}
        if query:
            sys_inputs["query_regex"] = re.escape(query)

        typst.compile(
            str(self.cfg.template_path),
            output=str(output_png_path),
            font_paths=[str(self.cfg.font_dir)],
            format="png",
            ppi=ppi,
            sys_inputs=sys_inputs,
        )

        webp_path = output_png_path.with_suffix(".webp")
        try:
            with Image.open(output_png_path) as image:
                image.save(webp_path, "WEBP", quality=80, method=6)
        except Exception as exc:
            raise RuntimeError(f"Image processing failed: {exc}") from exc
        return webp_path

    async def render(self, job: RenderJob) -> RenderJob:
        async with self._render_lock:
            payload = self._generate_balanced_payload(
                job.plugins,
                job.title,
                job.mode,
            )
            content = json.dumps(payload, ensure_ascii=False, indent=2)
            stem = f"help_typst_render_{uuid.uuid4().hex}"
            try:
                ppi = self.cfg.rendering.ppi
                key = None
                if not job.query:
                    key = self.cache.build_key(content, ppi)
                    cached = self.cache.get(job.mode, key)
                    if cached:
                        logger.debug(f"[HelpTypst] 渲染缓存命中: {job.mode}")
                        job.images = [self.cache.deliver(cached)]
                        return job

                compile_task = asyncio.create_task(
                    asyncio.to_thread(
                        self._execute_render_task,
                        json_str=content,
                        output_png_path=self.temp_dir / f"{stem}.png",
                        query=job.query,
                        ppi=ppi,
                    )
                )
                try:
                    source = await asyncio.shield(compile_task)
                except asyncio.CancelledError:
                    try:
                        await compile_task
                    except Exception:
                        pass
                    raise

                if key is not None:
                    try:
                        self.cache.store(job.mode, key, source)
                    except OSError as exc:
                        logger.warning(f"[HelpTypst] 写入渲染缓存失败: {exc}")
                job.images = [self.cache.deliver(source)]
                return job
            finally:
                for path in self.temp_dir.glob(f"{stem}*"):
                    try:
                        path.unlink(missing_ok=True)
                    except OSError as exc:
                        logger.warning(f"[HelpTypst] 清理渲染文件失败 {path}: {exc}")
