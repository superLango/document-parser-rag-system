"""L4 边界异常：Phase 6 评测工具（M22）。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def test_empty_sample_dir_fails(tmp_path, monkeypatch):
    from qa.evaluation import evaluate_phase6

    monkeypatch.setattr(evaluate_phase6, "TEST_DOC", tmp_path)
    rc = evaluate_phase6.main(["--subset", "all", "--skip-ocr"])
    assert rc == 2


async def test_output_dir_escape_rejected(tmp_path):
    from qa.evaluation import evaluate_phase6

    rc = evaluate_phase6.main(
        ["--subset", "smoke", "--skip-ocr", "--output-dir", str(tmp_path)]
    )
    assert rc == 2


async def test_corrupt_sample_does_not_break(tmp_path):
    import json

    from qa.evaluation import evaluate_phase6

    corrupt = tmp_path / "bad.pdf"
    corrupt.write_bytes(b"%PDF-1.4 garbage")
    result = evaluate_phase6.evaluate_layout(corrupt, None, None)
    assert result["success"] is False
    assert result["elapsed"] >= 0


async def test_no_gt_sample_metrics_na():
    import json

    from qa.evaluation import evaluate_phase6

    metrics = {
        "sample": "x.pdf",
        "success": True,
        "elapsed": 1.0,
        "pages": 1,
        "blocks": 1,
        "layout_recall": None,
        "layout_precision": None,
        "title_block_hit_rate": None,
    }
    agg = evaluate_phase6.aggregate([metrics], [])
    assert agg["layout_recall"] is None
    assert agg["task_success_rate"] == 1.0


async def test_center_match_beyond_tolerance():
    from qa.evaluation.metrics import match_layout_blocks

    gt = [{"page": 1, "type": "text", "bbox": [0.0, 0.0, 0.1, 0.1]}]
    pred = [{"page": 1, "type": "text", "bbox": [0.8, 0.8, 0.9, 0.9]}]
    m = match_layout_blocks(gt, pred, match_mode="center", center_tolerance=0.05)
    assert m["tp"] == 0
