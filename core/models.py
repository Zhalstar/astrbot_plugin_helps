from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from astrbot.core.star.star import StarMetadata
from astrbot.core.star.star_handler import EventType

HelpMode = Literal["command", "event", "filter"]
HELP_MODES: frozenset[HelpMode] = frozenset({"command", "event", "filter"})

EVENT_TYPE_MAP: dict[EventType, str] = {
    EventType.OnAstrBotLoadedEvent: "系统启动 (Loaded)",
    EventType.OnPlatformLoadedEvent: "平台就绪 (Platform)",
    EventType.AdapterMessageEvent: "消息监听 (Message)",
    EventType.OnLLMRequestEvent: "LLM 请求前 (Pre-LLM)",
    EventType.OnLLMResponseEvent: "LLM 响应后 (Post-LLM)",
    EventType.OnDecoratingResultEvent: "消息修饰 (Decorate)",
    EventType.OnAfterMessageSentEvent: "发送回执 (Sent)",
}


class RenderNode(BaseModel):
    """
    通用渲染节点：
    - 在指令模式下：代表 指令组 或 指令
    - 在事件模式下：代表 事件类型分组 或 具体Handler
    """

    model_config = ConfigDict(
        use_enum_values=True,
        extra="ignore",  # 防御多余字段
    )

    name: str = Field(default="", description="显示名称")
    desc: str = Field(default="", description="描述文本")

    # 样式控制字段
    is_group: bool = Field(default=False, description="是否为容器/分组")
    tag: str = Field(default="normal", description="标记类型: normal/admin/event")
    priority: int | None = Field(default=None, description="事件监听优先级")

    # 递归定义
    children: list["RenderNode"] = Field(default_factory=list, description="子节点")


class PluginMetadata(BaseModel):
    """插件元数据容器"""

    model_config = ConfigDict(use_enum_values=True, extra="ignore")

    name: str = Field(default="", description="插件ID")
    display_name: str = Field(default="", description="展示名称")
    author: str = Field(default="", description="作者")
    desc: str = Field(default="", description="描述")
    short_desc: str = Field(default="", description="短描述")
    version: str = Field(default="", description="版本号")
    repo: str = Field(default="", description="仓库地址")
    logo_path: str = Field(default="", description="Logo 路径")
    astrbot_version: str = Field(default="", description="AstrBot 版本要求")
    module_path: str = Field(default="", description="插件模块路径")
    root_dir_name: str = Field(default="", description="插件目录名")
    support_platforms: list[str] = Field(default_factory=list)
    activated: bool = Field(default=True, description="是否已启用")

    nodes: list[RenderNode] = Field(default_factory=list)

    @classmethod
    def from_star(
        cls,
        metadata: StarMetadata,
        nodes: list[RenderNode] | None = None,
    ) -> "PluginMetadata":
        """Create normalized render metadata from AstrBot plugin metadata.

        Args:
            metadata: AstrBot plugin metadata to read.
            nodes: Optional render nodes associated with the plugin.

        Returns:
            Plugin metadata with missing text values normalized to empty strings.
        """
        return cls(
            name="" if metadata.name is None else str(metadata.name),
            display_name=(
                "" if metadata.display_name is None else str(metadata.display_name)
            ),
            author="" if metadata.author is None else str(metadata.author),
            desc="" if metadata.desc is None else str(metadata.desc),
            short_desc=(
                "" if metadata.short_desc is None else str(metadata.short_desc)
            ),
            version="" if metadata.version is None else str(metadata.version),
            repo="" if metadata.repo is None else str(metadata.repo),
            logo_path=("" if metadata.logo_path is None else str(metadata.logo_path)),
            astrbot_version=(
                ""
                if metadata.astrbot_version is None
                else str(metadata.astrbot_version)
            ),
            module_path=(
                "" if metadata.module_path is None else str(metadata.module_path)
            ),
            root_dir_name=(
                "" if metadata.root_dir_name is None else str(metadata.root_dir_name)
            ),
            support_platforms=[str(item) for item in metadata.support_platforms],
            activated=metadata.activated,
            nodes=[] if nodes is None else nodes,
        )


@dataclass(slots=True)
class RenderJob:
    """Input and output data for one help render operation."""

    mode: HelpMode
    plugins: list[PluginMetadata]
    title: str
    query: str = ""
    images: list[str] = field(default_factory=list, init=False)
