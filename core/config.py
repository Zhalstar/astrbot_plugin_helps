from collections.abc import Mapping, MutableMapping
from functools import cached_property
from pathlib import Path
from types import MappingProxyType, UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from PIL import ImageFont

from astrbot.api import AstrBotConfig, logger
from astrbot.core.star.context import Context
from astrbot.core.utils.astrbot_path import (
    get_astrbot_plugin_data_path,
    get_astrbot_plugin_path,
    get_astrbot_temp_path,
)


class ConfigNode:
    _SCHEMA_CACHE: dict[type, dict[str, type]] = {}
    _FIELDS_CACHE: dict[type, set[str]] = {}

    @classmethod
    def _schema(cls) -> dict[str, type]:
        return cls._SCHEMA_CACHE.setdefault(cls, get_type_hints(cls))

    @classmethod
    def _fields(cls) -> set[str]:
        return cls._FIELDS_CACHE.setdefault(
            cls,
            {k for k in cls._schema() if not k.startswith("_")},
        )

    @staticmethod
    def _is_optional(tp: type) -> bool:
        if get_origin(tp) in (Union, UnionType):
            return type(None) in get_args(tp)
        return False

    def __init__(self, data: MutableMapping[str, Any]):
        object.__setattr__(self, "_data", data)
        object.__setattr__(self, "_children", {})
        for key, tp in self._schema().items():
            if key.startswith("_"):
                continue
            if key in data:
                continue
            if hasattr(self.__class__, key):
                continue
            if self._is_optional(tp):
                continue
            logger.warning(f"[config:{self.__class__.__name__}] miss key: {key}")

    def __getattr__(self, key: str) -> Any:
        if key in self._fields():
            value = self._data.get(key)
            tp = self._schema().get(key)

            if isinstance(tp, type) and issubclass(tp, ConfigNode):
                children: dict[str, ConfigNode] = self.__dict__["_children"]
                if key not in children:
                    if not isinstance(value, MutableMapping):
                        raise TypeError(
                            f"[config:{self.__class__.__name__}] "
                            f"key {key} need dict but {type(value).__name__}"
                        )
                    children[key] = tp(value)
                return children[key]

            return value

        if key in self.__dict__:
            return self.__dict__[key]

        raise AttributeError(key)

    def __setattr__(self, key: str, value: Any) -> None:
        if key in self._fields():
            self._data[key] = value
            return
        object.__setattr__(self, key, value)

    def raw_data(self) -> Mapping[str, Any]:
        return MappingProxyType(self._data)

    def save_config(self) -> None:

        if not isinstance(self._data, AstrBotConfig):
            raise RuntimeError(
                f"{self.__class__.__name__}.save_config() only support AstrBotConfig"
            )
        self._data.save_config()


class RenderingConfig(ConfigNode):
    giant_threshold: int
    ppi: float


class PluginConfig(ConfigNode):
    ignored_plugins: list[str]
    rendering: RenderingConfig

    _plugin_name = "astrbot_plugin_helps"

    def __init__(self, config: AstrBotConfig, context: Context):
        super().__init__(config)
        self.context = context
        self.plugin_dir = Path(get_astrbot_plugin_path()) / self._plugin_name
        self.data_dir = Path(get_astrbot_plugin_data_path()) / self._plugin_name
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = Path(get_astrbot_temp_path())
        self.template_path = self.plugin_dir / "templates" / "base.typ"
        self.font_dir = self.plugin_dir / "fonts"
        self.prefixes: list[str] = self._get_prefixes()

    @cached_property
    def font_families(self) -> tuple[str, ...]:
        """Read Typst font family names from the bundled font files.

        Returns:
            Unique font family names in deterministic file order.

        Raises:
            RuntimeError: If the font directory contains no readable fonts.
        """
        families = []
        font_paths = sorted(
            (
                path
                for path in self.font_dir.rglob("*")
                if path.is_file() and path.suffix.lower() in {".ttf", ".otf", ".ttc"}
            ),
            key=lambda path: str(path.relative_to(self.font_dir)).lower(),
        )
        for path in font_paths:
            try:
                family = ImageFont.truetype(str(path), 12).getname()[0]
            except OSError as exc:
                logger.warning(f"[HelpTypst] Failed to read font {path}: {exc}")
                continue
            if family and family not in families:
                families.append(family)

        if not families:
            raise RuntimeError(f"No readable fonts found in {self.font_dir}")
        return tuple(families)

    def _get_prefixes(self) -> list[str]:
        raw = self.context.get_config().get("wake_prefix", ["/"])
        return [raw] if isinstance(raw, str) else list(raw)
