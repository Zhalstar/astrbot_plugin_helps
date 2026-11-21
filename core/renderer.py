import asyncio
import io
import json
import math
import re
import unicodedata
import uuid
from pathlib import Path
from typing import Any

import typst
from PIL import Image

from astrbot.api import logger

from .cache import RenderCache
from .config import PluginConfig
from .models import RenderJob, RenderNode

LOGO_MAX_EDGE = 128
LOGO_MAX_PIXELS = 16_000_000


class TypstRenderer:
    def __init__(self, config: PluginConfig, cache: RenderCache):
        self.temp_dir = config.temp_dir
        self.cfg = config
        self.cache = cache
        self._render_lock = asyncio.Lock()

    def _generate_balanced_payload(
        self, job: RenderJob, giant_threshold: int = 1500
    ) -> tuple[dict[str, Any], dict[str, Path]]:
        """Distribute plugin cards and collect their unique Logo paths."""
        giants = []
        complex_plugins = []
        logo_keys: dict[Path, str] = {}
        logo_paths: dict[str, Path] = {}

        for plugin in job.plugins:
            nodes = plugin.nodes
            logo_path = Path(plugin.logo_path) if plugin.logo_path else None
            if logo_path is None or not logo_path.is_file():
                logo_path = self.cfg.default_logo_path
            logo_path = logo_path.resolve()
            logo_key = logo_keys.get(logo_path)
            if logo_key is None:
                logo_key = f"logo_{len(logo_keys)}"
                logo_keys[logo_path] = logo_key
                logo_paths[logo_key] = logo_path
            plugin_data = plugin.model_dump()
            plugin_data["logo_key"] = logo_key

            height = self._estimate_height(nodes)
            if job.mode == "plugin":
                section_columns = [[] for _ in range(3)]
                section_heights = [0] * 3
                sections = sorted(
                    (
                        (node.model_dump(), self._estimate_height([node]) + 40)
                        for node in nodes
                    ),
                    key=lambda item: item[1],
                    reverse=True,
                )
                for node_data, section_height in sections:
                    index = section_heights.index(min(section_heights))
                    section_columns[index].append(node_data)
                    section_heights[index] += section_height
                plugin_data["section_columns"] = section_columns
                giants.append(plugin_data)
                continue
            if job.mode in ("hook", "filter") and height > giant_threshold:
                giants.append(plugin_data)
                continue
            complex_plugins.append((plugin, plugin_data))

        plugins_with_height = [
            (plugin_data, self._estimate_height(plugin.nodes) + 80)
            for plugin, plugin_data in complex_plugins
        ]
        sorted_plugins = sorted(
            plugins_with_height, key=lambda item: item[1], reverse=True
        )
        columns = [[] for _ in range(3)]
        column_heights = [0] * 3
        for plugin_data, height in sorted_plugins:
            index = column_heights.index(min(column_heights))
            columns[index].append(plugin_data)
            column_heights[index] += height

        return (
            {
                "title": job.title,
                "mode": job.mode,
                "prefixes": self.cfg.prefixes,
                "font_families": self.cfg.font_families,
                "plugin_count": len(job.plugins),
                "giants": giants,
                "columns": columns,
                "logos": {},
            },
            logo_paths,
        )

    def _load_logo_assets(self, logo_paths: dict[str, Path]) -> dict[str, list[int]]:
        """Normalize unique plugin Logos for Typst rendering"""
        if not logo_paths:
            return {}

        default_path = self.cfg.default_logo_path.resolve()
        encoded: dict[Path, list[int]] = {}
        paths = dict.fromkeys([default_path, *logo_paths.values()])
        for path in paths:
            try:
                with Image.open(path) as image:
                    if image.width * image.height > LOGO_MAX_PIXELS:
                        raise ValueError("Logo exceeds the pixel limit")
                    normalized = image.convert("RGBA")
                    normalized.thumbnail(
                        (LOGO_MAX_EDGE, LOGO_MAX_EDGE),
                        Image.Resampling.LANCZOS,
                    )
                    buffer = io.BytesIO()
                    normalized.save(buffer, "WEBP", lossless=True, method=6)
                    encoded[path] = list(buffer.getvalue())
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                if path == default_path:
                    raise RuntimeError(
                        f"Failed to process bundled plugin Logo: {exc}"
                    ) from exc
                logger.warning(f"Failed to process plugin Logo {path}: {exc}")
                encoded[path] = encoded[default_path]

        return {key: encoded[path] for key, path in logo_paths.items()}

    def _estimate_height(self, nodes: list[RenderNode]) -> int:
        """Estimate card height for greedy column balancing"""
        total_height = 0
        complex_nodes = [node for node in nodes if node.is_group or node.desc]
        simple_nodes = [node for node in nodes if not node.is_group and not node.desc]

        for node in complex_nodes:
            text_width = sum(
                2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
                for char in f"{node.name} {node.desc}"
            )
            wrapped_lines = max(1, math.ceil(text_width / 36))
            node_height = 60 + (wrapped_lines - 1) * 18
            if node.is_group:
                total_height += node_height + self._estimate_height(node.children)
            else:
                total_height += node_height

        if simple_nodes:
            total_height += math.ceil(len(simple_nodes) / 3) * 30 + 10
        return total_height

    def _execute_render_task(
        self,
        json_str: str,
        output_png_path: Path,
        query: str | None,
    ) -> Path:
        """Compile the Typst template and convert its PNG output to WebP"""
        sys_inputs = {"json_string": json_str}
        if query:
            sys_inputs["query_regex"] = re.escape(query)

        typst.compile(
            str(self.cfg.template_path),
            output=str(output_png_path),
            font_paths=[str(self.cfg.font_dir)],
            format="png",
            ppi=self.cfg.ppi,
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
            payload, logo_paths = self._generate_balanced_payload(job)
            cache_content = json.dumps(payload, ensure_ascii=False, indent=2)
            stem = f"help_typst_render_{uuid.uuid4().hex}"
            try:
                key = None
                if not job.query:
                    logo_files = [self.cfg.default_logo_path, *logo_paths.values()]
                    key = self.cache.build_key(cache_content, logo_files)
                    cached = self.cache.get(job.mode, key)
                    if cached:
                        logger.debug(f"渲染缓存命中: {job.mode}")
                        job.images = [self.cache.deliver(cached)]
                        return job

                payload["logos"] = self._load_logo_assets(logo_paths)
                content = json.dumps(payload, ensure_ascii=False, indent=2)
                compile_task = asyncio.create_task(
                    asyncio.to_thread(
                        self._execute_render_task,
                        json_str=content,
                        output_png_path=self.temp_dir / f"{stem}.png",
                        query=job.query,
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
                    self.cache.store(job.mode, key, source)
                job.images = [self.cache.deliver(source)]
                return job
            finally:
                for path in self.temp_dir.glob(f"{stem}*"):
                    try:
                        path.unlink(missing_ok=True)
                    except OSError as exc:
                        logger.warning(f"清理渲染文件失败 {path}: {exc}")
