"""Export Pydantic contracts as JSON Schemas.

Guided JSON decoding (Qwen, M2) and external consumers both need a frozen
machine-readable schema, not just Python classes.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import __version__
from .contracts import (
    SCHEMA_VERSION,
    ArtifactManifest,
    AuditReport,
    ClassificationItem,
    ClauseRecord,
    ColumnBinding,
    ColumnBindingResult,
    CoveragePlan,
    CoverageAudit,
    DocumentProfile,
    DocumentResult,
    ExtractionPlan,
    InspectionItem,
    ItemGroup,
    ItemInventory,
    ItemInventoryEntry,
    AlignmentResult,
    BusinessDictionary,
    BusinessDictionaryEntry,
    CanonicalMatch,
    NewTerm,
    NewTermStore,
    JobState,
    Recipe,
    RecipeSignature,
    Record,
    ReferenceGraph,
    TableClauseLink,
    TableGrid,
    TableLinkResult,
)
from .goldset import GoldDocument, GoldManifest

SCHEMA_MODELS = {
    "DocumentResult": DocumentResult,
    "DocumentProfile": DocumentProfile,
    "TableGrid": TableGrid,
    "Record": Record,
    "ClauseRecord": ClauseRecord,
    "InspectionItem": InspectionItem,
    "ClassificationItem": ClassificationItem,
    "CoveragePlan": CoveragePlan,
    "CoverageAudit": CoverageAudit,
    "TableClauseLink": TableClauseLink,
    "TableLinkResult": TableLinkResult,
    "AuditReport": AuditReport,
    "ReferenceGraph": ReferenceGraph,
    "ExtractionPlan": ExtractionPlan,
    "Recipe": Recipe,
    "RecipeSignature": RecipeSignature,
    "ColumnBinding": ColumnBinding,
    "ItemGroup": ItemGroup,
    "ItemInventory": ItemInventory,
    "ItemInventoryEntry": ItemInventoryEntry,
    "BusinessDictionary": BusinessDictionary,
    "BusinessDictionaryEntry": BusinessDictionaryEntry,
    "CanonicalMatch": CanonicalMatch,
    "NewTerm": NewTerm,
    "NewTermStore": NewTermStore,
    "AlignmentResult": AlignmentResult,
    "ColumnBindingResult": ColumnBindingResult,
    "ArtifactManifest": ArtifactManifest,
    "JobState": JobState,
    "GoldDocument": GoldDocument,
    "GoldManifest": GoldManifest,
}


def export_schemas(out_dir: str | Path) -> dict[str, str]:
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for name, model in SCHEMA_MODELS.items():
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["x-schema-version"] = SCHEMA_VERSION
        schema["x-producer-version"] = __version__
        file_name = f"{name}.schema.json"
        (target / file_name).write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        written[name] = file_name

    index = {
        "schema_version": SCHEMA_VERSION,
        "producer_version": __version__,
        "models": written,
    }
    (target / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return written
