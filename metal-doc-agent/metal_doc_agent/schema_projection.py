"""Project pipeline artifacts onto an external schema template.

The engine artifacts stay the source of truth. This module maps the extracted
inventory/records/clauses onto a schema template (categories + fields) and
reports filled/missing fields. It never invents values: anything the artifacts
do not contain is left empty and counted as a gap.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any

from .canonicalize.dictionary import (
    DictionaryIndex,
    JsonDictionaryAdapter,
    load_dictionary_path,
)
from .contracts import (
    ClassificationItem,
    ClauseRecord,
    DocumentMeta,
    InspectionItem,
    ItemInventory,
    ItemInventoryEntry,
    PropertyMatch,
    Record,
)
from .tablegrid.normalize import (
    canonical_element,
    canonical_property,
    is_footnote_row,
    looks_like_grade,
)

YEAR_RE = re.compile(r"-(?:19|20)\d{2}$")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
BATCH_QUANTITY_RE = re.compile(
    r"(?:每\s*批|每\s*炉|同一炉|同一批|每一?\s*炉号|每一?\s*锻件|每张钢板|"
    r"每\s*\d*\s*(?:件|根|支|张)|逐件|逐批|全检)"
)
BATCH_ONCE_RE = re.compile(r"每\s*(?:批|炉|根|件)\s*(?:一|1)\s*次")
DRAWN_COUNT_RE = re.compile(
    r"(?:抽取|抽|取)\s*(\d+)\s*(?:个|件|支|根|组|块|张)"
)
UNIT_COUNT_RE = re.compile(r"(\d+)\s*(?:个|件|支|根|组|块|张)")
DIRECTIONS = {"切向", "径向", "轴向", "纵向", "横向", "轧向", "锻向", "弦向"}
PAREN_RE = re.compile(r"[（(]\s*([^）)]+?)\s*[）)]")
UNIT_SUFFIX_RE = re.compile(
    r"\s*/\s*(?:%|MPa|GPa|J|HBW?|HRC|HV|mm|℃|°C)\s*$", re.IGNORECASE
)
NUMERIC_REQUIREMENT_RE = re.compile(
    r"^\s*[≥≤<>]\s*\d|^\s*\d+(?:\.\d+)?\s*[~～\-]\s*\d"
)
TEMPERATURE_RE = re.compile(
    r"(?<![\d.])(-?\d+(?:\.\d+)?(?:\s*[~～\-]\s*\d+(?:\.\d+)?)?)\s*℃"
)
THICKNESS_CONDITION_RE = re.compile(
    r"^(?:[<>≤≥]\s*)?\d+(?:\.\d+)?(?:\s*[~～\-]\s*\d+(?:\.\d+)?)?$"
)
STATE_CODE_RE = re.compile(r"^[A-Za-z]{1,3}\d")
STATE_WORDS = (
    "热轧",
    "正火",
    "退火",
    "淬火",
    "回火",
    "时效",
    "固溶",
    "铸态",
    "锻态",
    "冷轧",
    "热机械轧制",
)


@dataclass
class SchemaField:
    name: str
    type: str = "string"
    required: bool = True
    description: str = ""
    example: str | None = None
    required_when: str | None = None


@dataclass
class SchemaCategory:
    key: str
    name: str
    display_name: str
    return_type: str
    fields: list[SchemaField] = dataclass_field(default_factory=list)
    name_source: str = "manual"
    name_term_field: str = ""
    fixed_query: str = ""


@dataclass
class SchemaTemplate:
    name: str
    source: str
    template_id: str = ""
    slim: bool = False
    categories: list[SchemaCategory] = dataclass_field(default_factory=list)


def load_template(path: str | Path) -> SchemaTemplate:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    categories = []
    for raw in payload.get("categories", []):
        categories.append(
            SchemaCategory(
                key=raw["key"],
                name=raw.get("name", ""),
                display_name=raw.get("display_name") or raw.get("name") or raw["key"],
                return_type=raw.get("return_type", "array"),
                name_source=raw.get("name_source", "manual"),
                name_term_field=raw.get("name_term_field", ""),
                fixed_query=raw.get("fixed_query", ""),
                fields=[
                    SchemaField(
                        name=field["name"],
                        type=field.get("type", "string"),
                        required=bool(field.get("required", True)),
                        description=field.get("description", ""),
                        example=field.get("example"),
                        required_when=field.get("required_when"),
                    )
                    for field in raw.get("fields", [])
                ],
            )
        )
    return SchemaTemplate(
        name=payload.get("name", "schema"),
        source=payload.get("source", str(path)),
        template_id=payload.get("template_id", ""),
        slim=bool(payload.get("slim", False)),
        categories=categories,
    )


def load_dictionary_index(root: str | Path | None = None) -> DictionaryIndex | None:
    base = Path(root or Path(__file__).resolve().parents[1])
    split_dir = base / "configs" / "dictionaries"
    if split_dir.is_dir():
        try:
            dictionary = load_dictionary_path(split_dir)
            return DictionaryIndex.build(_with_learned(dictionary, base))
        except Exception:  # noqa: BLE001 - keep projection resilient
            pass
    snapshot = base / "configs" / "business_dictionary.hanson.json"
    if not snapshot.exists():
        return None
    override = base / "configs" / "business_dictionary.local.json"
    adapter = JsonDictionaryAdapter(snapshot, override if override.exists() else None)
    return DictionaryIndex.build(_with_learned(adapter.load(), base))


def _with_learned(dictionary, base: Path):
    try:
        from .selfheal.lexicon import apply_learned_lexicon

        return apply_learned_lexicon(dictionary, base)
    except Exception:  # noqa: BLE001 - learned overlay is optional
        return dictionary


def load_dictionary_index_path(path: str | Path | None) -> DictionaryIndex | None:
    if not path:
        return None
    snapshot = Path(path)
    if not snapshot.exists():
        return None
    try:
        dictionary = load_dictionary_path(snapshot)
    except Exception:  # noqa: BLE001 - keep projection resilient
        return None
    return DictionaryIndex.build(dictionary)


def load_qualitative_requirements(
    root: str | Path | None = None,
) -> dict[str, dict[str, list[str]]]:
    base = Path(root or Path(__file__).resolve().parents[1])
    path = base / "configs" / "qualitative_requirements.json"
    if not path.exists():
        return {}
    payload = _read_json(path)
    documents = payload.get("documents") or {}
    return {
        str(standard): {
            str(keyword): [str(clause_id) for clause_id in clause_ids]
            for keyword, clause_ids in (mapping or {}).items()
        }
        for standard, mapping in documents.items()
    }


def load_sampling_defaults(
    root: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    base = Path(root or Path(__file__).resolve().parents[1])
    path = base / "configs" / "sampling_defaults.json"
    if not path.exists():
        return {}
    payload = _read_json(path)
    return {
        str(family): dict(values or {})
        for family, values in (payload.get("families") or {}).items()
    }


_SAMPLING_DEFAULTS: dict[str, dict[str, Any]] | None = None


def _sampling_default(family: str) -> dict[str, Any] | None:
    global _SAMPLING_DEFAULTS
    if _SAMPLING_DEFAULTS is None:
        _SAMPLING_DEFAULTS = load_sampling_defaults()
    return _SAMPLING_DEFAULTS.get(family)


def project_job(
    job_dir: str | Path,
    template: SchemaTemplate,
    *,
    index: DictionaryIndex | None = None,
) -> dict[str, Any]:
    root = Path(job_dir)
    raw_result = _read_json(root / "result.json")
    inventory = _load_inventory(root)
    outline = _read_json(root / "outline.json") if (root / "outline.json").exists() else {}
    index = index if index is not None else load_dictionary_index()

    document = DocumentMeta.model_validate(raw_result.get("document") or {})
    records = [Record.model_validate(row) for row in raw_result.get("records") or []]
    inspections = [
        InspectionItem.model_validate(row)
        for row in raw_result.get("inspection_items") or []
    ]
    classifications = [
        ClassificationItem.model_validate(row)
        for row in raw_result.get("classification_items") or []
    ]
    clauses = [ClauseRecord.model_validate(row) for row in raw_result.get("clauses") or []]
    standard_name = _standard_name(document, outline)
    qualitative = load_qualitative_requirements().get(document.standard_no or "", {})

    builders = {
        "items": lambda cat: _build_items(
            cat,
            inventory,
            records,
            inspections,
            classifications,
            clauses,
            index,
            standard_name,
            qualitative,
        ),
        "standard_info": lambda cat: _build_standard_info(cat, document, standard_name),
        "heat_treatment": lambda cat: _build_heat_treatment(cat, clauses, classifications),
    }

    categories: list[dict[str, Any]] = []
    notes: list[str] = []
    for category in template.categories:
        builder = builders.get(category.key)
        if builder is None:
            rows, meta, note = [], [], f"未实现的 schema 类别：{category.key}"
        else:
            rows, meta, note = builder(category)
        if note:
            notes.append(note)
        categories.append(
            {
                "key": category.key,
                "name": category.name,
                "display_name": category.display_name,
                "return_type": category.return_type,
                "rows": rows,
                "meta": meta,
                "note": note,
                "applicable": bool(rows),
            }
        )

    errors = _validate(categories, template.categories)
    coverage = _coverage(categories, template.categories)
    return {
        "schema_version": "0.1.0",
        "template": template.name,
        "template_source": template.source,
        "doc_id": document.doc_id,
        "document": {
            "file_name": document.file_name,
            "standard_no": document.standard_no,
            "title": document.title,
        },
        "categories": categories,
        "coverage": coverage,
        "errors": errors,
        "notes": notes,
    }


# ------------------------------------------------- hansonDoc 精简投影

HANSON_STANDARD_FIELDS = ("标准名称", "标准编号")
HANSON_ITEM_CORE = ("项目名称", "材料牌号", "标准要求")
HANSON_ITEM_FIELDS = (
    "项目名称",
    "位置",
    "单位",
    "标准要求",
    "方向",
    "尺寸厚度",
    "试样状态",
    "取样数量",
    "取样说明",
    "锻件类型",
    "试验温度",
    "材料牌号",
    "试验方法",
)
HANSON_HEAT_FIELDS = (
    "材料牌号",
    "工艺名称",
    "保温温度",
    "保温时间",
    "冷却介质",
    "工序名称",
    "介质温度",
    "装炉温度",
    "升温速率",
    "降温速率",
    "出炉温度",
    "项目大类",
)
HANSON_HEAT_CORE = ("材料牌号", "工序名称", "保温温度", "保温时间")
HANSON_FEATURE_ORDER = (
    "化学成分",
    "室温拉伸",
    "高温拉伸",
    "低温拉伸",
    "高温光滑持久",
    "室温持久",
    "夏比冲击",
    "布氏硬度",
    "洛氏硬度",
    "维氏硬度",
    "低倍",
    "高倍组织",
    "超声波检测",
    "渗透检测",
    "射线检测",
    "外观质量",
    "尺寸",
)
HANSON_GENERIC_SAMPLING = {"", "一", "整根", "-", "—", "/"}
HANSON_DIRECTIONS = ("纵向", "横向", "切向", "径向", "轴向", "弦向", "高向", "轧向", "锻向")
HANSON_PRODUCT_FORMS = ("棒材", "锻件", "板材", "管材", "型材", "线材", "丝材", "带材", "箔材")
HANSON_HARDNESS = {"brinell": "布氏硬度", "rockwell": "洛氏硬度", "vickers": "维氏硬度"}
HANSON_PROPERTY_NAMES = {
    "Rm": "抗拉强度",
    "Rp0.2": "规定塑性延伸强度",
    "ReH": "屈服强度",
    "A": "断后伸长率",
    "A50mm": "断后伸长率(A50mm)",
    "Z": "断面收缩率",
    "KV2": "冲击吸收能量",
    "HB": "布氏硬度",
    "HRC": "洛氏硬度",
    "HRB": "洛氏硬度",
    "HV": "维氏硬度",
    "E": "弹性模量",
    "KIC": "断裂韧度",
    "σ100h": "持久强度σ100h",
    "σ50h": "持久强度σ50h",
    "σ35h": "持久强度σ35h",
}
# Property semantics define the unit; a mis-bound column must not label a
# 958 MPa proof strength as "%".
PROPERTY_UNITS = {
    "Rm": "MPa",
    "Rp0.2": "MPa",
    "ReH": "MPa",
    "ReL": "MPa",
    "A": "%",
    "A50mm": "%",
    "Z": "%",
}
HANSON_MECHANICAL_PROFILES = {"mechanical_properties"}
HANSON_HEAT_OPTIONAL = (
    "工艺名称",
    "冷却介质",
    "装炉温度",
    "出炉温度",
    "升温速率",
    "降温速率",
    "介质温度",
)
HANSON_HEAT_TEMPERATURE_RE = re.compile(
    r"\d+(?:\.\d+)?\s*℃(?:\s*[~～-]\s*\d+(?:\.\d+)?\s*℃)?"
    r"(?:\s*±\s*\d+(?:\.\d+)?\s*℃)?"
)
HANSON_HEAT_TIME_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:h|min)(?:\s*[~-]\s*\d+(?:\.\d+)?\s*(?:h|min))?"
)
HANSON_COOLING_RE = re.compile(r"(空冷|水冷|炉冷|油冷)")
STANDARD_TITLE_PRODUCT_TERMS = (
    "棒材",
    "板材",
    "管材",
    "型材",
    "线材",
    "丝材",
    "带材",
    "箔材",
    "锻件",
    "铸件",
    "合金",
    "钢材",
)
STANDARD_TITLE_BOILERPLATE = (
    "目次",
    "目录",
    "前言",
    "范围",
    "引用标准",
    "规范性引用文件",
    "术语",
    "定义",
    "符号",
    "订货合同",
    "标记示例",
    "技术要求",
    "试验方法",
    "检验规则",
    "标志",
    "包装",
    "运输",
    "贮存",
)
STANDARD_TITLE_NUMBER_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*(?:\s|$)")
METHOD_REFERENCE_RE = re.compile(
    r"(?:GB\s*/\s*T|GB/T|GB|HB|YB|Q\s*/\s*[A-Za-z]+|Q/[A-Za-z]+)"
    r"\s*\d+(?:\.\d+)*(?:\s*-\s*\d{2,4})?"
)
DOCUMENT_METHOD_REF_RE = re.compile(
    r"(?:GB\s*/\s*T|GB|GJB|JB\s*/\s*T|YB\s*/\s*T|NB\s*/\s*T|"
    r"ASTM|ISO|JIS|EN|DIN|API|ASME|AMS)"
    r"\s*[A-Z]?\s*\d+(?:\.\d+)*[A-Z]?(?:\s*-\s*\d{1,4})?"
)
METHOD_FAMILY_KEYWORDS = {
    "chemical_composition": (
        "化学成分", "化学分析", "溶鋼分析", "製品分析", "化学組成"
    ),
    "tensile": (
        "金属拉伸", "拉伸试验", "室温拉伸", "力学性能", "机械性能",
        "引張", "引张",
    ),
    "impact": ("冲击", "夏比", "衝撃", "シャルピー"),
    "hardness": (
        "硬度", "布氏", "洛氏", "维氏", "硬さ", "ロックウエル",
        "ブリネル", "ビッカース",
    ),
    "stress_rupture": ("持久", "蠕变", "クリープ"),
    "metallography": (
        "低倍", "显微组织", "高倍", "组织", "結晶粒度", "組織",
    ),
    "ndt": ("超声", "无损", "超音波", "放射線", "浸透"),
    "dimension": ("尺寸", "外形", "寸法", "外径", "厚さ"),
    "surface": ("表面", "外观"),
    "bend": ("弯曲", "曲げ"),
}


DOCUMENT_METHOD_FAMILIES = {
    "chemical_composition",
    "tensile",
    "impact",
}


def _document_method_index(root: Path) -> dict[str, str]:
    """Find one method reference per family from the whole document text.

    Clause extraction drops some reference-list bodies when OCR splits them on
    ``#`` headings. The pages artifact still has the full text, so use it as a
    conservative fallback: the standard number must be present in the document
    and the following label must name the family (拉伸/冲击/化学分析/...).
    """

    path = root / "pages.json"
    if not path.exists():
        return {}
    try:
        pages = _read_json(path)
    except (OSError, ValueError):
        return {}
    text = " ".join(
        str(page.get("markdown") or "") for page in pages if isinstance(page, dict)
    )
    if not text:
        return {}
    best: dict[str, tuple[int, int, int, str]] = {}
    for match in DOCUMENT_METHOD_REF_RE.finditer(text):
        reference = re.sub(r"\s*-\s*", "-", match.group(0))
        label = _method_reference_label(
            text, match.end(), DOCUMENT_METHOD_REF_RE
        )
        for family, keywords in METHOD_FAMILY_KEYWORDS.items():
            if family not in DOCUMENT_METHOD_FAMILIES:
                continue
            if not any(keyword in label for keyword in keywords):
                continue
            dated = 1 if YEAR_RE.search(reference) else 0
            preference = 0
            if family == "tensile":
                if any(word in label for word in ("高温", "低温")):
                    preference = -1
                elif any(word in label for word in ("室温", "常温")):
                    preference = 1
            candidate = (dated, preference, -match.start(), reference)
            if family not in best or candidate > best[family]:
                best[family] = candidate
    return {family: value[3] for family, value in best.items()}


def project_hanson_schema(
    job_dir: str | Path,
    template: SchemaTemplate,
    *,
    index: DictionaryIndex | None = None,
    timing_seconds: float = 0.0,
    records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Project engine artifacts onto the slim hansonDoc_RAG result schema.

    Only three blocks are produced: 标准信息, the item categories that actually
    occur in this document, and 热处理制度 when heat-treatment data exists.
    Optional fields are written only when they have a value.

    ``records`` overrides ``result.json`` records so reviewed values flow into
    the exported structure.
    """

    root = Path(job_dir)
    raw_result = _read_json(root / "result.json")
    inventory = _load_inventory(root)
    outline = _read_json(root / "outline.json") if (root / "outline.json").exists() else {}
    index = index if index is not None else load_dictionary_index()

    document = DocumentMeta.model_validate(raw_result.get("document") or {})
    record_rows = records if records is not None else raw_result.get("records") or []
    parsed_records = [Record.model_validate(row) for row in record_rows]
    inspections = [
        InspectionItem.model_validate(row)
        for row in raw_result.get("inspection_items") or []
    ]
    classifications = [
        ClassificationItem.model_validate(row)
        for row in raw_result.get("classification_items") or []
    ]
    clauses = [ClauseRecord.model_validate(row) for row in raw_result.get("clauses") or []]
    tables = {
        str(table.get("table_id")): table
        for table in raw_result.get("tables") or []
    }
    from .cross_standard_expand import load_merge_entries

    external_entries = load_merge_entries(root)
    standard_name = _standard_name(document, outline)
    qualitative = load_qualitative_requirements().get(document.standard_no or "", {})

    categories: list[dict[str, Any]] = [
        _hanson_category(
            "标准信息",
            [
                {
                    "标准名称": standard_name or "",
                    "标准编号": document.standard_no or "",
                }
            ],
            HANSON_STANDARD_FIELDS,
        )
    ]
    applicability = _hanson_applicability(inspections, inventory, tables)
    if not applicability["applicable"]:
        return {
            "schema_template_id": template.template_id
            or "6e2ad0d7-f92a-4663-b5cf-ae01c2378fa7",
            "schema_name": template.name,
            "categories": categories,
            "summary": {
                "total_records": 1,
                "kept_categories": 1,
                "effective_rows": 0,
            },
            "timing": {"total_sec": round(float(timing_seconds or 0.0), 2)},
            "applicability": applicability,
            "notes": [
                "文档缺少检验项目/取样数量表，未套用产品标准抽取模板。"
            ],
        }
    pages_path = Path(job_dir) / "pages.json"
    page_text = ""
    if pages_path.exists():
        page_text = "\n".join(
            page.get("markdown") or ""
            for page in json.loads(pages_path.read_text(encoding="utf-8"))
        )
    item_categories, expansions = _hanson_item_categories(
        inventory,
        parsed_records,
        inspections,
        classifications,
        clauses,
        tables,
        index=index,
        standard_name=standard_name,
        qualitative=qualitative,
        source_text=f"{document.file_name} {document.title or ''}",
        method_index=_document_method_index(root),
        external=external_entries,
        pages_text=page_text,
    )
    categories.extend(item_categories)
    heat = _hanson_heat_records(
        clauses, classifications, raw_result.get("tables") or []
    )
    if heat:
        categories.append(
            _hanson_category(
                "热处理制度",
                heat,
                HANSON_HEAT_CORE,
                fields=HANSON_HEAT_FIELDS,
            )
        )

    _fill_missing_grades(categories, _grade_hint_from_pages(Path(job_dir)))
    _dedupe_categories_after_fill(categories)
    return {
        "schema_template_id": template.template_id
        or "6e2ad0d7-f92a-4663-b5cf-ae01c2378fa7",
        "schema_name": template.name,
        "categories": categories,
        "expanded_requirements": expansions,
        "summary": {
            "total_records": sum(len(category["records"]) for category in categories),
            "kept_categories": len(categories),
            "effective_rows": _hanson_effective_rows(categories),
        },
        "timing": {"total_sec": round(float(timing_seconds or 0.0), 2)},
        "applicability": applicability,
    }


def _hanson_applicability(
    inspections: list[Any], inventory: ItemInventory, tables: dict[str, Any]
) -> dict[str, Any]:
    """产品标准模板只适用于单份标准；大汇编/程序类文档不生成空 schema。"""

    table_count = len(tables)
    item_count = len(inventory.items)
    if inspections:
        return {
            "applicable": True,
            "quality": "ok",
            "reason": "",
            "table_count": table_count,
            "inspection_count": len(inspections),
        }
    if table_count > 30 or item_count > 100:
        return {
            "applicable": False,
            "quality": "not_applicable",
            "reason": "no_inspection_table",
            "table_count": table_count,
            "inspection_count": 0,
        }
    return {
        "applicable": True,
        "quality": "low",
        "reason": "no_inspection_table",
        "table_count": table_count,
        "inspection_count": 0,
    }


BOGUS_GRADES = {
    "",
    "-",
    "—",
    "－",
    "/",
    "要求值",
    "牌号",
    "钢号",
    "材料牌号",
    "牌号要求",
    "技术要求",
    "≥",
    "≤",
}


def _dedupe_categories_after_fill(categories: list[dict[str, Any]]) -> None:
    """Merge rows that became identical only after grade forward-filling."""

    for category in categories:
        if category.get("feature") == "标准信息":
            continue
        records = category.get("records") or []
        deduped = _dedupe_hanson_rows(records)
        if len(deduped) != len(records):
            category["records"] = deduped
            category["hit_count"] = len(deduped)


def _fill_missing_grades(
    categories: list[dict[str, Any]], grade_hint: str | None = None
) -> None:
    """Forward-fill merged grade cells and use a document-level fallback.

    Chemistry tables often merge the grade cell across element rows, or put
    the grade only in the table header. Rows without any recoverable grade get
    the document grade, or ``全部牌号`` when the document itself has no
    concrete grade.
    """

    concrete: set[str] = set()
    for category in categories:
        if category.get("feature") == "标准信息":
            continue
        for row in category.get("records") or []:
            grade = _clean(row.get("材料牌号"))
            if grade and grade not in BOGUS_GRADES and grade != "全部牌号":
                concrete.add(grade)
    unique = sorted(concrete)

    for category in categories:
        if category.get("feature") == "标准信息":
            continue
        rows = category.get("records") or []
        last = ""
        for row in rows:
            grade = _clean(row.get("材料牌号"))
            if grade in BOGUS_GRADES:
                row["材料牌号"] = ""
                grade = ""
            if grade:
                last = grade
            elif last:
                row["材料牌号"] = last
        first = next(
            (
                _clean(row.get("材料牌号"))
                for row in rows
                if _clean(row.get("材料牌号"))
            ),
            "",
        )
        if first:
            for row in rows:
                if _clean(row.get("材料牌号")):
                    break
                row["材料牌号"] = first
        if any(_clean(row.get("材料牌号")) for row in rows):
            continue
        if len(unique) == 1:
            fallback = unique[0]
        elif grade_hint:
            fallback = grade_hint
        else:
            fallback = "全部牌号"
        for row in rows:
            row["材料牌号"] = fallback


GRADE_STATEMENT_RE = re.compile(
    r"(?:锻件|钢棒|棒材|钢材|材料|合金)?牌号\s*(?:为|：|:)\s*"
    r"([A-Za-z0-9][A-Za-z0-9.\-]{2,20})"
)


def _grade_hint_from_pages(root: Path) -> str | None:
    path = root / "pages.json"
    if not path.exists():
        return None
    try:
        pages = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    for page in pages[:8]:
        for match in GRADE_STATEMENT_RE.finditer(page.get("markdown") or ""):
            candidate = match.group(1).strip(" .,;")
            if looks_like_grade(candidate):
                return candidate
    return None


def _hanson_effective_rows(categories: list[dict[str, Any]]) -> int:
    keys = ("取样数量", "标准要求", "单位", "试验方法")
    return sum(
        1
        for category in categories
        for row in (category.get("records") or [])
        if any(_filled(row.get(name)) for name in keys)
    )


def _hanson_category(
    feature: str,
    records: list[dict[str, Any]],
    required_fields: tuple[str, ...],
    fields: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    missing = [
        name
        for name in required_fields
        if not any(_filled(row.get(name)) for row in records)
    ]
    return {
        "feature": feature,
        "fields": list(fields or required_fields),
        "records": records,
        "missing_fields": missing,
        "hit_count": len(records),
    }


def _hanson_item_categories(
    inventory: ItemInventory,
    records: list[Record],
    inspections: list[InspectionItem],
    classifications: list[ClassificationItem],
    clauses: list[ClauseRecord],
    tables: dict[str, dict[str, Any]],
    *,
    index: DictionaryIndex | None,
    standard_name: str | None,
    qualitative: dict[str, list[str]],
    source_text: str | None = None,
    method_index: dict[str, str] | None = None,
    external: list[dict[str, Any]] | None = None,
    pages_text: str | None = None,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    grade_context = " ".join(
        part for part in (standard_name, source_text) if part
    )
    grades = sorted(
        {item.grade for item in classifications if item.grade}
        | {record.grade for record in records if record.grade}
    )
    document_grade = _document_grade_from_clauses(clauses) or _grade_from_text(
        standard_name or ""
    )
    single_grade = (
        grades[0]
        if len(grades) == 1
        and _plausible_grade(grades[0])
        and not _looks_like_upload_id(grades[0], grade_context)
        else None
    )
    default_grade = document_grade or single_grade
    tensile_items = [
        item
        for item in inventory.items
        if (item.item_family or "") == "tensile"
        and item.status != "not_applicable"
    ]
    # 只有文档只有一个拉伸项时，才允许把同一张表里的室温/高温条件拆成
    # 两个项目；否则（文档已单列高温拉伸）按项目各自的温度边界投影，
    # 避免重复行。
    expand_tensile = len(tensile_items) == 1

    for item in inventory.items:
        if item.status == "not_applicable":
            # Strict category mode keeps unknown major categories out of the
            # projected schema.
            continue
        feature = _hanson_feature(item)
        candidates = _hanson_candidates(item, feature, records, tables)
        if (
            (item.item_family or "") == "tensile"
            and feature == "室温拉伸"
            and not candidates
            and str(item.facets.get("temperature_basis") or "") == "default"
        ):
            # Only a *defaulted* room-temperature item may fall back to the
            # hot table. An explicitly room-temperature item must stay empty
            # when the document has no room-temperature record.
            hot_candidates = _hanson_candidates(
                item, "高温拉伸", records, tables
            )
            if hot_candidates:
                feature = "高温拉伸"
                candidates = hot_candidates
        inspection = _find_inspection(item, inspections, feature)
        if feature == "室温持久" and inspection is not None:
            # 检验计划把持久试验温度写在“测试条件”列（650℃×725MPa）。
            condition_text = _normalize_degrees(
                getattr(inspection, "condition", None)
            )
            planned = _temperature_number(
                _test_temperature_from(condition_text)
                or _temperature_from(condition_text)
            )
            if planned is not None and planned >= 100:
                feature = "高温光滑持久"
        properties = list(item.properties or [])
        candidate_properties = sorted(
            {
                prop
                for record in candidates
                for prop in (record.properties or {})
                if _property_in_family(prop, item.item_family or "")
            }
        )
        if not properties:
            properties = candidate_properties
        elif (item.item_family or "") in {"tensile", "chemical_composition"}:
            # The inventory often lists only Rm/Rp0.2; elongation and
            # reduction of area live in the same mechanical row and must not
            # be dropped from the tensile category. The same holds for
            # chemistry: the table is authoritative, the checklist may omit
            # an element (e.g. Hg).
            properties = sorted(set(properties) | set(candidate_properties))
        pair_pool = candidates
        if expand_tensile and (item.item_family or "") == "tensile":
            pair_pool = _tensile_records(records, tables)
        pairs = _hanson_property_pairs(item, properties, pair_pool)
        if not pairs:
            clause_ids = _qualitative_clause_ids(item, qualitative)
            matched_inspections = (
                _matching_inspections(item, inspections, feature)
                if feature in PERSISTENCE_FEATURES
                else []
            ) or [inspection]
            for matched_inspection in matched_inspections:
                row = _hanson_item_row(
                    item,
                    None,
                    None,
                    None,
                    default_grade,
                    matched_inspection,
                    clauses,
                    index,
                    standard_name=standard_name,
                    qualitative_clause_ids=clause_ids,
                    default_grade=default_grade,
                    grade_context=grade_context,
                    method_fallback=(method_index or {}).get(item.item_family or ""),
                    external_requirement=_external_requirement(
                        external, item, feature, None
                    ),
                    pages_text=pages_text,
                    feature=feature,
                )
                groups.setdefault(feature, []).extend(
                    _expand_sample_variants([row], matched_inspection, feature)
                )
            continue
        for prop, match, record, value in pairs:
            row_feature = feature
            row_inspection = inspection
            if expand_tensile and (item.item_family or "") == "tensile":
                row_feature = _tensile_feature_for_record(record, feature)
                if row_feature != feature:
                    row_inspection = (
                        _inspection_with_temperature(
                            inspections, record, row_feature
                        )
                        or inspection
                    )
            row = _hanson_item_row(
                item,
                prop,
                match,
                value,
                record.grade if record is not None else default_grade,
                row_inspection,
                clauses,
                index,
                record=record,
                standard_name=standard_name,
                default_grade=default_grade,
                grade_context=grade_context,
                method_fallback=(method_index or {}).get(item.item_family or ""),
                external_requirement=_external_requirement(
                    external, item, row_feature, prop
                ),
                pages_text=pages_text,
                feature=row_feature,
            )
            groups.setdefault(row_feature, []).extend(
                _expand_sample_variants([row], row_inspection, row_feature)
            )

    persistence_method = None
    has_persistence = False
    for item in inventory.items:
        if (item.item_family or "") == "stress_rupture":
            if item.status == "not_applicable":
                continue
            has_persistence = True
            persistence_method = (
                _method_number(item, index)
                or _method_from_clauses(item, clauses)
                or (method_index or {}).get("stress_rupture")
            )
            break
    persistence = (
        _hanson_persistence_rows(
            tables,
            persistence_method,
            default_grade,
            inspections=inspections,
            standard_name=standard_name,
        )
        if has_persistence
        else []
    )
    persistence_groups: dict[str, list[dict[str, Any]]] = {}
    for row in persistence:
        feature = row.pop("_feature", "高温光滑持久")
        persistence_groups.setdefault(feature, []).append(row)
    for feature, rows in persistence_groups.items():
        groups[feature] = _dedupe_hanson_rows(rows)

    for feature, rows in groups.items():
        requirement = _requirement_from_tables(feature, tables)
        if not requirement:
            continue
        for row in rows:
            if not _filled(row.get("标准要求")):
                row["标准要求"] = requirement

    document_grades = [item for item in grades if _plausible_grade(item)]
    for feature, rows in groups.items():
        if feature not in CONDITION_FEATURES:
            continue
        for row in rows:
            if _filled(row.get("标准要求")):
                continue
            row["标准要求"] = (
                _requirement_from_condition_tables(
                    _clean(row.get("项目名称")) or feature,
                    feature,
                    _clean(row.get("材料牌号")) or "",
                    tables,
                    document_grades,
                )
                or ""
            )

    for feature, rows in groups.items():
        if feature not in QUALITATIVE_TABLE_FEATURES:
            continue
        for row in rows:
            current = _clean(row.get("标准要求")) or ""
            if current and not TABLE_REF_RE.search(current):
                continue
            # A verdict cell outranks a bare "应符合表X" reference, which would
            # otherwise be inlined as the whole table by the augmenter.
            row["标准要求"] = (
                _requirement_from_qualitative_tables(
                    feature,
                    _clean(row.get("项目名称")),
                    _clean(row.get("材料牌号")),
                    tables,
                )
                or current
            )

    for feature, rows in groups.items():
        if feature == "标准信息":
            continue
        for row in rows:
            if _filled(row.get("标准要求")):
                continue
            requirement = _requirement_from_test_requirement_tables(feature, tables)
            if requirement:
                row["标准要求"] = requirement

    if "化学成分" not in groups:
        chemical = _hanson_chemical_reference_row(clauses, standard_name)
        if chemical:
            external_chemical = _external_requirement_for_feature(
                external, "化学成分"
            )
            if external_chemical:
                chemical["标准要求"] = external_chemical
            groups["化学成分"] = [chemical]

    expansions = _augment_requirements_with_tables(groups, tables)

    categories: list[dict[str, Any]] = []
    for feature in sorted(groups, key=_hanson_feature_rank):
        rows = _dedupe_hanson_rows(groups[feature])
        if not rows:
            continue
        category = _hanson_category(
            feature,
            rows,
            HANSON_ITEM_CORE,
            fields=HANSON_ITEM_FIELDS,
        )
        if (
            any(_is_numeric_requirement(row.get("标准要求")) for row in rows)
            and not any(_filled(row.get("单位")) for row in rows)
        ):
            category["missing_fields"].append("单位")
        categories.append(category)
    return categories, expansions


def _external_requirement_for_feature(
    entries: list[dict[str, Any]] | None, feature: str
) -> str | None:
    """Feature-level external requirement for non-pair rows."""

    if not entries:
        return None
    target_feature = _clean(feature)
    for entry in entries:
        target = _clean(entry.get("inspection_item"))
        if not target:
            continue
        if not (
            target == target_feature
            or target in target_feature
            or target_feature in target
        ):
            continue
        requirement = _clean(entry.get("requirement"))
        if requirement:
            return requirement
    return None


def _external_requirement(
    entries: list[dict[str, Any]] | None,
    item: ItemInventoryEntry,
    feature: str,
    prop: str | None,
) -> str | None:
    """Return a cross-standard value for this item/property, if any."""

    if not entries:
        return None
    names = {
        _clean(feature),
        _clean(item.item_raw),
        _clean(item.business_name),
        _clean(item.item_canonical),
    }
    names.discard("")
    prop_key = canonical_property(prop) if prop else None
    for entry in entries:
        target = _clean(entry.get("inspection_item"))
        if not target:
            continue
        if not any(
            target == name or target in name or name in target for name in names
        ):
            continue
        field = _clean(entry.get("field"))
        if prop_key and field:
            field_key = canonical_property(field) or field
            whole_item = field_key in names or field in names
            if (
                not whole_item
                and field_key != prop_key
                and field not in (_clean(prop) or "")
            ):
                continue
        requirement = _clean(entry.get("requirement"))
        if requirement:
            return requirement
    return None


def _hanson_item_row(
    item: ItemInventoryEntry,
    prop: str | None,
    match: PropertyMatch | None,
    value: Any,
    grade: str | None,
    inspection: InspectionItem | None,
    clauses: list[ClauseRecord],
    index: DictionaryIndex | None,
    *,
    record: Record | None = None,
    standard_name: str | None = None,
    qualitative_clause_ids: list[str] | None = None,
    default_grade: str | None = None,
    grade_context: str | None = None,
    method_fallback: str | None = None,
    external_requirement: str | None = None,
    pages_text: str | None = None,
    feature: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {}
    display = _property_display(match, prop)
    if prop and not (match and match.canonical_name):
        display = HANSON_PROPERTY_NAMES.get(prop) or prop
    family = item.item_family or ""
    default_feature = _hanson_feature(item)
    feature = feature or default_feature
    if not prop and feature != default_feature:
        # The row was re-routed by its planned condition (e.g. 光滑持久 at
        # 650℃); the dictionary name "室温持久" would contradict the category.
        display = feature
    row["项目名称"] = display or _item_display(item) or ""
    row["材料牌号"] = _hanson_grade(
        grade, default_grade, family, grade_context or standard_name
    )
    requirement = (
        _hanson_requirement(value)
        or _requirement_text(inspection, clauses, pages_text)
        or _clause_requirement_text(qualitative_clause_ids or [], clauses)
        or _requirement_from_qualitative_clauses(feature, clauses)
        or ""
    )
    if not requirement and feature == "化学成分":
        requirement = (
            _requirement_from_chemical_sentence(
                row.get("项目名称") or "", clauses, pages_text
            )
            or ""
        )
    if not requirement:
        requirement = (
            _requirement_from_item_clauses(
                row.get("项目名称") or "", feature, clauses
            )
            or ""
        )
    if feature in MECHANICAL_FEATURES and any(
        marker in requirement for marker in ("化学成分", "wt%", "WT%", "ppm", "熔炼分析")
    ):
        requirement = ""
    if external_requirement and (
        not requirement or TABLE_REF_RE.search(requirement)
    ):
        # Cross-standard values only fill an empty requirement or a bare
        # "符合表X" reference; local concrete values are never overwritten.
        requirement = external_requirement
    if _implausible_item_requirement(row.get("项目名称") or "", feature, requirement):
        requirement = ""
    if feature in CORROSION_MECHANISMS and requirement:
        if any(
            mechanism in requirement
            for mechanism in CORROSION_MECHANISMS
            if mechanism != feature
        ) and feature not in requirement:
            # 应力腐蚀/剥落腐蚀 text must not be attached to a 晶间腐蚀 row
            # (and vice versa); the item alignment fix belongs to P4-D.
            requirement = ""
    row["标准要求"] = requirement
    if feature in PERSISTENCE_FEATURES and inspection is not None:
        stress = _test_stress_from(getattr(inspection, "condition", None))
        if stress and f"{stress}MPa" not in requirement:
            row["标准要求"] = (
                f"{requirement}；试验应力{stress}MPa"
                if requirement
                else f"试验应力{stress}MPa"
            )
    prop_key = canonical_property(prop) if prop else None
    if prop_key in {"HB", "HRB", "HRC", "HV"}:
        row["单位"] = prop_key
    elif prop_key in PROPERTY_UNITS:
        row["单位"] = PROPERTY_UNITS[prop_key]
    elif value is not None:
        unit = _clean(getattr(value, "unit", None))
        if unit:
            row["单位"] = unit
        elif getattr(value, "comparator", None) not in {"text", "na"}:
            row["单位"] = ""

    inspection_method = _method_from_citation(
        getattr(inspection, "method_clause", None), clauses, pages_text
    ) or _method_from_requirement_clause(
        getattr(inspection, "requirement_clause", None), clauses, pages_text
    )
    method = (
        # A high-temperature row may read the same tensile item as the room
        # row; the temperature-specific clause (ASTM E 21) must win over the
        # item-level room method (ASTM E 8).
        (
            inspection_method
            if family == "tensile" and feature != "室温拉伸"
            else None
        )
        or _method_number(
            item,
            index,
            prefer=_method_code_prefix(feature),
        )
        or inspection_method
        or (
            # 化学成分行在检验计划表里直接给出多个可接受方法；条款文本里
            # 相邻的“冲击 GB/T 229”不能覆盖这张表。
            _clean(getattr(inspection, "method_standard", None))
            if feature == "化学成分" and inspection is not None
            else None
        )
        or _method_from_clauses(item, clauses)
        or _clean(
            method_fallback
            if family != "tensile" or feature == "室温拉伸"
            else None
        )
        or _clean(getattr(inspection, "method_standard", None))
    )
    if method:
        row["试验方法"] = _select_hardness_method(method, feature)
    temperature = _hanson_temperature(feature, record, item, inspection)
    if temperature:
        row["试验温度"] = temperature
    position = _hanson_position(item, inspection)
    if position:
        row["位置"] = position
    direction = _hanson_direction(record, position)
    if direction:
        row["方向"] = direction
    thickness = _hanson_thickness(record, item)
    if thickness:
        row["尺寸厚度"] = thickness
    state = _state(record.condition) if record is not None else None
    if state:
        row["试样状态"] = state
    count = _sample_count(inspection)
    note = _sample_note(inspection) or (
        _clean(getattr(inspection, "note", None)) if inspection is not None else None
    )
    if count is None and not note:
        default = _sampling_default(family)
        if default:
            count = default.get("quantity")
            note = _clean(default.get("note"))
    if count is not None:
        row["取样数量"] = count
    if note:
        row["取样说明"] = note
    form = _hanson_product_form(standard_name)
    if form:
        row["锻件类型"] = form
    return row


def _hanson_chemical_reference_row(
    clauses: list[ClauseRecord], standard_name: str | None
) -> dict[str, Any] | None:
    for clause in clauses:
        title = _clean(clause.title) or ""
        body = _clause_body(clause) or ""
        if "化学成分" not in title and not body.startswith("化学成分"):
            continue
        if len(body) < 6 or not re.search(r"GB|符合|按", body):
            continue
        method = _method_for_family("chemical_composition", clauses)
        row: dict[str, Any] = {
            "项目名称": "化学成分",
            "材料牌号": "全部牌号",
            "标准要求": _strip_section_heading(body),
        }
        if method:
            row["试验方法"] = method
        form = _hanson_product_form(standard_name)
        if form:
            row["锻件类型"] = form
        return row
    return None


def _requirement_from_tables(
    feature: str, tables: dict[str, dict[str, Any]]
) -> str | None:
    keywords = TABLE_FEATURE_KEYWORDS.get(feature)
    if not keywords:
        return None
    captions: list[str] = []
    for table in tables.values():
        caption = _clean(table.get("caption")) or ""
        if caption and any(keyword in caption for keyword in keywords):
            captions.append(caption)
    if not captions:
        return None
    return "应符合" + "、".join(captions[:2]) + "的规定"


TABLE_REF_RE = re.compile(
    r"表\s*([A-Za-z]?\s*\.?\s*\d+(?:\.\d+)?(?:\s*[-—]\s*\d+)?)"
)
TABLE_FEATURE_KEYWORDS = {
    "尺寸": ("允许偏差", "规格", "尺寸"),
    "弯曲": ("弯曲度", "弯曲"),
    "晶粒度": ("晶粒度",),
    "高倍组织": ("显微组织", "金相", "高倍"),
    "低倍": ("低倍", "酸浸", "流线"),
    "非金属夹杂": ("非金属夹杂", "夹杂物"),
    "超声波检测": ("超声",),
    "晶间腐蚀": ("晶间腐蚀", "腐蚀减重"),
    "应力腐蚀": ("应力腐蚀",),
    "剥落腐蚀": ("剥落腐蚀", "剥落"),
    "塔形": ("塔形", "发纹"),
    "表面质量": ("表面质量", "外观"),
    "高温光滑持久": ("持久", "蠕变"),
    "持久": ("持久",),
    "蠕变": ("蠕变",),
    "铁素体": ("铁素体",),
}
FEATURE_TABLE_PROFILES: dict[str, set[str]] = {
    "化学成分": {"chemical_composition"},
    "室温拉伸": {"mechanical_properties"},
    "高温拉伸": {"mechanical_properties"},
    "低温拉伸": {"mechanical_properties"},
    "夏比冲击": {"mechanical_properties"},
    "布氏硬度": {"mechanical_properties"},
    "洛氏硬度": {"mechanical_properties"},
    "维氏硬度": {"mechanical_properties"},
    "高温持久": {"mechanical_properties"},
    "高温光滑持久": {"mechanical_properties", "inspection"},
    "室温持久": {"mechanical_properties"},
    "持久": {"mechanical_properties", "inspection"},
    "蠕变": {"mechanical_properties", "inspection"},
    "尺寸": {"dimension"},
    "低倍": {"inspection", "unknown"},
    "高倍组织": {"inspection", "unknown"},
    "晶粒度": {"inspection", "unknown"},
    "非金属夹杂": {"inspection", "unknown"},
    "铁素体": {"inspection", "unknown"},
    "晶间腐蚀": {"inspection", "unknown"},
    "应力腐蚀": {"inspection", "unknown"},
    "剥落腐蚀": {"inspection", "unknown"},
    "塔形": {"inspection", "unknown"},
}
QUALITATIVE_TABLE_FEATURES = {
    "尺寸",
    "弯曲",
    "晶粒度",
    "高倍组织",
    "低倍",
    "超声波检测",
    "晶间腐蚀",
    "应力腐蚀",
    "剥落腐蚀",
    "塔形",
}
MECHANICAL_FEATURES = {
    "室温拉伸",
    "高温拉伸",
    "低温拉伸",
    "夏比冲击",
    "冲击",
    "布氏硬度",
    "洛氏硬度",
    "维氏硬度",
    "硬度",
    "弯曲",
    "持久",
    "蠕变",
    "疲劳",
    "断裂韧性",
}
PERSISTENCE_FEATURES = {"高温光滑持久", "室温持久", "持久", "蠕变"}
TEST_STRESS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*MPa", re.IGNORECASE)


def _test_stress_from(condition: str | None) -> str | None:
    """Read the planned test stress from an inspection condition cell.

    ``650℃×725MPa`` is one cell: the temperature is projected into 试验温度,
    but the template has no stress field, so the stress is appended to
    标准要求 instead of being dropped.
    """

    match = TEST_STRESS_RE.search(_clean(condition) or "")
    return match.group(1) if match else None


def _normalize_table_ref(text: str | None) -> str:
    value = _clean(text).upper().replace(" ", "")
    value = value.lstrip(".")
    return value


def _caption_table_ref(caption: str | None) -> str:
    match = TABLE_REF_RE.search(_clean(caption) or "")
    return _normalize_table_ref(match.group(1)) if match else ""


def _table_headers_and_start(
    table: dict[str, Any],
) -> tuple[list[str], int]:
    rows = table.get("rows") or []
    header_rows = int(table.get("header_rows") or 1)
    paths = table.get("header_paths") or []
    headers = [
        "/".join(part for part in path if _clean(part)) for path in paths
    ]
    polluted = any(
        _clean(part) in {"-", "—", "/"} for path in paths for part in path
    )
    if (
        not headers
        or polluted
        or any(len(header) > 40 for header in headers)
    ) and rows:
        # Some appendix tables mark the first data row as a header row (e.g.
        # table B.4); fall back to the visible first row in that case.
        headers = [_clean(cell) for cell in rows[0]]
        return headers, 1
    return headers, header_rows


def _table_paragraph(table: dict[str, Any], limit: int = 3000) -> str | None:
    rows = table.get("rows") or []
    if not rows:
        return None
    headers, start = _table_headers_and_start(table)
    lines: list[str] = []
    for row in rows[start:]:
        if not row or is_footnote_row(row):
            continue
        non_empty = [_clean(cell) for cell in row if _clean(cell)]
        if (
            len(non_empty) >= 2
            and len(set(non_empty)) == 1
            and len(non_empty[0]) > 15
        ):
            continue
        cells: list[str] = []
        for index, value in enumerate(row):
            text = _clean(value)
            if not text:
                continue
            header = headers[index] if index < len(headers) else ""
            if header and header not in {"-", "—", "/"}:
                cells.append(f"{header}={text}")
            else:
                cells.append(text)
        if cells:
            lines.append("，".join(cells))
    if not lines:
        return None
    caption = _clean(table.get("caption"))
    body = "；".join(lines)
    text = f"{caption}：{body}" if caption else body
    return text[:limit] + ("…" if len(text) > limit else "")


def _tables_for_requirement(
    feature: str,
    requirement: str,
    tables: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    refs = {
        _normalize_table_ref(match.group(1))
        for match in TABLE_REF_RE.finditer(requirement or "")
    }
    for table in tables.values():
        if _caption_table_ref(table.get("caption")) in refs:
            key = str(table.get("table_id"))
            if key not in seen:
                seen.add(key)
                selected.append(table)
    if selected:
        return selected
    if refs:
        # Caption-less tables (common after page-split OCR) still carry a
        # document order. Restrict the fallback to tables whose profile is
        # compatible with the feature; otherwise "表4" can silently inline a
        # mechanical table into a low-magnification requirement.
        allowed = FEATURE_TABLE_PROFILES.get(feature)
        ordered = [
            table
            for table in tables.values()
            if not allowed or table.get("profile") in allowed
        ]
        for ref in refs:
            if not ref.isdigit():
                continue
            candidate = None
            expected = f"T{int(ref)}"
            for table in ordered:
                if str(table.get("table_id", "")).upper() == expected:
                    candidate = table
                    break
            if candidate is None and 0 < int(ref) <= len(ordered):
                candidate = ordered[int(ref) - 1]
            if candidate is None:
                continue
            key = str(candidate.get("table_id"))
            if key not in seen:
                seen.add(key)
                selected.append(candidate)
        if selected:
            return selected
    keywords = TABLE_FEATURE_KEYWORDS.get(feature)
    if not keywords:
        return []
    for table in tables.values():
        caption = _clean(table.get("caption"))
        if caption and any(keyword in caption for keyword in keywords):
            key = str(table.get("table_id"))
            if key not in seen:
                seen.add(key)
                selected.append(table)
    return selected


QUALITATIVE_VERDICT_CELL_RE = re.compile(
    r"不允许|不得|不准|不应|不出现|禁止|应无|无肉眼|无裂纹|无缺陷|"
    r"允许存在|符合|不低于|不超过|[≤≥]|级"
)
QUALITATIVE_SKIP_HEADER_RE = re.compile(r"条号|取样规定|取样数量|试样的?数量")


def _qualitative_label_column(headers: list[str]) -> int:
    for index, header in enumerate(headers):
        text = _clean(header) or ""
        if any(
            keyword in text
            for keyword in ("缺陷名称", "检验项目", "试验项目", "项目名称", "牌号", "组别")
        ):
            return index
    return 0


def _qualitative_verdict_row(
    headers: list[str],
    rows: list[list[str]],
    start: int,
    keywords: list[str],
    grade: str,
) -> str | None:
    label_col = _qualitative_label_column(headers)
    grade_col = next(
        (
            index
            for index, header in enumerate(headers)
            if "牌号" in (_clean(header) or "")
        ),
        None,
    )
    for row in rows[start:]:
        if not row or is_footnote_row(row):
            continue
        cells = [_clean(cell) or "" for cell in row]
        label = " ".join(
            cells[index] for index in (label_col, 0, 1) if index < len(cells)
        )
        row_text = " ".join(cells)
        keyword_hit = any(keyword and keyword in row_text for keyword in keywords)
        if not keyword_hit and keywords:
            continue
        if grade and grade not in {"全部牌号", "所有牌号", "各牌号"}:
            if grade_col is not None and grade_col < len(cells):
                if grade not in cells[grade_col]:
                    continue
            elif grade not in row_text:
                continue
        ordered = sorted(
            enumerate(cells),
            key=lambda item: (
                0
                if any(
                    token in (_clean(headers[item[0]]) or "")
                    for token in ("要求", "判定", "结果", "状态", "级别")
                )
                else 1,
                -item[0],
            ),
        )
        label_tokens = {label, *(cells[index] for index in (label_col, 0, 1) if index < len(cells))}
        for _, cell in ordered:
            if len(cell) < 2 or len(cell) > 200:
                continue
            if cell in label_tokens:
                continue
            if NUMERIC_CELL_RE.fullmatch(cell):
                continue
            if STANDARD_CODE_RE.fullmatch(cell):
                continue
            if not QUALITATIVE_VERDICT_CELL_RE.search(cell):
                continue
            return cell
    return None


def _requirement_from_qualitative_tables(
    feature: str,
    item: str | None,
    grade: str | None,
    tables: dict[str, dict[str, Any]],
) -> str | None:
    """Read a qualitative verdict directly from a table row.

    Standards such as GB/T 1220 state intergranular-corrosion acceptance as
    "不允许有晶间腐蚀裂纹" in the table's last column, not in a clause. Whole
    table expansion loses that sentence, so the verdict cell is selected first.
    """

    keywords = list(TABLE_FEATURE_KEYWORDS.get(feature, ()))
    keywords.extend(FEATURE_ITEM_SYNONYMS.get(feature, ()))
    cleaned_item = _clean(item) or ""
    if cleaned_item:
        keywords.append(cleaned_item)
    keywords = [keyword for keyword in dict.fromkeys(keywords) if keyword]
    for table in tables.values():
        caption = _clean(table.get("caption")) or ""
        headers, start = _table_headers_and_start(table)
        rows = table.get("rows") or []
        if not rows:
            continue
        if any(
            QUALITATIVE_SKIP_HEADER_RE.search(_clean(header) or "")
            for header in headers
        ):
            continue
        caption_hit = any(keyword in caption for keyword in keywords)
        label_col = _qualitative_label_column(headers)
        row_hit = any(
            keyword
            in " ".join(
                _clean(row[index]) or ""
                for index in (label_col, 0, 1)
                if index < len(row)
            )
            for row in rows[start:]
            for keyword in keywords
        )
        if not caption_hit and not row_hit:
            continue
        search_keywords = [] if caption_hit else keywords
        verdict = _qualitative_verdict_row(
            headers, rows, start, search_keywords, _clean(grade) or ""
        )
        if verdict:
            return verdict[:200]
    return None


TEST_REQUIREMENT_LABEL_MARKERS = (
    "测试类别", "试验项目", "检验项目", "测试项目", "检查项目", "项目",
    "test item", "test category", "inspection item",
)
TEST_REQUIREMENT_VALUE_MARKERS = (
    "验收指标", "验收要求", "验收标准", "要求",
    "acceptance criteria", "acceptance requirement",
)
TEST_REQUIREMENT_CONDITION_MARKERS = (
    "测试条件", "试验条件", "test condition",
)


def _requirement_from_test_requirement_tables(
    feature: str, tables: dict[str, dict[str, Any]]
) -> str | None:
    """Read "测试类别 + 验收指标" matrices (批准试验要求/采购规范).

    These tables list tests as rows and acceptance values as cells; the generic
    clause/qualitative lookups never see them.
    """

    keywords = [feature, *INSPECTION_SYNONYMS.get(feature, ())]
    keywords = [keyword for keyword in dict.fromkeys(keywords) if keyword]
    for table in tables.values():
        headers, start = _table_headers_and_start(table)
        label_col = next(
            (
                index
                for index, header in enumerate(headers)
                if any(
                    marker in (_clean(header) or "")
                    for marker in TEST_REQUIREMENT_LABEL_MARKERS
                )
            ),
            None,
        )
        value_col = next(
            (
                index
                for index, header in enumerate(headers)
                if any(
                    marker in (_clean(header) or "")
                    for marker in TEST_REQUIREMENT_VALUE_MARKERS
                )
            ),
            None,
        )
        if label_col is None or value_col is None:
            continue
        condition_col = next(
            (
                index
                for index, header in enumerate(headers)
                if any(
                    marker in (_clean(header) or "")
                    for marker in TEST_REQUIREMENT_CONDITION_MARKERS
                )
            ),
            None,
        )
        for row in (table.get("rows") or [])[start:]:
            cells = [_clean(cell) or "" for cell in row]
            if label_col >= len(cells):
                continue
            label = cells[label_col]
            if not any(keyword in label for keyword in keywords):
                continue
            value = cells[value_col] if value_col < len(cells) else ""
            if value and not re.fullmatch(r"[-—/]+", value):
                return value[:200]
            if condition_col is not None and condition_col < len(cells):
                condition = cells[condition_col]
                if condition and not re.fullmatch(r"[-—/]+", condition):
                    return condition[:200]
    return None


def _augment_requirements_with_tables(
    groups: dict[str, list[dict[str, Any]]],
    tables: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Inline a compact table summary and keep the full text separately.

    Requirements such as "显微组织应符合表B.4的规定" are not usable on their
    own; the corresponding table is rendered as a short paragraph. The full
    table text is preserved in ``expanded_requirements`` so the cell no longer
    holds thousands of characters.
    """

    expansions: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for feature, rows in groups.items():
        if feature == "标准信息":
            continue
        for row in rows:
            requirement = _clean(row.get("标准要求")) or ""
            has_table_ref = any(TABLE_REF_RE.finditer(requirement))
            if not has_table_ref and feature not in QUALITATIVE_TABLE_FEATURES:
                continue
            if not has_table_ref and requirement:
                continue
            summary: list[str] = []
            for table in _tables_for_requirement(feature, requirement, tables):
                paragraph = _table_paragraph(table)
                if not paragraph:
                    continue
                summary.append(paragraph)
                key = (
                    str(table.get("table_id")),
                    feature,
                    _clean(row.get("项目名称")),
                )
                if key in seen:
                    continue
                seen.add(key)
                full = _table_paragraph(table, limit=20000)
                if full:
                    expansions.append(
                        {
                            "feature": feature,
                            "item": _clean(row.get("项目名称")),
                            "grade": _clean(row.get("材料牌号")),
                            "table": _clean(table.get("caption"))
                            or str(table.get("table_id")),
                            "text": full,
                        }
                    )
            if not summary:
                continue
            addition = "；".join(summary)
            if addition in requirement:
                continue
            prefix = f"{requirement}；" if requirement else ""
            budget = max(0, 296 - len(prefix))
            if len(addition) > budget:
                addition = addition[: max(0, budget - 1)].rstrip("；") + "…"
            row["标准要求"] = prefix + addition
    return expansions


def _requirement_from_qualitative_clauses(
    feature: str,
    clauses: list[ClauseRecord],
) -> str | None:
    keywords = {
        "低倍": ("低倍组织", "低倍"),
        "高倍组织": ("显微组织", "高倍组织", "高倍"),
        "晶粒度": ("晶粒度", "晶粒"),
        "非金属夹杂": ("非金属夹杂", "夹杂物"),
        "表面质量": ("表面质量", "外观"),
        "外观质量": ("表面质量", "外观"),
        "超声波检测": ("超声波", "超声"),
        "尺寸": ("尺寸", "外形", "允许偏差"),
        "弯曲": ("弯曲",),
    }.get(feature)
    if not keywords:
        return None
    for clause in clauses:
        title = _clean(clause.title) or ""
        body = _clause_body(clause) or ""
        if not any(keyword in title for keyword in keywords) and not any(
            body.startswith(keyword) for keyword in keywords
        ):
            continue
        texts: list[str] = []
        parent_text = body
        if parent_text and _is_requirement_sentence(parent_text):
            texts.append(parent_text)
        for child in clauses:
            if not child.clause_id.startswith(f"{clause.clause_id}."):
                continue
            if child.kind not in {"technical_requirement", "other"}:
                continue
            text = _clause_body(child)
            if text and _is_requirement_sentence(text) and text not in texts:
                texts.append(text)
            if len(texts) >= 3:
                break
        if texts:
            return "；".join(texts)
    return None


ITEM_REQUIREMENT_KEYWORDS = (
    "抗拉强度",
    "屈服强度",
    "规定塑性延伸",
    "断后伸长率",
    "断面收缩率",
    "冲击吸收功",
    "布氏硬度",
    "洛氏硬度",
    "维氏硬度",
    "晶粒度",
    "非金属夹杂",
    "低倍",
    "高倍",
    "超声",
    "持久",
    "蠕变",
    "弯曲",
)
FEATURE_ITEM_SYNONYMS: dict[str, tuple[str, ...]] = {
    "高倍组织": ("高倍组织", "高倍", "显微组织", "金相"),
    "低倍": ("低倍", "低倍组织", "酸浸", "流线"),
    "晶间腐蚀": ("晶间腐蚀",),
    "应力腐蚀": ("应力腐蚀",),
    "剥落腐蚀": ("剥落腐蚀", "剥落"),
    "塔形": ("塔形", "发纹"),
    "晶粒度": ("晶粒度", "晶粒"),
    "非金属夹杂": ("非金属夹杂", "夹杂物"),
    "超声波检测": ("超声波检测", "超声波", "超声", "探伤"),
}


QUALITATIVE_REQUIREMENT_FEATURES = {
    "低倍",
    "高倍组织",
    "晶粒度",
    "非金属夹杂",
    "超声波检测",
    "表面质量",
    "铁素体",
    "断口",
    "晶间腐蚀",
    "应力腐蚀",
    "剥落腐蚀",
    "塔形",
}
CORROSION_MECHANISMS = ("晶间腐蚀", "应力腐蚀", "剥落腐蚀", "点蚀", "盐雾腐蚀")
QUALITATIVE_VERDICT_RE = re.compile(
    r"(?:GB\s*/?\s*T|GJB|JB\s*/?\s*T|NB\s*/?\s*T|ASTM|AMS|ISO|QJ|Q\s*/|YS\s*/|HB\s*/?)\s*[A-Z]?\s*\d"
    r"|不允许|不得有|不准许|不准|不应|禁止|应无|应符合|应合格|要求执行",
    re.IGNORECASE,
)
STANDARD_CODE_RE = re.compile(
    r"(?:GB\s*/?\s*T|GJB|JB\s*/?\s*T|NB\s*/?\s*T|ASTM|AMS|ISO|QJ|Q\s*/|YS\s*/|HB\s*/?)"
    r"\s*[A-Z]?\s*\d+(?:\.\d+)?(?:[-—]\d{2,4})?",
    re.IGNORECASE,
)


CHEM_ELEMENT_NAMES = {
    "碳": "C",
    "硅": "Si",
    "锰": "Mn",
    "磷": "P",
    "硫": "S",
    "铬": "Cr",
    "镍": "Ni",
    "钼": "Mo",
    "钛": "Ti",
    "铝": "Al",
    "铜": "Cu",
    "铌": "Nb",
    "钒": "V",
    "硼": "B",
    "钨": "W",
    "钴": "Co",
    "铁": "Fe",
    "氮": "N",
    "氢": "H",
    "氧": "O",
    "镁": "Mg",
    "钙": "Ca",
    "铅": "Pb",
    "锡": "Sn",
}


def _requirement_from_chemical_sentence(
    element: str,
    clauses: list[ClauseRecord],
    pages_text: str | None = None,
) -> str | None:
    """Fill an element row from prose such as "P、S 含量分别≤0.010%"."""

    symbol = _clean(element) or ""
    symbol = CHEM_ELEMENT_NAMES.get(symbol, symbol)
    if not re.fullmatch(r"[A-Z][a-z]?", symbol):
        return None
    pattern = re.compile(rf"(?<![A-Za-z]){re.escape(symbol)}(?![a-z])")
    blobs: list[str] = []
    for clause in clauses:
        parts = [_clean(clause.title)]
        for value in (clause.fields or {}).values():
            parts.append(_clean(getattr(value, "text", None)))
            parts.append(_clean(getattr(value, "raw", None)))
        body = " ".join(part for part in parts if part)
        if body:
            blobs.append(body)
    if pages_text:
        blobs.append(re.sub(r"<[^>]+>", " ", pages_text))
    for body in blobs:
        for sentence in re.split(r"[。；\n]", body):
            text = _clean(sentence) or ""
            if len(text) < 4 or len(text) > 200:
                continue
            match = pattern.search(text)
            if not match:
                continue
            tail = text[match.end() : match.end() + 14]
            if "含量" in tail or re.search(r"[≤≥<>]", tail[:10]):
                return text[:200]
    return None


def _requirement_from_item_clauses(
    item_display: str, feature: str, clauses: list[ClauseRecord]
) -> str | None:
    """Last-resort requirement lookup by property name in clause text."""

    if feature in {"标准信息", "热处理制度", "热处理方法"}:
        return None
    display = _clean(item_display) or ""
    keywords = [token for token in ITEM_REQUIREMENT_KEYWORDS if token in display]
    keywords.extend(FEATURE_ITEM_SYNONYMS.get(feature, ()))
    if not keywords and feature:
        keywords = [feature]
    keywords = list(dict.fromkeys(keywords))
    if not keywords:
        return None
    numeric = re.compile(r"[≥≤<>]\s*\d|\d+(?:\.\d+)?\s*[~～\-]\s*\d+")
    qualitative = feature in QUALITATIVE_REQUIREMENT_FEATURES
    skip_words = ("试验方法", "取样", "仲裁", "引用文件", "不合格")
    for clause in clauses:
        parts = [_clean(clause.title)]
        for value in (clause.fields or {}).values():
            parts.append(_clean(getattr(value, "text", None)))
            parts.append(_clean(getattr(value, "raw", None)))
        body = " ".join(part for part in parts if part)
        for sentence in re.split(r"[。；]", body):
            text = _clean(sentence) or ""
            if len(text) < 4 or len(text) > 200:
                continue
            if any(word in text for word in skip_words):
                continue
            if not any(keyword in text for keyword in keywords):
                continue
            if not numeric.search(text):
                if not (qualitative and QUALITATIVE_VERDICT_RE.search(text)):
                    continue
                if re.search(r"\d", STANDARD_CODE_RE.sub("", text)):
                    continue
            return text[:200]
    return None


IMPACT_FEATURES = {"夏比冲击", "冲击"}
IMPACT_MAX_J = 400.0


def _implausible_item_requirement(
    display: str, feature: str, requirement: str
) -> bool:
    """Reject values that landed in the wrong column of a mechanical table."""

    if not requirement:
        return False
    if feature in IMPACT_FEATURES or "冲击吸收功" in display:
        values = [float(item) for item in NUMBER_RE.findall(requirement)]
        if values and max(values) > IMPACT_MAX_J:
            return True
    if feature in MECHANICAL_FEATURES and re.match(
        r"^[≥≤<>]?\s*\d+(?:\.\d+)?\s*[\u4e00-\u9fff]{2,}", requirement
    ):
        # "≥3.7 低倍" comes from a chapter heading merged into a value cell.
        return True
    return False


CONDITION_FEATURES = {
    "室温拉伸",
    "高温拉伸",
    "低温拉伸",
    "夏比冲击",
    "冲击",
    "布氏硬度",
    "洛氏硬度",
    "维氏硬度",
    "硬度",
    "室温持久",
    "高温持久",
    "高温光滑持久",
    "持久",
    "蠕变",
    "低倍",
    "高倍组织",
    "晶粒度",
    "非金属夹杂",
    "超声波检测",
    "表面质量",
    "铁素体",
}
CONDITION_PROPERTY_TOKENS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("抗拉强度", ("抗拉强度", "σb", "Rm")),
    ("塑性延伸", ("塑性延伸", "σ0.2", "σ02", "σs", "Rp0.2", "Rp02", "ReL")),
    ("屈服", ("屈服", "σ0.2", "σ02", "σs", "Rp0.2", "Rp02", "ReL")),
    ("伸长率", ("伸长率", "延伸率", "δ5", "δ4", "δ10")),
    ("收缩率", ("收缩率", "ψ")),
    ("侧膨胀", ("侧膨胀", "LATERAL", "LE")),
    ("冲击", ("冲击", "KU", "KV", "AK")),
    ("硬度", ("硬度", "HBW", "HB", "HRC", "HRB", "HV")),
    ("弹性模量", ("弹性模量", "E/GPa")),
    ("晶粒度", ("晶粒度",)),
    ("低倍", ("低倍", "酸浸")),
    ("高倍", ("高倍", "显微")),
    ("超声", ("超声", "探伤")),
    ("持久", ("持久", "蠕变")),
    ("蠕变", ("蠕变", "持久")),
)
CONDITION_FEATURE_TOKENS = {
    "室温拉伸": ("抗拉强度", "屈服", "伸长率", "收缩率"),
    "高温拉伸": ("抗拉强度", "屈服", "伸长率", "收缩率"),
    "低温拉伸": ("抗拉强度", "屈服", "伸长率", "收缩率"),
    "夏比冲击": ("冲击", "KU", "KV", "AK"),
    "冲击": ("冲击", "KU", "KV", "AK"),
    "布氏硬度": ("布氏", "HBW"),
    "洛氏硬度": ("洛氏", "HRC", "HRB"),
    "维氏硬度": ("维氏", "HV"),
    "硬度": ("硬度", "HBW", "HRC", "HV"),
    "室温持久": ("持久", "蠕变"),
    "高温持久": ("持久", "蠕变"),
    "高温光滑持久": ("持久", "蠕变"),
    "持久": ("持久", "蠕变"),
    "蠕变": ("蠕变", "持久"),
    "低倍": ("低倍", "酸浸"),
    "高倍组织": ("高倍", "显微"),
    "晶粒度": ("晶粒度",),
    "非金属夹杂": ("非金属夹杂", "夹杂物"),
    "超声波检测": ("超声", "探伤"),
    "表面质量": ("表面质量", "外观"),
    "铁素体": ("铁素体",),
}
NUMERIC_CELL_RE = re.compile(
    r"^[≥≤<>]?\s*-?\d+(?:\.\d+)?(?:\s*[-~～]\s*-?\d+(?:\.\d+)?)?$"
)
CONDITION_VALUE_RE = re.compile(
    r"^[≥≤<>]?\s*-?\d+(?:\.\d+)?"
    r"(?:\s*[-~～]\s*-?\d+(?:\.\d+)?)?"
    r"(?:\s*[（(]\s*\d+(?:\.\d+)?\s*[)）])?"
    r"\s*(?:MPa|GPa|%|J|HBW|HRC|HB|HV)?$",
    re.IGNORECASE,
)
CONDITION_UNITS = ("MPa", "GPa", "HBW", "HRC", "HRB", "HV", "J", "%")


def _condition_label(text: str) -> str:
    """Drop property symbols so values do not hide behind "Rp0.2" digits."""

    label = _clean(text) or ""
    label = re.sub(
        r"\s*(?:R[mM]\b|R[pP]\s*\d+(?:\.\d+)?|R[eE][lLhH]|δ\s*\d+|ψ)\s*",
        "",
        label,
    )
    label = re.sub(r"\(\s*\)|（\s*）", "", label).strip(" ：:（）()")
    return label or _clean(text) or ""


def _condition_property_header(header: str) -> bool:
    text = (header or "").lower()
    return any(
        token.lower() in text
        for _, tokens in CONDITION_PROPERTY_TOKENS
        for token in tokens
    )


def _condition_tokens(display: str, feature: str) -> tuple[str, ...]:
    notch = re.match(r"^(KU|KV|AK)\d", display.strip(), re.IGNORECASE)
    if notch:
        return (display.strip(),)
    for key, tokens in CONDITION_PROPERTY_TOKENS:
        if key in display:
            return tokens
    return CONDITION_FEATURE_TOKENS.get(feature, ())


def _condition_header_allowed(feature: str, text: str) -> bool:
    """Keep高温/低温列 separate so tables do not leak across temperatures."""

    if not text:
        return True
    cleaned = re.sub(
        r"(?:固溶|时效|淬火|回火|退火|正火)[^/；;，,]*", "", text
    )
    if "高温" in feature or "持久" in feature or "蠕变" in feature:
        return "高温" in cleaned or bool(
            re.search(r"(?:[3-9]\d{2}|1\d{3})\s*(?:℃|°C)", cleaned)
        )
    if "低温" in feature:
        return "低温" in cleaned or bool(
            re.search(r"-\s*\d{2,3}\s*(?:℃|°C)", cleaned)
        )
    if feature in {"夏比冲击", "冲击"}:
        return True
    return "高温" not in cleaned and "低温" not in cleaned


def _condition_cell_value(cell: str, header: str) -> str | None:
    text = _clean(cell)
    if not text or text in {"-", "—", "－", "/", "实测"}:
        return None
    if not CONDITION_VALUE_RE.match(text):
        return None
    header_text = _clean(header) or ""
    if re.search(r"HB\s*[（(]?\s*[dD]\s*[)）]?(?![A-Za-z])|压痕", header_text):
        return None
    parenthesized = re.match(
        r"^(\d+(?:\.\d+)?)\s*[（(]\s*(\d+(?:\.\d+)?)\s*[)）]$", text
    )
    if parenthesized and "ksi" in header_text.lower():
        text = parenthesized.group(2)
    unit = next(
        (
            candidate
            for candidate in CONDITION_UNITS
            if candidate.lower() in header_text.lower()
        ),
        "",
    )
    if not text.startswith(("≥", "≤", "<", ">")):
        if "不小于" in header_text:
            text = f"≥{text}"
        elif "不大于" in header_text:
            text = f"≤{text}"
    if unit and unit.lower() not in text.lower():
        text = f"{text}{unit}"
    return text


def _condition_table_allowed(
    table: dict[str, Any], grade: str, grades: list[str]
) -> bool:
    caption = _clean(table.get("caption")) or ""
    if not caption:
        return True
    named = [item for item in grades if item and item in caption]
    if named and grade and grade not in named:
        return False
    return True


def _condition_segments_horizontal(
    display: str,
    feature: str,
    tokens: tuple[str, ...],
    table: dict[str, Any],
    grade: str,
) -> list[str]:
    headers, start = _table_headers_and_start(table)
    rows = table.get("rows") or []
    if not rows:
        return []
    skip_words = ("温度", "直径", "方向", "状态", "级别", "牌号", "公称", "序号")
    for column, header in enumerate(headers):
        if not header or any(word in header for word in skip_words):
            continue
        if not any(token.lower() in header.lower() for token in tokens):
            continue
        if not _condition_header_allowed(feature, header):
            continue
        segments: list[str] = []
        for row in rows[start:]:
            if not row or is_footnote_row(row) or column >= len(row):
                continue
            value = _condition_cell_value(row[column], header)
            if not value:
                continue
            conditions: list[str] = []
            for index, cell in enumerate(row):
                if index >= column:
                    break
                cell_header = headers[index] if index < len(headers) else ""
                if _condition_property_header(cell_header):
                    continue
                text = _clean(cell)
                if not text or text in {"-", "—", "－", "/"} or text == grade:
                    continue
                if "温度" in cell_header and NUMERIC_CELL_RE.match(text):
                    conditions.append(f"{text}℃")
                elif not NUMERIC_CELL_RE.match(text) and len(text) <= 24:
                    conditions.append(text)
            segment = f"{_condition_label(display)}：{value}"
            if conditions:
                segment += f"（{'，'.join(conditions[:3])}）"
            segments.append(segment)
        if segments:
            return segments
    return []


def _condition_segments_vertical(
    display: str,
    feature: str,
    tokens: tuple[str, ...],
    table: dict[str, Any],
    grade: str,
) -> list[str]:
    rows = table.get("rows") or []
    segments: list[str] = []
    for row in rows:
        if not row or is_footnote_row(row):
            continue
        cells = [_clean(cell) or "" for cell in row]
        match = None
        value_index = None
        for index, cell in enumerate(cells):
            if cell and any(token.lower() in cell.lower() for token in tokens):
                match = index
            elif match is not None and NUMERIC_CELL_RE.match(cell):
                value_index = index
                break
        if match is None or value_index is None:
            continue
        if re.search(r"HB\s*[（(]?\s*[dD]\s*[)）]?(?![A-Za-z])|压痕", cells[match]):
            continue
        row_text = " ".join(cells)
        if not _condition_header_allowed(feature, row_text):
            continue
        unit = next(
            (
                cell
                for cell in reversed(cells)
                if cell.upper() in {"MPA", "GPA", "J", "%", "HBW", "HRC", "HB", "HV"}
            ),
            "",
        )
        minimum = cells[value_index]
        maximum = ""
        if (
            value_index + 1 < len(cells)
            and NUMERIC_CELL_RE.match(cells[value_index + 1])
        ):
            maximum = cells[value_index + 1]
        if maximum:
            value = f"{minimum}~{maximum}"
        else:
            comparator = (
                "≥"
                if any("最小" in cell or "不小于" in cell for cell in cells)
                else ""
            )
            value = f"{comparator}{minimum}"
        if unit and unit.lower() not in value.lower():
            value += unit
        conditions = [
            cell
            for index, cell in enumerate(cells)
            if cell
            and index not in {match, value_index, value_index + 1}
            and cell != unit
            and cell != grade
            and cell not in {"-", "—", "－", "/"}
            and "试验" not in cell
            and not NUMERIC_CELL_RE.match(cell)
            and len(cell) <= 24
        ][:3]
        segment = f"{_condition_label(cells[match]) or _condition_label(display)}：{value}"
        if conditions:
            segment += f"（{'，'.join(conditions)}）"
        if segment not in segments:
            segments.append(segment)
        if len(segments) >= 3:
            break
    return segments


def _condition_table_is_schedule(table: dict[str, Any]) -> bool:
    """Inspection schedules ("要求条号/取样数量") carry no requirement values."""

    headers, _ = _table_headers_and_start(table)
    return any(
        "条号" in (header or "") or "取样数量" in (header or "")
        for header in headers
    )


def _requirement_from_condition_tables(
    display: str,
    feature: str,
    grade: str,
    tables: dict[str, dict[str, Any]],
    grades: list[str],
) -> str | None:
    """Summarise a table that keys requirements by size/direction/temperature.

    Some standards never repeat the grade inside mechanical tables: rows are
    "diameter + direction" and the columns are σb/σ0.2/δ5. Without this
    fallback those rows stay empty even though the values are present.
    """

    if feature not in CONDITION_FEATURES:
        return None
    tokens = _condition_tokens(display, feature)
    if not tokens:
        return None
    for table in tables.values():
        if _condition_table_is_schedule(table):
            continue
        if not _condition_table_allowed(table, grade, grades):
            continue
        segments = _condition_segments_horizontal(
            display, feature, tokens, table, grade
        ) or _condition_segments_vertical(display, feature, tokens, table, grade)
        if not segments:
            continue
        text = "；".join(segments[:3])
        return text[:240] + ("…" if len(text) > 240 else "")
    return None


def _clause_body(clause: ClauseRecord) -> str | None:
    text = _clause_text(clause)
    if text:
        return _strip_section_heading(text)
    for value in (clause.fields or {}).values():
        raw = _clean(getattr(value, "raw", None))
        if raw:
            return _strip_section_heading(raw)
    return None


def _strip_section_heading(text: str) -> str:
    return re.split(r"\s*##\s", text, maxsplit=1)[0].strip() or text


def _is_requirement_sentence(text: str) -> bool:
    if len(text) < 6:
        return False
    if any(word in text for word in ("试验方法", "取样", "检验方法", "检验规则", "仲裁")):
        return False
    return True


def _hanson_requirement(value: Any) -> str | None:
    if value is None:
        return None
    text = _clean(getattr(value, "text", None))
    comparator = getattr(value, "comparator", None)
    if text and comparator in {None, "text"}:
        return text
    raw = _clean(getattr(value, "raw", None))
    if not raw:
        return text
    if comparator == "min":
        return raw if raw.startswith(("≥", ">")) else f"≥{raw}"
    if comparator == "max":
        return raw if raw.startswith(("≤", "<")) else f"≤{raw}"
    if comparator == "na":
        return raw or "-"
    return raw or text


def _hanson_persistence_rows(
    tables: dict[str, dict[str, Any]],
    method: str | None,
    default_grade: str | None = None,
    *,
    inspections: list[Any] | None = None,
    standard_name: str | None = None,
) -> list[dict[str, Any]]:
    """Map 持久性能 tables (牌号/温度/应力/保持时间) into schema rows."""
    rows: list[dict[str, Any]] = []
    for table in tables.values():
        headers = [
            " ".join(path) for path in (table.get("header_paths") or [])
        ]
        if not headers or not any(
            "应力" in header or "σ" in header for header in headers
        ):
            continue
        if not any(
            "保持时间" in header
            or "持久" in header
            or "tau" in header.lower()
            for header in headers
        ):
            continue
        grade_index = next(
            (
                index
                for index, header in enumerate(headers)
                if "牌号" in header or "材料" in header
            ),
            None,
        )
        temperature_index = next(
            (index for index, header in enumerate(headers) if "温度" in header),
            None,
        )
        stress_index = next(
            (
                index
                for index, header in enumerate(headers)
                if "持久" in header and ("σ" in header or "应力" in header)
            ),
            None,
        )
        if stress_index is None:
            stress_index = next(
                (
                    index
                    for index, header in enumerate(headers)
                    if "应力" in header
                ),
                None,
            )
        if stress_index is None:
            stress_index = next(
                (
                    index
                    for index, header in enumerate(headers)
                    if "σ" in header and "σb" not in header.lower()
                ),
                None,
            )
        time_index = next(
            (
                index
                for index, header in enumerate(headers)
                if "保持时间" in header
                or "时间" in header
                or "tau" in header.lower()
            ),
            None,
        )
        if stress_index is None or time_index is None:
            continue
        header_rows = int(table.get("header_rows") or 0)
        for row in (table.get("rows") or [])[header_rows:]:
            if len(row) <= max(stress_index, time_index):
                continue
            grade = (
                _clean(row[grade_index])
                if grade_index is not None and grade_index < len(row)
                else default_grade
            )
            stress = _clean(row[stress_index])
            duration = _clean(row[time_index])
            if not grade or not stress or not duration:
                continue
            # 表注行（首列是整段说明）会被合并单元格重复填充，不能当数据行。
            if len(str(grade)) > 12 or str(grade).startswith("注"):
                continue
            if not NUMBER_RE.search(stress):
                continue
            temperature = ""
            if temperature_index is not None and temperature_index < len(row):
                temperature = _normalize_degrees(_clean(row[temperature_index]))
                if (
                    temperature
                    and "℃" not in temperature
                    and temperature not in {"室温", "高温", "低温"}
                ):
                    temperature = f"{temperature}℃"
            feature = "室温持久"
            if temperature and not re.search(r"[\s(]*(?:室温|20|23|25)", temperature):
                feature = "高温光滑持久"
            item_row: dict[str, Any] = {
                "项目名称": "持久强度",
                "材料牌号": grade,
                "标准要求": f"应力{stress}MPa，保持{duration}h",
                "单位": "MPa",
            }
            if temperature:
                item_row["试验温度"] = temperature
            if method:
                item_row["试验方法"] = method
            inspection = _find_inspection_by_feature(feature, inspections or [])
            position = ""
            if inspection is not None:
                position = _clean(getattr(inspection, "sample_location", None))
                if position in HANSON_GENERIC_SAMPLING:
                    position = ""
            form = _hanson_product_form(standard_name)
            base_row = dict(item_row)
            variants = _sample_variants(inspection)
            for key, raw, count in variants:
                item_row = dict(base_row)
                label = _class_label(key)
                if label:
                    item_row["类别"] = label
                if count is not None:
                    item_row["取样数量"] = count
                if raw:
                    if key and key != "default":
                        item_row["取样说明"] = f"{key}:{raw}"
                    else:
                        item_row["取样说明"] = raw
                elif inspection is not None:
                    note = _sample_note(inspection) or _clean(
                        getattr(inspection, "note", None)
                    )
                    if note:
                        item_row["取样说明"] = note
                if position:
                    item_row["位置"] = position
                    direction = _direction(position)
                    if direction:
                        item_row["方向"] = direction
                if form:
                    item_row["锻件类型"] = form
                item_row["_feature"] = feature
                rows.append(item_row)
    return rows


def _hanson_heat_records(
    clauses: list[ClauseRecord],
    classifications: list[ClassificationItem],
    tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    grade = classifications[0].grade if len(classifications) == 1 else None
    for clause in clauses:
        text = _clause_text(clause)
        if not text or not re.search(r"热处理|淬火|回火|时效|固溶|退火", text):
            continue
        params = _heat_params(text)
        if not params:
            continue
        row: dict[str, Any] = {
            "材料牌号": grade or "",
            "工序名称": params.get("工序名称") or "",
            "保温温度": params.get("保温温度") or "",
            "保温时间": params.get("保温时间") or "",
        }
        for name in HANSON_HEAT_OPTIONAL:
            value = params.get(name)
            if value:
                row[name] = value
        rows.append(row)
    rows.extend(_hanson_heat_from_tables(tables, grade))
    return _dedupe_hanson_rows(rows)


def _hanson_heat_from_tables(
    tables: list[dict[str, Any]], grade: str | None
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in tables:
        header_rows = int(table.get("header_rows") or 0)
        for row in (table.get("rows") or [])[header_rows:]:
            if len(row) < 2:
                continue
            cells = [str(cell).strip() for cell in row if str(cell).strip()]
            if not cells or len(set(cells)) == 1:
                continue
            grade_value = str(row[0]).strip()
            text = _normalize_degrees(str(row[1]))
            if not grade_value or not text:
                continue
            if "牌号" in grade_value or "材料" in grade_value:
                continue
            if not HANSON_HEAT_TEMPERATURE_RE.search(text):
                continue
            for segment in re.split(r"[。；]", text):
                segment = segment.strip()
                if not segment:
                    continue
                process = ""
                match = re.match(r"^(.{1,12}?)[：:]", segment)
                if match:
                    process = match.group(1).strip()
                    segment = segment[match.end() :]
                else:
                    for keyword in ("固溶", "淬火", "回火", "时效", "退火", "正火"):
                        if keyword in segment:
                            process = keyword
                            break
                temperature = HANSON_HEAT_TEMPERATURE_RE.search(segment)
                duration = HANSON_HEAT_TIME_RE.search(segment)
                cooling = HANSON_COOLING_RE.findall(segment)
                if not temperature and not duration:
                    continue
                row: dict[str, Any] = {
                    "材料牌号": grade_value or grade or "",
                    "工序名称": process,
                    "保温温度": temperature.group(0).replace(" ", "")
                    if temperature
                    else "",
                    "保温时间": duration.group(0) if duration else "",
                }
                if process:
                    row["工艺名称"] = process
                if cooling:
                    row["冷却介质"] = "/".join(dict.fromkeys(cooling))
                rows.append(row)
    return rows


def _property_in_family(prop: str, family: str) -> bool:
    key = canonical_property(prop) or prop
    if family == "impact":
        return key in {"KV2", "KU1", "KU2", "KU5", "LE"}
    if family == "hardness":
        return key in {"HB", "HRB", "HRC", "HV"}
    if family == "tensile":
        return key in {
            "Rm",
            "Rp0.2",
            "ReH",
            "ReL",
            "A",
            "A50mm",
            "Z",
            "E",
            "KIC",
        }
    if family == "stress_rupture":
        return str(key).startswith("σ")
    return True


def _is_product_analysis(record: Record) -> bool:
    """A 成品分析 chemistry row (as opposed to 熔炼分析)."""

    if (record.facets or {}).get("analysis") == "成品分析":
        return True
    return _clean(record.condition) == "成品分析"


def _value_signature(value: Any) -> tuple:
    """Semantic value identity for duplicate heat/product rows."""

    return (
        str(getattr(value, "comparator", None) or ""),
        getattr(value, "value", None),
        getattr(value, "lower", None),
        getattr(value, "upper", None),
        str(getattr(value, "text", None) or ""),
        str(getattr(value, "unit", None) or ""),
    )


def _hanson_candidates(
    item: ItemInventoryEntry,
    feature: str,
    records: list[Record],
    tables: dict[str, dict[str, Any]],
) -> list[Record]:
    if not records:
        return []
    family = item.item_family or ""
    profiles = {
        record.source_table_id: (tables.get(str(record.source_table_id)) or {}).get(
            "profile"
        )
        for record in records
    }
    if family == "chemical_composition":
        chemical = [
            record
            for record in records
            if profiles.get(record.source_table_id) == "chemical_composition"
        ]
        heat_signatures: dict[str, set[tuple]] = {}
        for record in chemical:
            if _is_product_analysis(record):
                continue
            for key, value in (record.properties or {}).items():
                heat_signatures.setdefault(key, set()).add(_value_signature(value))
        # 成品分析只去掉“与任一熔炼分析值完全相同”的重复项；数值不同的
        # 成品分析（如 304 的 Mn ≤2.04 对熔炼 ≤2.00）必须保留。
        filtered: list[Record] = []
        for record in chemical:
            if not _is_product_analysis(record):
                filtered.append(record)
                continue
            remaining = {
                key: value
                for key, value in (record.properties or {}).items()
                if _value_signature(value) not in heat_signatures.get(key, set())
            }
            if remaining:
                filtered.append(
                    record.model_copy(update={"properties": remaining})
                )
        return filtered
    if family == "tensile":
        hot = "高温" in feature
        low = "低温" in feature
        selected: list[Record] = []
        for record in records:
            if profiles.get(record.source_table_id) not in HANSON_MECHANICAL_PROFILES:
                continue
            temperature = _hanson_record_temperature(record)
            condition = _normalize_degrees(record.condition)
            if "试验温度" in condition:
                continue
            if hot:
                if temperature and temperature not in {"室温", "20℃", "23℃", "25℃"}:
                    selected.append(record)
            elif low:
                if "低温" in temperature or temperature.startswith("-"):
                    selected.append(record)
            elif not temperature or temperature in {"室温", "20℃", "23℃", "25℃"}:
                selected.append(record)
        return selected
    if family == "hardness":
        scale = str(item.facets.get("hardness_scale") or "")
        allowed = {
            "brinell": {"HB"},
            "rockwell": {"HRB", "HRC"},
            "vickers": {"HV"},
        }.get(scale)
        if allowed:
            return [
                record
                for record in records
                if any(
                    canonical_property(key) in allowed
                    for key in (record.properties or {})
                )
            ]
        return [
            record
            for record in records
            if any(
                canonical_property(key) in {"HB", "HRB", "HRC", "HV"}
                for key in (record.properties or {})
            )
        ]
    if family == "impact":
        return [
            record
            for record in records
            if any(
                canonical_property(key) in {"KV2", "KU1", "KU2", "KU5", "LE"}
                for key in (record.properties or {})
            )
        ]
    if family == "stress_rupture":
        return [
            record
            for record in records
            if any(str(key).startswith("σ") for key in (record.properties or {}))
        ]
    if family in {"metallography", "surface", "dimension", "ndt"}:
        return []
    if not item.properties:
        return []
    return list(records)


def _tensile_records(
    records: list[Record], tables: dict[str, dict[str, Any]]
) -> list[Record]:
    """All tensile records, across room-, high- and low-temperature tables."""

    profiles = {
        record.source_table_id: (tables.get(str(record.source_table_id)) or {}).get(
            "profile"
        )
        for record in records
    }
    selected: list[Record] = []
    for record in records:
        if profiles.get(record.source_table_id) not in HANSON_MECHANICAL_PROFILES:
            continue
        if any(
            _property_in_family(key, "tensile")
            for key in (record.properties or {})
        ):
            selected.append(record)
    return selected


def _inspection_with_temperature(
    inspections: list[Any], record: Record | None, feature: str
) -> Any | None:
    """Pick the inspection row that names the record's test temperature."""

    if record is None or not inspections:
        return None
    temperature = _normalize_degrees(_hanson_record_temperature(record))
    if not temperature:
        return None
    for inspection in inspections:
        item_text = _normalize_degrees(_clean(getattr(inspection, "item", None)))
        if temperature in item_text:
            return inspection
        if feature.startswith("高温") and "高温" in item_text:
            return inspection
    return None


def _temperature_number(text: str | None) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", text or "")
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _tensile_feature_for_record(record: Record | None, default: str) -> str:
    """Route one tensile value to the feature implied by its temperature."""

    if record is None:
        return default
    temperature = _hanson_record_temperature(record)
    if not temperature:
        return default
    if "低温" in temperature or temperature.startswith("-"):
        return "低温拉伸"
    value = _temperature_number(temperature)
    if value is not None:
        if value <= 0:
            return "低温拉伸"
        if value >= 100:
            return "高温拉伸"
    return "室温拉伸"


def _hanson_property_pairs(
    item: ItemInventoryEntry,
    properties: list[str],
    candidates: list[Record],
) -> list[tuple[str, PropertyMatch | None, Record | None, Any]]:
    matches = {match.raw: match for match in item.property_matches}
    pairs: list[tuple[str, PropertyMatch | None, Record | None, Any]] = []
    for prop in properties:
        match = matches.get(prop)
        key = (
            canonical_property(prop)
            or canonical_property(match.raw if match else None)
            or prop
        )
        element = canonical_element(prop) if not canonical_property(prop) else None
        found = False
        for record in candidates:
            for record_key, value in (record.properties or {}).items():
                if key and (
                    canonical_property(record_key) == key or record_key == key
                ):
                    pairs.append((prop, match, record, value))
                    found = True
                elif element and canonical_element(record_key) == element:
                    pairs.append((prop, match, record, value))
                    found = True
        if not found:
            pairs.append((prop, match, None, None))
    return pairs


def _hanson_feature(item: ItemInventoryEntry) -> str:
    family = item.item_family or ""
    label = f"{item.item_raw or ''} {item.business_name or ''}"
    facets = item.facets or {}
    temperature = str(facets.get("temperature") or "")
    if family == "tensile":
        numeric = _label_temperature(label)
        if "高温" in label or "高温" in temperature or (
            numeric is not None and numeric >= 100
        ):
            return "高温拉伸"
        if "低温" in label or "低温" in temperature or (
            numeric is not None and numeric <= 0
        ):
            return "低温拉伸"
        name = _clean(item.business_category_name)
        if name in {"室温拉伸", "高温拉伸", "低温拉伸"}:
            return name
        return "室温拉伸"
    if family == "dimension":
        return "尺寸"
    if family == "stress_rupture":
        # 字典把“光滑持久”统一归到“室温持久”，但 650℃ 的持久试验必须
        # 投影为高温持久，否则试验温度与项目名称自相矛盾。
        numeric = _label_temperature(label)
        if "高温" in label or "高温" in temperature or (
            numeric is not None and numeric >= 100
        ):
            return "高温光滑持久"
        name = _clean(item.business_category_name)
        return name or "室温持久"
    name = _clean(item.business_category_name)
    if name:
        return name
    if family == "hardness":
        return HANSON_HARDNESS.get(str(facets.get("hardness_scale") or ""), "布氏硬度")
    if family == "impact":
        return "夏比冲击"
    if family == "chemical_composition":
        return "化学成分"
    if family == "surface":
        return "外观质量"
    if family == "ndt":
        if any(keyword in label for keyword in ("渗透", "荧光")):
            return "渗透检测"
        if "磁粉" in label:
            return "磁粉检测"
        if "射线" in label:
            return "射线检测"
        return "超声波检测"
    if family == "metallography":
        return "低倍" if "低倍" in label else "高倍组织"
    return (
        _clean(item.business_name)
        or _clean(item.item_canonical)
        or _clean(item.item_raw)
        or "其他检测项目"
    )


def _label_temperature(label: str) -> float | None:
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:℃|°C)", label)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


GRADE_IN_TEXT_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(GH\d{3,4}[A-Za-z]*|TA\d{1,2}|TC\d{1,2}|TB\d{1,2}"
    r"|\d{1,3}Cr\d{1,2}(?:[A-Z][a-z]?\d{0,2})+"
    r"|[A-Z]{1,2}\d{2,4}[A-Za-z]?)"
    r"(?![A-Za-z0-9])"
)


def _grade_from_text(text: str | None) -> str | None:
    value = _clean(text) or ""
    for match in GRADE_IN_TEXT_RE.finditer(value):
        window = value[max(0, match.start() - 16) : match.end() + 16]
        if any(
            token in window
            for token in ("合金", "牌号", "不锈钢", "钢", "锻件", "棒材", "技术条件")
        ):
            return match.group(1)
    return None


def _document_grade_from_clauses(clauses: list[ClauseRecord]) -> str | None:
    """Infer the product grade from the scope clause (e.g. GH4169合金棒材)."""

    for clause in clauses:
        title = _clean(clause.title) or ""
        text = " ".join(
            part for part in (title, _clause_body(clause) or "") if part
        )
        if not text:
            continue
        if (
            "范围" not in title
            and "本文件" not in text
            and "本规范" not in text
            and "本技术协议" not in text
        ):
            continue
        grade = _grade_from_text(text)
        if grade:
            return grade
    return None


def _plausible_grade(text: str | None) -> bool:
    value = _clean(text)
    if not value:
        return False
    if value == "全部牌号":
        return True
    # 2xxx–8xxx 是常见铝合金牌号；第二位必须是 0 或字母（6061/7075/2A12）。
    # 4892/6219/4963 这类文档号片段不是牌号。
    if re.fullmatch(r"[2-8](?:0|[A-Z])\d{2}", value):
        return True
    return looks_like_grade(value)


def _looks_like_upload_id(grade: str | None, text: str | None) -> bool:
    value = _clean(grade) or ""
    if not re.fullmatch(r"\d{4}", value):
        return False
    for token in re.findall(r"[0-9a-fA-F]{20,}", text or ""):
        if value in token:
            return True
    return False


def _hanson_grade(
    grade: str | None,
    default_grade: str | None,
    family: str,
    standard_name: str | None = None,
) -> str:
    text = _clean(grade) or ""
    fallback = _clean(default_grade) or ""
    if _looks_like_upload_id(text, standard_name):
        text = fallback
    elif (
        re.fullmatch(r"[2-8]\d{3}", text)
        and fallback
        and fallback[:2].upper() in {"GH", "TA", "TC", "TB"}
    ):
        # JX-25-035 / MAS7079 upload ids are 4-digit prefixes, not grades.
        text = fallback
    elif not _plausible_grade(text):
        # 级别（A/B）、尺寸区间、上传编号都不是牌号；没有可靠兜底时留空。
        text = fallback
    if not text and family in {
        "dimension",
        "bend",
        "metallography",
        "surface",
        "ndt",
    }:
        return "全部牌号"
    return text


def _method_code_prefix(feature: str) -> str | None:
    return {
        "洛氏硬度": "HR",
        "布氏硬度": "HB",
        "维氏硬度": "HV",
    }.get(feature)


def _select_hardness_method(method: str, feature: str) -> str:
    parts = [part.strip() for part in re.split(r"[,，、;；]", method) if part.strip()]
    if len(parts) <= 1:
        return method
    keyword = {
        "洛氏硬度": "230",
        "布氏硬度": "231",
        "维氏硬度": "4340",
    }.get(feature)
    if keyword:
        for part in parts:
            if keyword in part:
                return part
    return method


def _hanson_feature_rank(feature: str) -> int:
    try:
        return HANSON_FEATURE_ORDER.index(feature)
    except ValueError:
        return len(HANSON_FEATURE_ORDER)


def _hanson_temperature(
    feature: str,
    record: Record | None,
    item: ItemInventoryEntry,
    inspection: Any | None = None,
) -> str | None:
    if feature == "化学成分":
        return None
    text = _normalize_degrees(record.condition) if record is not None else ""
    # 条件列通常按“状态 / 热处理 / 试验温度”排列；只取独立的温度段，
    # 避免把热处理制度里的 1020℃ 当成试验温度。
    temperature = _test_temperature_from(text)
    if temperature:
        if feature.startswith("室温") and temperature in {"20℃", "23℃", "25℃"}:
            return "室温"
        return temperature
    if inspection is not None:
        # 检验计划把试验温度写在“测试条件”列（650℃×725MPa），记录本身
        # 没有 condition。
        condition_text = _normalize_degrees(getattr(inspection, "condition", None))
        planned = _test_temperature_from(condition_text) or _temperature_from(
            condition_text
        )
        if planned:
            return planned
    # 硬度/冲击未单列试验温度时按室温处理。
    if feature in {"布氏硬度", "洛氏硬度", "维氏硬度", "夏比冲击"}:
        return "室温"
    if feature.startswith("室温"):
        return "室温"
    if "室温" in text:
        return "室温"
    if feature.startswith("高温") and "高温" in text:
        return "高温"
    if feature.startswith("低温") and "低温" in text:
        return "低温"
    value = (item.facets or {}).get("temperature")
    text = _normalize_degrees(value if isinstance(value, str) else None)
    if text == "室温":
        return "室温"
    if "℃" in text:
        return text
    return None


def _hanson_position(
    item: ItemInventoryEntry, inspection: InspectionItem | None
) -> str | None:
    values = [
        getattr(inspection, "sample_location", None) if inspection is not None else None,
        (item.facets or {}).get("sampling_position"),
    ]
    for raw in values:
        text = _clean(raw)
        if text and text not in HANSON_GENERIC_SAMPLING:
            return text
    return None


def _hanson_direction(record: Record | None, position: str | None) -> str | None:
    if record is not None:
        direction = _direction(record.condition)
        if direction:
            return direction
    text = position or ""
    for token in HANSON_DIRECTIONS:
        if token in text:
            return token
    return None


def _hanson_thickness(record: Record | None, item: ItemInventoryEntry) -> str | None:
    facets = item.facets or {}
    for key in ("size_thickness", "thickness", "dimension"):
        value = _clean(facets.get(key))
        if value:
            return value
    if record is not None:
        for part in reversed(_normalize_degrees(record.condition).split("/")):
            text = part.strip()
            if THICKNESS_CONDITION_RE.match(text):
                return text
    return None


def _hanson_product_form(standard_name: str | None) -> str | None:
    text = standard_name or ""
    for token in HANSON_PRODUCT_FORMS:
        if token in text:
            return token
    return None


def _hanson_record_temperature(record: Record) -> str:
    return _test_temperature_from(_normalize_degrees(record.condition)) or ""


def _normalize_degrees(text: str | None) -> str:
    value = text or ""
    return value.replace("°C", "℃").replace("°c", "℃").replace("oC", "℃")


PROPERTY_SUFFIX_RE = re.compile(
    r"\s*(?:Rm|Rp0\.2|ReH|A50mm|A|Z|KU2|KU5|KV2|HBW|HBS|HRC|HRB|HV)\s*$",
    re.IGNORECASE,
)
ROW_MERGE_FIELDS = (
    "标准要求",
    "试验方法",
    "单位",
    "取样数量",
    "取样说明",
    "试验温度",
    "位置",
    "方向",
    "尺寸厚度",
    "试样状态",
    "锻件类型",
)


def _row_dedupe_key(row: dict[str, Any]) -> tuple[str, ...]:
    item = PROPERTY_SUFFIX_RE.sub("", _clean(row.get("项目名称")) or "").strip()
    return (
        _clean(row.get("材料牌号")) or "",
        item,
        _clean(row.get("试验温度")) or "",
        _clean(row.get("位置")) or "",
        _clean(row.get("尺寸厚度")) or "",
    )


def _merge_row_fields(existing: dict[str, Any], row: dict[str, Any]) -> None:
    for field in ROW_MERGE_FIELDS:
        if not _filled(existing.get(field)) and _filled(row.get(field)):
            existing[field] = row[field]


def _dedupe_hanson_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge duplicate item rows without mixing temperatures or requirements.

    The same physical row can be projected twice when two inventory items share
    a table (e.g. 室温拉伸 and 高温拉伸 both read one mechanical table). Exact
    JSON dedupe misses that because the display names differ slightly
    (``抗拉强度`` vs ``抗拉强度 Rm``); merging fills the empty method/requirement
    cells from the sibling row instead.

    A single grade can still carry several requirement rows that differ only by
    an unprojected size/state dimension (e.g. ≥1310/≥1170/≥1070). Those must
    stay separate: collapsing them would silently drop all but the first value.
    """

    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    order: list[tuple[str, ...]] = []
    for row in rows:
        key = _row_dedupe_key(row)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(row)

    merged: list[dict[str, Any]] = []
    for key in order:
        group = grouped[key]
        requirements = {
            _clean(row.get("标准要求"))
            for row in group
            if _clean(row.get("标准要求"))
        }
        if len(requirements) <= 1:
            current = dict(group[0])
            for row in group[1:]:
                _merge_row_fields(current, row)
            merged.append(current)
            continue
        by_requirement: dict[str, dict[str, Any]] = {}
        for row in group:
            requirement = _clean(row.get("标准要求")) or ""
            existing = by_requirement.get(requirement)
            if existing is None:
                by_requirement[requirement] = dict(row)
            else:
                _merge_row_fields(existing, row)
        merged.extend(by_requirement.values())
    return merged


# --------------------------------------------------------------- builders


def _build_items(
    category: SchemaCategory,
    inventory: ItemInventory,
    records: list[Record],
    inspections: list[Any],
    classifications: list[ClassificationItem],
    clauses: list[ClauseRecord],
    index: DictionaryIndex | None,
    standard_name: str | None,
    qualitative: dict[str, list[str]],
) -> tuple[list[dict], list[dict], str | None]:
    rows: list[dict[str, Any]] = []
    meta: list[dict[str, Any]] = []
    grades = sorted({item.grade for item in classifications if item.grade})
    default_grade = grades[0] if len(grades) == 1 else None

    for item in inventory.items:
        if item.status == "not_applicable":
            # Strict category mode excludes unknown major categories from the
            # projected schema; they remain in the aligned inventory artifact.
            continue
        inspection = _find_inspection(item, inspections)
        matches = {match.raw: match for match in item.property_matches}
        properties = item.properties or [match.raw for match in item.property_matches]
        pairs = _property_records(item, properties, records)
        if not pairs:
            clause_ids = _qualitative_clause_ids(item, qualitative)
            grade = default_grade
            if grade is None and clause_ids:
                grade = "全部牌号"
            rows.append(
                _item_row(
                    category,
                    item,
                    None,
                    None,
                    None,
                    grade,
                    inspection,
                    clauses,
                    index,
                    standard_name=standard_name,
                    qualitative_clause_ids=clause_ids,
                )
            )
            meta.append(_item_meta(item, None, None, inspection))
            continue
        for prop, match, record, value in pairs:
            rows.append(
                _item_row(
                    category,
                    item,
                    prop,
                    match or matches.get(prop),
                    value,
                    record.grade if record else default_grade,
                    inspection,
                    clauses,
                    index,
                    record=record,
                    standard_name=standard_name,
                )
            )
            meta.append(_item_meta(item, prop, value, inspection))

    note = None
    if not rows:
        note = "未从项目清单生成检测项目行"
    return rows, meta, note


def _build_standard_info(
    category: SchemaCategory,
    document: DocumentMeta,
    standard_name: str | None,
) -> tuple[list[dict], list[dict], str | None]:
    row = {
        "标准名称": standard_name,
        "标准编号": document.standard_no,
    }
    note = None
    if not standard_name:
        note = "未从版面/大纲识别到标准名称"
    return [row], [{"evidence": "outline.json"}], note


def _build_heat_treatment(
    category: SchemaCategory,
    clauses: list[ClauseRecord],
    classifications: list[ClassificationItem],
) -> tuple[list[dict], list[dict], str | None]:
    rows: list[dict[str, Any]] = []
    meta: list[dict[str, Any]] = []
    for clause in clauses:
        text = _clause_text(clause)
        if not text or not re.search(r"热处理|淬火|回火|时效|固溶|退火", text):
            continue
        params = _heat_params(text)
        if not params:
            continue
        grade = classifications[0].grade if len(classifications) == 1 else None
        row = {field.name: None for field in category.fields}
        row.update(
            {
                "工序名称": params.get("工序名称"),
                "工艺名称": params.get("工艺名称"),
                "材料牌号": grade,
                "项目大类": "热处理",
                "保温温度": params.get("保温温度"),
                "保温时间": params.get("保温时间"),
                "升温速率": params.get("升温速率"),
                "降温速率": params.get("降温速率"),
                "装炉温度": params.get("装炉温度"),
                "出炉温度": params.get("出炉温度"),
                "冷却介质": params.get("冷却介质"),
                "介质温度": params.get("介质温度"),
            }
        )
        rows.append(row)
        meta.append({"clause_id": clause.clause_id})
    note = None
    if not rows:
        note = "未识别到含温度/时间/介质参数的热处理条款（当前标准仅有状态代号表）"
    return rows, meta, note


# --------------------------------------------------------------- mapping helpers


def _item_row(
    category: SchemaCategory,
    item: ItemInventoryEntry,
    prop: str | None,
    match: PropertyMatch | None,
    value: Any,
    grade: str | None,
    inspection: Any,
    clauses: list[ClauseRecord],
    index: DictionaryIndex | None,
    *,
    record: Record | None = None,
    standard_name: str | None = None,
    qualitative_clause_ids: list[str] | None = None,
) -> dict[str, Any]:
    row = {field.name: None for field in category.fields}
    row["项目名称"] = _property_display(match, prop) or _item_display(item)
    row["材料牌号"] = grade
    row["标准要求"] = (
        _format_value(value)
        or _requirement_text(inspection, clauses)
        or _clause_requirement_text(qualitative_clause_ids or [], clauses)
    )
    row["单位"] = getattr(value, "unit", None) if value is not None else None
    row["试验方法"] = _method_number(item, index)
    row["试验温度"] = (
        _temperature_from(record.condition)
        if record
        else None
    ) or (
        record.facets.get("temperature") if record else None
    ) or item.facets.get("temperature")
    row["位置"] = (
        (inspection.sample_location if inspection else None)
        or item.facets.get("sampling_position")
    )
    row["方向"] = _direction(record.condition) if record else None
    row["尺寸厚度"] = (
        item.facets.get("size_thickness")
        or item.facets.get("thickness")
        or item.facets.get("dimension")
        or (_thickness_from(record.condition) if record else None)
    )
    row["试样状态"] = _state(record.condition) if record else None
    row["取样数量"] = _sample_count(inspection)
    row["取样说明"] = _sample_note(inspection)
    row["锻件类型"] = (
        item.facets.get("forging_type")
        or _forging_type(item, inspection, standard_name)
    )
    return row


def _property_records(
    item: ItemInventoryEntry,
    properties: list[str],
    records: list[Record],
) -> list[tuple[str, PropertyMatch | None, Record | None, Any]]:
    matches = {match.raw: match for match in item.property_matches}
    table_records = [row for row in records if row.source_table_id == item.table_id]
    scoped = table_records or records
    pairs: list[tuple[str, PropertyMatch | None, Record | None, Any]] = []
    for prop in properties:
        key = canonical_property(prop) or canonical_property(
            (matches.get(prop).raw if matches.get(prop) else None)
        )
        if not key and prop in {"CEV", "Pcm"}:
            key = prop
        element_key = canonical_element(prop) if not key else None
        found = False
        if key or element_key:
            for record in scoped:
                for record_key, value in record.properties.items():
                    if key and (
                        canonical_property(record_key) == key or record_key == key
                    ):
                        pairs.append((prop, matches.get(prop), record, value))
                        found = True
                    elif element_key and canonical_element(record_key) == element_key:
                        pairs.append((prop, matches.get(prop), record, value))
                        found = True
        if not found:
            pairs.append((prop, matches.get(prop), None, None))
    return pairs


INSPECTION_SYNONYMS: dict[str, tuple[str, ...]] = {
    "化学成分": ("化学成分", "成品分析", "化学分析"),
    "高温光滑持久": ("高温光滑持久", "高温持久", "高温纵向持久", "持久"),
    "室温持久": ("室温持久", "室温持久试验", "持久"),
    "夏比冲击": ("夏比冲击", "室温冲击", "低温冲击", "冲击试验", "冲击"),
    "超声波检测": (
        "超声波检测",
        "超声波检验",
        "超声波探伤",
        "超声检测",
        "超声检验",
        "超声探伤",
        "无损检测",
        "无损检验",
    ),
    "渗透检测": (
        "渗透检测",
        "渗透检验",
        "荧光检测",
        "荧光渗透检测",
    ),
    "射线检测": ("射线检测", "射线检验", "X射线检测", "X射线检验"),
    "尺寸": ("尺寸", "尺寸、外形", "尺寸和外形", "外形", "尺寸偏差", "尺寸外形"),
    "低倍": ("低倍", "低倍组织"),
    "高倍组织": ("高倍组织", "显微组织"),
    "产品标识": ("产品标识", "产品标志"),
    "布氏硬度": ("布氏硬度", "硬度"),
    "洛氏硬度": ("洛氏硬度", "硬度"),
    "室温拉伸": (
        "室温拉伸",
        "室温纵向拉伸",
        "室温拉伸试验",
        "拉伸试验",
        "拉伸试样",
        "力学性能",
    ),
    "高温拉伸": ("高温拉伸", "高温纵向拉伸", "高温拉伸试验", "拉伸"),
    "低温拉伸": ("低温拉伸", "低温纵向拉伸", "低温拉伸试验", "拉伸"),
}


def _normalize_term(text: str | None) -> str:
    value = re.sub(r"[\s\u3000、，,。；;：:（）()《》〈〉\-—_/]+", "", text or "")
    return value.lower()


def _inspection_score(inspection: Any, candidates: list[str]) -> int:
    item = _normalize_term(getattr(inspection, "item", ""))
    if not item:
        return -1
    best = -1
    for index, candidate in enumerate(candidates):
        value = _normalize_term(candidate)
        if not value:
            continue
        if item == value:
            score = 100 - index
        elif len(item) >= 2 and len(value) >= 2 and (value in item or item in value):
            score = 50 - index
        else:
            continue
        if getattr(inspection, "quantities", None):
            score += 10
        if getattr(inspection, "method_standard", None):
            score += 2
        if getattr(inspection, "sample_location", None):
            score += 1
        best = max(best, score)
    return best


def _matching_inspections(
    item: ItemInventoryEntry, inspections: list[Any], feature: str
) -> list[Any]:
    """All inspection rows belonging to one item (e.g. 盘前/盘后 sampling rows)."""

    candidates = [
        feature,
        *INSPECTION_SYNONYMS.get(feature, ()),
        item.item_raw or "",
        item.item_canonical or "",
    ]
    candidates = list(dict.fromkeys(value for value in candidates if value))
    scored = [
        (_inspection_score(inspection, candidates), index, inspection)
        for index, inspection in enumerate(inspections)
    ]
    scored = [row for row in scored if row[0] >= 0]
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in scored]


def _find_inspection(
    item: ItemInventoryEntry, inspections: list[Any], feature: str | None = None
) -> Any:
    candidates = [item.item_raw or "", item.item_canonical or ""]
    if feature:
        candidates.insert(0, feature)
        candidates.extend(INSPECTION_SYNONYMS.get(feature, ()))
    else:
        for name in list(candidates):
            candidates.extend(INSPECTION_SYNONYMS.get(name, ()))
    candidates = list(dict.fromkeys(value for value in candidates if value))
    scored = [
        (_inspection_score(inspection, candidates), index, inspection)
        for index, inspection in enumerate(inspections)
    ]
    scored = [row for row in scored if row[0] >= 0]
    if not scored:
        return None
    scored.sort(key=lambda row: (-row[0], row[1]))
    return scored[0][2]


def _find_inspection_by_feature(feature: str, inspections: list[Any]) -> Any:
    candidates = [feature, *INSPECTION_SYNONYMS.get(feature, ())]
    scored = [
        (_inspection_score(inspection, candidates), index, inspection)
        for index, inspection in enumerate(inspections)
    ]
    scored = [row for row in scored if row[0] >= 0]
    if not scored:
        return None
    scored.sort(key=lambda row: (-row[0], row[1]))
    return scored[0][2]



def _item_display(item: ItemInventoryEntry) -> str | None:
    if item.match_type in {
        "exact",
        "alias",
        "granularity",
        "semantic",
        "edit_distance",
    } and item.business_name:
        return item.business_name
    return item.item_canonical or item.item_raw or item.business_name


PROPERTY_LABELS = {
    "CEV": "碳当量",
    "Pcm": "焊接裂纹敏感性指数",
}


def _property_display(match: PropertyMatch | None, prop: str | None) -> str | None:
    if match and match.canonical_name:
        return _unwrap_parens(match.canonical_name)
    if prop in PROPERTY_LABELS:
        return PROPERTY_LABELS[prop]
    return prop


def _unwrap_parens(name: str) -> str:
    text = PAREN_RE.sub(lambda m: f" {m.group(1)}", name).replace(")", "").strip()
    return UNIT_SUFFIX_RE.sub("", text).strip()


def _format_value(value: Any) -> str | None:
    if value is None:
        return None
    text = _clean(value.text)
    if text and value.comparator in {None, "text"}:
        return text
    raw = _clean(value.raw)
    if value.comparator == "min":
        return f"≥{raw}" if raw else None
    if value.comparator == "max":
        return f"≤{raw}" if raw else None
    if value.comparator == "range":
        if value.lower is not None and value.upper is not None:
            return f"{_number(value.lower)}~{_number(value.upper)}"
        return raw
    return raw or text


def _qualitative_clause_ids(
    item: ItemInventoryEntry,
    mapping: dict[str, list[str]],
) -> list[str]:
    if not mapping:
        return []
    names = [item.item_raw or "", item.item_canonical or ""]
    matches = [
        (keyword, clause_ids)
        for keyword, clause_ids in mapping.items()
        if any(keyword and keyword in name for name in names)
    ]
    if not matches:
        return []
    return max(matches, key=lambda pair: len(pair[0]))[1]


def _clause_requirement_text(
    clause_ids: list[str],
    clauses: list[ClauseRecord],
) -> str | None:
    texts: list[str] = []
    for clause_id in clause_ids:
        for clause in clauses:
            if clause.clause_id != clause_id:
                continue
            text = _clause_text(clause) or _clean(clause.title)
            if text and text not in texts:
                texts.append(text)
            break
    return "；".join(texts) if texts else None


def _requirement_text(
    inspection: Any, clauses: list[ClauseRecord], pages_text: str | None = None
) -> str | None:
    if inspection is None:
        return None
    # 验收指标/验收要求 cells are the requirement itself; a clause citation is
    # only the fallback when the table points elsewhere.
    direct = _clean(getattr(inspection, "requirement", None))
    if direct:
        return direct
    if not inspection.requirement_clause:
        return None
    return _citation_requirement(inspection.requirement_clause, clauses, pages_text)


CLAUSE_CITATION_RE = re.compile(
    r"^\s*(?:见\s*)?(?P<id>\d{1,2}(?:\.\d{1,3}){0,4})\s*$"
)


def _normalize_citation(value: str | None) -> str | None:
    text = _clean(value) or ""
    match = CLAUSE_CITATION_RE.match(text)
    if match is None and len(text) <= 24 and not re.search(r"[A-Za-z]", text):
        # Free text such as "按4.4.2条" is acceptable; a standard number such
        # as "GB/T 4334.1" must never be mistaken for a clause citation.
        match = re.search(
            r"(?:见|按|符合)\s*(\d{1,2}(?:\.\d{1,3}){0,4})", text
        )
    return match.group(1) if match else None


def _citation_requirement(
    citation: str | None,
    clauses: list[ClauseRecord],
    pages_text: str | None = None,
) -> str | None:
    """Resolve a clause citation (``4.4.2``) to requirement text.

    Clause extraction misses some subsections when OCR drops a page or splits
    a heading into a table. The page text is the second source; when both are
    silent the caller must treat the citation as unresolved instead of
    inventing a value.
    """

    target = _normalize_citation(citation)
    if not target:
        return None
    texts: list[str] = []
    for clause in clauses:
        clause_id = _clean(clause.clause_id) or ""
        if clause_id != target and not (
            target.count(".") >= 1 and clause_id.startswith(f"{target}.")
        ):
            continue
        text = _clause_text(clause)
        if text and text not in texts:
            texts.append(text)
    if texts:
        return "；".join(texts)
    if not pages_text:
        return None
    heading = re.compile(
        rf"^(?:#{{1,6}}\s*)?{re.escape(target)}(?![\d.])(?:\s+[^\n]*)?$",
        re.MULTILINE,
    )
    match = heading.search(pages_text)
    if match is None:
        return None
    tail = pages_text[match.end() : match.end() + 800]
    tail = re.split(
        r"\n(?:\s*#{1,6}\s*)?\d{1,2}(?:\.\d{1,3}){1,4}\s", tail, maxsplit=1
    )[0]
    body = re.sub(r"<[^>]+>", " ", tail)
    body = re.sub(r"\s+", " ", body).strip()
    if len(body) < 6:
        return None
    return body[:240]


METHOD_CLAUSE_MARKERS = (
    "试验方法",
    "进行测试",
    "试验按",
    "按astm",
    "按gb/t 228",
    "in accordance with",
    "tested in accordance",
)


def _method_from_requirement_clause(
    citation: str | None,
    clauses: list[ClauseRecord],
    pages_text: str | None = None,
) -> str | None:
    """Read the method from the clause cited as the acceptance requirement.

    Inspection plans often cite "要求的章条号" (e.g. 3.4.2); that clause carries
    the test method ("按 ASTM E 21 进行测试"). Only clauses that explicitly
    mention a test method are used, so a process-standard citation is never
    mistaken for a test method.
    """

    target = _normalize_citation(citation)
    if not target:
        return None
    for clause in clauses:
        clause_id = _clean(clause.clause_id) or ""
        if clause_id != target and not (
            target.count(".") >= 1 and clause_id.startswith(f"{target}.")
        ):
            continue
        value = (clause.fields or {}).get("method_standard")
        if value is not None:
            method = _clean(getattr(value, "text", None)) or _clean(
                getattr(value, "raw", None)
            )
            if method:
                return method
    text = _citation_requirement(citation, clauses, pages_text) or ""
    lowered = text.lower()
    if not any(marker in lowered for marker in METHOD_CLAUSE_MARKERS):
        return None
    return _method_from_citation(citation, clauses, pages_text)


def _method_from_citation(
    citation: str | None,
    clauses: list[ClauseRecord],
    pages_text: str | None = None,
) -> str | None:
    """Return the first standard number mentioned by a cited clause."""

    text = _citation_requirement(citation, clauses, pages_text)
    if text:
        match = DOCUMENT_METHOD_REF_RE.search(text)
        if match is not None:
            return re.sub(r"\s*-\s*", "-", match.group(0))
    return _method_from_child_clauses(citation, clauses)


def _method_from_child_clauses(
    citation: str | None, clauses: list[ClauseRecord]
) -> str | None:
    """Collect methods stored on 4.7.1/4.7.2 when 4.7 carries only a title."""

    base = _normalize_citation(citation)
    if not base:
        return None
    found: list[str] = []
    for clause in clauses:
        clause_id = _clean(clause.clause_id) or ""
        if not clause_id.startswith(f"{base}."):
            continue
        value = (clause.fields or {}).get("method_standard")
        text = _clean(getattr(value, "text", None)) or _clean(
            getattr(value, "raw", None)
        )
        if text and text not in found:
            found.append(text)
    return "、".join(found) if found else None


def _clause_text(clause: ClauseRecord) -> str | None:
    field = clause.fields.get("requirement")
    if field is None:
        # Clauses without a positive requirement marker store their body under
        # the generic "text" field; negative requirements ("不准许…") used to
        # disappear here even after clause extraction captured them.
        field = clause.fields.get("text")
    if field is None:
        return None
    return _clean(field.text) or _clean(field.raw)


def _heat_params(text: str) -> dict[str, str]:
    """Very small parameter reader for inline heat-treatment sentences."""
    params: dict[str, str] = {}
    patterns = {
        "保温温度": r"(?:保温温度|加热温度)[^\d]{0,6}(\d+(?:\.\d+)?)\s*℃",
        "保温时间": r"(?:保温时间|保温)[^\d]{0,6}(\d+(?:\.\d+)?)\s*(?:h|小时)",
        "装炉温度": r"装炉温度[^\d]{0,6}(\d+(?:\.\d+)?)",
        "出炉温度": r"出炉温度[^\d]{0,6}(\d+(?:\.\d+)?)",
        "升温速率": r"升温速率[^\d]{0,6}(\d+(?:\.\d+)?)",
        "降温速率": r"降温速率[^\d]{0,6}(\d+(?:\.\d+)?)",
        "介质温度": r"介质温度[^\d]{0,6}(\d+(?:\.\d+)?)",
        "冷却介质": r"(?:冷却介质|介质)[为是:：]?\s*([\u4e00-\u9fff]{1,6}(?:冷|淬))",
    }
    for name, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            params[name] = match.group(1)
    if "工序名称" not in params:
        for keyword in ("固溶", "淬火", "回火", "时效", "退火", "正火"):
            if keyword in text:
                params["工序名称"] = keyword
                params.setdefault("工艺名称", keyword)
                break
    return params


def _method_number(
    item: ItemInventoryEntry,
    index: DictionaryIndex | None,
    *,
    prefer: str | None = None,
) -> str | None:
    codes = [code for code in (item.method_code or "").split("、") if code]
    if prefer:
        prefix = prefer.upper()
        codes.sort(
            key=lambda code: 0
            if code.split(":")[0].strip().upper() == prefix
            else 1
        )
    if index is not None and codes:
        entries = {
            entry.business_code: entry
            for entry in index.dictionary.entries
            if entry.type == "method"
        }
        numbers = [
            entries[code].standard_no
            for code in codes
            if code in entries and entries[code].standard_no
        ]
        dated = [number for number in numbers if YEAR_RE.search(number)]
        if dated:
            return dated[0]
        if numbers:
            return numbers[0]
    return item.method_standard


def _direction(condition: str | None) -> str | None:
    if not condition:
        return None
    for part in reversed([part for part in condition.split("/") if part.strip()]):
        if part.strip() in DIRECTIONS:
            return part.strip()
    return None


def _state(condition: str | None) -> str | None:
    if not condition:
        return None
    first = condition.split("/")[0].strip()
    if not first:
        return None
    if STATE_CODE_RE.match(first) or any(word in first for word in STATE_WORDS):
        return first
    return None


def _test_temperature_from(condition: str | None) -> str | None:
    """Return an explicit test-temperature segment, ignoring heat treatment.

    Conditions are assembled as ``状态 / 热处理 / 试验温度``; only the last
    standalone temperature segment is the test temperature. A value such as
    ``固溶(1020℃~1050℃...)`` must not leak into 试验温度.
    """

    if not condition:
        return None
    parts = [
        _normalize_degrees(part)
        for part in re.split(r"[/／]", condition)
        if part.strip()
    ]
    for part in reversed(parts):
        value = part.strip()
        if value in {"室温", "高温", "低温"}:
            return value
        if re.fullmatch(r"[<>≤≥]?\s*-?\d+(?:\.\d+)?\s*℃", value):
            return re.sub(r"\s+", "", value)
        if value.startswith("室温"):
            return "室温"
    return None


def _temperature_from(condition: str | None) -> str | None:
    if not condition:
        return None
    match = TEMPERATURE_RE.search(condition)
    if match:
        return f"{match.group(1)}℃"
    for word in ("室温", "高温", "低温"):
        if word in condition:
            return word
    return None


def _thickness_from(condition: str | None) -> str | None:
    if not condition:
        return None
    text = condition.split("/")[0].strip()
    return text if THICKNESS_CONDITION_RE.match(text) else None


def _class_label(key: str) -> str:
    return key if key and re.search(r"(类|级|组|规格|直径|状态)", key) else ""


def _sample_variants(inspection: Any) -> list[tuple[str, str | None, int | None]]:
    if inspection is None or not getattr(inspection, "quantities", None):
        return [("", None, None)]
    variants: list[tuple[str, str | None, int | None]] = []
    for key, raw in inspection.quantities.items():
        text = str(raw).strip()
        if not text or text in {"-", "—", "－", "/"}:
            continue
        holder = type("QuantityHolder", (), {"quantities": {key: text}})()
        variants.append((key, text, _sample_count(holder)))
    return variants or [("", None, None)]


def _expand_sample_variants(
    rows: list[dict[str, Any]], inspection: Any, feature: str
) -> list[dict[str, Any]]:
    """按 I/II/III/IV 类等取样要求展开行，避免多类数量被压成 None。

    化学成分按元素逐行给出要求，取样方案是批级要求；按类展开只会把
    每个元素复制多份，不增加信息量，因此跳过。
    """

    if feature == "化学成分":
        return rows
    variants = _sample_variants(inspection)
    if len([key for key, _, _ in variants if key]) < 2:
        return rows
    if len({(raw, count) for _, raw, count in variants}) < 2:
        return rows
    expanded: list[dict[str, Any]] = []
    for row in rows:
        for key, raw, count in variants:
            item_row = dict(row)
            item_row.pop("取样数量", None)
            item_row.pop("取样说明", None)
            label = _class_label(key)
            if label:
                item_row["类别"] = label
            if count is not None:
                item_row["取样数量"] = count
            if raw:
                item_row["取样说明"] = (
                    f"{key}:{raw}" if key and key != "default" else raw
                )
            expanded.append(item_row)
    return expanded


def _sample_count(inspection: Any) -> int | None:
    if inspection is None:
        return None
    values = [
        str(value).strip()
        for value in (inspection.quantities or {}).values()
        if value and str(value).strip() not in {"-", "—", "/"}
    ]
    if not values:
        return None
    counts: list[int] = []
    for value in values:
        # “表3，C”中的 3 是表号，不是取样件数；只有解析后才能得到数值。
        if re.search(r"表\s*[A-Za-z]?\s*\.?\s*\d+", value):
            continue
        # “不少于 N 件”取 N；百分比不是件数，不能当整数用。
        if "不少于" in value:
            match = re.search(r"不少于\s*(\d+)", value)
            if match:
                counts.append(int(match.group(1)))
            continue
        if "%" in value or "％" in value:
            continue
        # 区间取下限，例如“1~2个/批”取 1；原文保留在取样说明。
        if re.search(r"[~～]", value):
            numbers = [int(float(item)) for item in NUMBER_RE.findall(value)]
            if numbers:
                counts.append(min(numbers))
            continue
        # “每批/每炉/逐件”按一批一个样品计；若同时写了明确件数则取明确件数。
        if BATCH_ONCE_RE.search(value):
            counts.append(1)
            continue
        batch = BATCH_QUANTITY_RE.search(value)
        if batch:
            drawn = DRAWN_COUNT_RE.search(value)
            if drawn:
                counts.append(int(drawn.group(1)))
                continue
            explicit = UNIT_COUNT_RE.search(value)
            if explicit:
                counts.append(int(explicit.group(1)))
                continue
            counts.append(1)
            continue
        # 优先取显式件数；“逐件试验环，2个”应取 2，而不是逐件的 1。
        numbers = NUMBER_RE.findall(value)
        if numbers:
            counts.append(int(float(numbers[0])))
            continue
        if "逐" in value:
            counts.append(1)
    if not counts:
        return None
    unique = sorted(set(counts))
    if len(unique) > 1:
        return None
    return unique[0]


def _sample_note(inspection: Any) -> str | None:
    if inspection is None:
        return None
    parts = [
        (f"{key}:{value}" if key and key != "default" else str(value))
        for key, value in (inspection.quantities or {}).items()
        if value
    ]
    note = _clean(getattr(inspection, "note", None))
    if note and note not in parts:
        parts.append(note)
    return "；".join(parts) or None


def _forging_type(
    item: ItemInventoryEntry,
    inspection: Any = None,
    standard_name: str | None = None,
) -> str | None:
    if standard_name and "轧制锻件" in standard_name:
        return "轧制锻件"
    for value in (
        item.facets.get("sampling_position"),
        getattr(inspection, "sample_location", None) if inspection else None,
    ):
        if value and "锻件" in value:
            return value
    return None


def _has_cjk(text: str) -> int:
    return 1 if re.search(r"[\u4e00-\u9fff]", text) else 0


def _standard_name(document: DocumentMeta, outline: dict[str, Any]) -> str | None:
    candidates: list[tuple[float, int, str]] = []
    for order, node in enumerate(outline.get("nodes") or []):
        if node.get("kind") != "clause":
            continue
        page = node.get("page_no")
        if page is not None and page > 3:
            continue
        title = _normalize_standard_title(node.get("title"))
        if not title or len(title) < 4:
            continue
        score = _standard_title_score(title, page)
        if score <= 0:
            continue
        candidates.append((score, -order, title))
    if candidates:
        return max(candidates)[2]
    return _standard_name_from_filename(document)


def _standard_title_score(title: str, page: int | None) -> float:
    score = 0.0
    if STANDARD_TITLE_NUMBER_RE.match(title):
        score -= 8
    if any(word in title for word in STANDARD_TITLE_BOILERPLATE):
        score -= 7
    if title.endswith(("专用标准", "国家标准", "行业标准", "企业标准", "标准")):
        score -= 4
    if any(term in title for term in STANDARD_TITLE_PRODUCT_TERMS):
        score += 5
    if 4 <= len(title) <= 30:
        score += 2
    if _has_cjk(title):
        score += 2
    else:
        score -= 3
    if page == 1:
        score += 3
    elif page == 2:
        score += 1
    return score


def _normalize_standard_title(value: Any) -> str | None:
    text = _clean(value)
    if not text:
        return None
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff0-9A-Za-z])", "", text)
    text = re.sub(r"(?<=[0-9A-Za-z])\s+(?=[\u4e00-\u9fff])", "", text)
    return text.strip() or None


def _standard_name_from_filename(document: DocumentMeta) -> str | None:
    title = _clean(document.title) or _clean(document.file_name) or ""
    title = re.sub(r"^[0-9a-f]{20,}-", "", title, flags=re.IGNORECASE)
    title = re.sub(r"^\d+\s*[、.．]\s*", "", title)
    title = re.sub(r"\.(pdf|md|docx?)$", "", title, flags=re.IGNORECASE)
    standard_no = _clean(document.standard_no)
    if standard_no:
        compact = re.sub(r"\s+", "", standard_no)
        variants = {
            standard_no,
            compact,
            standard_no.replace("/", "／"),
            compact.replace("/", "／"),
            standard_no.replace("/", ""),
            compact.replace("/", ""),
        }
        for variant in sorted(variants, key=len, reverse=True):
            if title.startswith(variant):
                title = title[len(variant):]
                break
    title = re.sub(r"^[\s\-—_、]+", "", title)
    title = _normalize_standard_title(title)
    if title and len(title) >= 4 and _has_cjk(title):
        return title
    return None


def _method_from_clauses(
    item: ItemInventoryEntry, clauses: list[ClauseRecord]
) -> str | None:
    return _method_for_family(
        item.item_family or "",
        clauses,
        names=[
            name
            for name in (item.item_raw, item.item_canonical, item.business_name)
            if name
        ],
    )


def _method_for_family(
    family: str,
    clauses: list[ClauseRecord],
    names: list[str] | None = None,
) -> str | None:
    keywords = METHOD_FAMILY_KEYWORDS.get(family, ())
    if not keywords:
        return None
    names = names or []
    best: tuple[float, int, int, str] | None = None
    for order, clause in enumerate(clauses):
        text_parts = [_clean(clause.title), _clause_text(clause)]
        for value in (clause.fields or {}).values():
            text_parts.append(_clean(getattr(value, "raw", None)))
            text_parts.append(_clean(getattr(value, "text", None)))
        text = " ".join(part for part in text_parts if part)
        title = _clean(clause.title) or ""
        title_match = any(keyword in title for keyword in keywords)
        base = 0.0
        if clause.kind in {"test_method", "sampling", "inspection"}:
            base += 3
        if "试验方法" in title:
            base += 3
        if "方法" in title:
            base += 6
        if any(name in text for name in names):
            base += 2
        for match in METHOD_REFERENCE_RE.finditer(text):
            reference = re.sub(r"\s*-\s*", "-", match.group(0))
            label = _method_reference_label(text, match.end())
            label_match = any(keyword in label for keyword in keywords)
            if not title_match and not label_match:
                continue
            score = base
            if label_match:
                score += 5
            if title_match:
                score += 3
            if "-" in reference:
                score += 1
            candidate = (score, -order, -match.start(), reference)
            if best is None or candidate > best:
                best = candidate
    return best[3] if best is not None else None


def _method_reference_label(
    text: str, start: int, pattern: re.Pattern[str] | None = None
) -> str:
    tail = text[start : start + 120]
    next_match = (pattern or METHOD_REFERENCE_RE).search(tail)
    if next_match is not None:
        tail = tail[: next_match.start()]
    return tail[:80]




def _item_meta(
    item: ItemInventoryEntry,
    prop: str | None,
    value: Any,
    inspection: Any = None,
) -> dict[str, Any]:
    evidence = []
    if value is not None and getattr(value, "evidence_id", None):
        evidence.append(value.evidence_id)
    if not evidence:
        evidence.extend(item.evidence)
    return {
        "item_code": item.business_code,
        "property": prop,
        "table_id": item.table_id,
        "page_no": item.page_no,
        "evidence_ids": evidence,
        "sample_quantities": getattr(inspection, "quantities", None) if inspection else None,
    }


# --------------------------------------------------------------- coverage


def _validate(
    categories: list[dict[str, Any]], template: list[SchemaCategory]
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    by_key = {category.key: category for category in template}
    for output in categories:
        category = by_key[output["key"]]
        for row_index, row in enumerate(output["rows"]):
            for field in category.fields:
                value = row.get(field.name)
                required = field.required or _required_by_condition(field, row)
                if required and not _filled(value):
                    errors.append(
                        {
                            "code": "required_missing",
                            "category": category.key,
                            "row": row_index,
                            "field": field.name,
                        }
                    )
                if field.type == "number" and _filled(value) and not _is_number(value):
                    errors.append(
                        {
                            "code": "type_mismatch",
                            "category": category.key,
                            "row": row_index,
                            "field": field.name,
                            "value": value,
                        }
                    )
    return errors


def _required_by_condition(field: SchemaField, row: dict[str, Any]) -> bool:
    if field.required_when == "numeric":
        return _is_numeric_requirement(row.get("标准要求"))
    return False


def _is_numeric_requirement(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return bool(NUMERIC_REQUIREMENT_RE.match(value))


def _coverage(
    categories: list[dict[str, Any]], template: list[SchemaCategory]
) -> dict[str, Any]:
    by_key = {category.key: category for category in template}
    total = filled = required_total = required_filled = 0
    per_category: dict[str, Any] = {}
    for output in categories:
        category = by_key[output["key"]]
        rows = output["rows"]
        cat_total = len(rows) * len(category.fields)
        cat_filled = sum(
            1 for row in rows for field in category.fields if _filled(row.get(field.name))
        )
        cat_required = sum(
            1
            for row in rows
            for field in category.fields
            if field.required or _required_by_condition(field, row)
        )
        cat_required_filled = sum(
            1
            for row in rows
            for field in category.fields
            if (field.required or _required_by_condition(field, row))
            and _filled(row.get(field.name))
        )
        per_category[category.key] = {
            "rows": len(rows),
            "fields_total": cat_total,
            "fields_filled": cat_filled,
            "field_rate": _ratio(cat_filled, cat_total),
            "required_total": cat_required,
            "required_filled": cat_required_filled,
            "required_rate": _ratio(cat_required_filled, cat_required),
            "fields": {
                field.name: {
                    "filled": sum(1 for row in rows if _filled(row.get(field.name))),
                    "rows": len(rows),
                    "rate": _ratio(
                        sum(1 for row in rows if _filled(row.get(field.name))), len(rows)
                    ),
                }
                for field in category.fields
            },
        }
        total += cat_total
        filled += cat_filled
        required_total += cat_required
        required_filled += cat_required_filled
    return {
        "fields_total": total,
        "fields_filled": filled,
        "field_rate": _ratio(filled, total),
        "required_total": required_total,
        "required_filled": required_filled,
        "required_rate": _ratio(required_filled, required_total),
        "by_category": per_category,
    }


def _filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _is_number(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return True
    return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", str(value).strip()))


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


# --------------------------------------------------------------- io helpers


def _load_inventory(root: Path) -> ItemInventory:
    for name in ("item_inventory_aligned.json", "item_inventory.json"):
        path = root / name
        if path.exists():
            return ItemInventory.model_validate_json(path.read_text(encoding="utf-8"))
    return ItemInventory(doc_id=root.name)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
