"""4 份文档对照 v3：稳定匹配口径（括号内容剥离 + 同义词归一 + 牌号容错）。"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
_SPACE = re.compile(r"\s+")

SYNONYMS = [
    ("规定非比例伸长应力", "规定塑性延伸强度"),
    ("规定非比例延伸强度", "规定塑性延伸强度"),
    ("规定塑性延伸强度", "规定塑性延伸强度"),
    ("非比例延伸强度", "规定塑性延伸强度"),
    ("断后伸长率", "断后伸长率"),
    ("伸长率", "断后伸长率"),
    ("断面收缩率", "断面收缩率"),
    ("冲击吸收功", "冲击吸收功"),
    ("布氏硬度", "布氏硬度"),
    ("洛氏硬度", "洛氏硬度"),
    ("维氏硬度", "维氏硬度"),
    ("持久试验强度", "持久试验强度"),
    ("持久强度", "持久试验强度"),
    ("蠕变应变强度", "蠕变应变强度"),
    ("抗拉强度", "抗拉强度"),
    ("屈服强度", "屈服强度"),
]


def norm(text: str) -> str:
    return _SPACE.sub("", str(text or "")).translate(str.maketrans(
        {"≥": ">=", "≤": "<=", "～": "~", "－": "-", "—": "-", "–": "-", "％": "%",
         "（": "(", "）": ")", "，": ",", "。": "", "：": ":"})).lower()


def norm_grade(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", norm(text))


def item_key(text: str) -> str:
    value = norm(text)
    # 硬度代号在括号内外视为同一项目：洛氏硬度(HRB) 与 洛氏硬度 HRB
    value = re.sub(r"(硬度)\(([a-z]{2,4})\)", r"\1\2", value)
    value = re.sub(r"\([^)]*\)", "", value)
    value = value.replace("¬", "")
    for old, new in SYNONYMS:
        if old in value:
            value = value.replace(old, new) if old != new else value
    if "蠕变应变强度" in value:
        value = value[: value.index("蠕变应变强度") + len("蠕变应变强度")]
    return value


def norm_temp(text: str) -> str:
    raw = re.sub(r"(℃|°c|度|°)$", "", norm(text))
    return "" if raw in {"室温", "常温", "room"} else raw


def numbers(text: str) -> tuple[str, ...]:
    raw = norm(text)
    return tuple(v.rstrip("0").rstrip(".") if "." in v else v for v in re.findall(r"\d+(?:\.\d+)?", raw))


def grade_match(gold: str, ours: str) -> bool:
    if not gold or not ours:
        return True
    if gold == ours:
        return True
    return gold in ours or ours in gold


def field_ok(gold: str, ours: str) -> bool:
    g, o = norm(gold), norm(ours)
    if not g:
        return True
    if not o:
        return False
    if g == o or g in o or o in g:
        return True
    return bool(set(numbers(g)) & set(numbers(o)))


def load_gold(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[dict] = []
    for category in data.get("categories") or []:
        feature = str(category.get("feature"))
        for raw in category.get("records") or []:
            if feature == "标准信息":
                out.append({"category": feature, "item": "", "grade": "", "temp": "",
                            "value": numbers(raw.get("标准名称")), "method": "", "sampling": "",
                            "position": "", "state": ""})
            elif feature == "热处理制度":
                out.append({"category": feature,
                            "item": f"{raw.get('工序名称') or ''}/{raw.get('工艺名称') or ''}".strip("/"),
                            "grade": norm_grade(raw.get("材料牌号")), "temp": "",
                            "value": numbers(raw.get("保温温度")), "method": "", "sampling": "",
                            "position": "", "state": ""})
            else:
                out.append({"category": feature,
                            "item": str(raw.get("项目名称") or ""),
                            "grade": norm_grade(raw.get("材料牌号")),
                            "temp": norm_temp(raw.get("试验温度")),
                            "value": numbers(raw.get("标准要求")),
                            "method": str(raw.get("试验方法") or ""),
                            "sampling": str(raw.get("取样数量") or ""),
                            "position": str(raw.get("位置") or ""),
                            "state": str(raw.get("试样状态") or "")})
    return out


def load_ours(path: Path) -> list[dict]:
    report = json.loads(path.read_text(encoding="utf-8"))
    records = report.get("records") if isinstance(report, dict) else report
    out = []
    for record in records or []:
        conditions = record.get("conditions") or {}
        enrichment = record.get("enrichment") or {}
        out.append({"category": str(record.get("category") or ""),
                    "item": str(record.get("item") or ""),
                    "grade": norm_grade(record.get("grade")),
                    "temp": norm_temp(conditions.get("试验温度") or ""),
                    "value": numbers(record.get("requirement") or ""),
                    "method": str(enrichment.get("method") or ""),
                    "sampling": str(enrichment.get("sampling_num") or ""),
                    "position": str(enrichment.get("position") or ""),
                    "state": str(enrichment.get("state") or ""),
                    "source_table": record.get("source_table")})
    return out


def compare(gold: list[dict], ours: list[dict]) -> dict:  # v4: state-preferred pairing
    used: set[int] = set()
    matched = value_exact = temp_conflict = 0
    missing: list[dict] = []
    fields = {key: {"gold": 0, "ok": 0} for key in ("method", "sampling", "position", "state")}
    by_category: Counter = Counter()
    matched_by_category: Counter = Counter()
    value_by_category: Counter = Counter()
    for target in gold:
        by_category[target["category"]] += 1
        if target["category"] == "标准信息":
            candidates = [index for index, record in enumerate(ours)
                          if record["category"] == "标准信息" and index not in used]
            if candidates:
                used.add(candidates[0])
                matched += 1
                value_exact += 1
                matched_by_category["标准信息"] += 1
                value_by_category["标准信息"] += 1
            else:
                missing.append(target)
            continue
        if target["category"] == "热处理制度":
            candidates = [index for index, record in enumerate(ours)
                          if record["category"] == "热处理制度" and index not in used
                          and grade_match(target["grade"], record["grade"])]
            best = None
            for index in candidates:
                if target["value"] and set(target["value"]) & set(ours[index]["value"]):
                    best = index
                    break
            if best is None and candidates:
                best = candidates[0]
            if best is None:
                missing.append(target)
                continue
            used.add(best)
            matched += 1
            matched_by_category["热处理制度"] += 1
            ok = not target["value"] or bool(set(target["value"]) & set(ours[best]["value"]))
            value_exact += 1 if ok else 0
            value_by_category["热处理制度"] += 1 if ok else 0
            continue
        key = item_key(target["item"])
        candidates = [index for index, record in enumerate(ours)
                      if record["category"] == target["category"] and item_key(record["item"]) == key]
        best = None
        for index in candidates:
            if index in used:
                continue
            if not grade_match(target["grade"], ours[index]["grade"]):
                continue
            if ours[index]["temp"] != target["temp"]:
                continue
            if target.get("state") and ours[index].get("state") and norm(target["state"]) != norm(ours[index]["state"]):
                continue
            best = index
            break
        if best is None:
            for index in candidates:
                if index in used:
                    continue
                if not grade_match(target["grade"], ours[index]["grade"]):
                    continue
                if ours[index]["temp"] == target["temp"] and norm(target.get("state") or "") == norm(ours[index].get("state") or ""):
                    best = index
                    break
        if best is None:
            for index in candidates:
                if index in used:
                    continue
                if not grade_match(target["grade"], ours[index]["grade"]):
                    continue
                best = index
                break
        if best is None:
            missing.append(target)
            continue
        used.add(best)
        record = ours[best]
        matched += 1
        matched_by_category[target["category"]] += 1
        if record["temp"] != target["temp"]:
            temp_conflict += 1
        ok = set(target["value"]) == set(record["value"])
        value_exact += 1 if ok else 0
        value_by_category[target["category"]] += 1 if ok else 0
        for field in fields:
            if target[field]:
                fields[field]["gold"] += 1
                fields[field]["ok"] += int(field_ok(target[field], record[field]))
    extra = [record for index, record in enumerate(ours) if index not in used]
    return {"gold": len(gold), "ours": len(ours), "matched": matched,
            "value_exact": value_exact, "temp_conflict": temp_conflict,
            "missing": len(missing), "extra": len(extra),
            "value_consistency": round(value_exact / matched, 4) if matched else 0.0,
            "by_category": dict(by_category),
            "matched_by_category": dict(matched_by_category),
            "value_by_category": dict(value_by_category),
            "fields": fields,
            "missing_by_category": dict(Counter(item["category"] for item in missing)),
            "extra_by_category": dict(Counter(record["category"] for record in extra))}


def main() -> int:
    base = Path(r"F:\hanson\hanson_doc_parse\.tmp\batch7")
    pairs = [
        ("GBT3191", r"E:\Desktop\gbt-3191-1998.json", "docA_GBT3191-1998"),
        ("GBT6892", r"E:\Desktop\gbt-6892-2015.json", "docB_GBT6892-2015"),
        ("GJB2294", r"E:\Desktop\gjb-2294-1995.json", "docC_GJB2294-1995"),
        ("YST397", r"E:\Desktop\yst-397-2015.json", "docD_YST397-2015"),
    ]
    summary = {}
    for tag, gold_path, doc in pairs:
        gold = load_gold(Path(gold_path))
        ours = load_ours(base / doc / "extract" / "assembled" / "assembly-report.json")
        result = compare(gold, ours)
        summary[tag] = result
        coverage = {key: f"{result['matched_by_category'].get(key, 0)}/{value}"
                    for key, value in result["by_category"].items()}
        values = {key: f"{result['value_by_category'].get(key, 0)}/{result['matched_by_category'].get(key, 0)}"
                  for key in result["by_category"]}
        print(f"===== {tag} =====")
        print(f"  gold={result['gold']} ours={result['ours']} matched={result['matched']}")
        print(f"  匹配后值一致: {result['value_exact']}/{result['matched']} = {result['value_consistency']:.4f} "
              f"（缺失={result['missing']} 多余={result['extra']}）")
        print(f"  类别覆盖: {coverage}")
        print(f"  类别值一致: {values}")
        print(f"  缺失类别: {result['missing_by_category']}  多余类别: {result['extra_by_category']}")
        print(f"  字段: { {k: (v['ok'], v['gold']) for k, v in result['fields'].items()} }")
        print()
    (base / "compare-report-v3.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved:", base / "compare-report-v3.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
