"""E3 脚本工具层：受限子进程内可用的真实 kb_tools。

对齐原项目 ``KbScriptTools``（document-parser-rag-system/.../script_tools.py）：
- ``get_term_records(name, *fields)``：按术语集名称读取记录（键为传入字段名）；
- ``embed(texts)``：走当前项目 BGE-M3 嵌入服务（内部端点）；
- ``semantic_search(records, query, match_fields, top_k, return_fields)``：记录内语义检索；
- ``match_record(name, records, match_fields, threshold)``：语义→精确→编辑距离三级匹配。

脚本仍在受限子进程（``python -I`` + 超时 + stdin 传数据）中执行；
嵌入服务由父进程持有（单例模型），子进程通过内部端点调用，避免重复加载模型。
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.glossary import TERM_STATUS_ACTIVE, Term, TermBase

# 嵌入令牌有效期（秒）：脚本子进程运行期间有效，运行结束即吊销
EMBED_TOKEN_TTL = 600
# 单次嵌入文本数上限（保护内部端点，避免超大请求）
EMBED_MAX_TEXTS = 512

# 内部端点路径模板（挂载于 cfg_router：/kb/{kb_id}/extraction-config/script-embed）
EMBED_ENDPOINT_PATH = "/api/v1/kb/{kb_id}/extraction-config/script-embed"


# ---------------------------------------------------------------------------
# 纯函数（嵌入到子进程模板，供语义检索/编辑距离使用；同一份源码可单测）
# ---------------------------------------------------------------------------
_EDIT_SIMILARITY_SRC = '''
def _edit_similarity(s1, s2):
    """编辑距离相似度（1 - distance/max_len），用于 match_record 编辑距离兜底。"""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0

    def _norm(s):
        return "".join(
            str(c).strip().lower()
            for c in s
        ).translate(
            str.maketrans(
                "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
                "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
            )
        )

    def _levenshtein(a, b):
        if len(a) < len(b):
            return _levenshtein(b, a)
        if len(b) == 0:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a):
            cur = [i + 1]
            for j, cb in enumerate(b):
                cur.append(min(prev[j + 1] + 1, cur[j] + 1, prev[j] + (ca != cb)))
            prev = cur
        return prev[-1]

    s1_norm = _norm(s1)
    s2_norm = _norm(s2)
    if s1_norm == s2_norm:
        return 1.0
    max_len = max(len(s1_norm), len(s2_norm))
    return 1.0 - _levenshtein(s1_norm, s2_norm) / max_len
'''

_KB_TOOLS_CLASS_SRC = '''
class _KbTools:
    """脚本注入工具句柄（子进程内实现，对齐原项目 KbScriptTools）。"""

    def __init__(self, embed_url, embed_token):
        self.embed_url = embed_url
        self.embed_token = embed_token
        self._semantic_top_k = 5
        self._match_top_k = 1
        self._match_threshold = 0.90

    @staticmethod
    def _dot(a, b):
        return sum(x * y for x, y in zip(a, b))

    async def embed(self, texts):
        """文本向量化（BGE-M3 dense，1024 维，已归一化）。"""
        import urllib.request

        if isinstance(texts, str):
            texts = [texts]
        texts = [t for t in texts if isinstance(t, str) and t.strip()]
        if not texts:
            return []

        def _call():
            body = json.dumps({"token": self.embed_token, "texts": texts}).encode("utf-8")
            req = urllib.request.Request(
                self.embed_url, data=body, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))

        data = await asyncio.to_thread(_call)
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data["data"]
        vectors = (data or {}).get("vectors")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise RuntimeError(
                f"嵌入服务返回异常：向量数量({len(vectors) if isinstance(vectors, list) else '非列表'})"
                f"与文本数量({len(texts)})不一致"
            )
        return vectors

    async def get_term_records(self, name, *fields):
        """按术语集名称读取记录列表（键为传入字段名）。"""
        rows = TERM_DATA.get(name, [])
        if not fields:
            return [dict(r) for r in rows]
        return [{f: r.get(f) for f in fields} for r in rows]

    async def semantic_search(self, records, query, match_fields, top_k=None, return_fields=None):
        """记录内语义检索：返回带 score 的 top_k 条。"""
        top_k = top_k if top_k is not None else self._semantic_top_k
        if not records or not query:
            return []
        mfs = [match_fields] if isinstance(match_fields, str) else list(match_fields or [])
        mfs = [f for f in mfs if f]
        if not mfs:
            raise ValueError("match_fields 不能为空")

        texts = []
        valid_idx = []
        for i, r in enumerate(records):
            parts = [str(r.get(f, "")).strip() for f in mfs]
            text = " ".join(p for p in parts if p).strip()
            if text:
                texts.append(text)
                valid_idx.append(i)
        if not texts:
            return []

        vecs = await self.embed([str(query).strip()] + texts)
        query_vec = vecs[0]
        rec_vecs = vecs[1:]
        scored = []
        for idx, vec in zip(valid_idx, rec_vecs):
            sim = self._dot(query_vec, vec)
            if return_fields:
                item = {k: records[idx].get(k) for k in return_fields if k in records[idx]}
            else:
                item = dict(records[idx])
            item["score"] = sim
            scored.append((sim, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:top_k]]

    async def match_record(self, name, records, match_fields, threshold=None):
        """单条记录匹配：语义检索优先 + 精确/编辑距离 fallback。"""
        threshold = threshold if threshold is not None else self._match_threshold
        if not name or not records:
            return {"canonical": name, "score": 0.0, "type": "unverified", "record": None}
        mfs = [match_fields] if isinstance(match_fields, str) else list(match_fields or [])
        mfs = [f for f in mfs if f]
        canonical_field = mfs[0] if mfs else None
        name_clean = str(name).strip()

        # 1. 语义检索优先（失败回退精确/编辑距离，与对齐目标一致）
        try:
            top = await self.semantic_search(records, name_clean, mfs, top_k=self._match_top_k)
            if top and top[0]["score"] >= threshold:
                hit = top[0]
                canonical = str(hit.get(canonical_field) or name_clean)
                return {
                    "canonical": canonical,
                    "score": hit["score"],
                    "type": "vector",
                    "record": hit,
                }
        except Exception:
            pass

        # 2. 精确匹配
        for r in records:
            for f in mfs:
                if str(r.get(f, "")).strip() == name_clean:
                    return {
                        "canonical": name_clean,
                        "score": 1.0,
                        "type": "exact",
                        "record": r,
                    }

        # 3. 编辑距离匹配
        best_r = None
        best_val = ""
        best_sim = 0.0
        for r in records:
            for f in mfs:
                val = str(r.get(f, "")).strip()
                if not val:
                    continue
                sim = _edit_similarity(name_clean, val)
                if sim > best_sim:
                    best_sim = sim
                    best_r = r
                    best_val = val
        if best_r and best_sim >= 0.85:
            return {
                "canonical": best_val,
                "score": best_sim,
                "type": "edit_distance",
                "record": best_r,
            }

        return {
            "canonical": name,
            "score": best_sim,
            "type": "unverified",
            "record": None,
        }
'''


def build_script_code(code: str) -> str:
    """组装受限子进程可执行脚本：数据经 stdin 传入，避免命令行参数超限。"""
    return (
        "import asyncio, json, sys\n"
        "\n"
        "_payload = json.loads(sys.stdin.read())\n"
        "TERM_DATA = _payload[\"term_data\"]\n"
        "_args = _payload[\"args\"]\n"
        "_embed = _payload[\"embed\"]\n"
        "\n"
        + _EDIT_SIMILARITY_SRC
        + "\n"
        + _KB_TOOLS_CLASS_SRC
        + "\n"
        "kb_tools = _KbTools(_embed[\"url\"], _embed[\"token\"])\n"
        "\n"
        + code
        + "\n"
        "async def _main():\n"
        "    result = run(_args)\n"
        "    if asyncio.iscoroutine(result):\n"
        "        result = await result\n"
        "    sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str))\n"
        "\n"
        "asyncio.run(_main())\n"
    )


# ---------------------------------------------------------------------------
# 术语集只读数据（父进程构建，注入子进程）
# ---------------------------------------------------------------------------
async def load_term_data(db: AsyncSession, kb_id, max_rows: int = 1000) -> dict[str, list[dict[str, Any]]]:
    """按术语集名称构建 {名称: [记录 dict]}；含内置字段 + extras + 别名。"""
    bases = (
        await db.execute(
            select(TermBase).where(TermBase.kb_id == kb_id).order_by(TermBase.name)
        )
    ).scalars().all()
    data: dict[str, list[dict[str, Any]]] = {}
    for b in bases:
        terms = (
            await db.execute(
                select(Term)
                .where(
                    Term.kb_id == kb_id,
                    Term.term_base_id == b.id,
                    Term.status == TERM_STATUS_ACTIVE,
                )
                .order_by(Term.term_name)
                .limit(max_rows)
            )
        ).scalars().all()
        records: list[dict[str, Any]] = []
        for t in terms:
            rec: dict[str, Any] = {
                "term_name": t.term_name,
                "standard_name": t.standard_name,
                "english_term": t.english_term,
                "definition": t.definition,
                "category": t.category,
                "standard_number": t.standard_number,
            }
            if t.aliases:
                rec["aliases"] = t.aliases
            if t.synonyms:
                rec["synonyms"] = t.synonyms
            for k, v in (t.extras or {}).items():
                rec[str(k)] = v
            # 兼容两种 column_aliases 方向：新表头→原始字段 与 原始字段→新表头
            for a, b_raw in (b.column_aliases or {}).items():
                if a in rec:
                    rec[str(b_raw)] = rec[a]
                if b_raw in rec:
                    rec[str(a)] = rec[b_raw]
            records.append(rec)
        data[b.name] = records
    return data


# ---------------------------------------------------------------------------
# 内部嵌入端点令牌（无状态 HMAC：跨进程可用，TTL 自动过期）
# ---------------------------------------------------------------------------
def issue_embed_token(kb_id) -> str:
    """签发带过期时间的 HMAC 令牌（后端/worker 不同进程共享 SECRET_KEY）。"""
    from app.core.config import settings

    exp = int(time.time()) + EMBED_TOKEN_TTL
    payload = f"{kb_id}:{exp}"
    sig = hmac.new(
        settings.SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:32]
    return f"{exp}.{sig}"


def validate_embed_token(token: str, kb_id) -> bool:
    """校验令牌：签名一致且未过期。"""
    from app.core.config import settings

    if not token:
        return False
    try:
        exp_s, sig = token.split(".", 1)
        exp = int(exp_s)
    except (ValueError, AttributeError):
        return False
    if int(time.time()) > exp:
        return False
    payload = f"{kb_id}:{exp}"
    expect = hmac.new(
        settings.SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:32]
    return hmac.compare_digest(sig, expect)


def revoke_embed_token(token: str) -> None:
    """无状态令牌无需吊销：TTL 自动过期（保留兼容调用）。"""



# ---------------------------------------------------------------------------
# 嵌入结果缓存（进程内，避免脚本每类别重复编码同一批术语记录）
# ---------------------------------------------------------------------------
_embed_cache: dict[str, list[float]] = {}
_embed_cache_lock = threading.Lock()
_EMBED_CACHE_MAX = 20000


async def _cache_embed(texts: list[str]) -> list[list[float]]:
    """带缓存的嵌入：命中直接返回，未命中批量编码后写入。"""
    from app.services.embedding.embedding_service import embedding_service

    cached: list[list[float] | None] = []
    missing: list[str] = []
    missing_idx: list[int] = []
    with _embed_cache_lock:
        for i, t in enumerate(texts):
            v = _embed_cache.get(t)
            if v is not None:
                cached.append(v)
            else:
                cached.append(None)
                missing.append(t)
                missing_idx.append(i)
    if missing:
        vectors = await embedding_service.embed(missing)
        with _embed_cache_lock:
            if len(_embed_cache) + len(missing) > _EMBED_CACHE_MAX:
                _embed_cache.clear()
            for t, v in zip(missing, vectors):
                _embed_cache[t] = v
        for idx, v in zip(missing_idx, vectors):
            cached[idx] = v
    return [v for v in cached if v is not None]


async def warmup_embed() -> None:
    """抽取前预热：加载 BGE-M3 模型并缓存预热文本，避免脚本超时窗口内首次加载。"""
    await _cache_embed(["预热文本"])


def embed_endpoint_url(kb_id) -> str:
    """内部嵌入端点地址（子进程回调父进程）。"""
    from app.core.config import settings

    base = (settings.SCRIPT_EMBED_BASE_URL or "http://127.0.0.1:8000").rstrip("/")
    return f"{base}{EMBED_ENDPOINT_PATH.format(kb_id=kb_id)}"



__all__ = [
    "EMBED_MAX_TEXTS",
    "EMBED_TOKEN_TTL",
    "build_script_code",
    "embed_endpoint_url",
    "issue_embed_token",
    "load_term_data",
    "revoke_embed_token",
    "validate_embed_token",
]
