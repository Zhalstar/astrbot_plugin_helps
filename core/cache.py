"""Disk cache for rendered help images."""

import hashlib
import shutil
import uuid
from collections.abc import Iterable
from pathlib import Path

from PIL import Image

from astrbot.api import logger

from .config import PluginConfig
from .models import HelpMode


class RenderCache:
    """Cache one rendered WebP image for each static help mode."""

    PREFIX = "help_typst_mode_cache_"

    def __init__(self, config: PluginConfig):
        self.cfg = config
        self.data_dir = config.data_dir

    def build_key(self, content: str, logo_paths: Iterable[Path]) -> str:
        """Calculate a cache key for the rendered content and assets"""
        files = {
            self.cfg.template_path.resolve(),
            Path(__file__).with_name("renderer.py").resolve(),
        }
        if self.cfg.font_dir.is_dir():
            files.update(
                path.resolve()
                for path in self.cfg.font_dir.rglob("*")
                if path.is_file()
            )
        files.update(path.resolve() for path in logo_paths)

        hasher = hashlib.blake2s()
        hasher.update(content.encode("utf-8"))
        hasher.update(str(self.cfg.ppi).encode("ascii"))
        for path in sorted(files):
            stat = path.stat()
            hasher.update(str(path).encode("utf-8"))
            hasher.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode("ascii"))
        return hasher.hexdigest()

    def get(self, mode: HelpMode, key: str) -> Path | None:
        """Return a valid cached image when its key matches"""
        image_path = self.data_dir / f"{self.PREFIX}{mode}_0000.webp"
        hash_path = self.data_dir / f"{self.PREFIX}{mode}.hash"
        try:
            if hash_path.read_text(encoding="ascii") != key:
                return None
            with Image.open(image_path) as image:
                if image.format != "WEBP":
                    raise ValueError("Cached output must be WebP")
                image.verify()
            return image_path
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            image_path.unlink(missing_ok=True)
            hash_path.unlink(missing_ok=True)
            return None

    def store(self, mode: HelpMode, key: str, source: Path) -> Path | None:
        """Replace the cached image for a help mode"""
        image_path = self.data_dir / f"{self.PREFIX}{mode}_0000.webp"
        hash_path = self.data_dir / f"{self.PREFIX}{mode}.hash"
        try:
            hash_path.unlink(missing_ok=True)
            shutil.copyfile(source, image_path)
            hash_path.write_text(key, encoding="ascii")
        except OSError as exc:
            logger.warning(f"Failed to write help render cache: {exc}")
            return None
        return image_path

    def deliver(self, source: Path) -> str:
        """Copy an image to a unique temporary path for message sending"""
        target = self.cfg.temp_dir / f"help_typst_delivery_{uuid.uuid4().hex}.webp"
        try:
            shutil.copyfile(source, target)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return str(target)
