"""L2 集成链路：Phase 6 评测工具（M22）。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def test_generator_produces_samples_and_gt():
    from qa.evaluation import generate_samples

    paths = generate_samples.generate_all(count=3)
    assert len(paths) >= 3
    for pdf in paths:
        assert pdf.exists()
        gt = pdf.with_suffix(".json")
        assert (Path(__file__).resolve().parent.parent / "evaluation" / "ground_truth" / gt.name).exists()


async def test_evaluate_smoke_cli(tmp_path):
    from qa.evaluation import evaluate_phase6

    out_dir = Path(__file__).resolve().parent.parent / "evaluation" / "reports" / "pytest_smoke"
    try:
        rc = evaluate_phase6.main(
            ["--subset", "smoke", "--skip-ocr", "--output-dir", str(out_dir)]
        )
        assert rc == 0
        report = json.loads((out_dir / "phase6_metrics.json").read_text(encoding="utf-8"))
        assert report["metrics"]["task_success_rate"] == 1.0
        assert "layout_recall" in report["metrics"]
        assert "gates" in report
        assert (out_dir / "phase6_report.md").exists()
    finally:
        import shutil

        shutil.rmtree(out_dir, ignore_errors=True)
