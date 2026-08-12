"""L1 单元测试：Phase 1-6 整体验收（M23）。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def test_config_completeness():
    from app.core.config import settings

    for key in (
        "PARSEKIT_LAYOUT_MODEL_DIR",
        "PARSEKIT_DPI",
        "PARSEKIT_HEADER_FOOTER_MODE",
        "PARSEKIT_PAGE_CONCURRENCY",
        "PARSEKIT_BLOCK_CONCURRENCY",
        "PARSEKIT_PARTIAL_ON_PAGE_FAILURE",
        "PARSEKIT_OCR_ENABLED",
        "PARSEKIT_OCR_FAILURE_POLICY",
        "PARSEKIT_INTERMEDIATE_RETENTION_DAYS",
        "GLMOCR_SERVER_URL",
        "GLMOCR_MODEL",
        "GLMOCR_MAX_TOKENS",
        "GLMOCR_RETRIES",
        "GLMOCR_MAX_EDGE",
    ):
        assert hasattr(settings, key), f"缺少配置 {key}"


async def test_artifact_contract():
    import pymupdf

    from app.services.parsekit import ParseOptions, parse_pdf

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "overall contract", fontsize=12)
    data = doc.tobytes()
    doc.close()
    result = parse_pdf(
        data, options=ParseOptions(dpi=100, ocr_enabled=False)
    )
    layout = result.layout
    assert layout["schema_version"] == "1.2"
    for key in ("pages", "page_failures", "ocr_failures", "ocr", "rebuild"):
        assert key in layout, f"layout.json 缺少 {key}"
    assert "document_tree" in layout["rebuild"]
    assert layout["pages"][0]["path"] == "pages/page-0001.png"


async def test_module_inventory():
    root = ROOT / "backend" / "app" / "services"
    expected = [
        "parsekit/__init__.py",
        "parsekit/render.py",
        "parsekit/header_footer.py",
        "parsekit/layout_ppdoc.py",
        "parsekit/reading_order.py",
        "parsekit/assemble.py",
        "parsekit/rebuild.py",
        "parsekit/ocr.py",
        "parsekit/pipeline.py",
        "ocr_backend/__init__.py",
        "ocr_backend/base.py",
        "ocr_backend/glmocr.py",
    ]
    for rel in expected:
        assert (root / rel).exists(), f"缺少模块 {rel}"


async def test_evaluation_gates_defined():
    from qa.evaluation.evaluate_phase6 import GATES

    for key in (
        "task_success_rate",
        "layout_recall",
        "layout_precision",
        "title_accuracy",
        "ocr_page_accuracy",
        "table_restore_rate",
    ):
        assert key in GATES, f"缺少门禁 {key}"


async def test_overall_sample_set():
    real = list((ROOT / "test_doc").glob("*.pdf"))
    generated = list((ROOT / "test_doc" / "generated").glob("*.pdf"))
    assert len(real) >= 6
    assert len(generated) >= 14
    assert len(real) + len(generated) >= 20
