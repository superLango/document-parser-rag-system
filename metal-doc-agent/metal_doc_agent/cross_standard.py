"""Demand-driven cross-standard tasks.

Cross-standard expansion is not the default. A task is only created when the
current document defers a *named parameter* to another standard, for example
"按 GB/T 3880.2 规定的弯曲半径进行弯曲试验" or
"成品化学成分允许偏差应符合 GB/T 222 的规定". Pure method references
("超声检测按 GJB 1580A 的规定进行") name no missing parameter, so they are
ignored.

Supported phrasings:

* ``按照? <std> [标准]?[之的]?规定[的]? <field> <verb>``
* ``按照? <std> [标准]?[之的]?规定[的]? <field>`` (field must be a parameter)
* ``<field> 应符合/满足 <std> [中…] [的]?规定/要求``
* ``<field> 应按 <std> [中…]? [的]?[规定]? [进行]? <verb>``
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .contracts import CrossStandardTask, DocumentMeta, Page
from .references import STANDARD_RE
from .standards import StandardRegistry
from .tablegrid.normalize import clean_text

STANDARD_TOKEN = (
    r"(?P<std>(?:GB\s*/\s*T|GB|GJB\s*/\s*Z|GJB|JB\s*/\s*T|YB\s*/\s*T|HB\s*/\s*Z|HB|"
    r"ASTM|ISO|AMS(?:-STD)?|QJ|Q\s*/\s*(?:[A-Za-z]+|[A-Za-z0-9]*[A-Za-z])|JX|MAS|MFS)"
    r"\s*-?\d+(?:\.\d+)*(?:-\d+)?[A-Za-z]?"
    r"(?:\s*[-—–:]\s*\d{4})?)"
)
VERBS = (
    "进行",
    "执行",
    "检验",
    "试验",
    "检测",
    "测定",
    "评定",
    "检查",
    "验收",
    "判定",
    "测试",
    "探伤",
)
VERB_PATTERN = "|".join(VERBS)
INTERNAL_STANDARD_TOKEN = (
    r"(?P<std_org>410\s*JX)\s*[（(]?\s*通用\s*[)）]?\s*[-—–]\s*D\s*[-—–]\s*"
    r"(?P<std_num>S?\d{1,2}(?:\.\d+)?\s*[-—–.]\s*\d{3,4})"
    r"(?:\s*[-—–]\s*(?P<std_year>\d{4}))?"
)
INTERNAL_STANDARD_RE = re.compile(INTERNAL_STANDARD_TOKEN, re.IGNORECASE)
INTERNAL_CLAUSE_RE = re.compile(
    rf"(?:按|按照|依据|根据|符合|满足)\s*(?P<std>{INTERNAL_STANDARD_TOKEN})"
    rf"\s*(?:标准)?[^，。；]{{0,20}}?(?:要求|规定)",
    re.IGNORECASE,
)
STD_FIRST_RE = re.compile(
    rf"按(?:照)?\s*{STANDARD_TOKEN}\s*(?:标准)?\s*(?:之|的)?\s*(?:规定|要求)\s*(?:的)?\s*"
    rf"(?P<field>[^，。；、,;]{{1,30}}?)\s*(?:{VERB_PATTERN})"
)
STD_FIRST_NOUN_RE = re.compile(
    rf"按(?:照)?\s*{STANDARD_TOKEN}\s*(?:标准)?\s*(?:之|的)?\s*(?:规定|要求)\s*(?:的)?\s*"
    rf"(?P<field>[^，。；、,;]{{2,20}})"
)
COMPLY_RE = re.compile(
    rf"(?:符合|满足|执行)\s*{STANDARD_TOKEN}\s*(?:标准)?\s*(?:中[^，。；、]{{0,12}}?)?\s*"
    rf"(?:的|之)?\s*[^，。；、]{{0,8}}?(?:规定|要求)"
)
APPLY_RE = re.compile(
    rf"(?:应)?按(?:照)?\s*{STANDARD_TOKEN}\s*(?:标准)?\s*(?:中[^，。；、]{{0,12}}?)?\s*"
    rf"(?:的)?\s*(?:规定)?\s*(?:的)?\s*(?:{VERB_PATTERN})"
)
APPLY_NOUN_RE = re.compile(
    rf"(?:应)?按(?:照)?\s*{STANDARD_TOKEN}\s*(?:标准)?\s*"
    rf"(?:中[^，。；、]{{0,12}}?|表\s*[A-Za-z]?\d+(?:\.\d+)?)?\s*"
    rf"(?:的)?\s*(?:规定|要求)"
)
METHOD_HINT_RE = re.compile(r"方法|法|图|附录")
HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?P<id>\d{1,2}(?:\.\s*\d{1,3}){0,3})\.?\s+(?P<title>\S.*)$"
)
# Fields that name a *parameter* rather than a method. A cross-standard task
# is only created when the deferred field ends with one of these suffixes.
PARAMETER_SUFFIXES = (
    "化学成分允许偏差",
    "允许偏差",
    "非金属夹杂物",
    "断面收缩率",
    "弯曲半径",
    "弯曲角度",
    "试验温度",
    "试验时间",
    "试验速率",
    "取样数量",
    "取样部位",
    "取样方向",
    "试样尺寸",
    "试样状态",
    "试样数量",
    "检测级别",
    "检验级别",
    "合格级别",
    "验收级别",
    "表面质量",
    "表面缺陷",
    "表面粗糙度",
    "加工余量",
    "几何尺寸",
    "外形尺寸",
    "外形",
    "尺寸偏差",
    "厚度偏差",
    "直径偏差",
    "长度偏差",
    "重量偏差",
    "质量偏差",
    "低倍组织",
    "显微组织",
    "高倍组织",
    "晶粒度",
    "脱碳层",
    "延伸率",
    "冲击功",
    "夹杂物",
    "硬度",
    "强度",
    "塑性",
    "韧性",
    "探伤",
    "级别",
    "余量",
    "公差",
    "偏差",
    "半径",
    "角度",
    "温度",
    "时间",
    "速率",
    "方向",
    "位置",
    "数量",
    "部位",
    "尺寸",
    "厚度",
    "直径",
    "长度",
    "宽度",
    "重量",
    "质量",
    "组织",
    "状态",
    "表面",
    "缺陷",
    "间距",
    "间隙",
    "指标",
    "范围",
    "含量",
    "项目",
    "顺序",
)
_PARAMETER_ALTERNATION = "|".join(
    sorted(PARAMETER_SUFFIXES, key=len, reverse=True)
)
FIELD_TAIL_RE = re.compile(
    rf"(?P<field>[\u4e00-\u9fff]{{0,14}}(?:{_PARAMETER_ALTERNATION}))$"
)
NOISE_FIELD_PARTS = ("方法", "规定", "要求", "标准", "附录")
NOISE_FIELD_SUFFIXES = ("法", "表", "章", "条", "节")
LEADING_FILLER_RE = re.compile(
    r"^(?:其|该|本|此|上述|以上|所有|全部|各|每|对|对于|并|且|尚|均|都|也|应|的|等|"
    r"重新|同时|分别|直接|另行|单独|逐根|逐件|逐批|在|只|仅|须|按)+"
)
PRODUCT_PREFIX_RE = re.compile(
    r"^(?:锻件|棒材|钢材|钢棒|钢坯|坯料|成品|半成品|产品|交货|原材料|合金)+"
)
LEAD_VERB_RE = re.compile(rf"^(?:{VERB_PATTERN})+")
AUX_VERB_RE = re.compile(r"^(?:进行|执行)+")
TRAIL_VERB_RE = re.compile(rf"(?:{VERB_PATTERN}).*$")
GENERIC_ITEMS = {
    "技术要求",
    "基本要求",
    "要求",
    "检验",
    "试验",
    "其他",
    "一般要求",
    "验收要求",
    "质量要求",
}
ITEM_KEYWORDS = (
    "化学成分",
    "非金属夹杂物",
    "低倍组织",
    "显微组织",
    "高倍组织",
    "室温拉伸",
    "高温拉伸",
    "断裂韧性",
    "超声波探伤",
    "超声探伤",
    "超声检测",
    "转变温度",
    "力学性能",
    "加工余量",
    "表面质量",
    "外观质量",
    "晶粒度",
    "低倍",
    "硬度",
    "拉伸",
    "冲击",
    "探伤",
    "断口",
    "尺寸",
)
ITEM_ONLY_SUFFIXES = (
    "非金属夹杂物",
    "低倍组织",
    "显微组织",
    "高倍组织",
    "断裂韧性",
    "晶粒度",
    "夹杂物",
    "组织",
    "硬度",
    "强度",
    "塑性",
    "韧性",
    "探伤",
    "断口",
    "拉伸",
    "冲击",
    "低倍",
)
STOP_FIELDS = {
    "项目",
    "要求",
    "规定",
    "方法",
    "标准",
    "检验",
    "试验",
    "检测",
    "测定",
    "评定",
    "重新",
    "全长",
    "全部",
    "所有",
    "其他",
    "其余",
    "任何",
    "上述",
    "如下",
    "下列",
    "内容",
    "情况",
    "工作",
    "过程",
    "结果",
    "质量",
}


def detect_tasks(
    pages: list[Page],
    document: DocumentMeta,
    registry: StandardRegistry | None = None,
    catalog_path: str | Path | None = None,
) -> list[CrossStandardTask]:
    index = _load_catalog(catalog_path)
    tasks: list[CrossStandardTask] = []
    for page in pages:
        lines = page.markdown.splitlines()
        for line_no, line in enumerate(lines):
            seen: set[tuple[str, str | None, str]] = set()
            for raw_standard, field in _iter_references(line):
                parsed = _standard_parts(raw_standard)
                if parsed is None:
                    continue
                standard_no, edition = parsed
                key = (standard_no, edition, field)
                if key in seen:
                    continue
                seen.add(key)
                optional = "根据需方要求" in line and "增加" in line
                if optional and "横波" in line:
                    field = "横波检测要求"
                elif optional and "级别" in line:
                    field = "检测级别"
                heading = _nearest_heading(lines, line_no)
                item = _item_name(heading, line)
                if item and (
                    not re.search(r"[\u4e00-\u9fff]", item)
                    or item.endswith("。")
                    or "应符合" in item
                    or "的规定" in item
                ):
                    item = None
                if item is None or item in GENERIC_ITEMS:
                    item = _field_item(field) or item
                task = CrossStandardTask(
                    task_id="",
                    doc_id=document.doc_id,
                    inspection_item=item,
                    missing_fields=[field],
                    requirement_standard=standard_no,
                    requirement_edition=edition,
                    clause_id=heading[0] if heading else None,
                    page_no=page.page_no,
                    quote=clean_text(line)[:300],
                    optional=optional,
                )
                _resolve(task, registry, index)
                task.task_id = _task_id(task)
                tasks.append(task)
    return _dedupe(tasks)


def _iter_references(line: str) -> Iterator[tuple[str, str]]:
    """Yield ``(standard, missing field)`` pairs found on one line."""

    for match in INTERNAL_CLAUSE_RE.finditer(line):
        yield match.group("std"), "标准要求"
    for match in STD_FIRST_RE.finditer(line):
        field = _std_first_field(match.group("field"), strip_verb=False)
        if field:
            yield match.group("std"), field
    for match in STD_FIRST_NOUN_RE.finditer(line):
        field = _std_first_field(match.group("field"), strip_verb=True)
        if field:
            yield match.group("std"), field
    for pattern in (COMPLY_RE, APPLY_RE, APPLY_NOUN_RE):
        for match in pattern.finditer(line):
            trailing = re.split(r"[，。；、]", line[match.end() : match.end() + 8])[0]
            if METHOD_HINT_RE.search(match.group(0)) or METHOD_HINT_RE.search(trailing):
                continue
            field = _lookback_field(
                line, match.start(), allow_item_only=pattern is COMPLY_RE
            )
            if field:
                yield match.group("std"), field


def _std_first_field(raw: str, *, strip_verb: bool) -> str | None:
    field = clean_text(raw).strip(" 的")
    trailing = TRAIL_VERB_RE.search(field)
    if trailing and trailing.start() > 0:
        field = field[: trailing.start()].strip(" 的")
    field = _clean_field_text(field, strip_verb=strip_verb)
    if not field or field in STOP_FIELDS or _is_noise_field(field):
        return None
    return field if _is_parameter(field) else None


def _lookback_field(
    line: str, start: int, *, allow_item_only: bool = True
) -> str | None:
    """Recover the parameter named before "应符合/应按"."""

    window = line[max(0, start - 60) : start]
    window = re.split(r"[，。；：、,;:！？]", window)[-1]
    window = re.sub(r"(?:应|均|都|也|亦|尚|须|并|且|可|的)+$", "", window)
    match = FIELD_TAIL_RE.search(window)
    if not match:
        return None
    field = _normalize_field(match.group("field"))
    if not field or _is_noise_field(field) or not _is_parameter(field):
        return None
    if not allow_item_only and _is_item_only(field):
        return None
    return field


def _normalize_field(field: str) -> str:
    field = clean_text(field).strip(" 的等")
    if "的" in field:
        tail = field.rsplit("的", 1)[1]
        if _is_parameter(tail):
            field = tail
    return _clean_field_text(field)


def _clean_field_text(field: str, *, strip_verb: bool = True) -> str:
    for _ in range(2):
        before = field
        field = re.sub(r"\s+", "", field).replace("成份", "成分")
        if strip_verb:
            field = LEAD_VERB_RE.sub("", field)
        field = AUX_VERB_RE.sub("", field)
        field = LEADING_FILLER_RE.sub("", field)
        field = PRODUCT_PREFIX_RE.sub("", field)
        field = field.strip(" 的等")
        if field == before:
            break
    return field


def _is_parameter(field: str) -> bool:
    return bool(field) and field.endswith(PARAMETER_SUFFIXES)


def _is_item_only(field: str) -> bool:
    """True when the field is just an inspection item, not a parameter."""

    return field.endswith(ITEM_ONLY_SUFFIXES)


def _is_noise_field(field: str) -> bool:
    if any(part in field for part in NOISE_FIELD_PARTS):
        return True
    return field.endswith(NOISE_FIELD_SUFFIXES)


@dataclass(frozen=True)
class CorpusDoc:
    file: str
    edition: str | None = None
    title: str | None = None
    doc_type: str | None = None


@dataclass
class CorpusIndex:
    """Inverted index over the whole corpus, regardless of document type.

    ``bodies`` are documents that *are* a standard (cover number matches), so
    they can supply requirements. ``mentions`` are documents that only cite a
    standard (technical agreements, outlines, QA files); they prove the number
    exists in the corpus but cannot replace the missing body.
    """

    bodies: dict[str, list[CorpusDoc]] = field(default_factory=dict)
    mentions: dict[str, list[CorpusDoc]] = field(default_factory=dict)


def _load_catalog(path: str | Path | None) -> CorpusIndex:
    index = CorpusIndex()
    if path is None:
        return index
    target = Path(path)
    if not target.exists():
        return index
    data = json.loads(target.read_text(encoding="utf-8"))
    for record in data.get("records", []):
        if record.get("duplicate_of"):
            continue
        file_name = record.get("file") or ""
        standard_no = record.get("standard_no")
        if standard_no:
            index.bodies.setdefault(_norm(standard_no), []).append(
                CorpusDoc(
                    file=file_name,
                    edition=record.get("edition"),
                    title=record.get("title"),
                    doc_type=record.get("doc_type"),
                )
            )
        for raw in record.get("cited_standards") or []:
            parsed = _standard_parts(raw)
            if parsed is None:
                continue
            index.mentions.setdefault(_norm(parsed[0]), []).append(
                CorpusDoc(
                    file=file_name,
                    edition=parsed[1],
                    doc_type=record.get("doc_type"),
                )
            )
    for key, mentions in index.mentions.items():
        body_files = {doc.file for doc in index.bodies.get(key, [])}
        seen: set[tuple[str, str | None]] = set()
        deduped: list[CorpusDoc] = []
        for doc in mentions:
            if doc.file in body_files:
                continue
            marker = (doc.file, doc.edition)
            if marker in seen:
                continue
            seen.add(marker)
            deduped.append(doc)
        mentions[:] = deduped
    return index


def _find_body(
    index: CorpusIndex, standard_no: str, edition: str | None
) -> CorpusDoc | None:
    bodies = index.bodies.get(_norm(standard_no), [])
    if not bodies:
        return None
    if edition:
        exact = [
            doc for doc in bodies if _norm(doc.edition) == _norm(edition)
        ]
        if exact:
            return exact[0]
        unknown = [doc for doc in bodies if not doc.edition]
        return unknown[0] if len(unknown) == 1 else None
    return bodies[0] if len(bodies) == 1 else None


def _resolve(
    task: CrossStandardTask,
    registry: StandardRegistry | None,
    index: CorpusIndex,
) -> None:
    body = _find_body(index, task.requirement_standard, task.requirement_edition)
    resolution = (
        registry.resolve(task.requirement_standard, task.requirement_edition)
        if registry
        else None
    )

    if resolution is not None and resolution.record is not None:
        record = resolution.record
        task.resolution_basis = resolution.basis
        if record.doc_id or record.source_file:
            task.status = "candidate" if record.status == "unknown" else "resolved"
            task.resolved_doc_id = record.doc_id
            task.resolved_source_file = record.source_file
            if task.resolved_source_file is None and body is not None:
                task.resolved_source_file = body.file
                task.resolution_basis = f"{resolution.basis or 'registered'}+corpus-body"
            return
        if body is not None:
            task.status = "resolved"
            task.resolved_source_file = body.file
            task.resolution_basis = f"{resolution.basis or 'registered'}+corpus-body"
            return
        task.status = "needs_source"
        task.gap = (
            f"{task.requirement_standard}（版本已解析，但无本地正文"
            f"{_mention_hint(index, task.requirement_standard)}）"
        )
        return

    if body is not None:
        task.status = "resolved"
        task.resolved_source_file = body.file
        task.resolution_basis = "corpus-body"
        return

    mentions = index.mentions.get(_norm(task.requirement_standard)) or []
    if mentions:
        task.status = "candidate"
        task.resolution_basis = "语料引用候选"
        reason = resolution.reason if resolution is not None else "未入库"
        task.gap = (
            f"{task.requirement_standard}（语料中 {len(mentions)} 份文件引用，"
            f"无正文；{reason}）"
        )
        return

    task.status = "not_found"
    reason = resolution.reason if resolution is not None else "未入库"
    task.gap = f"{task.requirement_standard}（{reason}）"


def _mention_hint(index: CorpusIndex, standard_no: str) -> str:
    mentions = index.mentions.get(_norm(standard_no)) or []
    if not mentions:
        return ""
    return f"；语料中 {len(mentions)} 份文件引用该标准"


ITEM_TAIL_RE = re.compile(
    r"(高倍组织|低倍组织|显微组织|晶粒度|非金属夹杂物?|化学成分|力学性能|"
    r"超声波检测|超声检测|布氏硬度|洛氏硬度|维氏硬度|室温拉伸|高温拉伸|"
    r"低温拉伸|冲击|持久|蠕变|腐蚀|硬度|尺寸|表面质量)$"
)


def _normalize_item(text: str) -> str:
    value = re.sub(r"^(?:(?:规定|增加|进行|可|应))+", "", text).strip("的 ")
    if len(value) <= 12:
        return value
    tail = ITEM_TAIL_RE.search(value)
    return tail.group(1) if tail else value[:12]


def _item_name(heading: tuple[str, str] | None, line: str) -> str | None:
    if heading and len(heading[1]) <= 24:
        return _normalize_item(heading[1])
    match = re.search(
        r"(?P<item>[\u4e00-\u9fff、/\-]{2,12}"
        r"(?:检测|检验|试验|探伤|性能|组织|腐蚀|硬度))",
        line,
    )
    if match:
        return _normalize_item(match.group("item"))
    return heading[1][:24] if heading else None


def _field_item(field: str) -> str | None:
    """Infer the inspection item from the deferred parameter name."""

    for keyword in ITEM_KEYWORDS:
        if keyword in field:
            return keyword
    return None


def _nearest_heading(lines: list[str], index: int) -> tuple[str, str] | None:
    for line in reversed(lines[:index]):
        match = HEADING_RE.match(line.strip())
        if match:
            clause_id = re.sub(r"\s+", "", match.group("id")).rstrip(".")
            return clause_id, clean_text(match.group("title"))
    return None


def _standard_parts(raw: str) -> tuple[str, str | None] | None:
    internal = INTERNAL_STANDARD_RE.search(raw)
    if internal:
        number = re.sub(r"\s+", "", clean_text(internal.group("std_num")))
        number = number.replace("—", "-").replace("–", "-")
        year = clean_text(internal.group("std_year")) or None
        return f"Q/{number}", year
    match = STANDARD_RE.search(raw)
    if not match:
        return None
    org = re.sub(r"\s+", "", clean_text(match.group("org")))
    number = re.sub(r"\s+", "", clean_text(match.group("num")))
    year = clean_text(match.group("year")) or None
    if not year:
        suffix = re.search(r"-(\d{4})$", number)
        if suffix and suffix.start() > 0 and 1900 <= int(suffix.group(1)) <= 2099:
            year = suffix.group(1)
            number = number[: suffix.start()]
    return f"{org} {number}", year


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "").upper())


def _task_id(task: CrossStandardTask) -> str:
    key = "|".join(
        [
            task.doc_id,
            task.inspection_item or "",
            task.requirement_standard,
            task.requirement_edition or "",
            str(task.page_no or ""),
            "|".join(task.missing_fields),
        ]
    )
    return f"xstd-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:10]}"


def _dedupe(tasks: list[CrossStandardTask]) -> list[CrossStandardTask]:
    by_id: dict[str, CrossStandardTask] = {}
    by_quote: dict[str, CrossStandardTask] = {}
    result: list[CrossStandardTask] = []
    for task in tasks:
        # OCR frequently repeats one clause twice (with/without spaces), so the
        # same requirement can appear under two headings and two task ids.
        quote_key = "|".join(
            [
                task.requirement_standard,
                task.requirement_edition or "",
                str(task.page_no or ""),
                "|".join(sorted(task.missing_fields)),
                re.sub(r"\s+", "", task.quote or ""),
            ]
        )
        existing = by_id.get(task.task_id) or by_quote.get(quote_key)
        if existing is None:
            by_id[task.task_id] = task
            by_quote[quote_key] = task
            result.append(task)
            continue
        by_id.setdefault(task.task_id, existing)
        by_quote.setdefault(quote_key, existing)
        for field in task.missing_fields:
            if field not in existing.missing_fields:
                existing.missing_fields.append(field)
    return result


def render_report(doc_id: str, tasks: list[CrossStandardTask]) -> str:
    lines = [
        f"# 跨标准补全任务：{doc_id}",
        "",
        f"- 任务数：{len(tasks)}",
        f"- 已解析：{sum(1 for task in tasks if task.status == 'resolved')}",
        f"- 语料正文命中：{sum(1 for task in tasks if task.resolved_source_file)}",
        f"- 候选：{sum(1 for task in tasks if task.status == 'candidate')}",
        f"- 待补正文：{sum(1 for task in tasks if task.status == 'needs_source')}",
        f"- 未入库：{sum(1 for task in tasks if task.status == 'not_found')}",
        "",
        "| 任务 | 检测项目 | 缺失字段 | 要求来源 | 页码 | 可选 | 状态 | 来源文件 | 依据/缺口 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for task in tasks:
        lines.append(
            f"| {task.task_id} | {task.inspection_item or ''} | "
            f"{'、'.join(task.missing_fields)} | {task.requirement_standard}"
            f"{('-' + task.requirement_edition) if task.requirement_edition else ''} | "
            f"{task.page_no or ''} | {'是' if task.optional else '否'} | {task.status} | "
            f"{task.resolved_source_file or task.resolved_doc_id or ''} | "
            f"{task.gap or task.resolution_basis or ''} |"
        )
    lines.append("")
    return "\n".join(lines)
