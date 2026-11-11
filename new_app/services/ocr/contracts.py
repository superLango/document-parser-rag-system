from pydantic import BaseModel, Field


class OcrRequest(BaseModel):
    document_id: str
    storage_key: str
    filename: str
    content_type: str = "application/octet-stream"
    backend: str | None = None


class DocumentMeta(BaseModel):
    file_name: str = ""
    title: str = ""
    standard_no: str | None = None


class Page(BaseModel):
    page_no: int
    width: float = 0.0
    height: float = 0.0
    dpi: int = 0
    markdown: str = ""
    image_key: str | None = None
    layout_key: str | None = None


class Merge(BaseModel):
    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1
    text: str = ""
    is_header: bool = False


class TableBlock(BaseModel):
    block_id: str
    start_row: int
    header_rows: int = 1
    header_paths: list[list[str]] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class TableGrid(BaseModel):
    table_id: str
    page_no: int
    caption: str | None = None
    context: str | None = None
    profile: str = "unknown"
    orientation: str = "grade_rows"
    n_rows: int = 0
    n_cols: int = 0
    header_rows: int = 1
    header_paths: list[list[str]] = Field(default_factory=list)
    units: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    blocks: list[TableBlock] = Field(default_factory=list)
    bbox: list[float] | None = None
    merges: list[Merge] = Field(default_factory=list)
    footnotes: list[str] = Field(default_factory=list)
    raw_html: str = ""
    continuation_of: str | None = None
    merged_pages: list[int] = Field(default_factory=list)


class LayoutBlock(BaseModel):
    block_id: str
    page_no: int = 0
    type: str
    bbox: list[float] = Field(default_factory=list)
    text: str = ""


class ArtifactRef(BaseModel):
    key: str
    sha256: str
    bytes: int
    content_type: str


class OcrResult(BaseModel):
    document_id: str
    backend: str
    pages: list[Page] = Field(default_factory=list)
    markdown: str = ""
    tables: list[TableGrid] = Field(default_factory=list)
    layout: list[LayoutBlock] = Field(default_factory=list)
    quality: float = 1.0
    warnings: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
