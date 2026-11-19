import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from astrbot.api import logger

from .cache import RenderCache
from .config import PluginConfig
from .models import HelpMode
from .worker import RenderTask, execute_render_task

T = TypeVar("T")


async def finish_cleanup(awaitable: Awaitable[T]) -> T:
    """Finish cleanup before propagating repeated cancellation."""
    cleanup = asyncio.ensure_future(awaitable)
    cancelled = False
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            cancelled = True
    result = cleanup.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


@dataclass
class RenderResult:
    """Paths copied to AstrBot's managed temporary directory for sending."""

    images: list[str]


RenderOutcome = tuple[RenderResult | None, str]


@dataclass
class RenderFlight:
    task: asyncio.Task[list[str]]
    stem: str
    files: list[Path]
    waiters: int = 0


class TypstRenderer:
    def __init__(self, config: PluginConfig, cache: RenderCache):
        self.temp_dir = config.temp_dir
        self.cfg = config
        self.cache = cache
        self._compile_semaphore = asyncio.Semaphore(
            self.cfg.rendering.max_concurrent_tasks
        )
        self._closed = False
        self._render_tasks: set[asyncio.Task[RenderOutcome]] = set()
        self._compile_tasks: set[asyncio.Task[list[str]]] = set()
        self._deferred_stems: set[str] = set()
        self._flights: dict[str, RenderFlight] = {}

    def _get_config_snapshot(self) -> dict[str, Any]:
        # Layout and filtering inputs are already represented in the generated JSON.
        return {
            "ppi": self.cfg.rendering.ppi,
            "split_height": self.cfg.rendering.split_height,
        }

    async def render(
        self,
        content: str,
        mode: HelpMode,
        query: str | None = None,
    ) -> RenderOutcome:
        """Render prepared layout JSON into deliverable images.

        Args:
            content: Serialized layout JSON consumed by the Typst template.
            mode: Help data category being rendered.
            query: Optional search query used for highlighting and cache policy.

        Returns:
            Rendered image paths and an optional error message.
        """
        if self._closed:
            return None, "渲染器已关闭"
        # 只跟踪渲染操作，卸载时不等待 AstrBot 外层消息处理任务。
        request = asyncio.create_task(self._render_request(content, mode, query))
        self._render_tasks.add(request)
        try:
            return await request
        finally:
            self._render_tasks.discard(request)

    async def _file_io(self, operation: Callable[[], T]) -> T:
        """线程中的文件操作完成后才能清理其文件或释放共享结果。"""
        task = asyncio.create_task(asyncio.to_thread(operation))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await finish_cleanup(asyncio.gather(task, return_exceptions=True))
            raise

    async def _render_request(
        self,
        content: str,
        mode: HelpMode,
        query: str | None,
    ) -> RenderOutcome:
        delivery_files: list[Path] = []
        try:
            config = self._get_config_snapshot()
            key = await self._file_io(
                lambda: self.cache.build_key(content, mode, query, config)
            )
            flight = self._flights.get(key)
            if flight is None:
                stem = f"help_typst_render_{uuid.uuid4().hex}"
                files: list[Path] = []
                task = asyncio.create_task(
                    self._build_images(key, mode, query, content, config, stem, files)
                )
                flight = RenderFlight(task, stem, files)
                self._flights[key] = flight
            flight.waiters += 1
            try:
                # 单个请求取消不会连带取消仍有等待者的共享编译。
                sources = await asyncio.shield(flight.task)
                images = await self._file_io(
                    lambda: self.cache.deliver(
                        [Path(path) for path in sources], delivery_files
                    )
                )
                return RenderResult(images), ""
            finally:
                await finish_cleanup(self._release_flight(key, flight))
        except asyncio.CancelledError:
            await finish_cleanup(self._discard_files(delivery_files))
            raise
        except asyncio.TimeoutError:
            await finish_cleanup(self._discard_files(delivery_files))
            return (
                None,
                "Typst 编译超时，后台任务完成后会自动清理，请降低 PPI 或增加编译超时时间",
            )
        except Exception as exc:
            logger.error(f"[HelpTypst] Render Error: {exc}", exc_info=True)
            await finish_cleanup(self._discard_files(delivery_files))
            return None, f"渲染过程出错: {exc}"

    async def _build_images(
        self,
        key: str,
        mode: HelpMode,
        query: str | None,
        content: str,
        config: dict[str, Any],
        stem: str,
        files: list[Path],
    ) -> list[str]:
        cacheable = not query
        if cacheable:
            try:
                images = await self._file_io(lambda: self.cache.get(mode, key, files))
                if images:
                    logger.debug(f"[HelpTypst] 渲染缓存命中: {mode}")
                    return images
            except OSError as exc:
                logger.warning(f"[HelpTypst] 读取渲染缓存失败，重新渲染: {exc}")

        task = RenderTask(
            template_path=str(self.cfg.template_path),
            json_str=content,
            output_png_path=str(self.temp_dir / f"{stem}.png"),
            output_dir=str(self.temp_dir),
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            query=query,
            split_height=config["split_height"],
            ppi=config["ppi"],
        )
        await self._compile_semaphore.acquire()
        if self._closed:
            self._compile_semaphore.release()
            raise asyncio.CancelledError
        compile_task = asyncio.create_task(asyncio.to_thread(execute_render_task, task))
        self._compile_tasks.add(compile_task)
        compile_task.add_done_callback(self._release_compile_task)
        try:
            images = await asyncio.wait_for(
                asyncio.shield(compile_task),
                timeout=self.cfg.rendering.timeout_compile,
            )
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._deferred_stems.add(stem)
            compile_task.add_done_callback(
                lambda done: self._discard_compile_result(done, stem)
            )
            raise
        if not images:
            raise RuntimeError("渲染未生成图片文件")
        sources = [Path(path) for path in images]
        if cacheable:
            try:
                await self._file_io(lambda: self.cache.store(mode, key, sources))
            except OSError as exc:
                logger.warning(f"[HelpTypst] 写入渲染缓存失败: {exc}")
                await self._file_io(lambda: self.cache.validate(sources))
        else:
            await self._file_io(lambda: self.cache.validate(sources))
        return images

    async def _release_flight(self, key: str, flight: RenderFlight) -> None:
        flight.waiters -= 1
        if flight.waiters:
            return
        self._flights.pop(key, None)
        if not flight.task.done():
            flight.task.cancel()
        await finish_cleanup(asyncio.gather(flight.task, return_exceptions=True))
        paths = list(flight.files)
        if flight.stem not in self._deferred_stems:
            paths.extend(self.temp_dir.glob(f"{flight.stem}*"))
        await self._discard_files(paths)

    def _release_compile_task(self, task: asyncio.Task[list[str]]) -> None:
        """Release the concurrency slot held by a completed compile task."""
        self._compile_tasks.discard(task)
        self._compile_semaphore.release()

    def _discard_compile_result(self, task: asyncio.Task[list[str]], stem: str) -> None:
        """Consume and remove the result of a detached compile task."""
        self._deferred_stems.discard(stem)
        if not task.cancelled():
            try:
                task.result()
            except Exception:
                pass
        for path in self.temp_dir.glob(f"{stem}*"):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(
                    f"[HelpTypst] Failed to clean background render file {path}: {exc}"
                )

    async def _discard_files(self, paths: list[Path]) -> None:
        def discard() -> None:
            for path in paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning(f"[HelpTypst] 清理渲染文件失败 {path}: {exc}")

        await self._file_io(discard)

    async def close(self) -> None:
        """Cancel requests while detached compile threads finish in background."""
        self._closed = True
        requests = list(self._render_tasks)
        for task in requests:
            task.cancel()
        if requests:
            await finish_cleanup(asyncio.gather(*requests, return_exceptions=True))
        try:
            await self._file_io(self.cache.cleanup)
        except OSError as exc:
            logger.warning(f"[HelpTypst] 清理渲染缓存失败: {exc}")
