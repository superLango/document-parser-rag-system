import asyncio
import json
import sys

from sqlalchemy import select

from services.agent.agents.review import (
    _compact_record,
    _sample_evidence,
    _sample_records,
    _sample_rows,
)
from services.agent.context.tokenizer import build_tokenizer
from services.agent.config import Settings
from services.orchestration.db import SessionLocal
from services.orchestration.models import Artifact
from services.orchestration.config import settings as orch_settings
from services.orchestration.workflow import get_store, set_store
from services.shared.storage import build_store

set_store(build_store(orch_settings.storage_config()))


async def load(run_id: str) -> dict:
    async with SessionLocal() as session:
        rows = (
            await session.execute(select(Artifact).where(Artifact.run_id == run_id))
        ).scalars().all()
        meta = {a.role: a.storage_key for a in rows}
    store = get_store()
    out = {}
    for role, key in meta.items():
        try:
            raw = await store.get_bytes(key)
        except Exception:
            continue
        try:
            out[role] = json.loads(raw)
        except ValueError:
            out[role] = raw
    return out


def main(run_id: str) -> None:
    async def run() -> None:
        data = await load(run_id)
        for role, value in sorted(data.items()):
            if isinstance(value, (dict, list)):
                print("%-24s json_chars=%d" % (role, len(json.dumps(value, ensure_ascii=False))))
            elif isinstance(value, bytes):
                print("%-24s bytes=%d" % (role, len(value)))
        records = data.get("records") or []
        if isinstance(records, dict):
            records = records.get("records") or []
        evidence = data.get("evidence") or []
        if isinstance(evidence, bytes):
            try:
                evidence = json.loads(evidence)
            except ValueError:
                evidence = []
        if isinstance(evidence, dict):
            evidence = evidence.get("evidence") or evidence.get("items") or []
        tables = data.get("tables.json") or data.get("tables") or []
        if isinstance(tables, dict):
            tables = tables.get("tables") or tables.get("items") or []
        print("records=%d evidence=%d tables=%d" % (len(records), len(evidence), len(tables)))
        sampled_records = _sample_records([r for r in records if isinstance(r, dict)])
        sampled_evidence = _sample_evidence([e for e in evidence if isinstance(e, dict)], sampled_records)
        compact = {
            "records": [_compact_record(item) for item in sampled_records],
            "evidence": sampled_evidence,
            "tables": [
                {
                    "table_id": item.get("table_id"),
                    "page_no": item.get("page_no"),
                    "header_paths": item.get("header_paths") or [],
                    "units": item.get("units") or [],
                    "sample_rows": _sample_rows(item.get("rows")),
                }
                for item in tables
                if isinstance(item, dict)
            ],
        }
        parts = {k: len(json.dumps(v, ensure_ascii=False, sort_keys=True)) for k, v in compact.items()}
        total_chars = len(json.dumps(compact, ensure_ascii=False, sort_keys=True))
        print("compact_chars:", parts, "total=%d" % total_chars)
        settings = Settings()
        tok = build_tokenizer(settings.tokenizer_mode, settings.endpoints()[0].base_url, settings.model)
        for key, value in compact.items():
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
            print("tokens %-9s = %d" % (key, await tok.count(text)))
        print("tokens total = %d" % (await tok.count(json.dumps(compact, ensure_ascii=False, sort_keys=True))))

    asyncio.run(run())


if __name__ == "__main__":
    main(sys.argv[1])
