"""DSH Agent 语义绑定通道（S0/S1 脚手架）。

用法：
    单表调试：
        python scripts/dev/dsh_bind.py --ocr <ocr.json> --tables T243 --outdir .tmp/t1
    全文档批跑（自动降级 + 断点续跑）：
        python scripts/dev/dsh_bind.py --ocr <ocr.json> --auto --batch-size 4 \
            --outdir .tmp/full --ideal "E:\\Desktop\\gbt-713-7-2023.json" --resume

调度策略（docs/dsh-agent-integration-plan.md §11.4）：
    1. 选表：n_rows≥3、n_cols≥2、非退化（单列长编号序列 / 近空表）；
    2. 难表（n_cols≥15 或 n_rows≥20）直接单表任务，避免长输出被截断；
    3. 其余按表型分组批跑（每批 ≤ batch-size）；
    4. 批失败或批内缺表 → 自动降级为逐表单跑；
    5. 每张表绑定成功即落盘 tables/<id>.json，--resume 时跳过已有结果；
    6. 全部完成后合并为 all-records.json，并按业务类别与理想 JSON 对照。

注意：本脚本用 SSH 直连远端 DSH；生产形态由 agent-service 的 DSH Adapter 承担。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import threading
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from services.agent.dsh.binding_apply import (  # noqa: E402
    apply_batch,
    apply_binding,
    summarize,
    validate_batch_binding,
)
from services.agent.dsh.categories import collect_category_enum  # noqa: E402
from services.agent.dsh.table_ir import (  # noqa: E402
    build_batch_ir,
    build_catalog,
    build_compact_catalog,
    build_table_ir,
    chunk_table,
    load_ocr,
    merge_chunk_bindings,
    plan_column_chunks,
)

RECIPES = ROOT / "services/recipe_registry/data/recipes"
DSH_PKG = ROOT / "services/agent/dsh"
KNOWLEDGE = DSH_PKG / "knowledge/AGENTS.extract.md"
SCHEMA_BATCH = DSH_PKG / "schemas/binding-batch.schema.json"
SCHEMA_ONE = DSH_PKG / "schemas/binding.schema.json"
INSTRUCTION_BATCH = DSH_PKG / "instruction_batch.txt"

DEFAULT_REMOTE = os.environ.get("HANSON_DSH_REMOTE", "grainuser@192.168.188.75")
DEFAULT_KEY = os.environ.get("HANSON_DSH_SSH_KEY", r"C:\Users\lango\.ssh\id_rsa")
# 不继承宿主的 DSH_PROFILE —— 脚本可能在 DSH 桌面会话内运行。
DEFAULT_PROFILE = os.environ.get("HANSON_DSH_PROFILE", "hanson")

PROFILE_GROUP = {
    "mechanical_properties": "mechanical",
    "chemical_composition": "chemical",
    "chemical_element_rows": "chemical",
    "heat_treatment": "heat_treatment",
    "dimension": "other",
    "inspection": "other",
    "classification": "other",
    "admin": "other",
    "unknown": "other",
}

# 难表阈值：超过就单表处理，避免长输出被截断
HARD_COLS = 15
HARD_ROWS = 20

SSH_COMMON_OPTS = [
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no",
    "-o", "ConnectTimeout=20",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=6",
    "-o", "TCPKeepAlive=yes",
]

_RETRYABLE = (
    "kex_exchange_identification",
    "Connection reset",
    "Connection closed",
    "Connection timed out",
    "Connection refused",
)


# ---------------------------------------------------------------------------
# SSH 传输（带重试）
# ---------------------------------------------------------------------------

def _is_retryable(stderr: str) -> bool:
    return any(token in (stderr or "") for token in _RETRYABLE)


# 短连接（scp 上传/下载）并发上限：避免并发任务同时建连把 sshd MaxStartups 打满
_CONN_SEM = threading.Semaphore(3)


def _retry(fn, *, attempts: int = 5, backoff: float = 2.5):
    last = None
    for attempt in range(1, attempts + 1):
        result = fn()
        if result is None or result.returncode == 0:
            return result
        stderr = result.stderr.decode("utf-8", "replace") if isinstance(result.stderr, bytes) else str(result.stderr or "")
        if not _is_retryable(stderr) or attempt == attempts:
            return result
        wait = backoff * attempt + random.uniform(0, 1.5)
        print(f"  [retry] 连接异常，{wait:.0f}s 后重试（{attempt}/{attempts - 1}）", flush=True)
        time.sleep(wait)
        last = result
    return last


def ssh(remote: str, key: str, command: str, *, timeout: int,
        stdin: bytes | None = None) -> subprocess.CompletedProcess:
    def once() -> subprocess.CompletedProcess:
        return subprocess.run(
            ["ssh", "-i", key, *SSH_COMMON_OPTS, remote, command],
            input=stdin, capture_output=True, timeout=timeout, check=False,
        )

    return _retry(once)


def scp_to(remote: str, key: str, local: Path, remote_path: str) -> None:
    def once() -> subprocess.CompletedProcess:
        with _CONN_SEM:
            return subprocess.run(
                ["scp", "-i", key, *SSH_COMMON_OPTS, "-r", str(local), f"{remote}:{remote_path}"],
                capture_output=True, check=False,
            )

    result = _retry(once)
    if result is not None and result.returncode != 0:
        raise RuntimeError(f"scp upload failed: {result.stderr.decode('utf-8', 'replace')[:200]}")


def scp_from_dir(remote: str, key: str, remote_dir: str, local_dir: Path) -> bool:
    for attempt in range(1, 5):
        local_dir.parent.mkdir(parents=True, exist_ok=True)
        if local_dir.exists():
            shutil.rmtree(local_dir, ignore_errors=True)
        with _CONN_SEM:
            result = subprocess.run(
                ["scp", "-i", key, *SSH_COMMON_OPTS, "-r", f"{remote}:{remote_dir}", str(local_dir)],
                capture_output=True, check=False,
            )
        if result.returncode == 0:
            return True
        stderr = result.stderr.decode("utf-8", "replace")
        if "No such file or directory" in stderr and attempt >= 2:
            print(f"  [scp] 远端无目录：{remote_dir}", flush=True)
            return False
        print(f"  [scp] 第 {attempt} 次失败：{stderr.strip().splitlines()[-1][:120] if stderr.strip() else ''}", flush=True)
        time.sleep(2 * attempt)
    return False


def _complete_brackets(raw: str) -> str:
    """按括号栈补全被截断的 JSON（忽略字符串内的括号），用于抢救缺闭合符的文件。"""
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in raw:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            stack.append(char)
        elif char == "]" and stack and stack[-1] == "[":
            stack.pop()
        elif char == "}" and stack and stack[-1] == "{":
            stack.pop()
    suffix = ""
    while stack:
        suffix += "]" if stack.pop() == "[" else "}"
    return raw + suffix


def _load_json_lenient(path: Path) -> Any:
    """尽力解析 JSON：直接解析 → 去 Markdown 围栏 → 截取第一个完整对象。"""
    raw = path.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        return None
    for candidate in (raw, raw.replace("```json", "").replace("```", "").strip()):
        try:
            return json.loads(candidate)
        except Exception:  # noqa: BLE001
            pass
        for opening in ("{", "["):
            start = candidate.find(opening)
            if start < 0:
                continue
            try:
                value, _ = json.JSONDecoder().raw_decode(candidate[start:])
                return value
            except Exception:  # noqa: BLE001
                continue
    return None


def _load_json_lenient_text(raw: str) -> Any:
    raw = (raw or "").strip()
    if not raw:
        return None
    for candidate in (raw, raw.replace("```json", "").replace("```", "").strip()):
        try:
            return json.loads(candidate)
        except Exception:  # noqa: BLE001
            pass
        for opening in ("{", "["):
            start = candidate.find(opening)
            if start < 0:
                continue
            try:
                value, _ = json.JSONDecoder().raw_decode(candidate[start:])
                return value
            except Exception:  # noqa: BLE001
                continue
    return None


def _salvage_tables(raw: str) -> list[dict[str, Any]]:
    """从被截断的 binding.json 文本里抢救**完整**的表对象（丢弃不完整尾部）。"""
    marker = raw.find('"tables"')
    if marker < 0:
        return []
    start = raw.find("[", marker)
    if start < 0:
        return []
    tables: list[dict[str, Any]] = []
    depth = 0
    in_string = False
    escaped = False
    object_start = -1
    for index in range(start, len(raw)):
        char = raw[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth <= 0:
                break
        elif char == "{":
            if depth == 1:
                object_start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 1 and object_start >= 0:
                try:
                    tables.append(json.loads(raw[object_start : index + 1]))
                except Exception:  # noqa: BLE001
                    pass
                object_start = -1
    return tables


def collect_bindings(out_dir: Path) -> list[dict[str, Any]]:
    """优先取 binding.json（容忍截断/围栏）；否则从逐表文件合并。"""
    merged: list[dict[str, Any]] = []
    batch_file = out_dir / "binding.json"
    if batch_file.exists():
        raw_text = batch_file.read_text(encoding="utf-8", errors="replace")
        payload = _load_json_lenient(batch_file)
        if isinstance(payload, dict) and isinstance(payload.get("tables"), list):
            return payload["tables"]
        if isinstance(payload, dict) and payload.get("table_id"):
            return [payload]
        repaired = _load_json_lenient_text(_complete_brackets(raw_text))
        if isinstance(repaired, dict) and isinstance(repaired.get("tables"), list):
            print(f"  [merge] binding.json 缺闭合符，已自动补全并解析（{len(repaired['tables'])} 张）", flush=True)
            return repaired["tables"]
        salvaged = _salvage_tables(raw_text)
        looks_complete = raw_text.rstrip().endswith(("}", "]"))
        if salvaged:
            reason = "JSON 语法错误" if looks_complete else "被截断"
            print(f"  [merge] binding.json {reason}，抢救出 {len(salvaged)} 张完整表", flush=True)
            return salvaged
        reason = "JSON 语法错误" if looks_complete else "被截断"
        print(f"  [merge] binding.json {reason}且无可抢救表，回退逐表文件", flush=True)
    broken: list[str] = []
    for path in sorted(out_dir.glob("*.json")):
        if path.name.startswith("binding"):
            continue
        payload = _load_json_lenient(path)
        if isinstance(payload, dict) and isinstance(payload.get("tables"), list):
            merged.extend(payload["tables"])
        elif isinstance(payload, dict) and payload.get("table_id"):
            merged.append(payload)
        else:
            broken.append(path.name)
    if broken:
        print(f"  [merge] 跳过 {len(broken)} 个非法/不完整 JSON：{broken[:5]}", flush=True)
    return merged


def parse_events(ndjson: str) -> dict[str, Any]:
    usage = {"inputTokens": 0, "outputTokens": 0, "cacheReadTokens": 0}
    session_id = ""
    final_text = ""
    count = 0
    for line in ndjson.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        count += 1
        kind = event.get("type")
        if kind == "session":
            session_id = event.get("sessionId") or session_id
        elif kind == "status" and event.get("phase") == "step_end":
            for name in usage:
                usage[name] += int((event.get("usage") or {}).get(name) or 0)
        elif kind == "final":
            final_text = event.get("text") or final_text
    return {"session_id": session_id, "usage": usage, "final_text": final_text, "event_count": count}


# ---------------------------------------------------------------------------
# 工作区
# ---------------------------------------------------------------------------

def _write_workspace(ws: Path, *, tables_payload: dict[str, Any], catalog: dict[str, Any]) -> None:
    (ws / "inputs").mkdir(parents=True, exist_ok=True)
    (ws / "out").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(KNOWLEDGE, ws / "AGENTS.md")
    shutil.copyfile(SCHEMA_BATCH, ws / "out" / SCHEMA_BATCH.name)
    shutil.copyfile(SCHEMA_ONE, ws / "out" / SCHEMA_ONE.name)
    shutil.copyfile(INSTRUCTION_BATCH, ws / "inputs/instruction.txt")
    (ws / "inputs/tables.json").write_text(
        json.dumps(tables_payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (ws / "inputs/catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )


def run_task(
    args,
    ws: Path,
    remote_ws: str,
    label: str,
    tables_payload: dict[str, Any],
    catalog: dict[str, Any],
) -> dict[str, Any]:
    """物化工作区 → 远端 DSH → 回传 out/ → 解析绑定。"""
    _write_workspace(ws, tables_payload=tables_payload, catalog=catalog)
    started = time.time()
    staging = f"{remote_ws}.staging"
    ssh(args.remote, args.key,
        f"rm -rf {remote_ws} {staging} && mkdir -p {staging}", timeout=120)
    scp_to(args.remote, args.key, ws, staging)
    ssh(args.remote, args.key,
        f"mv {staging}/ws {remote_ws} && rmdir {staging} 2>/dev/null || true", timeout=120)
    command = (
        f"cd {remote_ws} && LOCAL_LLM_API_KEY=sk-local timeout {args.timeout} "
        f"/home/grainuser/.npm-global/bin/dsh --profile {args.profile} "
        f"--permission-mode workspace-write --approval-policy never --json -"
    )
    result = ssh(args.remote, args.key, command, timeout=args.timeout + 180,
                 stdin=INSTRUCTION_BATCH.read_bytes())
    elapsed = round(time.time() - started, 1)
    parsed = parse_events(result.stdout.decode("utf-8", "replace"))
    ws.parent.joinpath(f"{label}.events.ndjson").write_text(
        result.stdout.decode("utf-8", "replace"), encoding="utf-8"
    )
    ws.parent.joinpath(f"{label}.stderr.log").write_text(
        result.stderr.decode("utf-8", "replace"), encoding="utf-8"
    )
    got = scp_from_dir(args.remote, args.key, f"{remote_ws}/out", ws / "out")
    bindings = collect_bindings(ws / "out") if got else []
    return {
        "run_ok": result.returncode == 0,
        "elapsed_sec": elapsed,
        "bindings": bindings,
        "usage": parsed["usage"],
        "events": parsed["event_count"],
        "final_text": parsed["final_text"][:200],
    }


# ---------------------------------------------------------------------------
# 表选择
# ---------------------------------------------------------------------------

def _is_degenerate(table: dict[str, Any]) -> bool:
    rows = table.get("rows") or []
    n_cols = int(table.get("n_cols") or 0)
    if n_cols <= 1 and len(rows) >= 50:
        return True
    if len(rows) <= 2:
        return True
    filled = 0
    for row in rows[:20]:
        for cell in row:
            if str(cell or "").strip():
                filled += 1
    return filled <= 6


def needs_single(table: dict[str, Any]) -> bool:
    return int(table.get("n_cols") or 0) >= HARD_COLS or int(table.get("n_rows") or 0) >= HARD_ROWS


def select_tables(ocr: dict[str, Any], *, min_rows: int = 3, min_cols: int = 2,
                  max_tables: int = 0) -> list[dict[str, Any]]:
    selected = [
        table
        for table in ocr.get("tables") or []
        if int(table.get("n_rows") or 0) >= min_rows
        and int(table.get("n_cols") or 0) >= min_cols
        and not _is_degenerate(table)
    ]
    return selected[:max_tables] if max_tables else selected


def group_tables(tables: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for table in tables:
        buckets.setdefault(PROFILE_GROUP.get(str(table.get("profile")), "other"), []).append(table)
    return [(group, items) for group, items in buckets.items() if items]


# ---------------------------------------------------------------------------
# 结果落盘 / 对照
# ---------------------------------------------------------------------------

def save_table_result(out_root: Path, binding, records: list[dict[str, Any]]) -> Path:
    path = out_root / "tables" / f"{binding.table_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"table_id": binding.table_id, "binding": binding.model_dump(), "records": records},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_done_tables(out_root: Path) -> set[str]:
    done = set()
    tables_dir = out_root / "tables"
    if tables_dir.is_dir():
        done = {p.stem for p in tables_dir.glob("*.json")}
    return done


CHEMICAL = {"C", "Si", "Mn", "P", "S", "Cr", "Ni", "Mo", "Cu", "N", "Ti", "Nb", "V", "Al", "W", "B",
            "Ce", "O", "H", "CEV", "Pcm", "Sn", "As", "Pb", "Sb", "Bi", "Ca", "Mg", "Zn", "Fe", "Zr", "Ta"}
HARDNESS = ("HB", "HBW", "HRB", "HRC", "HV")


def classify(measure: str, conditions: dict[str, str]) -> str:
    """把 measure 映射到业务大类，用于与理想 JSON 对照。"""
    name = measure or ""
    if name in CHEMICAL or (len(name) <= 3 and name[:1].isupper() and name.isalpha()):
        return "化学成分"
    if "硬度" in name or any(name.startswith(token) for token in HARDNESS):
        return "硬度试验"
    if "冲击" in name or name.startswith(("KV", "KU")):
        return "冲击试验"
    if "弯曲" in name:
        return "弯曲试验"
    if "蠕变" in name:
        return "蠕变试验"
    if "持久" in name:
        return "持久试验"
    if any(token in name for token in ("晶粒", "铁素体", "夹杂")):
        return "高倍"
    if any(token in name for token in ("保温", "冷却", "升温", "降温", "装炉", "出炉", "介质")):
        return "热处理制度"
    if any(key in name for key in ("Rm", "Rp", "Re", "强度", "伸长", "收缩", "模量", "延伸")):
        temp = str((conditions or {}).get("试验温度") or "")
        return "室温拉伸" if ("室温" in temp or not temp) else "高温拉伸"
    return "其他"


def ideal_counts(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_category: dict[str, int] = {}
    by_item: dict[str, int] = {}
    for category in payload.get("categories") or []:
        feature = str(category.get("feature") or "")
        records = category.get("records") or []
        by_category[feature] = by_category.get(feature, 0) + len(records)
        for record in records:
            item = str(record.get("项目名称") or "")
            if item:
                by_item[item] = by_item.get(item, 0) + 1
    return {"by_category": by_category, "by_item": by_item,
            "total": sum(by_category.values())}


def compare(records_by_table: dict[str, list[dict[str, Any]]], ideal: dict[str, Any]) -> dict[str, Any]:
    agent_by_category: dict[str, int] = {}
    agent_by_item: dict[str, int] = {}
    total = 0
    for records in records_by_table.values():
        for record in records:
            total += 1
            category = classify(record.get("measure") or "", record.get("conditions") or {})
            agent_by_category[category] = agent_by_category.get(category, 0) + 1
            item = record.get("measure") or ""
            agent_by_item[item] = agent_by_item.get(item, 0) + 1
    categories = []
    for name, ideal_value in sorted(ideal["by_category"].items(), key=lambda kv: -kv[1]):
        agent_value = agent_by_category.get(name, 0)
        categories.append({
            "category": name,
            "ideal": ideal_value,
            "agent": agent_value,
            "recall": round(agent_value / ideal_value, 3) if ideal_value else None,
        })
    return {
        "total": {"ideal": ideal["total"], "agent": total},
        "categories": categories,
        "agent_by_category": agent_by_category,
        "agent_by_item": agent_by_item,
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def process_composite_table(args, out_root: Path, table: dict[str, Any], done: set[str], *, category_enum: list[str] | None = None) -> list[dict[str, Any]]:
    """P0：复合表按列组分块绑定，再合并回父表。

    动机：复合表（拉伸/冲击/硬度并列）整表绑定会让 Agent 在"多列同名度量"上做取舍，
    要么重复要么欠抽。按语义列组拆分后每块列少、语义单一。
    """
    parent_id = str(table.get("table_id"))
    chunks = plan_column_chunks(table)
    if len(chunks) < 2:
        return []

    profiles = sorted({str(table.get("profile") or "unknown"), "unknown"})
    catalog = build_compact_catalog(RECIPES, profiles=profiles)
    chunk_tables: list[dict[str, Any]] = []
    for index, group in enumerate(chunks, start=1):
        sub = chunk_table(table, group)
        sub["table_id"] = f"{parent_id}#g{index}"
        sub["group_name"] = group["name"]
        chunk_tables.append(sub)

    results: list[dict[str, Any]] = []
    batches = [chunk_tables[i : i + 4] for i in range(0, len(chunk_tables), 4)]
    collected: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for batch_index, batch in enumerate(batches, start=1):
        label = f"chunk-{parent_id}-{batch_index}"
        payload = build_batch_ir(batch, category_enum=category_enum)
        for item, sub in zip(payload["tables"], batch):
            item["chunk"] = {"parent_table_id": parent_id, "group": sub.get("group_name")}
        ws = out_root / "work" / label / "ws"
        print(f"\n=== {label}: {[t['table_id'] for t in batch]} catalog={len(catalog['measures'])}度量 ===", flush=True)
        meta = run_task(args, ws, f"{args.remote_base}/{label}", label, payload, catalog)
        print(f"  [run] {meta['elapsed_sec']}s bindings={len(meta['bindings'])}", flush=True)
        if not meta["bindings"]:
            continue
        by_id = {str(b.get("table_id")): b for b in meta["bindings"]}
        for sub in batch:
            binding = by_id.get(str(sub.get("table_id")))
            if binding is None:
                continue
            collected[str(sub.get("table_id"))] = (sub, binding)

    if not collected:
        print(f"  [fail] {parent_id}: 分块绑定全部失败", flush=True)
        return []

    merged = merge_chunk_bindings(
        parent_id,
        [(sub, binding) for sub, binding in collected.values()],
    )
    try:
        binding_model = validate_chunk_merged(merged)
    except Exception as exc:  # noqa: BLE001
        print(f"  [fail] {parent_id}: 合并 binding 校验失败 {type(exc).__name__}: {exc}", flush=True)
        return []

    allowed = set(catalog["conditions"])
    records = apply_binding(table, binding_model, allowed_conditions=allowed)
    summary = summarize(records, binding_model)
    save_table_result(out_root, binding_model, records)
    print(f"  [merged] {parent_id}: 分块 {len(collected)}/{len(chunk_tables)} 组 → "
          f"records={len(records)} conf={binding_model.confidence} measures={summary['measures']} "
          f"unresolved={len(binding_model.unresolved)}", flush=True)
    results.append({"table_id": parent_id, "records": len(records), "summary": summary})
    return results


def validate_chunk_merged(payload: dict[str, Any]):
    from services.agent.dsh.binding_apply import TableBinding

    return TableBinding.model_validate(payload)


def process_table_group(args, out_root: Path, label: str, tables: list[dict[str, Any]],
                        done: set[str], *, category_enum: list[str] | None = None) -> list[dict[str, Any]]:
    """处理一批或一张表；返回新增的成功结果。"""
    pending = [t for t in tables if str(t.get("table_id")) not in done]
    if not pending:
        return []
    ids = [str(t.get("table_id")) for t in pending]
    profiles = sorted({str(t.get("profile") or "unknown") for t in pending} | {"unknown"})
    catalog = build_compact_catalog(RECIPES, profiles=profiles)
    payload = build_batch_ir(pending, category_enum=category_enum)
    ws = out_root / "work" / label / "ws"

    print(f"\n=== {label}: {ids} catalog={len(catalog['measures'])}度量 ===", flush=True)
    meta = run_task(args, ws, f"{args.remote_base}/{label}", label, payload, catalog)
    print(f"  [run] {meta['elapsed_sec']}s ok={meta['run_ok']} bindings={len(meta['bindings'])} "
          f"usage={meta['usage']}", flush=True)
    if not meta["bindings"]:
        print(f"  [fail] 无绑定返回；{(meta.get('final_text') or '')[:160]}", flush=True)
        return []

    try:
        bindings = validate_batch_binding({"tables": meta["bindings"]})
    except Exception as exc:  # noqa: BLE001
        print(f"  [fail] 绑定校验失败 {type(exc).__name__}: {exc}", flush=True)
        return []

    table_map = {str(t.get("table_id")): t for t in pending}
    allowed = set(catalog["conditions"])
    per_table = apply_batch(table_map, bindings, allowed_conditions=allowed)
    results = []
    for binding in bindings:
        records = per_table.get(binding.table_id) or []
        summary = summarize(records, binding)
        save_table_result(out_root, binding, records)
        print(f"  {binding.table_id:<6} records={len(records):>4} conf={binding.confidence} "
              f"measures={summary['measures']} unresolved={len(binding.unresolved)}", flush=True)
        results.append({"table_id": binding.table_id, "records": len(records), "summary": summary})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr", required=True)
    parser.add_argument("--tables", default="")
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--min-rows", type=int, default=3)
    parser.add_argument("--min-cols", type=int, default=2)
    parser.add_argument("--max-tables", type=int, default=0)
    parser.add_argument("--outdir", default=".tmp/bind")
    parser.add_argument("--remote", default=DEFAULT_REMOTE)
    parser.add_argument("--key", default=DEFAULT_KEY)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--remote-base", default="/tmp/hanson-bind")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--resume", action="store_true", help="跳过 outdir/tables 下已有结果的表")
    parser.add_argument("--no-fallback-single", action="store_true", help="批失败时不逐张重试")
    parser.add_argument("--ideal", default="", help="理想 JSON 路径，用于产出对照报告")
    parser.add_argument("--no-chunk", action="store_true", help="关闭复合表按列组分块（P0）")
    parser.add_argument("--concurrency", type=int, default=1, help="并发任务数（不超过服务端 max-num-seqs）")
    parser.add_argument("--skip-profiles", default="", help="跳过的表类型（逗号分隔，如 dimension,admin,inspection）")
    parser.add_argument("--skip-run", action="store_true")
    args = parser.parse_args()

    ocr = load_ocr(args.ocr)
    full_catalog = build_catalog(RECIPES)
    out_root = (ROOT / args.outdir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    done = load_done_tables(out_root) if args.resume else set()
    if done:
        print(f"[resume] 已完成 {len(done)} 张表，跳过", flush=True)

    all_tables = {str(t.get("table_id")): t for t in ocr.get("tables") or []}
    if args.tables:
        selected = [all_tables[t] for t in (x.strip() for x in args.tables.split(",")) if t in all_tables]
    else:
        selected = select_tables(ocr, min_rows=args.min_rows, min_cols=args.min_cols,
                                 max_tables=args.max_tables)
    skip_profiles = {p.strip() for p in args.skip_profiles.split(",") if p.strip()}
    if skip_profiles:
        before = len(selected)
        selected = [t for t in selected if str(t.get("profile") or "") not in skip_profiles]
        print(f"[filter] 跳过非数据表类型 {sorted(skip_profiles)}：{before} → {len(selected)} 张", flush=True)
    print(f"[catalog] 全量度量={len(full_catalog['measures'])}；候选表 {len(selected)} 张", flush=True)
    category_enum = collect_category_enum(ocr)
    print(f"[category_enum] {category_enum}", flush=True)

    # P0：复合表按列组分块（≥2 个度量列组才分块）
    composite: list[dict[str, Any]] = []
    plain: list[dict[str, Any]] = []
    for table in selected:
        if not args.no_chunk and len(plan_column_chunks(table)) >= 2:
            composite.append(table)
        else:
            plain.append(table)
    if composite:
        print(f"[P0] 复合表 {len(composite)} 张将按列组分块：{[t.get('table_id') for t in composite]}", flush=True)

    results: list[dict[str, Any]] = []
    if not args.skip_run:
        # 任务清单：复合表（内部按列组分块）与普通表批次一起进并发池
        task_calls: list[tuple[str, Any]] = []
        for table in composite:
            tid = str(table.get("table_id"))
            task_calls.append((
                f"composite-{tid}",
                lambda t=table: process_composite_table(args, out_root, t, set(),
                                                         category_enum=category_enum),
            ))

        hard = [t for t in plain if needs_single(t)]
        easy = [t for t in plain if not needs_single(t)]
        tasks: list[tuple[str, list[dict[str, Any]]]] = []
        for index, table in enumerate(hard, start=1):
            tasks.append((f"single{index:03d}", [table]))
        batch_index = 0
        for _group, items in group_tables(easy):
            for start in range(0, len(items), args.batch_size):
                batch_index += 1
                tasks.append((f"batch{batch_index:03d}", items[start : start + args.batch_size]))
        for label, tables in tasks:
            task_calls.append((
                label,
                lambda l=label, ts=tables: process_table_group(args, out_root, l, ts, set(),
                                                               category_enum=category_enum),
            ))
        print(f"[plan] 复合表 {len(composite)} 张 + 难表 {len(hard)} 张 + 普通表批次 {batch_index} 个，"
              f"共 {len(task_calls)} 个任务，并发 {args.concurrency}", flush=True)

        started_at = time.time()
        if args.concurrency > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                futures = {pool.submit(fn): label for label, fn in task_calls}
                for future in as_completed(futures):
                    label = futures[future]
                    try:
                        got = future.result()
                    except Exception as exc:  # noqa: BLE001
                        print(f"  [fail] {label}: {type(exc).__name__}: {exc}", flush=True)
                        continue
                    results.extend(got)
                    for item in got:
                        done.add(item["table_id"])
        else:
            for label, fn in task_calls:
                got = fn()
                results.extend(got)
                for item in got:
                    done.add(item["table_id"])
        print(f"[timing] 绑定阶段耗时 {round(time.time() - started_at, 1)}s（并发 {args.concurrency}）",
              flush=True)

    # 自动降级：批任务后仍缺表 → 逐张单跑
    if args.auto and not args.no_fallback_single and not args.skip_run:
        missing = [t for t in selected if str(t.get("table_id")) not in done]
        if missing:
            print(f"\n[fallback] {len(missing)} 张表未成功，逐张单跑：{[t.get('table_id') for t in missing]}",
                  flush=True)
            for index, table in enumerate(missing, start=1):
                got = process_table_group(args, out_root, f"retry{index:03d}", [table], done)
                results.extend(got)
                for item in got:
                    done.add(item["table_id"])

    # 汇总
    records_by_table: dict[str, list[dict[str, Any]]] = {}
    for path in sorted((out_root / "tables").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        records_by_table[payload["table_id"]] = payload.get("records") or []
    (out_root / "all-records.json").write_text(
        json.dumps(records_by_table, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    report: dict[str, Any] = {
        "tables_requested": len(selected),
        "tables_bound": len(records_by_table),
        "records_total": sum(len(v) for v in records_by_table.values()),
        "per_table": {tid: len(recs) for tid, recs in records_by_table.items()},
        "runs": results,
    }
    if args.ideal:
        ideal = ideal_counts(Path(args.ideal))
        report["comparison"] = compare(records_by_table, ideal)

    (out_root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print("\n" + "=" * 70)
    print(f"[汇总] 请求 {report['tables_requested']} 张，成功 {report['tables_bound']} 张，"
          f"记录 {report['records_total']} 条")
    if args.ideal:
        comparison = report["comparison"]
        print(f"[对照] 理想总计 {comparison['total']['ideal']} 条，本通道 {comparison['total']['agent']} 条")
        print(f"{'业务大类':<12}{'理想':>8}{'本通道':>8}{'召回率':>8}")
        for row in comparison["categories"]:
            print(f"{row['category']:<12}{row['ideal']:>8}{row['agent']:>8}"
                  f"{(row['recall'] if row['recall'] is not None else 0):>8.2f}")
    print(f"[report] {out_root / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
