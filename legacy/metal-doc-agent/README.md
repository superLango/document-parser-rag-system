# Metal Document Agent

Local-first framework for extracting structured data from metal material standards.

This repository is the **framework skeleton** from the development plan. It runs
end-to-end on a laptop with **mock OCR + mock extraction**, using the existing
OCR-produced `.md` files. Real GLM-OCR / Qwen3.5-9B adapters plug into the same
contracts later.

## What is implemented

- Pydantic v2 contracts: Schema v0 (`DocumentResult`, `Record`, `ClauseRecord`, `InspectionItem`, `ClassificationItem`, `ReferenceGraph`, `ExtractionPlan`, `ArtifactManifest`, `JobState`).
- Page ingestion from `# Page N` markdown.
- HTML table parser: rowspan/colspan, header paths, units, footnotes, repeated header blocks.
- TableGrid v1: cross-page caption inheritance, continuation merge (`merged_pages`), multi-row header detection, transposed tables, footnotes, profile/orientation rules. Hard tables are tracked in `docs/hard-tables.md`.
- Deterministic normalization: `0.000 03`, `不大于`, `≤`, ranges, `余量`, `σb → Rm`, `σ0.2 → Rp0.2`, `δs → A`.
- Mock extractor for chemical/mechanical tables; every value gets an evidence pointer.
- L0 structure / L1 evidence locator+quote / L2 domain+unit+range checks / L3.5 coverage audit; `metal-doc validate --run` re-runs them on an existing run.
- JSON Schema export (`schemas/v0`), golden set manifest (20 docs), 20 draft annotations, field/record/inspection/clause evaluator, regression baseline.
- Model service clients (M1-S1): OpenAI-compatible, GLM-OCR image blocks, Qwen JSON/thinking control, PP-DocLayoutV3 layout HTTP; health check CLI.
- Qwen zero-shot extraction (M1-S4): Qwen column mapping + deterministic row assembly + normalization + cell evidence; rule fallback when the model mapping fails.
- Artifact contract and job API (M1-S6): SHA256 `artifacts.json` manifest + verifier, file-backed `JobStore` (`jobs/{job_id}/state.json`), idempotent FastAPI jobs, worker runner.
- Annotation and evaluation (M1-S7): 20 draft annotations (60 tables / 149 records / 157 inspection items / 87 clauses), evidence-locator verification, A/B diff, error taxonomy, per-profile/source/split reports, hard-table report, regression baseline.
- Full acceptance (M1-S8): `metal-doc accept` gate, 20-document run, repeatable demo, G1 decision memo.
- Items, coverage and clauses (M1.7): item inventory, outline graph, clause records, coverage plan, table-clause links, coverage audit.
- Business dictionary alignment (M1.8): three term sets (项目大类/检测项目/试验方法), category→item→method matching, new-term flow, HTTP adapters, G1.8 smoke. The pipeline now emits item inventory, business alignment and new-term artifacts for every run.
- CLI, FastAPI job API, worker entry point.
- Unit + integration tests, including a real Q-Du 302 run and goldset/eval tests.

## Business dictionary (M1.8)

The business system is represented by three term sets imported from
hansonDoc_RAG: **项目大类** (category), **检测项目** (item), **试验方法**
(method). `configs/business_dictionary.hanson.json` holds the offline snapshot
(39 / 283 / 645 entries). `configs/business_dictionary.json` stays as the small
unit-test fixture.

Every pipeline run (CLI, job API, worker) now performs the M1.6–M1.8 chain and
writes:

```text
column_bindings.json        # table column -> item group/property
item_inventory.json         # projects/families/facets/properties
item_inventory_aligned.json # + business codes, category, property matches
alignment.json              # AlignmentResult (categories/items/methods/new)
new_terms.json              # new category/item/method candidates
clauses.jsonl  links.json   # clauses + table-clause links
coverage_audit.json         # measure columns, mentions, orphan tables
```

Alignment uses `configs/business_dictionary.hanson.json` by default; override
with `BUSINESS_DICTIONARY_SNAPSHOT=/path/to/dictionary.json` and disable with
`METAL_DOC_ALIGNMENT=0`. Reviewed terms are merged from
`configs/business_dictionary.local.json` (override with
`BUSINESS_DICTIONARY_OVERRIDE`, empty string disables). A missing or broken
dictionary skips alignment and never fails extraction.

```powershell
python tools\import_hanson_terms.py
python tools\canonicalize_pilot.py --run runs\m1.5_qwen\gbt1220_2007
python tools\business_smoke.py --snapshot configs\business_dictionary.hanson.json --runs runs\m1.5_qwen --out eval\business\hanson
```

The single-document pilot writes `item_inventory_aligned.json`, `alignment.json`,
`new_terms.json` and `canonical_report.md` into the run directory (use `--out`
for another location, `--dictionary` to switch the snapshot).

## Quickstart

```powershell
cd f:\hanson\hanson_doc_parse\metal-doc-agent

# Inspect tables in a real standard
python -m metal_doc_agent.cli inspect "..\标准文件\Q-Du 302-2015.md"

# Run the full mock pipeline
python -m metal_doc_agent.cli run "..\标准文件\Q-Du 302-2015.md" --out runs\qdu302

# Try the multi-block chemistry table
python -m metal_doc_agent.cli run "..\标准文件\GBT 40303-2021\GBT 40303-2021   GH4169合金棒材通用技术条件.md" --out runs\gh4169

# Schema v0 and golden set
python -m metal_doc_agent.cli schema export --out schemas\v0

# Project a finished job onto a business schema template (product standard)
python -m metal_doc_agent.cli schema project --job data\jobs\<job_id> `
  --template configs\schema_templates\product_standard.json --out eval\schema\product_standard\result.json

python -m metal_doc_agent.cli gold validate --manifest goldset\v0\manifest.json
python -m metal_doc_agent.cli gold status --manifest goldset\v0\manifest.json
python -m metal_doc_agent.cli gold verify --manifest goldset\v0\manifest.json --runs runs\m1s7 --strict

# A/B annotation diff (record keys, values, comparator+unit, clause fields)
python -m metal_doc_agent.cli gold diff --a <A.json> --b <B.json> --out review.md --strict

# Evaluate 20 documents and compare with the frozen regression baseline
python -m metal_doc_agent.cli eval --gold goldset\v0 --runs runs\m1 --out eval\m1 `
  --baseline regression\v1.json --fail-on-regression

# Full acceptance gate and repeatable demo
python -m metal_doc_agent.cli accept --gold goldset\v0 --runs runs\m1 --out eval\acceptance
python tools\demo_m1.py --out runs\demo_m1

# Re-run L0-L2 on an existing run
python -m metal_doc_agent.cli validate --run runs\m1s5_qdu

# Verify artifact sizes and SHA256 against artifacts.json
python -m metal_doc_agent.cli artifacts verify --run runs\m1s6_qdu

# Start the API and consume one job with the worker
pip install -e ".[api]"
uvicorn metal_doc_agent.api:app --host 127.0.0.1 --port 8765
python apps\worker\main.py --job-id <job_id> --store data\jobs

# Score mock predictions against the 3-document mini golden set
python -m metal_doc_agent.cli run "..\标准文件\Q-Du 302-2015.md" --out runs\gold_v0\qdu302_2015 --template enterprise
python -m metal_doc_agent.cli run "..\标准文件\GBT 40303-2021\GBT 40303-2021   GH4169合金棒材通用技术条件.md" --out runs\gold_v0\gbt40303_2021 --template product_full
python -m metal_doc_agent.cli run "..\标准文件\GJB2057A-2018\89.GJB2057A-2018 航天用2219铝合金锻件规范.md" --out runs\gold_v0\gjb2057a_2018 --template gjb
python -m metal_doc_agent.cli eval --gold goldset\v0 --runs runs\gold_v0 --out runs\eval_v0
```

Output:

```text
runs/qdu302/
├─ artifacts.json        # SHA256 + size manifest (excludes itself)
├─ result.json           # document + tables + records + coverage + quality
├─ evidence.jsonl
├─ audit.md
├─ manifest.json
├─ pages.json
├─ outline.json
├─ coverage_plan.json
├─ column_bindings.json
├─ item_inventory.json
├─ item_inventory_aligned.json
├─ alignment.json
├─ new_terms.json
├─ clauses.jsonl
├─ links.json
├─ coverage_audit.json
├─ trace.json
└─ tablegrid/
   ├─ T1.json
   ├─ T2.json
   └─ ...
```

PDF OCR runs also write `pages/page-0001.png`; `.md` input reuses its existing pages. `records.json` / `audit.json` are not separate files — records live in `result.json` and the human-readable audit is `audit.md`.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The real-corpus test is skipped automatically if `..\标准文件\Q-Du 302-2015.md`
is not present.

## Real model integration

The framework defaults to mock backends:

```text
METAL_DOC_OCR=mock
METAL_DOC_EXTRACTOR=mock
```

Real adapters:

- `metal_doc_agent/ocr/glm.py`: implemented PDF → PP-DocLayoutV3 → block crop → GLM-OCR → page Markdown.
- `metal_doc_agent/extraction/qwen.py`: implemented zero-shot two-stage extraction (header mapping → row assembly). Strict guided JSON/schema decoding is deferred to M2.

Install the real OCR dependencies:

```powershell
pip install -e ".[models,pdf]"
```

Environment variables:

```text
# Remote model device (1.35)
GLM_OCR_BASE_URL=http://192.168.1.35:9977/v1
GLM_OCR_MODEL=GLM-OCR
QWEN_BASE_URL=http://192.168.1.35:9989/v1
QWEN_MODEL=Qwen3.5-9B
LAYOUT_SERVICE_URL=http://192.168.1.35:9978
OPENAI_API_KEY=local
```

The 1.35 host is the model device; it carries the layout/OCR stack for
hansonDoc_RAG. Services are not guaranteed to be running after a reboot, so
start/stop commands, call contracts and GPU budget are documented in
`../metal-standard-agent-plan/stages/09-模型服务与调用手册.md`.

`POST /v1/layout` is deployed on 1.35 at port 9978 (see
`infra/model_server/layout_api.py`). Model smoke scripts live in
`tools/model_smoke/`; the three services (GLM-OCR 9977, Qwen3.5-9B 9989,
layout 9978) passed real-call verification before the host move.

## Model service clients (M1-S1)

`metal_doc_agent/clients/` now contains:

- `OpenAICompatibleClient`: health, chat, JSON mode, retries, timeout;
- `GlmOcrClient`: image data URL, per-block prompts, 2048 edge resize;
- `QwenClient`: thinking disabled by default, JSON mode;
- `LayoutClient`: PP-DocLayoutV3 `/v1/layout` blocks.

Check all three services from the laptop:

```powershell
$env:GLM_OCR_BASE_URL="http://192.168.1.35:9977/v1"
$env:GLM_OCR_MODEL="GLM-OCR"
$env:QWEN_BASE_URL="http://192.168.1.35:9989/v1"
$env:QWEN_MODEL="Qwen3.5-9B"
$env:LAYOUT_SERVICE_URL="http://192.168.1.35:9978"
python -m metal_doc_agent.cli models check
```

Real client smoke (uses a rendered page image):

```powershell
python tools\model_smoke\client_smoke.py --image runs\glm_page.png
```

> M1-S1 only guarantees valid JSON, not schema-conformant field names. Strict
> guided JSON / schema enforcement belongs to M1-S4.

Real PDF OCR path (M1-S2) works with mock extraction:

```powershell
$env:METAL_DOC_OCR="glm"
$env:METAL_DOC_EXTRACTOR="mock"
$env:GLM_OCR_BASE_URL="http://192.168.1.35:9977/v1"
$env:LAYOUT_SERVICE_URL="http://192.168.1.35:9978"
python -m metal_doc_agent.cli run "..\标准文件\Q-Du 302-2015.pdf" --out runs\qdu_real --ocr glm --extractor mock
```

Qwen zero-shot extraction:

```powershell
$env:METAL_DOC_EXTRACTOR="qwen"
$env:QWEN_BASE_URL="http://192.168.1.35:9989/v1"
$env:QWEN_MODEL="Qwen3.5-9B"
python -m metal_doc_agent.cli run "..\标准文件\Q-Du 302-2015.pdf" --out runs\qdu_qwen --ocr glm --extractor qwen
```

## Job API (M1-S6)

```powershell
pip install -e ".[api]"   # fastapi, uvicorn, python-multipart
uvicorn metal_doc_agent.api:app --host 127.0.0.1 --port 8765
```

Upload a document and create a job (`.md` or `.pdf`, max 50 MB):

```powershell
curl -X POST http://127.0.0.1:8765/v1/jobs `
  -H "Idempotency-Key: qdu302-demo" `
  -F "file=@..\标准文件\Q-Du 302-2015.md" `
  -F "template=enterprise" -F "ocr=mock" -F "extractor=mock"
```

Endpoints:

```text
GET  /health
GET  /v1/recipes
GET  /v1/business-dictionary?type=&q=&limit=   # category/item/method snapshot
POST /v1/jobs                       # 201 new, 200 replay + X-Idempotent-Replay: true
GET  /v1/jobs?limit=
GET  /v1/jobs/{job_id}
GET  /v1/jobs/{job_id}/result
GET  /v1/jobs/{job_id}/evidence?limit=
GET  /v1/jobs/{job_id}/items         # aligned inventory (category/item codes)
GET  /v1/jobs/{job_id}/records       # extracted records (grade x condition x property)
GET  /v1/jobs/{job_id}/alignment     # category/item/method matches + new terms
GET  /v1/jobs/{job_id}/new-terms
GET  /v1/jobs/{job_id}/clauses?limit=
GET  /v1/jobs/{job_id}/links
GET  /v1/jobs/{job_id}/coverage-audit
GET  /v1/jobs/{job_id}/audit        # text/markdown
GET  /v1/jobs/{job_id}/trace
GET  /v1/jobs/{job_id}/artifacts
GET  /v1/jobs/{job_id}/artifacts/verify
POST /v1/jobs/{job_id}/retry        # failed/review only, 202
```

Jobs are persisted under `data/jobs/{job_id}/state.json` (override with
`METAL_DOC_DATA`); the run directory holds `artifacts.json` with SHA256 and size
for every required/optional artifact. `GET .../artifacts/verify` (or
`metal-doc artifacts verify --run`) reports missing files and hash mismatches.
Consume one queued job with:

```powershell
python apps\worker\main.py --job-id <job_id> --store data\jobs
```

The store is single-node/file-based. Multi-worker locking, cancellation and
object storage are M3 scope.

## Project layout

```text
metal_doc_agent/
├─ contracts.py          # Schema v0 Pydantic contracts
├─ goldset.py            # golden set models, loader, validation
├─ schema_export.py      # JSON Schema export
├─ eval/                 # field/record/inspection/clause metrics
├─ ingest.py             # .md ingestion + page splitting
├─ ocr/                  # mock + GLM-OCR adapter stub
├─ tablegrid/            # HTML table parser, normalization, profile rules
├─ extraction/           # mock + Qwen adapter stub
├─ validation/           # L0-L3.5 checks
├─ coverage/             # outline + coverage plan
├─ pipeline.py           # end-to-end orchestration + progress/trace
├─ artifacts.py          # artifact roles, SHA256 manifest, verifier
├─ jobs.py               # file-backed JobStore (states, idempotency)
├─ runner.py             # job runner shared by API/worker
├─ goldset_review.py     # A/B annotation diff + consistency gates
├─ goldset_verify.py     # evidence locator/quote verification
├─ acceptance.py         # M1-S8 full-corpus acceptance gate
├─ storage.py            # local artifact store
├─ cli.py                # metal-doc CLI
└─ api.py                # FastAPI job API

apps/worker/main.py      # --job-id/--store or ad-hoc --job/--out
apps/api/main.py         # uvicorn entry point

docs/                    # schemas.md (Schema v0), annotation.md (标注规范)
goldset/v0/              # manifest.json + docs/ (20 draft annotations) + hard_tables.json
schemas/v0/              # exported JSON Schemas
tools/                   # manifest / mini-goldset builders, PDF scanner, demo_m1.py
```

## Design rules

1. Models return **raw text**; code owns numbers, units, comparators and ranges.
2. Every extracted value must have an evidence pointer; missing values use status, not guesses.
3. Production runs registered recipes / deterministic workflows; Agent-first is for exploration.
4. The mock extractor is a baseline, not the final accuracy target.

## M1 status

- M1-S1–S8 complete; G1 decision is **GO**. All technical gates and the 20-annotation gate pass.
- Full runs: `runs/m1/` (mock) and `runs/m1_qwen_s8/` (real Qwen3.5-9B, final condition/coordinate fixes); both 20/20 result, 100% schema, 100% artifact verification.
- Real-Qwen metrics: record F1 0.88, field F1 0.82, value accuracy 0.93, evidence 1.00, coverage 0.85.
  Simple-table field F1 0.87, scanned 0.87, 30-page p95 214.3s.
  See `eval/m1_qwen.md`, `eval/acceptance_qwen/acceptance.md`, and `eval/g1-review.md`.
- Annotation status: 20/20 `verified`, based on `gold verify` (1595 evidence checks) plus an automated consistency audit with an owner override; strict human A/B double-blind review remains a recommended follow-up.
- Known corpus gap: only 6 digital-native PDFs (plan asked 8); 1 hybrid, 13 scanned.

## Next steps

- Improve chemical/mechanical header mapping, multi-block grade normalization and mechanical condition keys.
- Add table-level/document-level Qwen scheduling to bring 30-page p95 under 5 minutes.
- Complete strict human A/B double-blind review and record arbitration for the already-verified annotations.
- Re-run `metal-doc accept --runs runs/m1_qwen_s8 --strict` to reproduce the GO decision.
- Strict guided JSON / schema-constrained decoding for Qwen (M2).
- Add recipe registry + router + three queues.
- Add LangGraph state machine and checkpointing.
- Add review UI and batch API.
