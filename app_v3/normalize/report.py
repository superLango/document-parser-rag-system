"""归一化报告输出（HTML/Markdown 可选；S1 先提供 dict 汇总）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def render_markdown(summary: dict[str, Any], title: str = "app_v3 S1 归一化报告") -> str:
    lines = [f"# {title}", ""]
    lines.append(f"- 记录总数：{summary.get('total', 0)}")
    lines.append(f"- 状态分布：{json.dumps(summary.get('status') or {}, ensure_ascii=False)}")
    lines.append(f"- 牌号解析率：{summary.get('grade_resolved_rate', 0)}")
    lines.append("")
    lines.append("## 类别分布")
    for category, count in sorted((summary.get("categories") or {}).items(), key=lambda item: -item[1]):
        lines.append(f"- {category}: {count}")
    lines.append("")
    lines.append("## 诊断码")
    for code, count in sorted((summary.get("diagnostics") or {}).items(), key=lambda item: -item[1]):
        lines.append(f"- {code}: {count}")
    return "\n".join(lines) + "\n"


def write_report(summary: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(summary), encoding="utf-8")
