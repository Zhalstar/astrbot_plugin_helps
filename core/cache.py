"""Disk cache for rendered help images."""

import hashlib
import shutil
import uuid
from pathlib import Path

from PIL import Image

from .config import PluginConfig
from .models import HelpMode


class RenderCache:
    """Cache one rendered WebP image for each static help mode."""

    PREFIX = "help_typst_mode_cache_"

    def __init__(self, config: PluginConfig):
        self.cfg = config
        self.data_dir = config.data_dir

    def build_key(self, content: str, ppi: float) -> str:
        """Calculate a cache key for the rendered content and assets.

        Args:
            content: Serialized layout JSON.
            ppi: Typst rasterization resolution.

        Returns:
            A stable BLAKE2s hash for the rendering input.
        """
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

        hasher = hashlib.blake2s()
        hasher.update(content.encode("utf-8"))
        hasher.update(str(ppi).encode("ascii"))
        for path in sorted(files):
            stat = path.stat()
            hasher.update(str(path).encode("utf-8"))
            hasher.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode("ascii"))
        return hasher.hexdigest()

    def get(self, mode: HelpMode, key: str) -> Path | None:
        """Return a valid cached image when its key matches.

        Args:
            mode: Help mode associated with the cached image.
            key: Expected cache key.

        Returns:
            Cached image path, or ``None`` on a miss.
        """
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

    def store(self, mode: HelpMode, key: str, source: Path) -> Path:
        """Replace the cached image for a help mode.

        Args:
            mode: Help mode associated with the rendered image.
            key: Cache key for the rendered image.
            source: Newly rendered WebP image.

        Returns:
            Cached image path.
        """
        image_path = self.data_dir / f"{self.PREFIX}{mode}_0000.webp"
        hash_path = self.data_dir / f"{self.PREFIX}{mode}.hash"
        hash_path.unlink(missing_ok=True)
        try:
            shutil.copyfile(source, image_path)
            hash_path.write_text(key, encoding="ascii")
        except Exception:
            image_path.unlink(missing_ok=True)
            raise
        return image_path

    def deliver(self, source: Path) -> str:
        """Copy an image to a unique temporary path for message sending.

        Args:
            source: Cached or newly rendered WebP image.

        Returns:
            Temporary image path.
        """
        target = self.cfg.temp_dir / f"help_typst_delivery_{uuid.uuid4().hex}.webp"
        try:
            shutil.copyfile(source, target)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return str(target)
