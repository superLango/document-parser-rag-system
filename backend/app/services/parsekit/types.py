"""parsekit 数据类型与常量。"""

from __future__ import annotations

from dataclasses import dataclass, field

BLOCK_TYPES = frozenset(
    {
        "title",
        "text",
        "table",
        "formula",
        "image",
        "image_caption",
        "table_caption",
        "page_title",
        "page_number",
        "header",
        "footer",
        "list_item",
        "aside_text",
        "footnote",
    }
)


@dataclass(slots=True)
class BBox:
    """页面坐标边界框（点坐标，y 向下）。"""

    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        self.x0, self.x1 = min(self.x0, self.x1), max(self.x0, self.x1)
        self.y0, self.y1 = min(self.y0, self.y1), max(self.y0, self.y1)

    @property
    def width(self) -> float:
        return max(self.x1 - self.x0, 0.0)

    @property
    def height(self) -> float:
        return max(self.y1 - self.y0, 0.0)

    @property
    def area(self) -> float:
        return self.width * self.height

    def normalized(self, width: float, height: float) -> BBox:
        w = max(width, 1.0)
        h = max(height, 1.0)
        return BBox(
            max(0.0, min(1.0, self.x0 / w)),
            max(0.0, min(1.0, self.y0 / h)),
            max(0.0, min(1.0, self.x1 / w)),
            max(0.0, min(1.0, self.y1 / h)),
        )

    def as_list(self) -> list[float]:
        return [self.x0, self.y0, self.x1, self.y1]

    def overlap_ratio(self, other: BBox) -> float:
        """本框被 other 覆盖的面积占比（0..1）。"""
        if self.area <= 0:
            return 0.0
        ox0, oy0 = max(self.x0, other.x0), max(self.y0, other.y0)
        ox1, oy1 = min(self.x1, other.x1), min(self.y1, other.y1)
        inter = max(ox1 - ox0, 0.0) * max(oy1 - oy0, 0.0)
        return inter / self.area


@dataclass(slots=True)
class TextBlock:
    """PDF 文本层提取的块。"""

    text: str
    bbox: BBox
    font_size: float = 0.0
    font_name: str = ""
    flags: int = 0
    page_index: int = 0
    erased: bool = False


@dataclass(slots=True)
class LayoutBlock:
    """版面块（bbox 归一化 0..1）。"""

    type: str
    bbox: BBox
    page_index: int = 0
    order: int = 0
    confidence: float = 1.0
    content: str = ""
    # U9 预留字段：后续分块入库/结构化抽取时使用
    path: str | None = None
    title: str | None = None
    structural: dict | None = None
    source: str = "rule"


@dataclass(slots=True)
class RenderPage:
    """单页渲染产物。"""

    page_index: int
    width: float
    height: float
    image_bytes: bytes
    text_blocks: list[TextBlock] = field(default_factory=list)
    image_boxes: list[BBox] = field(default_factory=list)


@dataclass(slots=True)
class RenderResult:
    """PDF 渲染结果（支持单页失败 partial，U11）。"""

    pages: list[RenderPage]
    failures: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class ErasedBlock:
    """被页眉页脚擦除的块记录（供 A/B 评测）。"""

    page_index: int
    bbox: BBox
    text: str
    reason: str
    strategy: str


@dataclass(slots=True)
class EraseResult:
    """页眉页脚擦除结果。"""

    pages: list[list[TextBlock]]
    erased: list[ErasedBlock] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
