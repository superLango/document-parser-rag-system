"""Qwen zero-shot extractor.

Two stages:
1. Qwen maps columns to grade / condition / property / ignore.
2. Code assembles row records from the mapped cells, normalizes values, and
   attaches cell-level evidence.

Models never own the numeric value: they only choose column roles and property
names. This keeps hallucinated numbers out of the result by construction.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from ..clients import ModelServiceError, QwenClient, build_qwen_client
from ..contracts import DocumentMeta, Evidence, ExtractedValue, Record, TableBlock, TableGrid
from ..settings import Settings
from ..tablegrid.normalize import (
    ELEMENTS,
    NUMERIC_GRADES,
    apply_default_comparator,
    canonical_element,
    canonical_property,
    clean_text,
    is_footnote_row,
    looks_like_grade,
    normalize_value,
    parse_unit,
)
from .base import ExtractionOutput
from .sft_prompts import INSTRUCTIONS as SFT_INSTRUCTIONS
from .sft_prompts import SYSTEM as SFT_SYSTEM

logger = logging.getLogger(__name__)

CONDITION_MARKERS = (
    "热处理",
    "状态",
    "方向",
    "温度",
    "取样",
    "交货",
    "种类",
    "直径",
    "规格",
    "厚度",
    "毛坯",
    "冷却",
    "淬火",
    "固溶",
    "回火",
    "时效",
    "类型",
    "类别",
    "组织",
    "尺寸",
)
CHEMICAL_CONDITION_MARKERS = (
    "类型",
    "类别",
    "组织",
    "交货状态",
    "供货状态",
)
REMARK_CONDITION_RE = re.compile(
    r"(淬火|时效|退火|固溶|正火|回火|热加工|冷加工|冷拉|冷轧|热轧|热锻|锻态|铸态)"
)
QUALITY_LEVELS = {"普通级", "优质级", "高纯级"}
ALLOWED_PROPERTIES = (
    "Rm",
    "Rp0.2",
    "ReH",
    "A",
    "A50mm",
    "Z",
    "KV2",
    "HB",
    "HRC",
    "HRB",
    "HV",
    "E",
    "KIC",
)


@dataclass
class ColumnMapping:
    grade_col: int | None = None
    grade_cols: list[int] = field(default_factory=list)
    alt_grade_cols: list[int] = field(default_factory=list)
    condition_cols: list[int] = field(default_factory=list)
    remark_cols: list[int] = field(default_factory=list)
    property_cols: dict[int, str] = field(default_factory=dict)
    units: dict[int, str | None] = field(default_factory=dict)


class QwenExtractor:
    name = "qwen"

    def __init__(
        self,
        settings: Settings,
        *,
        client: QwenClient | None = None,
        max_tokens: int = 768,
    ) -> None:
        self.settings = settings
        self.client = client or build_qwen_client(settings)
        self.max_tokens = max_tokens
        self.concurrency = max(1, int(getattr(settings, "qwen_concurrency", 1)))
        self.prompt_style = (
            str(getattr(settings, "extractor_prompt_style", "native") or "native")
            .strip()
            .lower()
        )
        self.sft_max_tokens = int(getattr(settings, "sft_max_tokens", 512))
        self.sft_row_limit = int(getattr(settings, "sft_row_limit", 30))
        self.sft_rules_first = bool(getattr(settings, "sft_rules_first", False))
        self.last_sft: dict[str, int] = {
            "header_calls": 0,
            "row_calls": 0,
            "row_fallbacks": 0,
            "rows_skipped": 0,
            "rows_dropped": 0,
            "properties_added": 0,
        }
        self.last_vote: dict[str, int] = {}
        self.sft_client = None
        if self.prompt_style in {"sft_m2", "vote"} and settings.sft_base_url:
            self.sft_client = QwenClient(
                settings.sft_base_url,
                settings.sft_model,
                fallback_base_url=settings.sft_fallback_base_url,
                failover_probe_seconds=settings.model_failover_probe_seconds,
                enable_thinking=False,
                max_tokens=self.sft_max_tokens,
                stream=getattr(settings, "qwen_stream", True),
                api_key=settings.api_key,
                timeout=settings.request_timeout,
                retries=settings.model_retries,
            )
        self.last_mapping_source: dict[str, str] = {}
        self.last_errors: list[dict] = []

    @property
    def usage(self) -> dict[str, int]:
        totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        for client in (self.client, self.sft_client):
            if client is None:
                continue
            for key in totals:
                totals[key] += int(client.usage.get(key) or 0)
        return totals

    def extract(self, table: TableGrid, document: DocumentMeta) -> ExtractionOutput:
        output = ExtractionOutput()
        if table.profile not in {"chemical_composition", "mechanical_properties"}:
            return output
        if getattr(self, "_last_doc_id", None) != document.doc_id:
            self._last_doc_id = document.doc_id
            self._last_caption_grade = None
        caption_grade = _caption_grade(table.caption)
        if caption_grade:
            self._last_caption_grade = caption_grade
        blocks = table.blocks or [self._table_as_block(table)]
        if self.concurrency > 1 and len(blocks) > 1:
            with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
                results = list(
                    pool.map(lambda block: self._extract_block(table, block, document), blocks)
                )
        else:
            results = [self._extract_block(table, block, document) for block in blocks]
        for records, evidence in results:
            output.records.extend(records)
            output.evidence.extend(evidence)
        output.records = self._merge_records(output.records)
        return output

    def _extract_block(
        self, table: TableGrid, block: TableBlock, document: DocumentMeta
    ) -> tuple[list[Record], list[Evidence]]:
        if table.profile == "chemical_composition":
            if table.orientation == "element_rows":
                return self._extract_element_rows(table, block, document)
            return self._extract_chemical(table, block, document)
        return self._extract_mechanical(table, block, document)

    @staticmethod
    def _table_as_block(table: TableGrid) -> TableBlock:
        return TableBlock(
            block_id=f"{table.table_id}-B1",
            start_row=0,
            header_rows=table.header_rows,
            header_paths=table.header_paths,
            rows=table.rows,
        )

    # ------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------
    def _map_columns(
        self, table: TableGrid, block: TableBlock, profile: str
    ) -> ColumnMapping:
        paths = block.header_paths
        deterministic = self._deterministic_mapping(block, profile)
        if (
            self.sft_rules_first
            and self.prompt_style == "sft_m2"
            and deterministic.grade_cols
            and len(deterministic.property_cols) >= 2
        ):
            # Rules already resolve the layout: asking the adapter only adds
            # latency and cannot improve the binding.
            self.last_mapping_source[block.block_id] = "rules"
            return deterministic
        if (
            self.prompt_style != "sft_m2"
            and profile == "chemical_composition"
            and deterministic.grade_cols
            and len(deterministic.property_cols) >= 2
        ):
            self.last_mapping_source[block.block_id] = "rules"
            return deterministic
        try:
            if self.prompt_style == "vote":
                model_columns = self._vote_mapping(table, block, profile)
                if model_columns is None:
                    self.last_mapping_source[block.block_id] = "rules"
                    return deterministic
            elif self.prompt_style == "sft_m2":
                model_columns = self._ask_mapping_sft(table, block, profile)
            else:
                model_columns = self._ask_mapping(table, block, profile)
        except Exception as exc:  # noqa: BLE001 - fallback to rules
            self.last_errors.append(
                {
                    "table_id": table.table_id,
                    "block_id": block.block_id,
                    "stage": "header_mapping",
                    "error": str(exc)[:300],
                }
            )
            logger.warning(
                "Qwen header mapping failed table=%s block=%s: %s",
                table.table_id,
                block.block_id,
                str(exc)[:200],
            )
            self.last_mapping_source[block.block_id] = "rules"
            return deterministic

        model_grade = None
        model_conditions: set[int] = set()
        model_properties: dict[int, str] = {}
        for index, column in model_columns.items():
            role = str(column.get("role", "ignore")).lower()
            if role == "grade":
                model_grade = index
            elif role == "condition":
                model_conditions.add(index)
            elif role == "property":
                prop = self._canonical_property(column.get("property"), profile)
                if prop:
                    model_properties[index] = prop

        grade_col = deterministic.grade_col if deterministic.grade_col is not None else model_grade
        grade_cols = list(deterministic.grade_cols)
        alt_grade_cols = list(deterministic.alt_grade_cols)
        if profile == "mechanical_properties" and not grade_cols:
            grade_col = None
            grade_cols = []
        elif not grade_cols and grade_col is not None:
            grade_cols = [grade_col]
        condition_cols = set(deterministic.condition_cols)
        condition_cols.update(
            index
            for index in model_conditions
            if index not in deterministic.property_cols
            and index < len(paths)
            and any(
                marker in clean_text(" ".join(paths[index]))
                for marker in CONDITION_MARKERS
            )
        )
        condition_cols.difference_update(grade_cols)

        property_cols: dict[int, str] = {}
        owned_props: set[str] = set()
        for index in range(len(paths)):
            if index in grade_cols or index in condition_cols:
                continue
            if profile == "chemical_composition" and index in deterministic.property_cols:
                prop = deterministic.property_cols[index]
                property_cols[index] = prop
                owned_props.add(prop)
            elif index in deterministic.property_cols:
                # Rules own a column they recognise; the model may only refine
                # ambiguous tensile variants (A50mm/ReH/KIC) or fill gaps.
                if (
                    deterministic.property_cols[index] in {"A50mm", "ReH", "KIC"}
                    and index in model_properties
                ):
                    prop = model_properties[index]
                else:
                    prop = deterministic.property_cols[index]
                property_cols[index] = prop
                owned_props.add(prop)
            elif index in model_properties:
                # Never bind a second column to a property the rules already
                # assigned: values would overwrite each other in row order
                # (e.g. hardness 250 landing in the elongation column).
                prop = model_properties[index]
                if prop in owned_props:
                    continue
                property_cols[index] = prop
                owned_props.add(prop)

        indentation_cols = {
            index
            for index in range(len(paths))
            if "硬度" in clean_text(" ".join(paths[index]))
            and "压痕" in clean_text(" ".join(paths[index]))
        }
        # "布氏硬度(压痕直径)mm" holds a diameter, not a test condition;
        # leaving it in condition_cols polluted the record with "3.30~3.55"
        # and made a room-temperature row look like a 750℃ row. The column
        # stays a hardness property so the inspection item survives; the
        # implausible-value filter drops the millimetre reading later.
        condition_cols.difference_update(indentation_cols)

        units = dict(deterministic.units)
        for index, column in model_columns.items():
            if units.get(index) is None and column.get("unit"):
                units[index] = clean_text(str(column["unit"]))

        if profile == "mechanical_properties":
            heat_markers = ("热处理", "淬火", "固溶", "回火", "时效", "毛坯")
            heat_treatment = any(
                any(marker in clean_text(" ".join(paths[col])) for marker in heat_markers)
                for col in condition_cols
                if col < len(paths)
            )
            if heat_treatment:
                condition_cols = {
                    col
                    for col in condition_cols
                    if col < len(paths)
                    and not any(
                        marker in clean_text(" ".join(paths[col]))
                        for marker in ("类型", "类别", "组织")
                    )
                }

        self.last_mapping_source[block.block_id] = (
            "vote"
            if self.prompt_style == "vote"
            else ("qwen-sft" if self.prompt_style == "sft_m2" else "qwen")
        )
        return ColumnMapping(
            grade_col=grade_col,
            grade_cols=grade_cols,
            alt_grade_cols=alt_grade_cols,
            condition_cols=sorted(condition_cols),
            remark_cols=[
                col
                for col in deterministic.remark_cols
                if col < len(paths)
                and col not in grade_cols
                and col not in condition_cols
                and col not in property_cols
            ],
            property_cols=property_cols,
            units=units,
        )

    def _deterministic_mapping(self, block: TableBlock, profile: str) -> ColumnMapping:
        paths = block.header_paths
        grade_cols = self._find_grade_cols(paths)
        alt_grade_cols = [
            col
            for col, path in enumerate(paths)
            if any(
                marker in clean_text(" ".join(path))
                for marker in ("旧牌号", "原牌号")
            )
        ]
        grade_col = grade_cols[0] if grade_cols else None
        condition_cols: list[int] = []
        remark_cols: list[int] = []
        property_cols: dict[int, str] = {}
        units: dict[int, str | None] = {}
        element_groups: dict[tuple[str, ...], list[int]] = {}
        for col, path in enumerate(paths):
            text = " ".join(path)
            units[col] = parse_unit(text)
            if col in grade_cols:
                continue
            if profile == "chemical_composition":
                if text.strip() == "元素" or any(
                    marker in text for marker in CHEMICAL_CONDITION_MARKERS
                ):
                    condition_cols.append(col)
                    continue
                residue = _residue_property(text)
                if residue:
                    property_cols[col] = residue
                    continue
                tokens = _element_tokens(text)
                if len(tokens) == 1:
                    property_cols[col] = tokens[0]
                    continue
                if len(tokens) >= 2:
                    element_groups.setdefault(tuple(tokens), []).append(col)
                    continue
                element = canonical_element(text)
                if element:
                    property_cols[col] = element
            else:
                if any(marker in text for marker in CONDITION_MARKERS):
                    condition_cols.append(col)
                    continue
                if "备注" in text or "说明" in text:
                    # TB2-style tables keep the per-row performance qualifier
                    # (淬火性能/时效性能) in a 备注 column.
                    remark_cols.append(col)
                    continue
                persistence = _persistence_property(text)
                if persistence:
                    property_cols[col] = persistence
                    continue
                prop = canonical_property(text)
                if prop:
                    property_cols[col] = prop
        for tokens, columns in element_groups.items():
            if len(columns) != len(tokens):
                continue
            for col, element in zip(columns, tokens):
                property_cols[col] = element
        return ColumnMapping(
            grade_col=grade_col,
            grade_cols=grade_cols,
            alt_grade_cols=alt_grade_cols,
            condition_cols=condition_cols,
            remark_cols=remark_cols,
            property_cols=property_cols,
            units=units,
        )

    def _ask_mapping(
        self, table: TableGrid, block: TableBlock, profile: str
    ) -> dict[int, dict[str, Any]]:
        sample_rows = block.rows[block.header_rows : block.header_rows + 3]
        payload = {
            "caption": table.caption,
            "profile": profile,
            "orientation": table.orientation,
            "n_cols": table.n_cols,
            "header_paths": block.header_paths,
            "sample_rows": sample_rows,
            "allowed_properties": list(ALLOWED_PROPERTIES),
            "allowed_elements": sorted(ELEMENTS),
        }
        prompt = (
            "你是金属材料标准表头映射器。只输出 JSON，不要解释。\n"
            "任务：把每一列映射为 grade（牌号/级别）、condition（状态/方向/温度/厚度等）、"
            "property（性能或元素）、ignore。\n"
            "property 必须从 allowed_properties 或 allowed_elements 中选择精确名称；"
            "不要发明新名称，不要输出数值。\n"
            "输出格式：{\"columns\":[{\"index\":0,\"role\":\"grade|condition|property|ignore\","
            "\"property\":null,\"unit\":null}]}；不要输出 reason 或其他字段。\n"
            f"输入：{json.dumps(payload, ensure_ascii=False)}"
        )
        response = self.client.chat(
            [
                {"role": "system", "content": "只输出 JSON，不要解释。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=self.max_tokens,
            temperature=0.0,
            json_mode=True,
        )
        data = _parse_json(response)
        return self._parse_columns(data, table.n_cols)

    def _ask_mapping_sft(
        self, table: TableGrid, block: TableBlock, profile: str
    ) -> dict[int, dict[str, Any]]:
        """SFT v2 header prompt: header paths, sample rows and the same
        ``allowed_properties`` / ``profile`` constraints the native prompt uses,
        so the adapter is trained and served with one distribution."""
        payload = {
            "caption": table.caption,
            "profile": profile,
            "orientation": table.orientation,
            "n_cols": table.n_cols,
            "header_paths": block.header_paths,
            "sample_rows": block.rows[block.header_rows : block.header_rows + 3],
            "allowed_properties": list(ALLOWED_PROPERTIES),
            "allowed_elements": sorted(ELEMENTS),
        }
        prompt = (
            SFT_INSTRUCTIONS["header_mapping_constrained"]
            + "\n输入："
            + json.dumps(payload, ensure_ascii=False)
        )
        response = (self.sft_client or self.client).chat(
            [
                {"role": "system", "content": SFT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=self.sft_max_tokens,
            temperature=0.0,
            json_mode=True,
        )
        self.last_sft["header_calls"] += 1
        data = _parse_json(response)
        return self._parse_columns(data, table.n_cols)

    @staticmethod
    def _parse_columns(data: dict[str, Any], n_cols: int) -> dict[int, dict[str, Any]]:
        columns = data.get("columns")
        if not isinstance(columns, list):
            raise ValueError("missing columns list")
        mapping: dict[int, dict[str, Any]] = {}
        for column in columns:
            if not isinstance(column, dict):
                continue
            try:
                index = int(column.get("index"))
            except (TypeError, ValueError):
                continue
            if 0 <= index < n_cols:
                mapping[index] = column
        if not mapping:
            raise ValueError("empty column mapping")
        return mapping

    # ------------------------------------------------------------------
    # Mapping vote (native prompt + constrained SFT prompt)
    # ------------------------------------------------------------------
    def _vote_mapping(
        self, table: TableGrid, block: TableBlock, profile: str
    ) -> dict[int, dict[str, Any]] | None:
        native_columns: dict[int, dict[str, Any]] = {}
        sft_columns: dict[int, dict[str, Any]] = {}
        try:
            native_columns = self._ask_mapping(table, block, profile)
        except Exception as exc:  # noqa: BLE001 - the other side may still answer
            self.last_errors.append(
                {
                    "table_id": table.table_id,
                    "block_id": block.block_id,
                    "stage": "header_mapping_native",
                    "error": str(exc)[:300],
                }
            )
        try:
            sft_columns = self._ask_mapping_sft(table, block, profile)
        except Exception as exc:  # noqa: BLE001
            self.last_errors.append(
                {
                    "table_id": table.table_id,
                    "block_id": block.block_id,
                    "stage": "header_mapping_sft",
                    "error": str(exc)[:300],
                }
            )
        if not native_columns and not sft_columns:
            return None
        return self._vote_columns(native_columns, sft_columns, profile)

    def _vote_columns(
        self,
        native: dict[int, dict[str, Any]],
        sft: dict[int, dict[str, Any]],
        profile: str,
    ) -> dict[int, dict[str, Any]]:
        merged: dict[int, dict[str, Any]] = {}
        counters = {
            "agree": 0,
            "conflict": 0,
            "native_only": 0,
            "sft_only": 0,
            "grade_dropped": 0,
        }
        for index in sorted(set(native) | set(sft)):
            native_column = native.get(index)
            sft_column = sft.get(index)
            if native_column is not None and sft_column is not None:
                if self._columns_agree(native_column, sft_column, profile):
                    merged[index] = self._merge_columns(native_column, sft_column)
                    counters["agree"] += 1
                else:
                    merged[index] = self._prefer_column(
                        native_column, sft_column, profile
                    )
                    counters["conflict"] += 1
            elif native_column is not None:
                merged[index] = native_column
                counters["native_only"] += 1
            else:
                merged[index] = sft_column
                counters["sft_only"] += 1
        native_grades = {
            index for index, column in native.items() if _column_role(column) == "grade"
        }
        sft_grades = {
            index for index, column in sft.items() if _column_role(column) == "grade"
        }
        if native_grades and sft_grades and native_grades != sft_grades:
            for index in native_grades | sft_grades:
                if index in merged:
                    merged[index] = {"index": index, "role": "ignore"}
            counters["grade_dropped"] = len(native_grades | sft_grades)
        self.last_vote = counters
        return merged

    def _columns_agree(
        self,
        native: dict[str, Any],
        sft: dict[str, Any],
        profile: str,
    ) -> bool:
        if _column_role(native) != _column_role(sft):
            return False
        if _column_role(native) != "property":
            return True
        return self._canonical_property(
            native.get("property"), profile
        ) == self._canonical_property(sft.get("property"), profile)

    @staticmethod
    def _merge_columns(
        native: dict[str, Any], sft: dict[str, Any]
    ) -> dict[str, Any]:
        merged = dict(native)
        if not merged.get("unit") and sft.get("unit"):
            merged["unit"] = sft["unit"]
        if not merged.get("property") and sft.get("property"):
            merged["property"] = sft["property"]
        return merged

    def _column_score(self, column: dict[str, Any], profile: str) -> int:
        role = _column_role(column)
        if role == "ignore":
            return 0
        if role in {"grade", "condition"}:
            return 2
        return 1 if not self._canonical_property(column.get("property"), profile) else 3

    def _prefer_column(
        self,
        native: dict[str, Any],
        sft: dict[str, Any],
        profile: str,
    ) -> dict[str, Any]:
        if self._column_score(native, profile) >= self._column_score(sft, profile):
            return dict(native)
        return dict(sft)

    def _canonical_property(self, value: Any, profile: str) -> str | None:
        if not value:
            return None
        text = clean_text(str(value))
        if profile == "chemical_composition":
            return canonical_element(text)
        return canonical_property(text)

    # ------------------------------------------------------------------
    # SFT row stage (behind extractor_prompt_style=sft_m2)
    # ------------------------------------------------------------------
    def _ask_row_sft(
        self, block: TableBlock, mapping: ColumnMapping, row: list[str]
    ) -> dict[str, Any] | None:
        """Ask the adapter for one row and keep only values that exist verbatim
        in that row; numbers never come from the model."""
        payload = {
            "header_paths": block.header_paths,
            "mapping": self._mapping_payload(mapping),
            "row": row,
        }
        prompt = (
            SFT_INSTRUCTIONS["row_record"]
            + "\n输入："
            + json.dumps(payload, ensure_ascii=False)
        )
        self.last_sft["row_calls"] += 1
        try:
            # The row stage must use the adapter endpoint too; otherwise the
            # LoRA is only used for header mapping and row prompts hit the base
            # model (the v1 -> v2 accuracy gap).
            response = (self.sft_client or self.client).chat(
                [
                    {"role": "system", "content": SFT_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=self.sft_max_tokens,
                temperature=0.0,
                json_mode=True,
            )
            data = _parse_json(response)
        except Exception as exc:  # noqa: BLE001 - caller falls back to rules
            self.last_sft["row_fallbacks"] += 1
            self.last_errors.append(
                {
                    "block_id": block.block_id,
                    "stage": "row_record_sft",
                    "error": str(exc)[:300],
                }
            )
            return None

        cells = {clean_text(cell) for cell in row if clean_text(cell)}
        properties: dict[str, str] = {}
        raw_props = data.get("properties")
        if isinstance(raw_props, dict):
            for key, item in raw_props.items():
                value = item.get("raw") if isinstance(item, dict) else item
                raw = clean_text(str(value)) if value is not None else ""
                name = clean_text(str(key))
                if not raw or not name or raw not in cells:
                    continue
                properties[name] = raw
        grade = clean_text(str(data.get("grade") or ""))
        return {"grade": grade or None, "properties": properties}

    def _sft_grade_is_acceptable(
        self, value: str | None, row: list[str], mapping: ColumnMapping
    ) -> bool:
        """Accept an SFT grade only when it looks like a grade and does not sit
        in a condition column (``T6`` is a heat-treatment state, not a grade)."""
        if not value or not looks_like_grade(value):
            return False
        cells = [clean_text(cell) for cell in row]
        if value not in cells:
            return False
        if any(
            column < len(cells) and cells[column] == value
            for column in mapping.condition_cols
        ):
            return False
        if mapping.grade_cols:
            return any(
                column < len(cells) and cells[column] == value
                for column in mapping.grade_cols
            )
        return True

    def _mapping_payload(self, mapping: ColumnMapping) -> dict[str, Any]:
        columns: list[dict[str, Any]] = []
        for index in sorted(mapping.grade_cols):
            columns.append(
                {"index": index, "role": "grade", "property": None, "unit": None}
            )
        for index in mapping.condition_cols:
            columns.append(
                {
                    "index": index,
                    "role": "condition",
                    "property": None,
                    "unit": mapping.units.get(index),
                }
            )
        for index, name in sorted(mapping.property_cols.items()):
            columns.append(
                {
                    "index": index,
                    "role": "property",
                    "property": name,
                    "unit": mapping.units.get(index),
                }
            )
        columns.sort(key=lambda column: column["index"])
        return {"columns": columns}

    def _sft_row_candidates(
        self,
        sft: dict[str, Any],
        row: list[str],
        mapping: ColumnMapping,
        profile: str,
    ) -> list[tuple[str, int, str]]:
        """Map SFT property names onto cells not already owned by the rules."""
        used = (
            set(mapping.property_cols)
            | set(mapping.condition_cols)
            | set(mapping.grade_cols)
        )
        cells = [clean_text(cell) for cell in row]
        candidates: list[tuple[str, int, str]] = []
        for name, raw in sft["properties"].items():
            # Only canonical properties enter the engine schema; free-form
            # labels would add junk fields (measured as field_fp).
            prop = self._canonical_property(name, profile)
            if not prop:
                continue
            columns = [
                index
                for index, cell in enumerate(cells)
                if cell == raw and index not in used
            ]
            if len(columns) != 1:
                continue
            column = columns[0]
            used.add(column)
            candidates.append((prop, column, raw))
        return candidates

    @staticmethod
    def _duplicate_row_indexes(
        block: TableBlock, rows: list[list[str]]
    ) -> set[int]:
        """Indexes of repeated header rows and duplicated page blocks.

        Continuation pages sometimes carry their own header row and repeat the
        previous block's rows (seen in GB/T 14992 T8); feeding them to stage 2
        produces fake records such as ``grade=新牌号``.
        """
        header_text = {
            clean_text(" ".join(path))
            for path in block.header_paths
            if clean_text(" ".join(path))
        }
        seen: set[tuple[str, ...]] = set()
        skip: set[int] = set()
        for index, row in enumerate(rows):
            cells = tuple(clean_text(cell) for cell in row)
            filled = {cell for cell in cells if cell}
            if filled and filled <= header_text:
                skip.add(index)
                continue
            if cells in seen:
                skip.add(index)
                continue
            seen.add(cells)
        return skip


    # ------------------------------------------------------------------
    # Row assembly
    # ------------------------------------------------------------------
    def _extract_chemical(
        self, table: TableGrid, block: TableBlock, document: DocumentMeta
    ) -> tuple[list[Record], list[Evidence]]:
        mapping = self._map_columns(table, block, "chemical_composition")
        if not mapping.property_cols:
            return [], []

        records: list[Record] = []
        evidence: list[Evidence] = []
        rows = block.rows[block.header_rows :]
        note_markers = _note_markers(block.rows)
        skip = (
            self._duplicate_row_indexes(block, rows)
            if self.prompt_style == "sft_m2"
            else set()
        )
        use_sft = self.prompt_style == "sft_m2" and len(rows) <= self.sft_row_limit
        if self.prompt_style == "sft_m2" and not use_sft:
            self.last_sft["rows_skipped"] += len(rows)
        last_grade: str | None = None
        last_grade_level: str | None = None
        for index, row in enumerate(rows):
            if index in skip:
                self.last_sft["rows_dropped"] += 1
                continue
            if _is_footnote_row(row):
                continue
            if _is_header_like_row(row, block.header_paths):
                continue
            grade, grade_level = self._row_grade(row, mapping, note_markers)
            if not mapping.grade_cols:
                cells = [
                    clean_text(row[col])
                    for col in mapping.property_cols
                    if col < len(row) and clean_text(row[col])
                ]
                if not cells:
                    continue
                # Skip the repeated element-name row in "element / value" blocks.
                if sum(1 for cell in cells if canonical_element(cell)) >= max(
                    1, len(cells) // 2
                ):
                    continue
            sft = self._ask_row_sft(block, mapping, row) if use_sft else None
            if sft and not grade and not grade_level and self._sft_grade_is_acceptable(
                sft.get("grade"), row, mapping
            ):
                grade = sft["grade"]
            if not grade and not grade_level:
                row_has_data = any(
                    clean_text(row[col])
                    for col in mapping.property_cols
                    if col < len(row)
                )
                if row_has_data and last_grade:
                    grade, grade_level = last_grade, last_grade_level
            if grade or grade_level:
                last_grade, last_grade_level = grade, grade_level
            if not grade and not grade_level:
                grade = (
                    _caption_grade(table.caption)
                    or getattr(self, "_last_caption_grade", None)
                    or _document_grade(document)
                )
            key_value = grade or grade_level
            if mapping.grade_cols and not self._is_plausible_key(key_value):
                continue
            condition = self._row_condition(table, block, row, mapping)
            if not condition:
                condition = _header_condition(block.header_paths, table.context)
            props: dict[str, ExtractedValue] = {}
            for col, element in mapping.property_cols.items():
                if element in props:
                    continue
                raw = clean_text(row[col]) if col < len(row) else ""
                if not raw:
                    continue
                item = self._make_value(
                    table,
                    block,
                    document,
                    index,
                    col,
                    raw,
                    mapping.units.get(col) or "%",
                    element,
                )
                if item is None:
                    continue
                if element in {"其余单个杂质", "其余杂质总和"} and item.comparator == "eq":
                    # Chemistry aggregates sit under "杂质元素，不大于"; OCR can
                    # lose that parent cell for the last column.
                    item.comparator = "max"
                item.condition = condition
                props[element] = item
                evidence.append(self._evidence(table, block, index, col, raw, item.evidence_id))
            if sft:
                for prop, col, raw in self._sft_row_candidates(
                    sft, row, mapping, "chemical_composition"
                ):
                    if prop in props:
                        continue
                    item = self._make_value(
                        table,
                        block,
                        document,
                        index,
                        col,
                        raw,
                        mapping.units.get(col) or "%",
                        prop,
                    )
                    if item is None:
                        continue
                    item.condition = condition
                    props[prop] = item
                    evidence.append(
                        self._evidence(table, block, index, col, raw, item.evidence_id)
                    )
                    self.last_sft["properties_added"] += 1
            if not props:
                continue
            records.append(
                Record(
                    record_id=self._record_id(
                        document.doc_id, table.table_id, key_value, condition
                    ),
                    source_table_id=table.table_id,
                    grade=grade,
                    grade_level=grade_level,
                    condition=condition,
                    properties=props,
                )
            )
        return records, evidence

    def _extract_mechanical(
        self, table: TableGrid, block: TableBlock, document: DocumentMeta
    ) -> tuple[list[Record], list[Evidence]]:
        mapping = self._map_columns(table, block, "mechanical_properties")
        if not mapping.property_cols:
            return [], []

        records: list[Record] = []
        evidence: list[Evidence] = []
        rows = block.rows[block.header_rows :]
        note_markers = _note_markers(block.rows)
        skip = (
            self._duplicate_row_indexes(block, rows)
            if self.prompt_style == "sft_m2"
            else set()
        )
        use_sft = self.prompt_style == "sft_m2" and len(rows) <= self.sft_row_limit
        if self.prompt_style == "sft_m2" and not use_sft:
            self.last_sft["rows_skipped"] += len(rows)
        last_grade: str | None = None
        last_grade_level: str | None = None
        for index, row in enumerate(rows):
            if index in skip:
                self.last_sft["rows_dropped"] += 1
                continue
            if _is_footnote_row(row):
                continue
            if _is_header_like_row(row, block.header_paths):
                continue
            grade, grade_level = self._row_grade(row, mapping, note_markers)
            sft = self._ask_row_sft(block, mapping, row) if use_sft else None
            if sft and not grade and not grade_level and self._sft_grade_is_acceptable(
                sft.get("grade"), row, mapping
            ):
                grade = sft["grade"]
            if not grade and not grade_level:
                row_has_data = any(
                    clean_text(row[col])
                    for col in mapping.property_cols
                    if col < len(row)
                )
                if row_has_data and last_grade:
                    grade, grade_level = last_grade, last_grade_level
            if grade or grade_level:
                last_grade, last_grade_level = grade, grade_level
            if not grade and not grade_level:
                grade = (
                    _caption_grade(table.caption)
                    or getattr(self, "_last_caption_grade", None)
                    or _document_grade(document)
                )
            key_value = grade or grade_level
            if mapping.grade_cols and not self._is_plausible_key(key_value):
                continue
            if _row_has_misplaced_condition(row, mapping.property_cols):
                # OCR sometimes inserts the merged grade/temper cell into the
                # property region (e.g. an extra "T6" column), shifting every
                # following value. Such rows cannot be aligned reliably; drop
                # them instead of emitting values from the wrong column.
                self.last_sft["rows_dropped"] += 1
                continue
            condition = self._row_condition(table, block, row, mapping)
            if not condition:
                condition = _header_condition(block.header_paths, table.context)
            props: dict[str, ExtractedValue] = {}
            for col, prop in mapping.property_cols.items():
                # Several columns can share one property key (longitudinal vs
                # transverse, or a unit/duplicate column). Keep the first bound
                # column: later duplicates used to overwrite the primary value
                # with another direction's or another property's cell.
                if prop in props:
                    continue
                raw = clean_text(row[col]) if col < len(row) else ""
                if not raw or _implausible_property(prop, raw):
                    continue
                item = self._make_value(
                    table,
                    block,
                    document,
                    index,
                    col,
                    raw,
                    mapping.units.get(col) or _default_unit(prop),
                    prop,
                )
                if item is None:
                    continue
                item.condition = condition
                props[prop] = item
                evidence.append(self._evidence(table, block, index, col, raw, item.evidence_id))
            if sft:
                for prop, col, raw in self._sft_row_candidates(
                    sft, row, mapping, "mechanical_properties"
                ):
                    if prop in props or _implausible_property(prop, raw):
                        continue
                    item = self._make_value(
                        table,
                        block,
                        document,
                        index,
                        col,
                        raw,
                        mapping.units.get(col) or _default_unit(prop),
                        prop,
                    )
                    if item is None:
                        continue
                    item.condition = condition
                    props[prop] = item
                    evidence.append(
                        self._evidence(table, block, index, col, raw, item.evidence_id)
                    )
                    self.last_sft["properties_added"] += 1
            if not props:
                continue
            records.append(
                Record(
                    record_id=self._record_id(
                        document.doc_id, table.table_id, key_value, condition
                    ),
                    source_table_id=table.table_id,
                    grade=grade,
                    grade_level=grade_level,
                    condition=condition,
                    properties=props,
                )
            )
        return records, evidence

    def _extract_element_rows(
        self, table: TableGrid, block: TableBlock, document: DocumentMeta
    ) -> tuple[list[Record], list[Evidence]]:
        paths = block.header_paths
        header_elements: list[str | None] = []
        for path in paths:
            tokens = _element_tokens(" ".join(path))
            header_elements.append(tokens[0] if len(tokens) == 1 else None)
        if sum(1 for element in header_elements if element) >= max(2, len(paths) // 2):
            grade = (
                _caption_grade(table.caption)
                or getattr(self, "_last_caption_grade", None)
                or _document_grade(document)
            )
            condition = _element_condition(table)
            props: dict[str, ExtractedValue] = {}
            evidence: list[Evidence] = []
            for index, row in enumerate(block.rows[block.header_rows :]):
                if _is_footnote_row(row):
                    continue
                if _is_header_like_row(row, block.header_paths):
                    continue
                for col, element in enumerate(header_elements):
                    if not element or col >= len(row):
                        continue
                    raw = clean_text(row[col])
                    if not raw:
                        continue
                    item = self._make_value(
                        table, block, document, index, col, raw, "%", element
                    )
                    if item is None:
                        continue
                    props[element] = item
                    evidence.append(
                        self._evidence(table, block, index, col, raw, item.evidence_id)
                    )
            if not props:
                return [], []
            return [
                Record(
                    record_id=self._record_id(
                        document.doc_id, table.table_id, grade, condition
                    ),
                    source_table_id=table.table_id,
                    grade=grade,
                    condition=condition,
                    properties=props,
                )
            ], evidence

        grade_cols = list(range(1, len(paths)))
        unit_default = parse_unit(table.caption or "") or "%"
        records_by_grade: dict[str, Record] = {}
        evidence = []
        for index, row in enumerate(block.rows[block.header_rows :]):
            if _is_footnote_row(row):
                continue
            if _is_header_like_row(row, block.header_paths):
                continue
            element = canonical_element(row[0]) if row else None
            if not element:
                continue
            for col in grade_cols:
                if col >= len(row):
                    continue
                raw = clean_text(row[col])
                if not raw:
                    continue
                grade = clean_text(" ".join(paths[col])) or f"col{col}"
                unit = parse_unit(" ".join(paths[col])) or unit_default
                item = self._make_value(
                    table, block, document, index, col, raw, unit, element
                )
                if item is None:
                    continue
                record = records_by_grade.setdefault(
                    grade,
                    Record(
                        record_id=self._record_id(
                            document.doc_id, table.table_id, grade, None
                        ),
                        source_table_id=table.table_id,
                        grade=grade,
                    ),
                )
                record.properties[element] = item
                evidence.append(
                    self._evidence(table, block, index, col, raw, item.evidence_id)
                )
        return list(records_by_grade.values()), evidence

    def _make_value(
        self,
        table: TableGrid,
        block: TableBlock,
        document: DocumentMeta,
        row_index: int,
        col: int,
        raw: str,
        header_unit: str | None,
        property_key: str | None = None,
    ) -> ExtractedValue | None:
        parsed = normalize_value(raw)
        parsed = apply_default_comparator(
            parsed,
            property_key=property_key,
            header_path=block.header_paths[col],
            chemical=table.profile == "chemical_composition",
        )
        comparator = parsed["comparator"]
        absolute_row = block.start_row + block.header_rows + row_index
        evidence_id = f"ev:{document.doc_id}:{table.table_id}:r{absolute_row}:c{col}"
        return ExtractedValue(
            raw=raw,
            value=parsed.get("value"),
            text=parsed.get("text"),
            unit=parsed.get("unit") or header_unit,
            comparator=comparator,
            lower=parsed.get("lower"),
            upper=parsed.get("upper"),
            evidence_id=evidence_id,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _find_grade_cols(paths: list[list[str]]) -> list[int]:
        markers = (
            "牌号",
            "钢级",
            "Grade",
            "grade",
            "合金牌号",
            "级别",
            "材质",
            "钢号",
            "材料",
            "钢类",
        )
        columns: list[int] = []
        for col, path in enumerate(paths):
            text = clean_text(" ".join(path))
            if not text or "原牌号" in text or "旧牌号" in text:
                continue
            if any(marker in text for marker in markers):
                columns.append(col)
        for col, path in enumerate(paths):
            if col in columns:
                continue
            text = clean_text(" ".join(path))
            if ("质量等级" in text or text == "等级") and (
                col - 1 in columns or col + 1 in columns
            ):
                columns.append(col)
        return sorted(set(columns))

    @staticmethod
    def _find_grade_col(paths: list[list[str]]) -> int | None:
        columns = QwenExtractor._find_grade_cols(paths)
        return columns[0] if columns else None

    @staticmethod
    def _row_grade(
        row: list[str],
        mapping: ColumnMapping,
        note_markers: set[str] | None = None,
    ) -> tuple[str | None, str | None]:
        if not mapping.grade_cols:
            return None, None
        values = [
            clean_text(row[col])
            for col in mapping.grade_cols
            if col < len(row) and clean_text(row[col])
        ]
        if values and all(value in {"-", "/", "—", "–"} for value in values):
            # "新牌号" is a dash when only an old grade exists; use 旧牌号.
            values = [
                clean_text(row[col])
                for col in mapping.alt_grade_cols
                if col < len(row) and clean_text(row[col]) not in {"-", "/", "—", "–", ""}
            ]
        if values and all(value in {"-", "/", "—", "–"} for value in values):
            # A dash with no fallback column means "same as above"; let the
            # forward-fill step inherit the previous grade.
            return None, None
        if not values:
            return None, None
        grade = values[0]
        if (
            note_markers
            and len(grade) > 1
            and grade[-1].islower()
            and grade[-1] in note_markers
        ):
            # OCR dropped the superscript: TC6a -> TC6, marker "a" is a footnote.
            grade = grade[:-1]
        if len(values) > 1 and grade and grade[-1].islower():
            grade = grade[:-1]
        grade_level = None
        for value in values[1:]:
            if value in QUALITY_LEVELS:
                grade_level = value
            elif re.fullmatch(r"[A-Za-z0-9]{1,3}", value):
                grade += value
            else:
                grade += value
        if grade in QUALITY_LEVELS:
            grade_level = grade
            grade = None
        cleaned = _clean_grade(grade)
        if (
            cleaned
            and cleaned.isdigit()
            and len(cleaned) != 4
            and cleaned not in NUMERIC_GRADES
        ):
            # A 2-3 digit number in the grade column is a property value from
            # a shifted row, not a grade. Known 3-digit stainless grades
            # (304/316/410...) are whitelisted in NUMERIC_GRADES.
            return None, grade_level
        return cleaned, grade_level

    @staticmethod
    def _row_condition(
        table: TableGrid, block: TableBlock, row: list[str], mapping: ColumnMapping
    ) -> str | None:
        parts: list[str] = []
        primary_group = _primary_measure_group(block, mapping)
        sub_table_tokens = ("持久", "蠕变", "硬度", "冲击", "疲劳", "腐蚀")
        primary_is_sub = bool(
            primary_group
            and any(token in primary_group for token in sub_table_tokens)
        )
        for col in mapping.condition_cols:
            if col >= len(row) or not clean_text(row[col]):
                continue
            path = block.header_paths[col] if col < len(block.header_paths) else []
            header_text = clean_text(" ".join(path))
            if "硬度" in header_text and "压痕" in header_text:
                # Indentation diameter is a dimension, never a test condition.
                continue
            if primary_group and len(path) > 1:
                group = str(path[0])
                if (
                    not primary_is_sub
                    and any(token in group for token in sub_table_tokens)
                    and not _same_header_group(group, primary_group)
                ):
                    # A second sub-table ("持久试验/试验温度") belongs to its
                    # own record family; appending it made the mechanical row
                    # look like a high-temperature test even when its own
                    # temperature was 室温. Generic condition groups such as
                    # "试样状态" are still kept.
                    continue
            part = _condition_part(" ".join(path), clean_text(row[col]))
            if part and not _is_condition_noise(part):
                parts.append(part)
        if table.profile == "mechanical_properties":
            for col in mapping.remark_cols:
                if col >= len(row):
                    continue
                text = clean_text(row[col])
                if (
                    len(text) <= 16
                    and not any(punct in text for punct in "。；;，,")
                    and REMARK_CONDITION_RE.search(text)
                    and not _is_condition_noise(text)
                    and text not in parts
                ):
                    parts.append(text)
            hints = clean_text((table.caption or "") + " " + (table.context or ""))
            for token in ("纵向", "横向"):
                if (
                    f"{token}拉伸" in hints or f"{token}力学性能" in hints
                ) and token not in parts:
                    parts.append(token)
            temperature = _caption_temperature(table.caption)
            if temperature and temperature not in parts:
                parts.append(temperature)
        if parts:
            return " / ".join(dict.fromkeys(parts))
        return _caption_condition(table.caption)

    @staticmethod
    def _is_plausible_key(text: str | None) -> bool:
        if not text or text in {
            "级别",
            "牌号",
            "材料牌号",
            "合金牌号",
            "供应状态",
            "锻件种类",
            "Grade",
            "序号",
            "名称",
            "材质",
            "材料",
            "元素",
            "含量/%",
        }:
            return False
        if len(text) > 30:
            return False
        if any(
            marker in text
            for marker in ("注", "试样结果", "仅实测", "根据需方", "不大于", "小于", "。", "；")
        ):
            return False
        return True

    @staticmethod
    def _evidence(
        table: TableGrid,
        block: TableBlock,
        row_index: int,
        col: int,
        raw: str,
        evidence_id: str,
    ) -> Evidence:
        absolute_row = block.start_row + block.header_rows + row_index
        return Evidence(
            evidence_id=evidence_id,
            page_no=table.page_no,
            table_id=table.table_id,
            row=absolute_row,
            col=col,
            quote=raw,
            artifact_uri=f"tablegrid/{table.table_id}.json",
        )

    @staticmethod
    def _record_id(doc_id: str, table_id: str, grade: str | None, condition: str | None) -> str:
        key = f"{doc_id}|{table_id}|{grade or ''}|{condition or ''}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
        return f"rec-{digest}"

    @staticmethod
    def _merge_records(records: list[Record]) -> list[Record]:
        merged: dict[tuple[str, str, str], Record] = {}
        for record in records:
            grade = clean_text(record.grade or record.grade_level or "")
            base_grade = re.sub(r"[a-z]$", "", _clean_grade(grade))
            key = (
                record.source_table_id or "",
                base_grade,
                clean_text(record.condition or ""),
            )
            existing = merged.get(key)
            if existing:
                existing.properties.update(record.properties)
            else:
                merged[key] = record
        return list(merged.values())


def _column_role(column: dict[str, Any] | None) -> str:
    if not column:
        return "ignore"
    return str(column.get("role") or "ignore").strip().lower()


def _primary_measure_group(
    block: TableBlock, mapping: "ColumnMapping"
) -> str | None:
    """Return the header group that owns the table's main properties."""

    groups: dict[str, list[str]] = {}
    for col, prop in mapping.property_cols.items():
        path = block.header_paths[col] if col < len(block.header_paths) else []
        if len(path) < 2:
            continue
        group = clean_text(path[0])
        if group:
            groups.setdefault(group, []).append(str(prop))
    if not groups:
        return None

    def score(item: tuple[str, list[str]]) -> tuple[int, int]:
        _, props = item
        tensile = sum(
            1
            for prop in props
            if prop in {"Rm", "Rp0.2", "ReH", "A", "A50mm", "Z"}
        )
        return tensile, len(props)

    return max(groups.items(), key=score)[0]


def _same_header_group(left: str, right: str) -> bool:
    def base(value: str) -> str:
        return re.sub(r"[，,].*$", "", clean_text(value)).strip()

    left_base = base(left)
    right_base = base(right)
    return bool(left_base) and bool(right_base) and (
        left_base == right_base
        or left_base in right_base
        or right_base in left_base
    )


def _condition_part(header: str, raw: str) -> str | None:
    text = clean_text(raw)
    header = clean_text(header)
    if not text or text in {"-", "/", "—", "–"}:
        return None
    if "毛坯" in header and re.fullmatch(r"\d+(?:\.\d+)?", text):
        return f"试样毛坯{text}"
    if "冷却" in header:
        if text in {"水", "油", "空气"}:
            return f"{text}冷"
        return _normalize_condition_part(text)
    if ("温度" in header or "℃" in header) and re.fullmatch(
        r"-?\d+(?:\.\d+)?(?:\s*[~-]\s*\d+(?:\.\d+)?)?", text
    ):
        value = re.sub(r"(?<=\d)\s*[~-]\s*(?=\d)", "~", text) + "°C"
        if "固溶" in header:
            return f"固溶:{value}"
        if "时效" in header:
            return f"时效:{value}"
        if "回火" in header:
            return f"回火:{value}"
        if "淬火" in header:
            return f"淬火:{value}"
        return value
    if "推荐" in header and "热处理" in header and not text.startswith("推荐热处理制度"):
        return f"推荐热处理制度:{text}"
    if "固溶" in text and "时效" in text and ("热处理" in header or "固溶" in header):
        return f"固溶+时效 / {text}"
    return _normalize_condition_part(text)


def _normalize_condition_part(text: str) -> str:
    if text in {"0", "O"}:
        return "O"
    return text


def _clean_grade(grade: str | None) -> str | None:
    if not grade:
        return grade
    grade = re.sub(r"textcircle[a-z]*$", "", grade)
    parts = [part.strip() for part in grade.split("、") if part.strip()]
    if (
        len(parts) > 1
        and re.search(r"[A-Za-z]$", parts[0])
        and all(re.fullmatch(r"[A-Za-z]", part) for part in parts[1:])
    ):
        base = parts[0][:-1]
        return "、".join([parts[0]] + [f"{base}{part}" for part in parts[1:]])
    return grade


def _is_footnote_row(row: list[str]) -> bool:
    return is_footnote_row(row)


HEADER_CELL_TOKENS = {
    "序号", "材料牌号", "牌号", "级别", "供应状态", "锻件种类", "热处理制度",
    "试验温度", "抗拉强度", "屈服强度", "断后伸长率", "断面收缩率", "布氏硬度",
    "冲击吸收能量", "力学性能", "化学成分", "公称直径", "取样方向",
}


def _is_header_like_row(row: list[str], paths: list[list[str]]) -> bool:
    """Detect a header row that leaked into a block's data rows."""

    cells = [clean_text(cell) for cell in row if clean_text(cell)]
    if len(cells) < 2:
        return False
    header_cells = {
        clean_text(part)
        for path in paths
        for part in path
        if clean_text(part)
    }
    hits = 0
    for cell in cells:
        if cell in header_cells or cell in HEADER_CELL_TOKENS:
            hits += 1
            continue
        if any(
            token in cell
            for token in (
                "抗拉强度", "断后伸长率", "断面收缩率", "规定塑性延伸",
                "冲击吸收", "布氏硬度", "力学性能", "单个最小值", "规定值",
            )
        ):
            hits += 1
    # A leaked header usually mixes several header cells with a few values, so
    # it does not reach a strict majority (e.g. 9 of 20 cells). Two strong
    # header cells already make a data row implausible; real data rows keep
    # their property names in a single column.
    return hits >= 2 and hits / len(cells) >= 0.4


NUMERIC_PROPERTIES = {
    "Rm",
    "Rp0.2",
    "ReH",
    "ReL",
    "A",
    "A50mm",
    "Z",
    "KV2",
    "KU1",
    "KU2",
    "KU5",
    "LE",
    "HB",
    "HRB",
    "HRC",
    "HV",
    "E",
    "KIC",
    "持久时间",
    "缺口持久时间",
    "Am",
}
SHIFTED_CONDITION_RE = re.compile(
    r"^(?:[OTQH]\d{1,3}[A-Z]?|模锻件|自由锻件|锻件|棒材|板材|型材|管材|丝材|锻态|铸态)$"
)


def _row_has_misplaced_condition(
    row: list[str], property_cols: dict[int, str]
) -> bool:
    """Detect a condition cell that leaked into a numeric property column."""

    for col in property_cols:
        if col >= len(row):
            continue
        cell = clean_text(row[col])
        if cell and SHIFTED_CONDITION_RE.match(cell):
            return True
    return False


TEXT_PLACEHOLDERS = {"实测", "提供实测数据", "协议", "协商确定", "由供需双方协商", "余量", "不规定"}
PROPERTY_HEADER_TOKENS = (
    "抗拉强度",
    "屈服强度",
    "规定非比例",
    "规定塑性延伸",
    "断后伸长率",
    "断面收缩率",
    "布氏硬度",
    "冲击吸收",
    "力学性能",
)


def _implausible_property(prop: str, raw: str) -> bool:
    """Reject obvious column-shift values before they reach the output."""

    text = clean_text(raw)
    key = canonical_property(prop) or prop
    if re.search(r"/(?:MPa|%|J|HBW|HRC|HV|mm)\b", text, re.IGNORECASE):
        return True
    if any(marker in text for marker in ("单个最小值", "规定值", "最小值", "最大值")):
        return True
    upper = text.upper()
    if "PPM" in upper or "WT%" in upper or "WT.%" in upper:
        return True
    if any(marker in text for marker in ("化学成分", "熔炼分析", "成品分析", "P、S含量")):
        return True
    if key in NUMERIC_PROPERTIES or prop.startswith("σ"):
        if any(token in text for token in PROPERTY_HEADER_TOKENS):
            return True
        if not any(ch.isdigit() for ch in text) and text not in TEXT_PLACEHOLDERS:
            return True
    number_match = re.search(r"-?\d+(?:\.\d+)?", text)
    number = float(number_match.group(0)) if number_match else None
    if key in {"Rm", "Rp0.2", "ReH", "ReL"}:
        if "℃" in text or any(
            marker in text for marker in ("退火", "淬火", "固溶", "正火", "回火", "时效")
        ):
            return True
        if key == "Rm" and number is not None and number < 50:
            return True
        if key != "Rm" and number is not None and number < 20:
            return True
    if key in {"A", "A50mm", "Z"}:
        if number is not None and number > 100:
            return True
    if key in {"KV2", "KU1", "KU2", "KU5"}:
        if number is not None and number > 2000:
            return True
    if key in {"HB", "HRB", "HRC", "HV"}:
        if number is not None and (number < 20 or number > 1500):
            return True
    return False


def _residue_property(header: str) -> str | None:
    """Aggregate impurity columns of a chemistry table."""
    text = clean_text(header)
    if any(
        marker in text
        for marker in ("其余单个杂质", "其它单个杂质", "其余元素单个杂质")
    ):
        return "其余单个杂质"
    if any(marker in text for marker in ("其余杂质总和", "其它杂质总和", "杂质总和")):
        return "其余杂质总和"
    return None


def _persistence_property(header: str) -> str | None:
    """Persistence/creep strength columns such as σ100h in high-temperature tables."""
    text = clean_text(header)
    if "持久" not in text and "蠕变" not in text:
        return None
    for symbol in ("σ100h", "σ50h", "σ35h"):
        if symbol in text:
            return symbol
    return None


def _note_markers(rows: list[list[str]]) -> set[str]:
    """Footnote marker letters of a table (rows such as ``aTC6棒材...``)."""
    markers: set[str] = set()
    for row in rows:
        cells = [clean_text(cell) for cell in row if clean_text(cell)]
        if len(cells) < 2:
            continue
        longest = max(cells, key=len)
        if len(longest) < 20 or cells.count(longest) < len(cells) - 1:
            continue
        match = re.match(r"^([a-z])", longest)
        if match:
            markers.add(match.group(1))
    return markers


def _element_tokens(text: str) -> tuple[str, ...]:
    elements: list[str] = []
    for token in re.split(r"[\s、,，/]+", clean_text(text)):
        element = _element_from_token(token.strip("()（）"))
        if element:
            elements.append(element)
    return tuple(elements)


def _element_from_token(token: str) -> str | None:
    if token in ELEMENTS:
        return token
    element = canonical_element(token)
    if element:
        return element
    if not token or len(token) > 3 or not token[-1].islower():
        return None
    if token == "Caa":
        return "C"
    if token[:2] in ELEMENTS and token[2:].islower():
        return token[:2]
    if token[0] in ELEMENTS and token[1:].islower():
        return token[0]
    return None


def _default_unit(prop: str) -> str | None:
    if prop in {"Rm", "Rp0.2"}:
        return "MPa"
    if prop in {"A", "Z"}:
        return "%"
    if prop == "KV2":
        return "J"
    if prop == "HB":
        return "HBW"
    if prop == "KIC":
        return "MPa·m^1/2"
    if prop in {"HRC", "HV", "E"}:
        return prop if prop != "E" else "GPa"
    return None


def _header_condition(paths: list[list[str]], context: str | None = None) -> str | None:
    text = clean_text(
        " ".join(" ".join(path) for path in paths) + " " + (context or "")
    )
    for marker in ("熔炼分析", "成品分析", "氢含量"):
        if marker in text:
            return marker
    return None


CAPTION_GRADE_PATTERNS = (
    r"GH\d{3,4}[A-Za-z]*",
    r"TA\d{1,2}",
    r"TC\d{1,2}",
    r"TB\d{1,2}",
    r"UNS\s?N\d{4,5}",
    r"(?<![A-Za-z0-9])\d{1,3}Cr\d{1,2}[A-Za-z0-9.-]*",
    r"(?<![A-Za-z0-9])\d{3}[A-Z]{1,3}(?![A-Za-z0-9])",
    r"(?<![A-Za-z0-9])\d{2,3}(?:Mn|Cr|Ni|Mo|Si|Al|Ti|Nb|V|W|N|S)[A-Za-z0-9]*",
    r"(?<![A-Za-z0-9])[A-Z]{1,3}-?\d{2,4}[A-Za-z]?(?![A-Za-z0-9])",
)


def _caption_grade(caption: str | None) -> str | None:
    """Recover the grade from a caption such as ``表2 GH4202力学性能``."""

    text = clean_text(caption)
    if not text:
        return None
    for pattern in CAPTION_GRADE_PATTERNS:
        for match in re.finditer(pattern, text):
            value = match.group(0)
            if value.isdigit():
                continue
            if re.match(r"^0\d", value):
                # Project/document codes such as 003ZWB are not grades.
                continue
            if looks_like_grade(value):
                return value
    return None


def _document_grade(document: DocumentMeta) -> str | None:
    for index, raw_text in enumerate((document.title or "", document.file_name or "")):
        # 平台上传会把文件名改成“{document_id}-{file_name}”，先去掉 32 位前缀，
        # 避免把 document_id 中的 4 位数字误判成牌号。
        text = re.sub(r"^[0-9a-f]{32}-", "", raw_text, flags=re.IGNORECASE)
        patterns = (
            r"GH\d{3,4}[A-Za-z]*",
            r"TA\d{1,2}",
            r"TC\d{1,2}",
            r"TB\d{1,2}",
            r"UNS\s?N\d{4,5}",
            r"(?<![A-Za-z0-9._/-])\d{3}(?![A-Za-z0-9._/-])",
        )
        if index == 0:
            patterns = (
                *patterns,
                r"(?<![A-Za-z0-9])\d{4}(?![A-Za-z0-9])",
                r"(?<![A-Za-z0-9])[A-Z]{1,2}\d{2,4}[A-Za-z]?(?![A-Za-z0-9])",
                r"(?<![A-Za-z0-9])\d{3}[A-Z]{1,3}(?![A-Za-z0-9])",
                r"(?<![A-Za-z0-9])\d{2,3}(?:Mn|Cr|Ni|Mo|Si|Al|Ti|Nb|V|W|N|S)[A-Za-z0-9]*",
            )
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            value = match.group(0)
            if value in {"GB", "GJB", "HB", "JB", "MAS", "Q"}:
                continue
            if re.match(r"^0\d", value):
                # Project codes such as 003ZWB are not material grades.
                continue
            if value.isdigit() and (
                value.startswith("0")
                or 1900 <= int(value) <= 2099
                or (len(value) == 3 and value not in NUMERIC_GRADES)
            ):
                continue
            return value
    return None


def _caption_temperature(caption: str | None) -> str | None:
    text = clean_text(caption or "")
    text = re.sub(r"^表\s*[A-Za-z]?\.?\s*\d\s*", "", text)
    match = re.search(r"(\d{2,4})\s*(?:℃|°C|circ\s*C)", text)
    if match:
        return f"{match.group(1)}°C"
    return None


def _element_condition(table: TableGrid) -> str | None:
    hints = clean_text((table.caption or "") + " " + (table.context or ""))
    if "化学成分" in hints:
        if "wt%" in hints.lower():
            return "wt% / 化学成分"
        return "化学成分"
    return _caption_condition(table.caption)


def _is_condition_noise(text: str) -> bool:
    if not text:
        return True
    if re.fullmatch(r"[\d.%~\-/]+", text):
        # Keep size/range conditions such as 200~300 or 15-400; drop single
        # numeric noise that carries no condition semantics.
        return not re.search(r"\d(?:\.\d+)?\s*[~\-]\s*\d", text)
    if text in {"不大于", "不小于", "-"}:
        return True
    if "公称厚度" in text or "厚度或直径" in text:
        return True
    return False


def _caption_condition(caption: str | None) -> str | None:
    text = clean_text(caption or "")
    for marker in (
        "热机械轧制",
        "正火轧制",
        "氢含量",
        "热轧",
        "正火",
        "淬火",
        "回火",
        "退火",
        "固溶",
        "冷拉",
        "冷轧",
    ):
        if marker in text:
            return marker
    return None


def _parse_json(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    return json.loads(raw)
