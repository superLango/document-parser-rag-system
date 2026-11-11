"""Long-task segmentation and deterministic map-reduce merging."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .context.tokenizer import Tokenizer


@dataclass
class Segment:
    segment_id: str
    kind: str
    payload: dict[str, Any]
    tokens: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "kind": self.kind,
            "payload": self.payload,
            "tokens": self.tokens,
        }


@dataclass
class MergeResult:
    output: dict[str, Any]
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    segments: int = 0
    merged_items: int = 0


class Segmenter:
    def __init__(self, tokenizer: Tokenizer, max_tokens: int = 24000) -> None:
        self.tokenizer = tokenizer
        self.max_tokens = max_tokens

    async def segment_tables(self, tables: list[dict[str, Any]]) -> list[Segment]:
        segments: list[Segment] = []
        for table in tables:
            table_id = str(table.get("table_id") or "T")
            header = {
                "table_id": table_id,
                "page_no": table.get("page_no"),
                "caption": table.get("caption"),
                "profile": table.get("profile"),
                "orientation": table.get("orientation"),
                "header_paths": table.get("header_paths") or [],
                "units": table.get("units") or [],
            }
            rows = list(table.get("rows") or [])
            header_tokens = await self._count_json(header)
            current: list[list[str]] = []
            current_tokens = header_tokens
            start = 0
            for index, row in enumerate(rows):
                row_tokens = await self._count_json(row)
                if current and current_tokens + row_tokens > self.max_tokens:
                    segments.append(
                        self._table_segment(table_id, header, current, start, index)
                    )
                    start = index
                    current = []
                    current_tokens = header_tokens
                current.append(row)
                current_tokens += row_tokens
            if current or not rows:
                segments.append(
                    self._table_segment(table_id, header, current, start, len(rows))
                )
        return segments

    def _table_segment(
        self,
        table_id: str,
        header: dict[str, Any],
        rows: list[list[str]],
        start: int,
        end: int,
    ) -> Segment:
        payload = dict(header)
        payload["rows"] = rows
        payload["row_start"] = start
        payload["row_end"] = end
        return Segment(
            segment_id=f"{table_id}:rows{start}-{end}",
            kind="table",
            payload=payload,
        )

    async def segment_pages(self, pages: list[dict[str, Any]]) -> list[Segment]:
        segments: list[Segment] = []
        for page in pages:
            page_no = int(page.get("page_no") or 0)
            text = str(page.get("markdown") or "")
            tokens = await self.tokenizer.count(text)
            if tokens <= self.max_tokens:
                segments.append(
                    Segment(
                        segment_id=f"page:{page_no}",
                        kind="page",
                        payload={"page_no": page_no, "markdown": text},
                        tokens=tokens,
                    )
                )
                continue
            chunk: list[str] = []
            chunk_tokens = 0
            chunk_index = 0
            for line in text.splitlines():
                line_tokens = await self.tokenizer.count(line)
                if chunk and chunk_tokens + line_tokens > self.max_tokens:
                    segments.append(
                        Segment(
                            segment_id=f"page:{page_no}:chunk{chunk_index}",
                            kind="page_range",
                            payload={
                                "page_no": page_no,
                                "markdown": "\n".join(chunk),
                                "chunk_index": chunk_index,
                            },
                            tokens=chunk_tokens,
                        )
                    )
                    chunk_index += 1
                    chunk = []
                    chunk_tokens = 0
                chunk.append(line)
                chunk_tokens += line_tokens
            if chunk:
                segments.append(
                    Segment(
                        segment_id=f"page:{page_no}:chunk{chunk_index}",
                        kind="page_range",
                        payload={
                            "page_no": page_no,
                            "markdown": "\n".join(chunk),
                            "chunk_index": chunk_index,
                        },
                        tokens=chunk_tokens,
                    )
                )
        return segments

    async def segment_schema(self, schema: dict[str, Any]) -> list[Segment]:
        categories = schema.get("categories") or []
        if not categories:
            return [
                Segment(
                    segment_id="schema:all",
                    kind="schema_category",
                    payload={"schema": schema},
                    tokens=await self._count_json(schema),
                )
            ]
        segments: list[Segment] = []
        group: list[dict[str, Any]] = []
        tokens = 0
        index = 0
        for category in categories:
            category_tokens = await self._count_json(category)
            if group and tokens + category_tokens > self.max_tokens:
                segments.append(
                    Segment(
                        segment_id=f"schema:group{index}",
                        kind="schema_category",
                        payload={"categories": group},
                        tokens=tokens,
                    )
                )
                index += 1
                group = []
                tokens = 0
            group.append(category)
            tokens += category_tokens
        if group:
            segments.append(
                Segment(
                    segment_id=f"schema:group{index}",
                    kind="schema_category",
                    payload={"categories": group},
                    tokens=tokens,
                )
            )
        return segments

    async def _count_json(self, value: Any) -> int:
        return await self.tokenizer.count(json.dumps(value, ensure_ascii=False, sort_keys=True))


def merge_segment_outputs(
    segments: list[Segment],
    outputs: list[dict[str, Any]],
    *,
    key_field: str = "record_id",
) -> MergeResult:
    """Deterministically merge segment outputs; conflicts are reported, not hidden."""
    if len(segments) != len(outputs):
        raise ValueError("segments and outputs must have the same length")
    merged: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    order: list[str] = []
    for segment, output in zip(segments, outputs, strict=True):
        if isinstance(output, dict):
            items = output.get("records", output.get("findings", output))
        else:
            items = output
        if not isinstance(items, list):
            raise ValueError(f"segment {segment.segment_id} output is not a list")
        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get(key_field) or item.get("evidence_id") or "")
            if not key:
                key = f"{segment.segment_id}:{len(order)}"
            canonical = json.dumps(item, ensure_ascii=False, sort_keys=True)
            existing = merged.get(key)
            if existing is not None:
                previous = json.dumps(existing, ensure_ascii=False, sort_keys=True)
                if previous != canonical:
                    conflicts.append(
                        {
                            "key": key,
                            "segment_id": segment.segment_id,
                            "previous": existing,
                            "incoming": item,
                        }
                    )
                continue
            merged[key] = item
            order.append(key)
    return MergeResult(
        output={key_field: [merged[key] for key in order]},
        conflicts=conflicts,
        segments=len(segments),
        merged_items=len(order),
    )
