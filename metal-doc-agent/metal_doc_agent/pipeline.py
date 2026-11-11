"""End-to-end pipeline.

The pipeline is deliberately boring: read, parse, extract, validate, write
artifacts. Model calls sit behind adapters; the mock adapters make the framework
runnable on a laptop with no GPU.
"""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .artifacts import write_artifact_manifest
from .canonicalize import (
    DictionaryIndex,
    JsonDictionaryAdapter,
    align_inventory,
    load_dictionary_path,
)
from .contracts import (
    AlignmentResult,
    AuditReport,
    CoveragePlan,
    DocumentMeta,
    DocumentResult,
    Evidence,
    ItemInventory,
    NewTermStore,
    Page,
    Record,
    TableGrid,
    TableIR,
    TableIRBundle,
)
from .coverage import build_coverage, build_coverage_audit, build_links, build_outline
from .cross_standard import detect_tasks
from .document_types import detect_document_type
from .extraction import build_extractor
from .extraction.base import Extractor
from .extraction.clauses import extract_clauses
from .extraction.ir_matrix import (
    compare_extraction_outputs,
    extract_bound_matrix_ir,
    extract_element_matrix_ir,
    extract_hardness_minmax_ir,
    extract_property_matrix_ir,
)
from .extraction.matrix import (
    extract_bound_matrix,
    extract_element_matrix,
    extract_grade_property_matrix,
    extract_grade_property_tail,
    extract_hardness_minmax,
    extract_property_matrix,
    extract_property_rows,
    merge_matrix_output,
)
from .extraction.nonrecord import (
    attach_nh_rule,
    compare_nonrecord_outputs,
    extract_nonrecord,
    extract_nonrecord_ir,
    extract_nh_rule,
    inspections_from_clauses,
    resolve_table_references,
)
from .ingest import apply_page_identity, ingest
from .items import attach_clause_methods, discover_items
from .ocr import build_ocr_adapter
from .ocr.base import OcrAdapter
from .queues.store import QueueStore
from .recipes import (
    bind_columns,
    decide_route,
    doc_queue,
    load_aliases,
    load_recipes,
    match_recipe,
)
from .recipes.lifecycle import RecipeRegistry
from .references import extract_references
from .relevance import plan_references
from .settings import Settings
from .standards import load_registry, resolve_references
from .storage import ArtifactStore
from .tablegrid import extract_tables
from .tablegrid.ir import build_table_ir
from .tablegrid.normalize import canonical_element, canonical_property
from .tablegrid.repairs import apply_table_repairs
from .validation import validate

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    result: DocumentResult
    evidence: list[Evidence]
    audit_markdown: str
    trace: dict[str, Any]
    inventory: ItemInventory | None = None
    alignment: AlignmentResult | None = None


def run_pipeline(
    doc_path: str | Path,
    out_dir: str | Path,
    settings: Settings | None = None,
    ocr: OcrAdapter | None = None,
    extractor: Extractor | None = None,
    coverage_template: str = "product_full",
    job_id: str | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> PipelineResult:
    started = time.perf_counter()
    settings = settings or Settings.from_env()
    ocr = ocr or build_ocr_adapter(settings)
    extractor = extractor or build_extractor(settings)
    store = ArtifactStore(Path(out_dir))
    steps: list[dict[str, Any]] = []
    job_id = job_id or Path(out_dir).name or "local"

    def mark(name: str, started_at: float, percent: int, **extra: Any) -> None:
        steps.append({"name": name, "ms": round((time.perf_counter() - started_at) * 1000, 2), **extra})
        if progress is not None:
            progress(name, percent)

    t = time.perf_counter()
    document, ingested_pages = ingest(doc_path)
    mark("ingest", t, 5, pages=len(ingested_pages))

    t = time.perf_counter()
    pages: list[Page] = ocr.recognize(Path(doc_path), out_dir=Path(out_dir))
    document = document.model_copy(update={"page_count": len(pages)})
    document = apply_page_identity(document, pages)
    mark("ocr", t, 25, backend=ocr.name, pages=len(pages))

    t = time.perf_counter()
    tables: list[TableGrid] = extract_tables(pages)
    tables = apply_table_repairs(
        tables,
        document,
        settings.project_root / "configs" / "table_repairs.json",
        learned_path=settings.data_dir / "repairs" / "table_repairs.json",
    )
    mark("tablegrid", t, 45, tables=len(tables))

    t = time.perf_counter()
    doc_type = detect_document_type(document, pages, tables)
    effective_template = coverage_template
    if (
        coverage_template == "product_full"
        and doc_type.coverage_template
        and doc_type.doc_type in {"purchase_spec", "process_document"}
    ):
        effective_template = doc_type.coverage_template
    mark(
        "document_type",
        t,
        46,
        type=doc_type.doc_type,
        confidence=doc_type.confidence,
        template=effective_template,
    )

    t = time.perf_counter()
    recipes = load_recipes(settings.project_root / "configs" / "recipes")
    aliases = load_aliases(settings.project_root / "configs" / "column_aliases.json")
    bindings: dict[str, Any] = {}
    recipe_hits = 0
    for table in tables:
        match = match_recipe(table, recipes)
        if match.status in {"exact", "candidate"}:
            recipe_hits += 1
        bindings[table.table_id] = bind_columns(
            table,
            recipe=match.recipe,
            aliases=aliases,
            match_status=match.status,
        )
    mark("bindings", t, 48, tables=len(bindings), recipes=recipe_hits)

    t = time.perf_counter()
    table_irs: list[TableIR] = [
        build_table_ir(
            table,
            binding=bindings.get(table.table_id),
            doc_id=document.doc_id,
        )
        for table in tables
    ]
    ir_by_table = {ir.table_id: ir for ir in table_irs}
    mark(
        "table_ir",
        t,
        48,
        tables=len(table_irs),
        cells=sum(len(ir.cells) for ir in table_irs),
    )

    t = time.perf_counter()
    routing: dict[str, Any] | None = None
    if settings.recipe_routing:
        routing = _route_document(settings, recipes, tables, document, job_id, doc_path)
        mark(
            "routing",
            t,
            49,
            queue=routing["queue"],
            tables=len(routing["tables"]),
            queued=routing["queued"],
        )

    t = time.perf_counter()
    outline = build_outline(document, pages)
    mark("outline", t, 50, nodes=len(outline.nodes))

    t = time.perf_counter()
    clause_output = extract_clauses(pages, document)
    clauses = clause_output.clauses
    mark("clauses", t, 55, clauses=len(clauses))

    t = time.perf_counter()
    references = extract_references(pages, document)
    registry = load_registry(settings.project_root / "configs" / "standards.json")
    version_report = resolve_references(references, registry)
    plan_references(references)
    version_markdown = version_report.to_markdown(references)
    mark(
        "references",
        t,
        58,
        edges=len(references.references),
        resolved=version_report.resolved,
        selected=references.budget.get("selected_documents"),
        gaps=len(references.gaps),
    )

    t = time.perf_counter()
    cross_tasks = detect_tasks(
        pages,
        document,
        registry=registry,
        catalog_path=settings.project_root / "data" / "standards_library" / "catalog.json",
    )
    mark("cross_standard", t, 59, tasks=len(cross_tasks))

    t = time.perf_counter()
    inventory = discover_items(
        pages,
        tables,
        bindings,
        cross_tasks,
        doc_id=document.doc_id,
        document_profile=doc_type.doc_type,
    )
    mark(
        "inventory",
        t,
        60,
        items=len(inventory.items),
        unknown=len(inventory.unknown_candidates),
    )

    t = time.perf_counter()
    records: list[Record] = []
    evidence: list[Evidence] = []
    evidence.extend(clause_output.evidence)
    workers = max(1, int(getattr(extractor, "concurrency", 1)))
    if workers > 1 and len(tables) > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            outputs = list(pool.map(lambda table: extractor.extract(table, document), tables))
    else:
        outputs = [extractor.extract(table, document) for table in tables]
    for output in outputs:
        records.extend(output.records)
        evidence.extend(output.evidence)
    mark("extract", t, 75, backend=extractor.name, records=len(records), evidence=len(evidence))

    t = time.perf_counter()
    matrix_tables = 0
    matrix_records = 0
    matrix_covered: set[str] = set()
    ir_diffs: dict[str, dict] = {}
    for table in tables:
        bound = bindings.get(table.table_id)
        if bound is None:
            continue
        output = extract_bound_matrix(table, bound, document)
        ir = ir_by_table.get(table.table_id)
        if ir is not None:
            # Dual-run gate: the legacy reader stays authoritative until the
            # IR path proves record- and evidence-identical on real documents.
            ir_diffs[f"{table.table_id}:bound_matrix"] = compare_extraction_outputs(
                output, extract_bound_matrix_ir(ir, bound, document)
            )
        if output is None:
            continue
        records, replace = merge_matrix_output(records, output, table.table_id)
        if replace:
            evidence = [item for item in evidence if item.table_id != table.table_id]
        evidence.extend(output.evidence)
        matrix_covered.add(table.table_id)
        matrix_tables += 1
        matrix_records += len(output.records)
    covered = {record.source_table_id for record in records}
    for table in tables:
        if table.table_id in covered:
            continue
        output = extract_property_matrix(table, document)
        ir = ir_by_table.get(table.table_id)
        if ir is not None:
            ir_diffs[f"{table.table_id}:property_matrix"] = compare_extraction_outputs(
                output, extract_property_matrix_ir(ir, document)
            )
        if output is None:
            continue
        records.extend(output.records)
        evidence.extend(output.evidence)
        matrix_covered.add(table.table_id)
        matrix_tables += 1
        matrix_records += len(output.records)
    # Imported specifications write grade rows with property columns
    # (``Grade | Tensile Strength | Yield Strength``) or vertical
    # ``Property | Value`` tables. Both are deterministic and override the
    # model's partial rows for that table.
    for table in tables:
        if table.profile != "mechanical_properties":
            continue
        output = None
        if table.table_id not in matrix_covered:
            output = extract_grade_property_matrix(table, document)
            if output is None:
                output = extract_property_rows(table, document)
        if output is None:
            # A wide mechanical table may have been claimed by a narrow bound
            # recipe (impact energy only); a multi-property numeric tail is the
            # more complete reading of the same row.
            tail = extract_grade_property_tail(table, document)
            if tail is not None:
                distinct = {
                    prop for record in tail.records for prop in record.properties
                }
                if len(distinct) >= 3:
                    output = tail
        if output is None or len(output.records) < 2:
            continue
        records = [
            record for record in records if record.source_table_id != table.table_id
        ]
        evidence = [item for item in evidence if item.table_id != table.table_id]
        records.extend(output.records)
        evidence.extend(output.evidence)
        matrix_covered.add(table.table_id)
        matrix_tables += 1
        matrix_records += len(output.records)
    for table in tables:
        if table.profile != "chemical_composition":
            continue
        output = extract_element_matrix(table, document)
        ir = ir_by_table.get(table.table_id)
        if ir is not None:
            ir_diffs[f"{table.table_id}:element_matrix"] = compare_extraction_outputs(
                output, extract_element_matrix_ir(ir, document)
            )
        if output is None:
            continue
        records = [
            record
            for record in records
            if record.source_table_id != table.table_id
        ]
        evidence = [
            item for item in evidence if item.table_id != table.table_id
        ]
        records.extend(output.records)
        evidence.extend(output.evidence)
        matrix_covered.add(table.table_id)
        matrix_tables += 1
        matrix_records += len(output.records)
    for table in tables:
        output = extract_hardness_minmax(table, document)
        ir = ir_by_table.get(table.table_id)
        if ir is not None:
            ir_diffs[f"{table.table_id}:hardness_minmax"] = compare_extraction_outputs(
                output, extract_hardness_minmax_ir(ir, document)
            )
        if output is None:
            continue
        records = [
            record for record in records if record.source_table_id != table.table_id
        ]
        evidence = [item for item in evidence if item.table_id != table.table_id]
        records.extend(output.records)
        evidence.extend(output.evidence)
        matrix_covered.add(table.table_id)
        matrix_tables += 1
        matrix_records += len(output.records)
    mark(
        "matrix_extract",
        t,
        76,
        tables=matrix_tables,
        records=matrix_records,
        ir_checked=len(ir_diffs),
    )

    t = time.perf_counter()
    inspection_items = []
    classification_items = []
    for table in tables:
        output = extract_nonrecord(table, document)
        ir = ir_by_table.get(table.table_id)
        if ir is not None:
            ir_diffs[f"{table.table_id}:nonrecord"] = compare_nonrecord_outputs(
                output, extract_nonrecord_ir(ir, document)
            )
        inspection_items.extend(output.inspection_items)
        classification_items.extend(output.classification_items)
        evidence.extend(output.evidence)
    ir_diff_summary = {
        "tables": len(ir_diffs),
        "identical": sum(
            1 for item in ir_diffs.values() if item["status"] == "identical"
        ),
        "skipped": sum(
            1 for item in ir_diffs.values() if item["status"] == "skipped"
        ),
        "mismatch": sum(
            1 for item in ir_diffs.values() if item["status"] == "mismatch"
        ),
    }
    table_ir_diff = {
        "doc_id": document.doc_id,
        "summary": ir_diff_summary,
        "tables": ir_diffs,
    }
    if ir_diff_summary["mismatch"]:
        logger.warning(
            "table IR dual-run mismatch: %s",
            [key for key, value in ir_diffs.items() if value["status"] == "mismatch"],
        )
    inspection_items = resolve_table_references(inspection_items, tables)
    # 汇编/程序类文档（表数量远超单份标准）不应因为一条通用取样条款
    # 就从“不适用”变成可套用产品模板，否则会把上千条记录投影成空行。
    # 已有检验表的文档仍允许用条款补充取样说明。
    if inspection_items or (len(tables) <= 30 and len(inventory.items) <= 100):
        inspection_items.extend(
            inspections_from_clauses(clauses, inspection_items)
        )
    # 检验记录清单常把“N=抽检数量、H=送检数量”的分档公式放在表尾备注里，
    # 单行无法换算成具体件数，把原始公式保留到取样说明。
    inspection_items = attach_nh_rule(
        inspection_items, extract_nh_rule(tables)
    )
    mark(
        "nonrecord",
        t,
        80,
        inspection=len(inspection_items),
        classification=len(classification_items),
        ir_mismatch=ir_diff_summary["mismatch"],
    )

    t = time.perf_counter()
    attached_methods = attach_clause_methods(inventory, inspection_items, clauses)
    mark("item_methods", t, 80, attached=attached_methods)

    t = time.perf_counter()
    bbox_count = attach_evidence_bboxes(evidence, pages)
    mark("evidence_bbox", t, 81, enriched=bbox_count)

    t = time.perf_counter()
    dictionary = _load_business_dictionary(settings)
    if dictionary is not None and settings.business_alignment:
        index = DictionaryIndex.build(dictionary)
        aligned_inventory, alignment = align_inventory(
            inventory,
            index,
            category_mode=settings.dictionary_category_mode,
        )
        mark(
            "alignment",
            t,
            82,
            dictionary=dictionary.version,
            categories=alignment.summary["categories_matched"],
            properties=alignment.summary["properties_matched"],
            methods=alignment.summary["methods_matched"],
            new_terms=alignment.summary["new_terms"],
        )
    else:
        aligned_inventory = inventory.model_copy(deep=True)
        alignment = None
        mark(
            "alignment",
            t,
            82,
            skipped=True,
            reason="dictionary missing" if dictionary is None else "disabled",
        )

    t = time.perf_counter()
    links = build_links(document.doc_id, pages, tables)
    mark(
        "links",
        t,
        83,
        linked=links.coverage.get("linked", 0),
        rate=links.coverage.get("link_rate", 0),
    )

    t = time.perf_counter()
    coverage_audit = build_coverage_audit(
        document.doc_id,
        pages,
        tables,
        inventory,
        links,
        bindings=bindings,
        records=records,
    )
    mark(
        "item_coverage",
        t,
        84,
        status=coverage_audit.status,
        gaps=len(coverage_audit.gaps),
    )

    t = time.perf_counter()
    outline_titles = [
        node.title for node in outline.nodes if node.kind in {"clause", "table", "appendix"}
    ]
    coverage: CoveragePlan = build_coverage(
        document=document,
        records=records,
        tables=tables,
        evidence=evidence,
        template=effective_template,
        settings=settings,
        outline_titles=outline_titles,
        document_type=doc_type,
    )
    mark("coverage", t, 85, items=len(coverage.items))

    t = time.perf_counter()
    expansion: dict[str, Any] | None = None
    if cross_tasks:
        try:
            from .cross_standard_expand import expand_tasks

            expansion = expand_tasks(
                Path(out_dir),
                Path(settings.project_root),
                cross_tasks,
            )
        except Exception as exc:  # noqa: BLE001 - expansion must not fail parsing
            logger.warning("cross-standard expansion failed: %s", str(exc)[:200])
            expansion = {"error": str(exc)[:300]}
    mark(
        "cross_standard_expand",
        t,
        87,
        tasks=len(cross_tasks),
        expanded=(expansion or {}).get("expanded", 0),
    )

    t = time.perf_counter()
    # 模型偶发把高温力学表读成化学成分（GB/T 713.7 的 Rp1.0 表出现 S=142%）。
    # 表已被确定性判定为力学表时，纯元素记录一定是幻觉，直接丢弃。
    profile_by_table = {table.table_id: table.profile for table in tables}
    records = [
        record
        for record in records
        if not (
            profile_by_table.get(record.source_table_id) == "mechanical_properties"
            and record.properties
            and all(
                canonical_element(name) is not None
                and canonical_property(name) is None
                for name in record.properties
            )
        )
    ]
    audit: AuditReport = validate(document, records, evidence, coverage, tables=tables)
    mark("validate", t, 95, status=audit.status, issues=len(audit.issues))

    result = DocumentResult(
        document=document,
        tables=tables,
        records=records,
        inspection_items=inspection_items,
        classification_items=classification_items,
        clauses=clauses,
        references=references,
        coverage=coverage,
        quality=audit,
    )

    artifacts = {
        "manifest": "manifest.json",
        "pages": "pages.json",
        "outline": "outline.json",
        "references": "references.json",
        "version_report": "version_report.md",
        "coverage": "coverage_plan.json",
        "evidence": "evidence.jsonl",
        "audit": "audit.md",
        "trace": "trace.json",
        "result": "result.json",
        "tablegrid": "tablegrid/",
        "table_ir": "table_ir.json",
        "table_ir_diff": "table_ir_diff.json",
        "column_bindings": "column_bindings.json",
        "item_inventory": "item_inventory.json",
        "clauses": "clauses.jsonl",
        "table_clause_links": "links.json",
        "item_coverage_audit": "coverage_audit.json",
        "cross_standard_tasks": "cross_standard_tasks.json",
        "cross_standard_expansion": "cross_standard_expansion.json",
        "cross_standard_merge": "cross_standard_merge.json",
        "document_type": "document_type.json",
        "artifact_manifest": "artifacts.json",
    }
    if alignment is not None:
        artifacts.update(
            {
                "item_inventory_aligned": "item_inventory_aligned.json",
                "alignment": "alignment.json",
                "new_terms": "new_terms.json",
            }
        )
    if routing is not None:
        artifacts["routing"] = "routing.json"
    result.artifacts = artifacts

    versions = {
        "pipeline": "0.1.0",
        "ocr": ocr.name,
        "extractor": extractor.name,
        "coverage_template": effective_template,
        "document_type": doc_type.doc_type,
        "schema": result.schema_version,
    }
    if alignment is not None:
        versions["business_dictionary"] = alignment.dictionary_version
    if routing is not None:
        versions["routing"] = "m2.5.3"
    trace = {
        "job_id": job_id,
        "doc_id": document.doc_id,
        "doc_path": str(doc_path),
        "source_sha256": document.sha256,
        "artifact_manifest": "artifacts.json",
        "steps": steps,
        "versions": versions,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    usage = getattr(extractor, "usage", None)
    if isinstance(usage, dict):
        trace["model_usage"] = usage

    audit_markdown = render_audit_markdown(result)
    store.write_json("manifest.json", document)
    store.write_json("pages.json", pages)
    for table in tables:
        store.write_json(f"tablegrid/{table.table_id}.json", table)
    store.write_json(
        "table_ir.json",
        TableIRBundle(doc_id=document.doc_id, tables=table_irs),
    )
    store.write_json("table_ir_diff.json", table_ir_diff)
    store.write_json("outline.json", outline)
    store.write_json("references.json", references)
    store.write_text("version_report.md", version_markdown)
    store.write_json("coverage_plan.json", coverage)
    store.write_jsonl("evidence.jsonl", evidence)
    store.write_text("audit.md", audit_markdown)
    store.write_json("trace.json", trace)
    store.write_json("result.json", result)
    store.write_json("column_bindings.json", bindings)
    store.write_json("item_inventory.json", inventory)
    store.write_jsonl("clauses.jsonl", clauses)
    store.write_json("links.json", links)
    store.write_json("coverage_audit.json", coverage_audit)
    store.write_json("document_type.json", doc_type.to_dict())
    store.write_json(
        "cross_standard_tasks.json",
        [task.model_dump(mode="json") for task in cross_tasks],
    )
    if alignment is not None:
        store.write_json("item_inventory_aligned.json", aligned_inventory)
        store.write_json("alignment.json", alignment)
        store.write_json(
            "new_terms.json",
            NewTermStore(
                dictionary_version=alignment.dictionary_version,
                terms=alignment.new_terms,
            ),
        )
    if routing is not None:
        store.write_json("routing.json", routing)
    try:
        if doc_type.not_applicable:
            # 热处理检查计划等文档没有产品字段可投影，保持 not_applicable，
            # 不生成空的 schema_result。
            logger.info(
                "schema projection skipped: %s (%s)",
                doc_type.doc_type,
                doc_type.label,
            )
        else:
            from .schema_projection import load_template, project_hanson_schema

            template = load_template(
                Path(__file__).resolve().parents[1]
                / "configs"
                / "schema_templates"
                / "product_standard.json"
            )
            dictionary = _load_business_dictionary(settings)
            payload = project_hanson_schema(
                Path(out_dir),
                template,
                index=(
                    DictionaryIndex.build(dictionary)
                    if dictionary is not None
                    else None
                ),
                timing_seconds=float(trace.get("elapsed_ms") or 0) / 1000.0,
            )
            try:
                from .method_binding import fill_projected_methods

                method_bindings = fill_projected_methods(payload, pages)
                if method_bindings["updated"]:
                    store.write_json("method_bindings.json", method_bindings)
            except Exception:  # noqa: BLE001 - binding must not fail the job
                logger.warning("method binding failed", exc_info=True)
            store.write_json("schema_result.json", payload)
    except Exception:  # noqa: BLE001 - projection must not fail the job
        logger.warning("schema projection failed", exc_info=True)
    write_artifact_manifest(Path(out_dir), job_id=job_id, doc_id=document.doc_id)
    if progress is not None:
        progress("done", 100)

    return PipelineResult(
        result=result,
        evidence=evidence,
        audit_markdown=audit_markdown,
        trace=trace,
        inventory=inventory,
        alignment=alignment,
    )


def _route_document(
    settings: Settings,
    recipes: list,
    tables: list[TableGrid],
    document: DocumentMeta,
    job_id: str,
    doc_path: str | Path,
) -> dict[str, Any]:
    """M2.5.3-01/03: route every table and deliver the document to one lane.

    Enqueue failures are logged, never raised: routing must not block extraction.
    """
    registry = RecipeRegistry(
        settings.project_root / "configs" / "recipes" / "registry.json"
    )
    history = registry.success_rates()
    scoped = [table for table in tables if table.profile != "admin"]
    decisions = [decide_route(table, recipes, history=history) for table in scoped]
    queue = doc_queue(decisions) if decisions else "production"
    payload: dict[str, Any] = {
        "doc_id": document.doc_id,
        "job_id": job_id,
        "doc_path": str(doc_path),
        "source_sha256": document.sha256,
        "queue": queue,
        "tables": {
            table.table_id: decision.to_dict()
            for table, decision in zip(scoped, decisions)
        },
    }
    queued = True
    try:
        if decisions:
            QueueStore(Path(settings.data_dir) / "queues").enqueue(queue, payload)
    except OSError:
        queued = False
        logger.warning("recipe queue enqueue failed", exc_info=True)
    payload["queued"] = queued
    return payload


def attach_evidence_bboxes(evidence: list[Evidence], pages: list[Page]) -> int:
    """Attach layout bboxes to evidence when OCR sidecars are available."""

    if not evidence:
        return 0
    blocks_by_page: dict[int, list[dict[str, Any]]] = {}
    for page in pages:
        if not page.layout_path:
            continue
        path = Path(page.layout_path)
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        blocks_by_page[page.page_no] = data.get("blocks") or []

    enriched = 0
    for item in evidence:
        if item.bbox:
            continue
        blocks = blocks_by_page.get(item.page_no) or []
        quote = re.sub(r"\s+", "", item.quote or "")
        match: dict[str, Any] | None = None
        if len(quote) >= 4:
            best = 0
            for block in blocks:
                text = re.sub(r"\s+", "", str(block.get("text") or ""))
                if len(text) < 4:
                    continue
                if quote in text or text in quote:
                    score = min(len(text), len(quote))
                    if score > best:
                        match, best = block, score
        if match is None and item.table_id:
            table_blocks = [b for b in blocks if b.get("type") == "table"]
            if len(table_blocks) == 1:
                match = table_blocks[0]
        bbox = (match or {}).get("bbox")
        if isinstance(bbox, list) and len(bbox) == 4:
            item.bbox = [round(float(value), 4) for value in bbox]
            enriched += 1
    return enriched


def _load_business_dictionary(settings: Settings):
    """Load the offline business dictionary; a broken file must not fail a run."""

    path = Path(settings.business_dictionary_path)
    if not path.is_absolute():
        path = settings.project_root / path
    if not path.exists():
        return None
    overrides = settings.business_dictionary_override_path
    override_path = None
    if overrides:
        override_path = Path(overrides)
        if not override_path.is_absolute():
            override_path = settings.project_root / override_path
    try:
        if path.is_dir():
            dictionary = load_dictionary_path(path)
        else:
            dictionary = JsonDictionaryAdapter(path, override_path).load()
        try:
            from .selfheal.lexicon import apply_learned_lexicon

            dictionary = apply_learned_lexicon(dictionary, settings.project_root)
        except Exception:  # noqa: BLE001 - learned overlay is optional
            pass
        return dictionary
    except Exception:  # noqa: BLE001 - keep extraction independent of dictionary state
        logger.warning("business dictionary load failed: %s", path, exc_info=True)
        return None


def render_audit_markdown(result: DocumentResult) -> str:
    doc = result.document
    audit = result.quality
    lines: list[str] = []
    lines.append(f"# 审核报告：{doc.standard_no or doc.file_name}")
    lines.append("")
    lines.append(f"- 文档：{doc.title or doc.file_name}")
    lines.append(f"- 页数：{doc.page_count}")
    lines.append(f"- 状态：**{audit.status if audit else 'unknown'}**")
    lines.append(f"- 表格：{len(result.tables)}")
    lines.append(f"- 记录：{len(result.records)}")
    lines.append("")

    if audit:
        lines.append("## 统计")
        lines.append("")
        lines.append("| 指标 | 值 |")
        lines.append("|---|---|")
        for key, value in audit.stats.items():
            lines.append(f"| {key} | {value} |")
        lines.append("")

    lines.append("## 覆盖")
    lines.append("")
    lines.append("| 字段 | 必填 | 状态 | 预期位置 | 说明 |")
    lines.append("|---|---|---|---|---|")
    for item in result.coverage.items if result.coverage else []:
        locations = "；".join(item.expected_locations[:3])
        lines.append(
            f"| {item.field} | {'是' if item.required else '否'} | {item.status} | {locations} | {item.reason or ''} |"
        )
    lines.append("")

    lines.append("## 校验问题")
    lines.append("")
    if audit and audit.issues:
        lines.append("| 层级 | 严重度 | 代码 | 字段 | 信息 |")
        lines.append("|---|---|---|---|---|")
        for issue in audit.issues:
            lines.append(
                f"| {issue.level} | {issue.severity} | {issue.code} | {issue.field or ''} | {issue.message} |"
            )
    else:
        lines.append("无。")
    lines.append("")

    lines.append("## 表格")
    lines.append("")
    lines.append("| 表 | 页 | 标题 | 画像 | 方向 | 行×列 | 块 |")
    lines.append("|---|---|---|---|---|---|---|")
    for table in result.tables:
        lines.append(
            f"| {table.table_id} | {table.page_no} | {table.caption or ''} | {table.profile} | "
            f"{table.orientation} | {table.n_rows}×{table.n_cols} | {len(table.blocks)} |"
        )
    lines.append("")

    lines.append("## 记录")
    lines.append("")
    if result.records:
        lines.append("| 记录 | 牌号/级别 | 条件 | 属性数 |")
        lines.append("|---|---|---|---|")
        for record in result.records[:50]:
            lines.append(
                f"| {record.record_id} | {record.grade or record.grade_level or ''} | "
                f"{record.condition or ''} | {len(record.properties)} |"
            )
    else:
        lines.append("无记录（mock 抽取器可能未覆盖该表型）。")
    lines.append("")

    return "\n".join(lines)
