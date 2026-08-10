"""L5 安全渗透：Phase 6 评测工具（M22）。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def test_report_does_not_leak_absolute_paths(tmp_path):
    from qa.evaluation import evaluate_phase6

    out_dir = Path(__file__).resolve().parent.parent / "evaluation" / "reports" / "pytest_sec"
    try:
        rc = evaluate_phase6.main(
            ["--subset", "smoke", "--skip-ocr", "--output-dir", str(out_dir)]
        )
        assert rc == 0
        md = (out_dir / "phase6_report.md").read_text(encoding="utf-8")
        assert "/home/" not in md
        assert "/tmp/" not in md
        report = json.loads((out_dir / "phase6_metrics.json").read_text(encoding="utf-8"))
        for sample in report["samples"]:
            assert "/" not in sample["sample"]
    finally:
        import shutil

        shutil.rmtree(out_dir, ignore_errors=True)


async def test_output_escape_rejected(tmp_path):
    from qa.evaluation import evaluate_phase6

    rc = evaluate_phase6.main(
        ["--subset", "smoke", "--skip-ocr", "--output-dir", str(tmp_path)]
    )
    assert rc == 2


async def test_gt_loader_stays_inside_gt_dir():
    from qa.evaluation import evaluate_phase6

    fake = Path("..") / "evil.pdf"
    result = evaluate_phase6.load_gt(fake)
    assert result is None  # 不读取 GT_DIR 外文件


async def test_unknown_subset_rejected():
    import pytest

    from qa.evaluation import evaluate_phase6

    with pytest.raises(SystemExit) as exc:
        evaluate_phase6.main(["--subset", "unknown", "--skip-ocr"])
    assert exc.value.code == 2
