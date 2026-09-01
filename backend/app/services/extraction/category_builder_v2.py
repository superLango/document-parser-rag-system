"""E3 类别构建 V2：文档感知术语精选路线（与 V1 并存，不修改 V1）。

V2 与 V1 的唯一差异 —— query 术语选择策略：

  V1（_build_refined_terms）：术语集**内部**语义去重（greedy 余弦 ≥ 阈值判重），
      再取前 limit 个，完全不看文档内容。实测对元素符号（C/Si/Mn/Cr...）
      余弦仅 0.55~0.77（< 0.85 阈值）导致去重失效，退化为「按术语表顺序
      无脑截断」，把文档中真实出现的术语全部丢出 query（化学成分 lost_gold
      平均 10.6/类别，Recall@15 0.759 vs 全量 1.000）。

  V2（_select_terms_by_doc_frequency_v2）：
      1) 候选 = 术语集全量（去重，query_main_limit）；
      2) 只保留「在当前文档中实际出现」的术语（符号用词元匹配，避免
         'C' 误命中 'Cr'；中文/长词用子串匹配）—— 文档中没有的术语
         不进 query；
      3) 按文档内出现频率降序排序（高频真实术语优先）；
      4) **不设数量上限**：无论符号还是中文词组，文档中出现的术语
         全部保留（数量由 query_main_limit 候选池与 content_max_chars
         长度兜底自然约束），彻底消除「精简截断丢掉真实术语」；
      5) 兜底：文档命中为空时回退 V1 语义去重结果。

其余环节（类别召回、两路上下文检索、rerank、过滤、schema 补全）与 V1
完全一致（复用 category_builder 的 _build_data_query/_build_meta_query/
_build_rerank_query 的 V1 版本，唯一替换点集中在术语精选函数），保证
对比时唯一变量是「术语选择」。

用法（三条路线并行，互不影响）：
    from app.services.extraction import category_builder, category_builder_v2
    targets, skipped = await category_builder.build_targets(cfg, db, kb_id=kb_id)  # 共享
    built_v1, _ = await category_builder.build_one(cfg, db, kb_id=kb_id, document_id=doc_id, target=t)
    built_v2, _ = await category_builder_v2.build_one_v2(cfg, db, kb_id=kb_id, document_id=doc_id, target=t)
    built_v2l, _ = await category_builder_v2.build_one_v2(
        cfg, db, kb_id=kb_id, document_id=doc_id, target=t,
        retrieval_override=LARGE_CANDIDATES,  # 候选放大实验
    )
"""

from __future__ import annotations

import copy
import logging
import re
import uuid

import numpy as np

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.extraction.category_builder import (
    _build_meta_query,
    _build_refined_terms,  # 兜底回退
    _build_rerank_query,
)
from app.services.extraction.extraction_models import ExtractionTarget, SkippedFeature
from app.services.extraction.term_base_loader import _read, distinct_field_values, load_term_base
from app.services.indexing.bm25 import tokenize_text
from app.services.embedding.embedding_service import embedding_service
logger = logging.getLogger(__name__)

from app.services.indexing.retrieval import SearchFilters, retrieval_service

__all__ = ["build_one_v2"]

_SYMBOL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-+/~]*")

# 文档全量可检索文本缓存（document_id -> {"text": str, "tokens": list[str] | None}）
_doc_full_cache: dict[str, dict] = {}


def _is_symbol(term: str) -> bool:
    """纯符号/短代码类术语（元素符号、牌号片段等），用词元匹配。"""
    return bool(_SYMBOL_RE.fullmatch(term or ""))


async def _doc_full_text(db: AsyncSession, document_id) -> dict:
    """文档全量可检索文本（content + content_for_embedding，含表格增强语义）。"""
    did = str(document_id)
    cached = _doc_full_cache.get(did)
    if cached is not None:
        return cached
    r = await db.execute(
        text(
            "SELECT content, content_for_embedding FROM document_chunks "
            "WHERE document_id=:d AND deleted_at IS NULL AND content IS NOT NULL"
        ),
        {"d": did},
    )
    parts = []
    for row in r.fetchall():
        parts.append(row.content or "")
        if row.content_for_embedding:
            parts.append(row.content_for_embedding or "")
    payload = {"text": "\n".join(parts), "tokens": None}
    _doc_full_cache[did] = payload
    return payload


def _term_hit_count(term: str, doc: dict) -> int:
    """术语在文档中的出现次数：符号用词元精确计数（避免 C 命中 Cr），中文用子串。"""
    if _is_symbol(term):
        if doc["tokens"] is None:
            doc["tokens"] = tokenize_text(doc["text"])
        return doc["tokens"].count(term)
    return doc["text"].count(term)


async def _select_terms_by_doc_frequency_v2(
    db: AsyncSession,
    kb_id,
    document_id,
    rows: list[dict],
    field: str,
    group_field: str,
    feature: str,
    top_n: int | None = None,
) -> list[str]:
    """文档感知术语精选（V2 核心）。

    与 V1 _select_terms_by_doc_frequency 的区别：
    - 符号术语用**词元**匹配（V1 子串匹配会用 'C' 误命中 '12Cr17Mn6Ni5N' 整串）；
    - **不做子串去重**（V1 的 `w in k or k in w` 会把 C/Cr 这类短符号互相顶掉）；
    - 只保留文档中实际出现的术语（术语集里文档没有的内容不进 query，
      精准对齐「query 术语必须源于文档内容」的原则）；
    - **默认不设数量上限**（top_n=None）：文档中出现的全部术语按频率
      降序返回，数量由调用侧候选池（query_main_limit）与内容长度上限
      （content_max_chars）自然约束，不再人为截断丢术语。
    """
    doc = await _doc_full_text(db, document_id)
    freq: dict[str, int] = {}
    for row in rows:
        if group_field:
            gv = str(_read(row, group_field) or "").strip()
            if gv and not _group_match(gv, feature):
                continue
        term = str(_read(row, field) or "").strip()
        if not term:
            continue
        cnt = _term_hit_count(term, doc)
        if cnt <= 0:
            continue
        freq[term] = max(freq.get(term, 0), cnt)
    if not freq:
        return []
    # 频率降序 → 长度升序（短符号优先）→ 字典序（稳定）
    ranked = sorted(freq.items(), key=lambda x: (-x[1], len(x[0]), x[0]))
    if top_n is None:
        return [w for w, _c in ranked]
    return [w for w, _c in ranked[:top_n]]


async def _build_query_terms_v2(
    db: AsyncSession,
    kb_id,
    target: ExtractionTarget,
    dedupe_threshold: float,
) -> list[str]:
    """固定 query + 术语集（V2：文档感知精选，不做术语集内部语义去重）。"""
    terms: list[str] = []
    if target.fixed_query:
        terms.extend(
            t.strip()
            for t in target.fixed_query.replace("，", " ").replace(",", " ").split()
            if t.strip()
        )
    for qs in target.query_sources or []:
        if not qs.get("in_query", False):
            continue
        tb_id = qs.get("term_base_id")
        if not tb_id:
            continue
        rows = await load_term_base(db, kb_id, uuid.UUID(str(tb_id)))
        group_field = (qs.get("group_field") or "").strip()
        if group_field:
            rows = [
                r for r in rows
                if _group_match(str(_read(r, group_field) or "").strip(), target.feature)
            ]
        field = qs.get("value_field") or "term_name"
        main_limit = int(qs.get("query_main_limit") or 30)
        refined_limit = int(qs.get("query_refined_limit") or 8)
        sel = await _select_terms_by_doc_frequency_v2(
            db, kb_id, target.document_id, rows, field, group_field,
            target.feature,  # top_n=None: 文档中出现的术语全保留，不设数量上限
        )
        if sel:
            terms.extend(sel)
        else:
            # 兜底（文档匹配失效）：回退 V1 语义去重，保证 query 非空
            if qs.get("dedupe") and refined_limit > 0:
                refined = await _build_refined_terms(rows, field, refined_limit, dedupe_threshold)
                terms.extend(refined or distinct_field_values(rows, field, main_limit))
            else:
                terms.extend(distinct_field_values(rows, field, main_limit))
    return list(dict.fromkeys(terms))


async def _build_data_query_v2(
    db: AsyncSession,
    kb_id,
    target: ExtractionTarget,
    dedupe_threshold: float,
    content_max_chars: int,
) -> str:
    """数据路检索 query（V2）：与 V1 _build_data_query 同构，仅术语来源换为文档感知精选。"""
    terms: list[str] = []
    for qs in target.query_sources or []:
        if not qs.get("in_query", False):
            continue
        tb_id = qs.get("term_base_id")
        if not tb_id:
            continue
        rows = await load_term_base(db, kb_id, uuid.UUID(str(tb_id)))
        group_field = (qs.get("group_field") or "").strip()
        if group_field:
            rows = [
                r for r in rows
                if _group_match(str(_read(r, group_field) or "").strip(), target.feature)
            ]
        field = qs.get("value_field") or "term_name"
        main_limit = int(qs.get("query_main_limit") or 30)
        refined_limit = int(qs.get("query_refined_limit") or 8)
        sel = await _select_terms_by_doc_frequency_v2(
            db, kb_id, target.document_id, rows, field, group_field,
            target.feature,  # top_n=None: 文档中出现的术语全保留，不设数量上限
        )
        if sel:
            terms.extend(sel)
        else:
            if qs.get("dedupe") and refined_limit > 0:
                refined = await _build_refined_terms(rows, field, refined_limit, dedupe_threshold)
                terms.extend(refined or distinct_field_values(rows, field, main_limit))
            else:
                terms.extend(distinct_field_values(rows, field, main_limit))
    query = " ".join([target.feature or "", *terms]).strip() or target.feature
    return query[:content_max_chars]


# 语义证据判定（方案 D 核心）：字面为零时，用「类别query vs 文档块最大余弦 ≥0.65 且表格块」救回漏检
_SEM_THRESHOLD_DEFAULT = 0.60



_GROUP_SEP_RE = re.compile(r"[、,，/|;；\s]+")


def _group_match(gv: str, feature: str) -> bool:
    """group_field 匹配: 包含匹配(而非等于)。

    术语集 group_field 字段可能为单个类型("化学成分")或拼接多个类型
    ("化学成分、室温拉伸" / "化学成分|高温拉伸"), 只要包含目标类型即可。
    注: 简单用子串包含即可覆盖拼接场景; 分隔符拆分用于更精确判断。
    """
    gv = (gv or "").strip()
    if not gv or not feature:
        return False
    if feature in gv:
        return True
    parts = [p2.strip() for p2 in _GROUP_SEP_RE.split(gv) if p2.strip()]
    return feature in parts


def _parse_vec(v):
    """pgvector 字符串/bytes -> np.float32 数组。"""
    if isinstance(v, (bytes, bytearray)):
        return np.frombuffer(v, dtype=np.float32)
    return np.array([float(x) for x in v.strip("[]").split(",")], dtype=np.float32)


async def _load_doc_block_vectors(db, document_id) -> tuple[list[str], list[dict], np.ndarray]:
    """预取文档全部块的 (chunk_id, 元数据, 归一化向量矩阵)。

    返回 (chunk_ids, metas, mat)：mat 为 (N, dim) 已 L2 归一化矩阵, 供批量语义证据复用。
    """
    import numpy as np

    rows = (
        await db.execute(
            text(
                "SELECT chunk_id, content, content_for_embedding, has_table, content_vector "
                "FROM document_chunks "
                "WHERE document_id=:d AND deleted_at IS NULL AND content_vector IS NOT NULL"
            ),
            {"d": str(document_id)},
        )
    ).fetchall()
    if not rows:
        return [], [], np.zeros((0, 0), dtype=np.float32)
    mats = []
    metas = []
    ids = []
    for r in rows:
        vec = _parse_vec(r.content_vector)
        n = float(np.linalg.norm(vec))
        if n <= 0:
            continue
        mats.append(vec / n)
        metas.append({
            "has_table": bool(r.has_table),
            "text": (r.content or "") + " " + (r.content_for_embedding or ""),
        })
        ids.append(getattr(r, "chunk_id", None) or "")
    mat = np.vstack(mats).astype(np.float32) if mats else np.zeros((0, 0), dtype=np.float32)
    return ids, metas, mat


async def _batch_semantic_evidence(
    db,
    kb_id,
    document_id,
    queries: list[str],
    thresholds: list[float] | None = None,
    keyword_checks: list[bool] | None = None,
    keyword_list: list[list[str]] | None = None,
    kw_threshold: float = 0.50,
) -> list[dict]:
    """批量语义证据（方案 A 优化）: 一次 embed 全部 query, 矩阵点积一次完成。

    queries[i] 对应返回 results[i]。每个结果形如:
      {"hit", "max_sim", "table", "chunk_id", "keyword_hit"}
    仅在 无字面命中 的类别调用; 语义判定逻辑与 _semantic_evidence_hit 完全一致。
    """
    import numpy as np

    results = []
    if not queries:
        return results
    # 1) 一次批量 embed（单次 GPU 调用, 不触发 embedding 串行锁问题）
    try:
        qvecs = await embedding_service.embed([q for q in queries if (q or "").strip()])
    except Exception:  # noqa: BLE001
        return [{"hit": False, "max_sim": 0.0, "table": False, "chunk_id": None, "keyword_hit": False} for _ in queries]
    qptr = 0
    # 2) 文档块向量一次取出（复用）
    ids, metas, mat = await _load_doc_block_vectors(db, document_id)
    if len(ids) == 0 or mat.shape[0] == 0:
        return [{"hit": False, "max_sim": 0.0, "table": False, "chunk_id": None, "keyword_hit": False} for _ in queries]

    def _one(qveclist, kw_ck: bool, kws: list[str]) -> dict:
        nonlocal qptr
        qv = qveclist[qptr]; qptr += 1
        qv_arr = np.array(qv, dtype=np.float32)
        n = float(np.linalg.norm(qv_arr))
        if n > 0:
            qv_arr = qv_arr / n
        sims = mat @ qv_arr  # (N,) 点积即余弦
        order = np.argsort(-sims)
        best_idx = int(order[0])
        best = float(sims[best_idx])
        hit = bool(best >= (thresholds[best_idx] if thresholds else _SEM_THRESHOLD_DEFAULT) and metas[best_idx]["has_table"])
        kw_hit = False
        if not hit and kw_ck and best >= kw_threshold:
            for idx in order:
                if float(sims[idx]) < kw_threshold:
                    break
                blob = metas[idx]["text"]
                for kw in (kws or []):
                    if not kw:
                        continue
                    if _is_symbol(kw):
                        if kw in tokenize_text(blob):
                            kw_hit = True
                            break
                    elif kw in blob:
                        kw_hit = True
                        break
                if kw_hit:
                    break
            hit = kw_hit
        return {
            "hit": hit,
            "max_sim": round(best, 4),
            "table": metas[best_idx]["has_table"],
            "chunk_id": ids[best_idx],
            "keyword_hit": kw_hit,
        }

    for i, q in enumerate(queries):
        if not (q or "").strip():
            results.append({"hit": False, "max_sim": 0.0, "table": False, "chunk_id": None, "keyword_hit": False})
            continue
        kw_ck = bool(keyword_checks[i]) if keyword_checks else False
        kws = keyword_list[i] if keyword_list else None
        results.append(_one(qvecs, kw_ck, kws))
    return results


async def _semantic_evidence_hit(
    db: AsyncSession,
    kb_id,
    document_id,
    query: str,
    threshold: float = _SEM_THRESHOLD_DEFAULT,
    keyword_check: bool = False,
    category_keywords: list[str] | None = None,
    keyword_threshold: float = 0.50,
) -> dict:
    """返回 (hit, max_sim, table, chunk_id, keyword_hit)。

    对文档全部块 content_vector 与 query 向量做余弦，取最大值。
    方案 C 判据（召回优先，宁可多留不可漏剔）：
      1) 主判据: max_sim ≥ threshold(0.60) 且表格块 → hit；
      2) 兜底判据: keyword_check=True 且 max_sim ≥ keyword_threshold(0.50)
         且 top 块命中类别关键词（词元/子串）→ hit（解决"低温拉伸"vs"拉伸"、
         "蠕变"vs"持久"等术语与文档用词不一致的漏剔，0.50~0.60 区间靠关键词兜底）。
    """
    import numpy as np

    def _no(mx=0.0, tbl=False, cid=None):
        return {"hit": False, "max_sim": round(mx, 4), "table": bool(tbl), "chunk_id": cid, "keyword_hit": False}

    if not (query or "").strip():
        return _no()
    try:
        qv = (await embedding_service.embed([query]))[0]
    except Exception:  # noqa: BLE001
        return _no()
    qv_arr = np.array(qv, dtype=np.float32)
    norm = np.linalg.norm(qv_arr)
    if norm > 0:
        qv_arr = qv_arr / norm
    # 复用批量向量矩阵（共享缓存 _block_vec_cache），矩阵点积一次完成
    ids, metas, mat = await _load_doc_block_vectors(db, document_id)
    if len(ids) == 0:
        return _no()
    sims = mat @ qv_arr
    order = np.argsort(-sims)
    best_idx = int(order[0])
    best = float(sims[best_idx])
    best_table = metas[best_idx]["has_table"]
    best_chunk_id = ids[best_idx]
    scored = [(float(sims[j]), metas[j]["has_table"], ids[j], metas[j]["text"]) for j in order]
    # 主判据: max_sim ≥ threshold 且表格块
    hit = bool(best >= threshold and best_table)
    kw_hit = False
    if not hit and keyword_check and best >= keyword_threshold:
        # 兜底: 文档中任意块(不限语义 top)命中类别核心词 且 语义≥keyword_threshold
        # (解决"术语集写蠕变、文档写持久"的词汇不一致: 核心词"持久"在文档任意块命中即强证据)
        for sim, tbl, cid, blob in scored:
            if sim < keyword_threshold:
                break  # 语义更低的块无证据力
            for kw in (category_keywords or []):
                if not kw:
                    continue
                if _is_symbol(kw):
                    if kw in tokenize_text(blob):
                        kw_hit = True
                        break
                elif kw in blob:
                    kw_hit = True
                    break
            if kw_hit:
                break
        hit = kw_hit
    return {
        "hit": hit,
        "max_sim": round(best, 4),
        "table": best_table,
        "chunk_id": best_chunk_id,
        "keyword_hit": kw_hit,
    }


# 类别核心关键词（方案 C 兜底）：类别名 + 术语核心词（去括号/去符号部分）
_KW_PAREN_RE = re.compile(r"[（(].*?[）)]")


# 专业近义核心词补充（方案 C 兜底, 召回优先）: 术语集/类别名与文档用词的恒定差异
_CATEGORY_ALIAS_CORE = {
    "蠕变": ["持久", "蠕变"], "持久": ["蠕变", "持久"],
    "热膨胀": ["膨胀", "热膨", "热膨胀"],
    "低温拉伸": ["低温", "拉伸"],
    "高温拉伸": ["高温", "拉伸"],
    "室温拉伸": ["室温", "拉伸"],
    "缺口持久": ["缺口", "持久"], "高温缺口拉伸": ["缺口", "拉伸"],
    "循环持久": ["循环", "持久"], "组合持久": ["组合", "持久"],
    "室温持久": ["室温", "持久"], "低周疲劳": ["疲劳", "低周"], "高周疲劳": ["疲劳", "高周"],
    "应力疲劳": ["疲劳", "应力"], "非金属夹杂": ["夹杂", "非金属"],
    "夏比冲击": ["冲击", "冲击功"], "洛氏硬度": ["洛氏", "硬度"], "维氏硬度": ["维氏", "硬度"],
    "布氏硬度": ["布氏", "硬度"], "铁素体": ["铁素体"], "晶粒度": ["晶粒"],
    "高倍组织": ["显微组织", "碳化物", "高倍"], "淬透性": ["淬透"],
}


def _category_keywords(feature: str, terms: list[str]) -> list[str]:
    """生成类别关键词（方案 C 兜底，召回优先）。

    原则: 关键词必须短小、可被文档块明确命中 —— 术语"持久断后伸长率(δ5)"
    在文档中可能写作"持久"或"伸长率"，所以从完整术语按以下顺序拆解：
      a) 完整核心词(去括号): 持久断后伸长率
      b) 核心词根: 对中文长词, 取 4~8 字关键词(如 "断后伸长率"→"伸长率")
      c) 类别名本身(如 "低温拉伸"→"低温拉伸"→再拆本词根)
    仅保留长度 2~8 的词, 符号类(1-3 字符)单独保留(词元匹配)。
    """
    out: list[str] = []
    def _add(w):
        w = (w or "").strip()
        if not w:
            return
        if 2 <= len(w) <= 20:
            out.append(w)
    # 特征名 + 特征名核心字词（如 "低温拉伸" → "低温"、"拉伸"）
    _add(feature)
    for alias in (_CATEGORY_ALIAS_CORE.get(feature or "", []) or []):
        _add(alias)
    if feature and len(feature) >= 3 and re.search(r"[\u4e00-\u9fff]", feature):
        # 拆出类别名中的常见核心词（映射表 + 自动拆后缀词）
        for suffix in ("拉伸", "持久", "疲劳", "硬度", "冲击", "弯曲", "夹杂", "落锤", "蠕变",
                       "疲劳", "组织", "断裂", "探伤", "试验", "检查", "检验", "试验"):
            if suffix in feature and suffix not in (feature, ""):
                _add(suffix)
        # 前缀（低温/高温/室温/循环/缺口/组合/应力/低周/高周等）
        for prefix in ("低温", "高温", "室温", "循环", "缺口", "组合", "应力", "低周", "高周", "步冷", "热"):
            if feature.startswith(prefix) and prefix != feature:
                _add(prefix)
    for term in (terms or []):
        core = _KW_PAREN_RE.sub("", term or "")
        core = re.split(r"[/／]", core)[0].strip()
        if not core:
            continue
        # 完整核心词
        _add(core)
        # 中文长词拆核心词根: 去除常见前缀词(持久/室温/高温/低温/循环/缺口/组合/应力/低周/高周/步冷/拉伸/硬度/疲劳等前段)
        if len(core) >= 5 and re.search(r"[一-鿿]", core):
            # 找子词: 以"XX后""XX率""XX度""XX力"等后缀词为主
            for suffix in ("伸长率", "收缩率", "强度", "硬度", "疲劳", "冲击", "持久", "蠕变", "拉伸",
                           "面缩率", "时间", "应力", "温度", "缺口", "晶粒度", "夹杂", "碳化物"):
                if suffix in core and len(suffix) <= 6:
                    _add(suffix)
            # 去掉括号内符号后的头部 (如 "持久断后伸长率" -> 取"持久")
            for prefix in ("持久", "室温", "高温", "低温", "循环", "缺口", "组合", "应力", "断后", "低周", "高周", "步冷"):
                if core.startswith(prefix) and len(prefix) >= 2:
                    _add(prefix)
    # 去重
    seen = set()
    res = []
    for w in out:
        if w in seen:
            continue
        seen.add(w)
        res.append(w)
    return res[:20]


async def build_one_v2(
    cfg,
    db: AsyncSession,
    *,
    kb_id,
    document_id,
    target: ExtractionTarget,
    top_k: int | None = None,
    retrieval_override: dict | None = None,
) -> tuple[ExtractionTarget | None, SkippedFeature | None]:
    """单类别召回（V2 路线）：与 V1 build_one 唯一差异是 query 术语为文档感知精选。

    retrieval_override：可选，浅合并到 KB 全局 retrieval 配置上（用于
    候选放大等实验路线，只影响本次调用，不修改全局配置）。
    """
    global_retrieval = {**(cfg.global_config.get("retrieval") or {}), **(retrieval_override or {})}
    default_top_k = top_k or global_retrieval.get("top_k") or 10
    category_recall = global_retrieval.get("category_recall") or {}
    recall_mode = category_recall.get("mode") or "loose"
    recall_top_k = int(category_recall.get("top_k") or 5)
    per_dim_top_k = int(category_recall.get("per_dim_top_k") or 10)
    default_threshold = float(global_retrieval.get("default_confidence_threshold") or 0.35)
    keyword_min_hits = int((global_retrieval.get("hybrid") or {}).get("keyword_min_hits") or 1)
    query_embed_cfg = global_retrieval.get("query_embed") or {}
    content_max_chars = int(query_embed_cfg.get("content_max_chars") or 2000)
    dedupe_threshold = float(query_embed_cfg.get("dedupe_similarity_threshold") or 0.85)
    t = copy.deepcopy(target)
    t.document_id = str(document_id)
    t.query_terms = await _build_query_terms_v2(db, kb_id, t, dedupe_threshold)
    data_query = await _build_data_query_v2(db, kb_id, t, dedupe_threshold, content_max_chars)
    meta_query = _build_meta_query(t, content_max_chars)
    rerank_query = await _build_rerank_query(cfg, db, kb_id, t)
    # 方案 D: 语义证据判定 —— 类别是否涉及当前文档（在检索前判定，避免误剔）
    sem_ev_cfg = (global_retrieval.get("reranker") or {})
    sem_enabled = bool(sem_ev_cfg.get("semantic_evidence_enabled", True))
    sem_thr = float(sem_ev_cfg.get("semantic_evidence_threshold") or _SEM_THRESHOLD_DEFAULT)
    # ===== 证据判定（召回优先，2026-08-29 定稿）=====
    # 原则：宁可多保留，不可缺项漏项。
    #   - always 类别（标准信息/热处理制度等）：无条件全部保留，不参与证据判定；
    #   - 非 always 类别：字面任意命中(文档出现该类型词) OR 语义≥0.60 → 保留；
    #     两路皆无证据 → 剔除（该文档确实无此类型）。
    sem_evidence = None
    if (t.extraction_strategy or "auto") == "always":
        t.has_content_evidence = True
    elif sem_enabled:
        # 字面任意命中：query_terms 中任一术语在文档全文(任意块/表格/正文)出现
        doc_full = await _doc_full_text(db, document_id)
        lit_any_hit = any(_term_hit_count(w, doc_full) > 0 for w in (t.query_terms or []))
        if not lit_any_hit:
            # 方案C: 语义主判据(≥0.60且表格) + 关键词兜底(≥0.50且任意块含类别核心词)
            # 语义 query 用「类别名 + 全量术语集」, 避免文档感知精简后丢失术语
            # (data_query 是文档感知后的, 对"蠕变vs持久"场景术语不全)
            from app.services.extraction.term_base_loader import _read as _rd, distinct_field_values as _dfv
            full_terms = []
            for qs in t.query_sources or []:
                if not qs.get("in_query", False):
                    continue
                tb_id = qs.get("term_base_id")
                if not tb_id:
                    continue
                rr3 = await load_term_base(db, kb_id, uuid.UUID(str(tb_id)))
                gf3 = (qs.get("group_field") or "").strip()
                if gf3:
                    rr3 = [x for x in rr3 if _group_match(str(_rd(x, gf3) or "").strip(), t.feature)]
                full_terms.extend(_dfv(rr3, qs.get("value_field") or "term_name", int(qs.get("query_main_limit") or 30)))
            sem_query = " ".join([t.feature or "", *dict.fromkeys(full_terms)]).strip()[:2000] or (data_query or "")
            kw = _category_keywords(t.feature, full_terms or t.query_terms or [])
            sem_evidence = await _semantic_evidence_hit(
                db, kb_id, document_id, sem_query,
                threshold=sem_thr, keyword_check=True,
                category_keywords=kw, keyword_threshold=0.50,
            )
        if lit_any_hit or (sem_evidence and sem_evidence.get("hit")):
            t.has_content_evidence = True
        else:
            return None, SkippedFeature(
                feature=t.feature,
                reason=f"文档无该类证据（字面0命中，语义{0 if sem_evidence is None else sem_evidence.get('max_sim'):.3f}未达阈值{sem_thr}，关键词{'未' if not (sem_evidence and sem_evidence.get('keyword_hit')) else '已'}命中）",
                score=0.0,
            )
    recall_hits = await retrieval_service.search(
        db,
        uuid.UUID(str(kb_id)),
        data_query,
        top_k=recall_top_k,
        per_dim_top_k=per_dim_top_k,
        filters=SearchFilters(document_id=uuid.UUID(str(document_id))),
        retrieval_config=global_retrieval,
        rerank_query=rerank_query,
    )
    # 方案 D 语义证据命中: 类别被证实在文档中存在（≥0.65 且表格块）,
    # 无论检索/rerank/阈值如何,都必须放行（避免误剔"语义相同表述不同"的类别）
    if sem_evidence and sem_evidence.get("hit"):
        logger.warning("语义证据命中，放行类别 feature=%s max_sim=%s", t.feature, sem_evidence.get("max_sim"))
    if not recall_hits:
        if getattr(t, "has_content_evidence", False):
            t.hit_score = sem_evidence.get("max_sim") or 0.0
            t.hit_count = 1
            t.sem_evidence = sem_evidence
        elif recall_mode == "off":
            t.hits = []
        else:
            return None, SkippedFeature(feature=t.feature, reason="零命中（检索无结果，语义证据未命中）", score=0.0)
    else:
        t.hit_score = max(h.score for h in recall_hits)
        t.hit_count = len(recall_hits)
        kw_count = sum(1 for h in recall_hits if getattr(h, "keyword_matched", False))
        threshold = (
            float(t.confidence_threshold)
            if t.confidence_threshold is not None
            else default_threshold
        )
        if recall_mode == "strict" and t.hit_score < threshold and kw_count < keyword_min_hits and not getattr(t, "has_content_evidence", False):
            return None, SkippedFeature(
                feature=t.feature,
                reason=f"置信度低于阈值（最高分 {t.hit_score:.3f} < {threshold}，词法命中 {kw_count} < {keyword_min_hits}）",
                score=t.hit_score,
            )
        data_route_top_k = int(global_retrieval.get("data_route_top_k") or 10)
        meta_route_top_k = int(global_retrieval.get("meta_route_top_k") or 5)
        data_hits = await retrieval_service.search(
            db,
            uuid.UUID(str(kb_id)),
            data_query,
            top_k=min(data_route_top_k, t.top_k or default_top_k),
            filters=SearchFilters(document_id=uuid.UUID(str(document_id))),
            retrieval_config=global_retrieval,
            rerank_query=rerank_query,
            skip_rerank=True,
        )
        meta_hits = await retrieval_service.search(
            db,
            uuid.UUID(str(kb_id)),
            meta_query,
            top_k=meta_route_top_k,
            filters=SearchFilters(document_id=uuid.UUID(str(document_id))),
            retrieval_config=global_retrieval,
            rerank_query=rerank_query,
            skip_rerank=True,
        )
        merged_hits: dict = {}
        for h in list(data_hits) + list(meta_hits):
            merged_hits.setdefault(h.chunk_id, h)
        context_hits = list(merged_hits.values())
        # 合并后重排: 已关闭(2026-08-29 v4 定稿)。
        # 实测确认: 重排分数在 V3 流程中三个用途均未生效——
        #   ① 类别过滤 threshold=-5(几乎不剔, 类别保留由证据判定决定),
        #   ② 上下文排序 sort_mode=page(页码序, 不用重排分),
        #   ③ 块级过滤 block_filter_enabled=false。
        # 重排不改变候选集合(召回不变), 仅耗时 +2-3s/类(41类 ~100s)。
        # 去掉即省 ~100s -> 单文档 ~110s, 召回 0.946 保持。
        # 如需启用: 将此处恢复并设 sort_mode=rerank 或开启 block_filter
        t.hits = [{
            "chunk_id": h.chunk_id,
            "content": h.content,
            "parent_text": h.parent_text,
            "source_pages": h.source_pages,
            "score": h.score,
            "has_table": getattr(h, "has_table", False),
            "rerank_score": getattr(h, "rerank_score", None),
        } for h in context_hits]
        if (t.extraction_strategy or "auto") != "always":
            reranker_cfg = global_retrieval.get("reranker") or {}
            if reranker_cfg.get("category_filter_enabled", True):
                rerank_threshold = float(reranker_cfg.get("threshold") or 0.0)
                max_rerank = max(
                    (h.get("rerank_score") for h in t.hits if h.get("rerank_score") is not None),
                    default=None,
                )
                if (max_rerank is None or max_rerank < rerank_threshold) and not getattr(t, "has_content_evidence", False):
                    return None, SkippedFeature(
                        feature=t.feature,
                        reason=f"重排分数低于阈值（最高 {max_rerank} < {rerank_threshold}）",
                        score=max_rerank,
                    )
    # schema / term_data 补全（与 V1 完全一致）
    properties = {}
    for f in t.fields:
        prop: dict = {"type": f.get("type") or "string"}
        if f.get("required"):
            prop["required"] = True
        if f.get("description"):
            prop["description"] = f["description"]
        if f.get("example"):
            prop["example"] = f["example"]
        properties[f["name"]] = prop
    t.schema = {"type": t.return_type, "properties": properties}
    for qs in t.query_sources or []:
        label = (qs.get("label") or "").strip()
        tb_id = qs.get("term_base_id")
        if label and tb_id:
            rows = await load_term_base(db, kb_id, uuid.UUID(str(tb_id)))
            gf = (qs.get("group_field") or "").strip()
            if gf:
                rows = [
                    r for r in rows
                    if _group_match(str(_read(r, gf) or "").strip(), target.feature)
                ]
            t.term_data[label] = rows
            # 诊断: 打印 term_data 填充结果(标签/过滤后行数/前3值)
            try:
                from app.services.extraction.term_base_loader import field_values as _fv
                _vals = _fv(rows, qs.get("value_field") or "term_name")
                logger.warning(
                    "term_data 填充诊断", feature=target.feature, label=label,
                    group_field=gf, term_base_id=str(tb_id), qs=qs,
                    rows=len(rows), all_rows=len(await load_term_base(db, kb_id, uuid.UUID(str(tb_id)))),
                    sample=_vals[:3],
                )
            except Exception:  # noqa: BLE001
                pass
    return t, None


# 候选放大实验配置（V2-L）：128k 上下文无压力，扩大候选池与召回宽度
LARGE_CANDIDATES: dict = {
    # k40 最终配置(2026-08-29 定稿): 保持候选宽度, 确保多表类别全数召回。
    # 实验: k30(全数率 0.828) 略优于 k40(0.809, 6 类别改善), 但存在 2 个实例退化
    #   (a62820a 室温拉伸 0.75 / GBT2965 热处理制度 0.667, 均为多表类别个别块排名噪声),
    #   且 a62820a 文档块表为空(历史孤儿, 非配置问题);
    # 为满足「数据全数召回」严格目标, 维持 k40, 不冒险降 top_k。
    "top_k": 40,
    "candidate_mult": 4,
    "category_recall": {"mode": "loose", "top_k": 25, "per_dim_top_k": 40},
    "data_route_top_k": 40,
    "meta_route_top_k": 20,
    "context_top_k": 60,
}

# 基准候选放大（k40, 现状）: 仅用于与 LARGE_CANDIDATES(k30) 对比
LARGE_CANDIDATES_K40: dict = {
    "top_k": 40,
    "candidate_mult": 4,
    "category_recall": {"mode": "loose", "top_k": 25, "per_dim_top_k": 40},
    "data_route_top_k": 40,
    "meta_route_top_k": 20,
    "context_top_k": 60,
}
