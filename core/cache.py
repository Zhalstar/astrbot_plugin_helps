"""Single-entry render caches keyed by the current rendering input."""

import hashlib
import json
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

from PIL import Image

from .config import PluginConfig
from .models import HELP_MODES, HelpMode


class RenderCache:
    """Keep one replaceable image set for each static render mode."""

    PREFIX = "help_typst_mode_cache_"
    LEGACY_PREFIX = "help_typst_cache_"

    def __init__(self, config: PluginConfig):
        self.root = config.cache_dir
        self.temp_dir = config.temp_dir
        self.template = config.template_path
        self.font_dir = config.font_dir
        self._lock = threading.Lock()
        self._prepared = False

    def build_key(
        self, content: str, mode: HelpMode, query: str | None, config: dict[str, Any]
    ) -> str:
        """Calculate the hash for one render request.

        Args:
            content: Generated layout JSON.
            mode: Render mode such as command, event, or filter.
            query: Optional search query.
            config: Rendering settings that affect output.

        Returns:
            A stable BLAKE2s hash for the rendering input.
        """
        files = {
            self.template.resolve(),
            Path(__file__).with_name("worker.py").resolve(),
        }
        if self.font_dir.is_dir():
            files.update(
                path.resolve() for path in self.font_dir.rglob("*") if path.is_file()
            )

        assets = []
        for path in sorted(files):
            stat = path.stat()
            assets.append((str(path), stat.st_size, stat.st_mtime_ns))

        payload = {
            "mode": mode,
            "query": query or "",
            "data": content,
            "config": config,
            "assets": assets,
        }
        stable = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.blake2s(stable.encode("utf-8")).hexdigest()

    def _hash_path(self, mode: HelpMode) -> Path:
        if mode not in HELP_MODES:
            raise ValueError(f"Unsupported cache mode: {mode}")
        return self.root / f"{self.PREFIX}{mode}.hash"

    def _image_paths(self, mode: HelpMode) -> list[Path]:
        self._hash_path(mode)
        return sorted(self.root.glob(f"{self.PREFIX}{mode}_*.webp"))

    def _clear(self, mode: HelpMode) -> None:
        self._hash_path(mode).unlink(missing_ok=True)
        for path in self._image_paths(mode):
            path.unlink(missing_ok=True)

    def _prepare(self) -> None:
        if self._prepared:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        for path in self.root.glob(f"{self.LEGACY_PREFIX}*"):
            if path.is_file():
                path.unlink(missing_ok=True)
        for path in self.root.glob(f"{self.PREFIX}*.tmp"):
            path.unlink(missing_ok=True)
        for mode in HELP_MODES:
            if not self._hash_path(mode).is_file():
                self._clear(mode)
        self._prepared = True

    @staticmethod
    def _inspect(path: Path) -> None:
        with Image.open(path) as image:
            if image.format != "WEBP":
                raise ValueError("Cached output must be WebP")
            image.verify()

    def _copy_images(
        self, sources: list[Path], delivery_files: list[Path]
    ) -> list[str]:
        request_id = uuid.uuid4().hex
        images = []
        for index, source in enumerate(sources):
            target = self.temp_dir / f"help_typst_delivery_{request_id}_{index}.webp"
            delivery_files.append(target)
            shutil.copyfile(source, target)
            images.append(str(target))
        return images

    def get(
        self,
        mode: HelpMode,
        key: str,
        delivery_files: list[Path],
    ) -> list[str] | None:
        """Return delivery copies when the mode cache matches the render key."""
        with self._lock:
            self._prepare()
            try:
                if self._hash_path(mode).read_text(encoding="ascii") != key:
                    return None
                paths = self._image_paths(mode)
                if not paths:
                    raise ValueError("Cached image list is empty")
                for path in paths:
                    self._inspect(path)
                return self._copy_images(paths, delivery_files)
            except FileNotFoundError:
                return None
            except (OSError, ValueError):
                self._clear(mode)
                for path in delivery_files:
                    path.unlink(missing_ok=True)
                delivery_files.clear()
                return None

    def store(self, mode: HelpMode, key: str, sources: list[Path]) -> None:
        """Replace one mode cache after all new images have been staged."""
        with self._lock:
            self._prepare()
            self.validate(sources)
            if not sources:
                raise ValueError("Rendered image list is empty")

            generation = uuid.uuid4().hex
            staged = []
            try:
                for index, source in enumerate(sources):
                    temporary = self.root / (
                        f"{self.PREFIX}{mode}_{index:04d}.webp.{generation}.tmp"
                    )
                    shutil.copyfile(source, temporary)
                    staged.append(temporary)
            except Exception:
                for path in staged:
                    path.unlink(missing_ok=True)
                raise

            try:
                self._clear(mode)
                for index, temporary in enumerate(staged):
                    target = self.root / f"{self.PREFIX}{mode}_{index:04d}.webp"
                    temporary.replace(target)
                hash_path = self._hash_path(mode)
                temporary_hash = hash_path.with_name(
                    f"{hash_path.name}.{generation}.tmp"
                )
                temporary_hash.write_text(key, encoding="ascii")
                temporary_hash.replace(hash_path)
            except Exception:
                self._clear(mode)
                raise
            finally:
                for path in staged:
                    path.unlink(missing_ok=True)
                for path in self.root.glob(f"{self.PREFIX}*.tmp"):
                    path.unlink(missing_ok=True)

    def deliver(self, sources: list[Path], delivery_files: list[Path]) -> list[str]:
        """Copy rendered images into the shared temporary directory."""
        return self._copy_images(sources, delivery_files)

    def validate(self, sources: list[Path]) -> None:
        """Validate newly rendered images before delivery or caching."""
        for source in sources:
            self._inspect(source)

    def cleanup(self) -> None:
        """Remove interrupted cache writes."""
        with self._lock:
            self._prepare()
            for path in self.root.glob(f"{self.PREFIX}*.tmp"):
                path.unlink(missing_ok=True)
