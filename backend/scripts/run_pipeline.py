#!/usr/bin/env python
"""端到端文档处理流水线编排脚本。

执行顺序：清理 → Schema → 上传 → OCR解析 → 分块入库 → 流式抽取 → 验证

用法：
    python scripts/run_pipeline.py --step all          # 全流程
    python scripts/run_pipeline.py --step cleanup      # 仅清理
    python scripts/run_pipeline.py --step parse        # 仅解析（需先 upload）
    python scripts/run_pipeline.py --step index        # 仅入库
    python scripts/run_pipeline.py --step extract      # 仅抽取
    python scripts/run_pipeline.py --step verify       # 仅验证
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import traceback
import uuid
from pathlib import Path

# ---------------------------------------------------------------
# 进程启动方式必须在导入 torch / FlagEmbedding / langextract 之前设置
# 否则 bge-m3 加载后主进程已有 torch CUDA 线程池，langextract 内部
# 触发 subprocess.Popen 会与 torch work_stealing_thread_pool 冲突：
#   F work_stealing_thread_pool.cc:303] Check failed: is_forking != was_forking
# forkserver 启动方式让所有后续 fork 从独立的 server 进程派生，
# server 进程不加载 torch，子进程可安全使用 torch 推理。
# 同时禁用 HuggingFace tokenizers 并行（避免其内部 fork）。
# ---------------------------------------------------------------
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")
import multiprocessing as _mp
try:
    _mp.set_start_method("forkserver")
except RuntimeError:
    # 已设置过（如重复调用）
    pass

# ---------------------------------------------------------------
# 预热 tiktoken + platform.uname().processor（关键！避免 langextract
# 并发调用 vLLM 时 fork 崩溃）
#
# 根因：platform.uname_result.processor 是 @functools.cached_property，
# 延迟加载。第一次访问时调用 subprocess.check_output(['uname', '-p']) → fork。
# openai SDK 在 chat.completions.create 时会访问 platform.system()/
# platform.machine()，某些路径触发 uname().__iter__()，迭代访问 lazy 的
# processor 属性 → fork。
#
# 若 lazy 加载发生在多线程并发场景（langextract 用 ThreadPoolExecutor
# 并发调用 vLLM），fork 会与已初始化的 torch Intel TBB
# work_stealing_thread_pool 冲突：
#   F work_stealing_thread_pool.cc:303] Check failed: is_forking != was_forking
#
# tiktoken 的 encoding lazy 加载同样会 fork uname -p。
#
# 修复：在程序启动时（torch 加载前）预热，让 lazy 加载在单线程完成并缓存。
# ---------------------------------------------------------------
try:
    import tiktoken as _tiktoken
    _tiktoken.get_encoding("cl100k_base")
    _tiktoken.get_encoding("o200k_base")
except Exception as _e:
    print(f"[WARN] tiktoken 预热失败: {_e}", flush=True)

try:
    import platform as _platform
    # 触发 uname_result.processor 的 lazy 加载并缓存
    # 后续多线程访问直接读缓存，不再 fork
    _uname = _platform.uname()
    _ = _uname.processor  # 触发 subprocess.check_output(['uname', '-p'])
    _ = _platform.processor()  # 同样预热
except Exception as _e:
    print(f"[WARN] platform.uname 预热失败: {_e}", flush=True)

# 确保能导入 app 模块（脚本位于 backend/scripts/，app 位于 backend/app/）
_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))
os.chdir(_BACKEND_DIR)

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy import func  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.schema_model import SchemaConfig  # noqa: E402
from app.services.extraction_service import extraction_service  # noqa: E402
from app.services.storage_service import storage_service  # noqa: E402
from app.services.vector_store import vector_store  # noqa: E402

# ============================================================
# 配置
# ============================================================
PDF_PATH = "/home/hanson/doc_parse_project/test_standard_doc/GB-T1220-2007 不锈钢棒.pdf"
PDF_FILENAME = "GB-T1220-2007 不锈钢棒.pdf"

# 全局状态（跨步骤共享）
_parent_schema_id: uuid.UUID | None = None
_doc_id: uuid.UUID | None = None


def _banner(title: str) -> None:
    print(f"\n{'=' * 60}\n  {title}\n{'=' * 60}")


def _gpu_mem() -> str:
    try:
        import subprocess
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        return f"{out} MiB"
    except Exception:
        return "N/A"


# ============================================================
# Step 1: 数据清理
# ============================================================
async def cleanup_all() -> None:
    _banner("Step 1: 数据清理")
    assert settings.APP_ENV == "development", "仅允许在 development 环境执行清理"

    # 1a. Milvus 集合
    print("[1/4] 清空 Milvus doc_chunks 集合...")
    try:
        await vector_store.delete_all()
        print("  ✓ Milvus 集合已删除（下次插入自动重建）")
    except Exception as exc:
        print(f"  ! Milvus 清理失败（可能未初始化）: {exc}")

    # 1b. SeaweedFS documents 桶
    print("[2/4] 清空 SeaweedFS documents 桶...")
    try:
        client = storage_service._get_client()
        # 列出并删除所有对象
        paginator = client.get_paginator("list_objects_v2")
        deleted_count = 0
        for page in paginator.paginate(Bucket=settings.MINIO_BUCKET):
            objects = page.get("Contents", [])
            if not objects:
                continue
            resp = client.delete_objects(
                Bucket=settings.MINIO_BUCKET,
                Delete={"Objects": [{"Key": o["Key"]} for o in objects]},
            )
            deleted_count += len(objects)
        print(f"  ✓ SeaweedFS 已删除 {deleted_count} 个对象")
    except Exception as exc:
        print(f"  ! SeaweedFS 清理失败: {exc}")

    # 1c. PostgreSQL 表（TRUNCATE CASCADE）
    print("[3/4] 清空 PostgreSQL 表 (documents/tasks/schema_configs)...")
    async with AsyncSessionLocal() as db:
        await db.execute(text("TRUNCATE documents RESTART IDENTITY CASCADE"))
        await db.execute(text("TRUNCATE tasks RESTART IDENTITY CASCADE"))
        await db.execute(text("TRUNCATE schema_configs RESTART IDENTITY CASCADE"))
        await db.commit()
        print("  ✓ documents / tasks / schema_configs 已清空")

    # 1d. Redis 缓存（可选，失败不影响）
    print("[4/4] 清理 Redis rag 缓存...")
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL)
        # 清理 RAG 相关缓存键
        for pattern in ("rag:response:*", "rag:retrieval:*"):
            keys = await r.keys(pattern)
            if keys:
                await r.delete(*keys)
        await r.close()
        print("  ✓ Redis rag 缓存已清理")
    except Exception as exc:
        print(f"  ! Redis 清理跳过: {exc}")

    # 验证
    async with AsyncSessionLocal() as db:
        doc_cnt = await db.scalar(select(func.count()).select_from(Document))
        schema_cnt = await db.scalar(select(func.count()).select_from(SchemaConfig))
    print(f"\n验证: documents={doc_cnt}, schema_configs={schema_cnt} (期望均为 0)")


# ============================================================
# Step 2: 创建 Schema（1 父 + 6 子）
# ============================================================
async def create_schema() -> uuid.UUID:
    global _parent_schema_id
    _banner("Step 2: 创建 Schema（1 父 + 6 子，共 27 字段）")

    parent = SchemaConfig(
        name="不锈钢棒材标准信息抽取",
        description="GB/T 1220 不锈钢棒标准结构化抽取，覆盖标准基本信息与五大性能大类",
        parent_id=None,
        schema_definition=[],  # 父分类字段为空
        sample_fields={},
        is_active=True,
        sort_order=0,
    )

    # 子 Schema 定义：name, sort_order, fields(列表), sample_fields
    children_def = [
        {
            "name": "标准基本信息",
            "sort_order": 1,
            "fields": [
                {"name": "标准名称", "type": "string", "description": "标准的正式名称，如 不锈钢棒", "required": True},
                {"name": "标准编号", "type": "string", "description": "标准编号，如 GB/T 1220-2007", "required": True},
            ],
            "samples": {"标准名称": "不锈钢棒", "标准编号": "GB/T 1220-2007"},
        },
        {
            "name": "化学成分",
            "sort_order": 2,
            "fields": _perf_fields("化学成分", "化学成分元素符号，如 C/Si/Mn/P/S/Cr/Ni/Mo/Cu/Ti/Nb/V/W/Co/Al/N", "%", "不适用"),
            "samples": {
                "化学成分_牌号": "06Cr19Ni10",
                "化学成分_项目": "C",
                "化学成分_单位": "%",
                "化学成分_温度": "不适用",
                "化学成分_标准要求": "≤0.08",
            },
        },
        {
            "name": "室温拉伸性能",
            "sort_order": 3,
            "fields": _perf_fields("室温拉伸", "拉伸性能项目，如 规定非比例延伸强度Rp0.2、抗拉强度Rm、断后伸长率A、断面收缩率Z", "MPa或%", "室温"),
            "samples": {
                "室温拉伸_牌号": "06Cr19Ni10",
                "室温拉伸_项目": "规定非比例延伸强度Rp0.2",
                "室温拉伸_单位": "MPa",
                "室温拉伸_温度": "室温",
                "室温拉伸_标准要求": "≥205",
            },
        },
        {
            "name": "冲击性能",
            "sort_order": 4,
            "fields": _perf_fields("冲击性能", "冲击性能项目，如 冲击吸收功KV2、冲击韧性", "J或J/cm²", "室温或低温如-196℃"),
            "samples": {
                "冲击性能_牌号": "12Cr13",
                "冲击性能_项目": "冲击吸收功KV2",
                "冲击性能_单位": "J",
                "冲击性能_温度": "室温",
                "冲击性能_标准要求": "≥55",
            },
        },
        {
            "name": "硬度性能",
            "sort_order": 5,
            "fields": _perf_fields("硬度性能", "硬度项目，如 HBW、HRC、HV", "HBW或HRC", "室温"),
            "samples": {
                "硬度性能_牌号": "06Cr19Ni10",
                "硬度性能_项目": "HBW",
                "硬度性能_单位": "HBW",
                "硬度性能_温度": "室温",
                "硬度性能_标准要求": "≤187",
            },
        },
        {
            "name": "气体分析",
            "sort_order": 6,
            "fields": _perf_fields("气体分析", "气体元素，如 O、N、H", "ppm或μg/g", "不适用"),
            "samples": {
                "气体分析_牌号": "06Cr19Ni10",
                "气体分析_项目": "N",
                "气体分析_单位": "ppm",
                "气体分析_温度": "不适用",
                "气体分析_标准要求": "≤0.10",
            },
        },
    ]

    async with AsyncSessionLocal() as db:
        db.add(parent)
        await db.flush()
        parent_id = parent.id

        for cd in children_def:
            child = SchemaConfig(
                name=cd["name"],
                description=f"{cd['name']}字段定义",
                parent_id=parent_id,
                schema_definition=cd["fields"],
                sample_fields=cd["samples"],
                is_active=True,
                sort_order=cd["sort_order"],
            )
            db.add(child)
        await db.commit()

        # 验证合并后字段数
        children = await db.execute(
            select(SchemaConfig).where(SchemaConfig.parent_id == parent_id).order_by(SchemaConfig.sort_order)
        )
        child_list = children.scalars().all()
        total_fields = sum(len(c.schema_definition or []) for c in child_list)
        print(f"  ✓ 父分类 ID: {parent_id}")
        print(f"  ✓ 子 Schema 数: {len(child_list)}")
        print(f"  ✓ 合并后总字段数: {total_fields} (期望 27)")

    _parent_schema_id = parent_id
    return parent_id


def _perf_fields(prefix: str, project_desc: str, unit_desc: str, temp_desc: str) -> list[dict]:
    """生成性能大类的 5 字段模板。"""
    return [
        {"name": f"{prefix}_牌号", "type": "string", "description": f"{prefix}对应的不锈钢牌号，如 06Cr19Ni10、12Cr13", "required": False},
        {"name": f"{prefix}_项目", "type": "string", "description": project_desc, "required": False},
        {"name": f"{prefix}_单位", "type": "string", "description": unit_desc, "required": False},
        {"name": f"{prefix}_温度", "type": "string", "description": f"试验温度，{temp_desc}", "required": False},
        {"name": f"{prefix}_标准要求", "type": "string", "description": "标准要求的最小值/最大值/范围，如 ≥205、≤0.08", "required": False},
    ]


# ============================================================
# Step 3: 上传 PDF + 创建 Document
# ============================================================
async def upload_pdf() -> uuid.UUID:
    global _doc_id
    _banner("Step 3: 上传 PDF + 创建 Document")

    assert os.path.isfile(PDF_PATH), f"PDF 不存在: {PDF_PATH}"
    with open(PDF_PATH, "rb") as f:
        content = f.read()
    file_size = len(content)
    print(f"  PDF 大小: {file_size} bytes ({file_size / 1024 / 1024:.1f} MB)")

    object_name = f"docs/{uuid.uuid4().hex}/{PDF_FILENAME}"
    await storage_service.upload(object_name, content, "application/pdf")
    print(f"  ✓ 已上传到 SeaweedFS: {object_name}")

    async with AsyncSessionLocal() as db:
        doc = Document(
            filename=PDF_FILENAME,
            file_size=file_size,
            file_type="pdf",
            status="pending",
            minio_object_name=object_name,
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        doc_id = doc.id

    print(f"  ✓ Document 记录已创建: {doc_id}")
    _doc_id = doc_id
    return doc_id


# ============================================================
# Step 4: OCR 解析
# ============================================================
async def parse_document() -> None:
    _banner("Step 4: OCR 解析 (GLM-OCR hybrid)")
    print(f"  GPU 显存(解析前): {_gpu_mem()}")

    from app.tasks.document_tasks import parse_document_impl

    doc_id = await _await_doc_id()
    # 不传 schema_id，跳过解析内结构化抽取（单独用流式抽取）
    await parse_document_impl(str(doc_id), None, None, {})

    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, doc_id)
        print(f"  ✓ 解析状态: {doc.status}")
        print(f"  ✓ 解析文本长度: {len(doc.parsed_text or '')}")
        print(f"  ✓ OCR 引擎: {(doc.layout_data or {}).get('ocr_engine', 'N/A')}")
        text_preview = (doc.parsed_text or "")[:200].replace("\n", " ")
        print(f"  ✓ 文本预览: {text_preview}...")
    print(f"  GPU 显存(解析后): {_gpu_mem()}")


# ============================================================
# Step 5: 分块入库
# ============================================================
async def index_document() -> None:
    _banner("Step 5: 分块入库 (结构感知 + 表格独立分块 + bge-m3 max_length=8192)")
    print(f"  GPU 显存(入库前): {_gpu_mem()}")

    from app.tasks.rag_tasks import index_document_impl

    doc_id = await _await_doc_id()
    result = await index_document_impl(str(doc_id), {})

    print(f"  ✓ 分块总数: {result.get('chunk_count', '?')}")
    print(f"  ✓ 表格分块数: {result.get('table_chunk_count', '?')}")
    print(f"  ✓ 入库向量数: {result.get('inserted', '?')}")
    print(f"  ✓ 删除旧分块: {result.get('deleted_old', '?')}")
    print(f"  ✓ 缓存失效: {result.get('cache_invalidated', '?')}")
    print(f"  GPU 显存(入库后): {_gpu_mem()}")


# ============================================================
# Step 6: 向量检索召回 + 分类列表抽取 (gemma4:26b)
# ============================================================
def _str_field(name: str, desc: str) -> dict:
    """快捷构造字符串字段定义。"""
    return {"name": name, "type": "string", "description": desc, "required": False}


def _long_fields() -> list[dict]:
    """长表格式统一5字段定义。"""
    return [
        _str_field("牌号", "不锈钢牌号，如 06Cr19Ni10、12Cr13"),
        _str_field("项目", "测试/分析项目名称，如 C、Si、Cr、规定非比例延伸强度Rp0.2、抗拉强度Rm、冲击吸收功Aku2、HBW 等"),
        _str_field("单位", "项目对应的单位，如 %、N/mm2、J、HBW、ppm"),
        _str_field("温度", "试验温度，如 室温、-196℃、不适用"),
        _str_field("标准要求", "标准规定的最小值/最大值/范围，如 ≥205、≤0.08、18.00~20.00"),
    ]


def _long_records(grade: str, items: list[tuple[str, str, str, str]]) -> list[dict]:
    """从宽表数据生成长表记录列表。

    Args:
        grade: 牌号。
        items: [(项目, 单位, 温度, 标准要求), ...] 列表。
    """
    return [
        {"牌号": grade, "项目": proj, "单位": unit, "温度": temp, "标准要求": req}
        for proj, unit, temp, req in items
    ]


def _build_extraction_categories() -> list[dict]:
    """构造分类型抽取定义：10 个大类，统一长表5字段。

    文档驱动抽取（方案A）：
    - 去除「气体分析」大类（基础表 sm_feature 无此大类）
    - 拆分原「冲击」为「夏比冲击」（对齐 sm_feature.NAME）
    - 拆分原「硬度」为「布氏硬度」「维氏硬度」「洛氏硬度」（对齐 sm_feature.NAME）
    - 补充「高温拉伸」「组合持久」「高温光滑持久」（文档实际涉及）
    - 大类名严格对齐 sm_feature.NAME，便于动态白名单与抽取后校验生效

    类别清单（10 个）：
        基础信息（single）、化学成分、室温拉伸、夏比冲击、
        布氏硬度、维氏硬度、洛氏硬度、高温拉伸、组合持久、高温光滑持久

    文档驱动抽取流程（extraction_service.extract_categories_with_retrieval）：
    1. 调用 project_dict_service.detect_document_categories(doc_id)
       识别文档实际涉及的大类
    2. 对每个 category 检查：
       (a) 不在 sm_feature.NAME 中 → 跳过（基础表无此大类则不抽取）
       (b) 文档未涉及该大类 → 跳过
    3. 仅对满足条件的类别执行向量检索 + LLM 抽取 + 动态白名单 + 抽取后校验
    """
    categories: list[dict] = []

    # ----------------------------------------------------------
    # 1. 基础信息（单条记录，top_k=3 精准召回封面页）
    # ----------------------------------------------------------
    categories.append({
        "name": "基础信息",
        "query": "中华人民共和国国家标准 GB/T 1220 不锈钢棒 Stainless steel bars 2007 代替",
        "single": True,
        "top_k": 3,
        "fields": [
            _str_field("标准名称", "标准的正式名称，如 不锈钢棒"),
            _str_field("标准编号", "标准编号，如 GB/T 1220-2007"),
        ],
    })

    # ----------------------------------------------------------
    # 2. 化学成分（长表格式，sm_feature.NAME='化学成分', FLAG='CA'）
    # ----------------------------------------------------------
    chem_example_text = (
        "| 新牌号 | C | Si | Mn | P | S | Cr | Ni | Mo | Cu | N |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| 06Cr19Ni10 | ≤0.08 | ≤1.00 | ≤2.00 | ≤0.045 | ≤0.030 | 18.00~20.00 | 8.00~11.00 | — | — | — |\n"
        "| 12Cr13 | ≤0.15 | ≤1.00 | ≤1.00 | ≤0.040 | ≤0.030 | 11.50~13.50 | ≤0.60 | ≤0.60 | — | — |"
    )
    chem_records = (
        _long_records("06Cr19Ni10", [
            ("C", "%", "不适用", "≤0.08"),
            ("Si", "%", "不适用", "≤1.00"),
            ("Mn", "%", "不适用", "≤2.00"),
            ("P", "%", "不适用", "≤0.045"),
            ("S", "%", "不适用", "≤0.030"),
            ("Cr", "%", "不适用", "18.00~20.00"),
            ("Ni", "%", "不适用", "8.00~11.00"),
        ])
        + _long_records("12Cr13", [
            ("C", "%", "不适用", "≤0.15"),
            ("Si", "%", "不适用", "≤1.00"),
            ("Mn", "%", "不适用", "≤1.00"),
            ("P", "%", "不适用", "≤0.040"),
            ("S", "%", "不适用", "≤0.030"),
            ("Cr", "%", "不适用", "11.50~13.50"),
            ("Ni", "%", "不适用", "≤0.60"),
        ])
    )
    categories.append({
        "name": "化学成分",
        "query": "化学成分 牌号 C Si Mn P S Cr Ni Mo Cu N 质量分数 不锈钢 表1 表2 表3 表4 表5",
        "fields": _long_fields(),
        "records": chem_records,
        "example_text": chem_example_text,
    })

    # ----------------------------------------------------------
    # 3. 室温拉伸（长表格式，sm_feature.NAME='室温拉伸', FLAG='RT'）
    # ----------------------------------------------------------
    tensile_example_text = (
        "| 新牌号 | 规定非比例延伸强度Rp0.2/(N/mm2) | 抗拉强度Rm/(N/mm2) | 断后伸长率A/% | 断面收缩率Z/% |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 06Cr19Ni10 | ≥205 | ≥520 | ≥40 | ≥60 |\n"
        "| 12Cr13 | ≥205 | ≥450 | ≥20 | ≥60 |"
    )
    tensile_records = (
        _long_records("06Cr19Ni10", [
            ("规定非比例延伸强度Rp0.2", "N/mm2", "室温", "≥205"),
            ("抗拉强度Rm", "N/mm2", "室温", "≥520"),
            ("断后伸长率A", "%", "室温", "≥40"),
            ("断面收缩率Z", "%", "室温", "≥60"),
        ])
        + _long_records("12Cr13", [
            ("规定非比例延伸强度Rp0.2", "N/mm2", "室温", "≥205"),
            ("抗拉强度Rm", "N/mm2", "室温", "≥450"),
            ("断后伸长率A", "%", "室温", "≥20"),
            ("断面收缩率Z", "%", "室温", "≥60"),
        ])
    )
    categories.append({
        "name": "室温拉伸",
        "query": "室温拉伸 规定非比例延伸强度Rp0.2 抗拉强度Rm 断后伸长率A 断面收缩率Z 力学性能 牌号 表6 表7 表8",
        "fields": _long_fields(),
        "records": tensile_records,
        "example_text": tensile_example_text,
    })

    # ----------------------------------------------------------
    # 4. 夏比冲击（长表格式，sm_feature.NAME='夏比冲击', FLAG='CI'）
    # 对齐 sm_feature.NAME（旧版「冲击」改为「夏比冲击」）
    # ----------------------------------------------------------
    impact_example_text = (
        "| 新牌号 | 冲击吸收功Aku2/J |\n"
        "| --- | --- |\n"
        "| 12Cr13 | ≥55 |\n"
        "| 20Cr13 | ≥35 |"
    )
    impact_records = (
        _long_records("12Cr13", [("冲击吸收功Aku2", "J", "室温", "≥55")])
        + _long_records("20Cr13", [("冲击吸收功Aku2", "J", "室温", "≥35")])
    )
    categories.append({
        "name": "夏比冲击",
        "query": "夏比冲击 冲击吸收功 Aku2 KV2 J 冲击韧性 力学性能 牌号 表6 表7 表8",
        "fields": _long_fields(),
        "records": impact_records,
        "example_text": impact_example_text,
    })

    # ----------------------------------------------------------
    # 5. 布氏硬度（长表格式，sm_feature.NAME='布氏硬度', FLAG='HB'）
    # 拆分原「硬度」为三类，便于基础表向量匹配精准过滤
    # ----------------------------------------------------------
    hbw_example_text = (
        "| 新牌号 | HBW |\n"
        "| --- | --- |\n"
        "| 06Cr19Ni10 | ≤187 |\n"
        "| 12Cr13 | ≤200 |"
    )
    hbw_records = (
        _long_records("06Cr19Ni10", [("HBW", "HBW", "室温", "≤187")])
        + _long_records("12Cr13", [("HBW", "HBW", "室温", "≤200")])
    )
    categories.append({
        "name": "布氏硬度",
        "query": "布氏硬度 HBW 力学性能 牌号 表6 表7 表8 不锈钢棒",
        "fields": _long_fields(),
        "records": hbw_records,
        "example_text": hbw_example_text,
    })

    # ----------------------------------------------------------
    # 6. 维氏硬度（长表格式，sm_feature.NAME='维氏硬度', FLAG='HV'）
    # ----------------------------------------------------------
    hv_example_text = (
        "| 新牌号 | HV |\n"
        "| --- | --- |\n"
        "| 06Cr19Ni10 | ≤200 |"
    )
    hv_records = _long_records("06Cr19Ni10", [("HV", "HV", "室温", "≤200")])
    categories.append({
        "name": "维氏硬度",
        "query": "维氏硬度 HV 力学性能 牌号 表6 表7 表8 不锈钢棒",
        "fields": _long_fields(),
        "records": hv_records,
        "example_text": hv_example_text,
    })

    # ----------------------------------------------------------
    # 7. 洛氏硬度（长表格式，sm_feature.NAME='洛氏硬度', FLAG='YD'）
    # ----------------------------------------------------------
    hrc_example_text = (
        "| 新牌号 | HRC |\n"
        "| --- | --- |\n"
        "| 06Cr19Ni10 | ≤90 |"
    )
    hrc_records = _long_records("06Cr19Ni10", [("HRC", "HRC", "室温", "≤90")])
    categories.append({
        "name": "洛氏硬度",
        "query": "洛氏硬度 HRC HRB HRA 力学性能 牌号 表6 表7 表8 不锈钢棒",
        "fields": _long_fields(),
        "records": hrc_records,
        "example_text": hrc_example_text,
    })

    # ----------------------------------------------------------
    # 8. 高温拉伸（长表格式，sm_feature.NAME='高温拉伸', FLAG='HT'）
    # 文档中存在高温拉伸性能数据表
    # ----------------------------------------------------------
    ht_tensile_example_text = (
        "| 新牌号 | 试验温度/℃ | 规定非比例延伸强度Rp0.2/(N/mm2) | 抗拉强度Rm/(N/mm2) | 断后伸长率A/% | 断面收缩率Z/% |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| 06Cr19Ni10 | 500 | ≥145 | ≥365 | ≥25 | ≥40 |"
    )
    ht_tensile_records = _long_records("06Cr19Ni10", [
        ("规定非比例延伸强度Rp0.2", "N/mm2", "500℃", "≥145"),
        ("抗拉强度Rm", "N/mm2", "500℃", "≥365"),
        ("断后伸长率A", "%", "500℃", "≥25"),
        ("断面收缩率Z", "%", "500℃", "≥40"),
    ])
    categories.append({
        "name": "高温拉伸",
        "query": "高温拉伸 高温规定非比例延伸强度 高温抗拉强度 高温断后伸长率 高温断面收缩率 力学性能 牌号 表9",
        "fields": _long_fields(),
        "records": ht_tensile_records,
        "example_text": ht_tensile_example_text,
    })

    # ----------------------------------------------------------
    # 9. 组合持久（长表格式，sm_feature.NAME='组合持久', FLAG='GC'）
    # 文档中存在持久性能数据表
    # ----------------------------------------------------------
    combo_creep_example_text = (
        "| 新牌号 | 试验温度/℃ | 持久强度/(N/mm2) | 断后伸长率A/% | 断面收缩率Z/% |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 06Cr19Ni10 | 700 | ≥130 | ≥20 | ≥30 |"
    )
    combo_creep_records = _long_records("06Cr19Ni10", [
        ("持久强度", "N/mm2", "700℃", "≥130"),
        ("断后伸长率A", "%", "700℃", "≥20"),
        ("断面收缩率Z", "%", "700℃", "≥30"),
    ])
    categories.append({
        "name": "组合持久",
        "query": "组合持久 持久强度 高温持久 断后伸长率 断面收缩率 力学性能 牌号 表",
        "fields": _long_fields(),
        "records": combo_creep_records,
        "example_text": combo_creep_example_text,
    })

    # ----------------------------------------------------------
    # 10. 高温光滑持久（长表格式，sm_feature.NAME='高温光滑持久', FLAG='SR'）
    # 文档中存在持久性能数据表
    # ----------------------------------------------------------
    ht_smooth_creep_example_text = (
        "| 新牌号 | 试验温度/℃ | 持久断裂时间/h | 持久强度/(N/mm2) |\n"
        "| --- | --- | --- | --- |\n"
        "| 06Cr19Ni10 | 815 | ≥30 | ≥80 |"
    )
    ht_smooth_creep_records = _long_records("06Cr19Ni10", [
        ("持久断裂时间", "h", "815℃", "≥30"),
        ("持久强度", "N/mm2", "815℃", "≥80"),
    ])
    categories.append({
        "name": "高温光滑持久",
        "query": "高温光滑持久 持久断裂时间 持久强度 高温持久 力学性能 牌号 表",
        "fields": _long_fields(),
        "records": ht_smooth_creep_records,
        "example_text": ht_smooth_creep_example_text,
    })

    return categories


async def extract_with_retrieval() -> dict:
    _banner("Step 6: 向量检索召回 + 文档驱动抽取 (vLLM Qwen3-14B 并行)")

    doc_id = await _await_doc_id()
    doc_id_str = str(doc_id)

    categories = _build_extraction_categories()
    print(f"  模型: {extraction_service._config.model_id} (provider={extraction_service._config.provider})")
    print(f"  并发上限: {extraction_service._max_concurrency}")
    print(f"  候选类别数: {len(categories)}（文档驱动抽取将基于文档实际涉及的大类过滤）")
    for cat in categories:
        kind = "单条" if cat.get("single") else f"长表(示例{len(cat.get('records', []))}条)"
        topk = cat.get("top_k", 15)
        print(f"    - {cat['name']}: {len(cat['fields'])} 字段, {kind}, top_k={topk}")

    # 执行向量检索召回 + 文档驱动分类抽取
    # doc_driven=True：基础表无此大类或文档未涉及该大类则跳过抽取
    print(f"\n  开始文档驱动抽取 (max_model_len=32768, 长表格式, asyncio.gather 并行)...")
    results = await extraction_service.extract_categories_with_retrieval(
        doc_id=doc_id_str,
        categories=categories,
        top_k=15,
        doc_driven=True,
    )

    # 分离抽取结果与元信息
    meta_info = results.pop("_meta", None)
    if meta_info:
        print(f"\n  {'=' * 50}")
        print(f"  [文档驱动抽取元信息]")
        print(f"    sm_feature 大类总数: {meta_info.get('sm_feature_count', '?')}")
        print(f"    文档涉及大类: {meta_info.get('detected_features', [])}")
        print(f"    实际抽取大类: {meta_info.get('extracted_categories', [])}")
        skipped = meta_info.get("skipped", [])
        print(f"    跳过类别数: {meta_info.get('skipped_count', 0)}")
        for sk in skipped:
            print(f"      - {sk['category']}: {sk['reason']}")
        # 方案 13：rejected_records 审计
        rejected_map = meta_info.get("rejected_records", {}) or {}
        total_rejected = meta_info.get("total_rejected", 0)
        if rejected_map:
            print(f"    [跨类混入剔除审计] 总剔除数: {total_rejected}")
            for cat_name, rejected_list in rejected_map.items():
                print(f"      - {cat_name}: 剔除 {len(rejected_list)} 条")
                for r in rejected_list[:2]:
                    reason = r.get("_reject_reason", "")
                    print(f"        · {reason}")

    # 打印各类别结果
    print(f"\n  {'=' * 50}")
    total_records = 0
    for cat_name, data in results.items():
        if isinstance(data, list):
            print(f"\n  【{cat_name}】{len(data)} 条记录")
            for i, rec in enumerate(data[:5]):
                preview = ", ".join(f"{k}={v}" for k, v in list(rec.items())[:5])
                print(f"    [{i+1}] {preview}")
            if len(data) > 5:
                print(f"    ... 共 {len(data)} 条")
            total_records += len(data)
        elif isinstance(data, dict):
            print(f"\n  【{cat_name}】{len(data)} 个字段")
            for k, v in data.items():
                print(f"    {k}: {v}")
            total_records += 1 if data else 0

    print(f"\n  总记录数: {total_records}")

    # 持久化到 Document.structured_data
    final_data = {
        "categories": results,
        "category_names": list(results.keys()),
        "total_records": total_records,
        "meta": meta_info,
        "extraction_mode": "doc_driven_v2",
    }
    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, doc_id)
        doc.structured_data = final_data
        await db.commit()
    print("  ✓ 结果已持久化到 Document.structured_data")

    return final_data


# ============================================================
# Step 7: 验证
# ============================================================
async def verify_all() -> None:
    _banner("Step 7: 验证")

    doc_id = await _await_doc_id()

    # 7a. 文档状态
    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, doc_id)
        print(f"[文档] status={doc.status}, parsed_text={len(doc.parsed_text or '')}字符")
        print(f"[文档] structured_data 字段数={len(doc.structured_data or {})}")

    # 7b. Milvus 分块统计
    print("\n[Milvus 分块统计]")
    try:
        vector_store._ensure_connected()
        from pymilvus import Collection
        collection = Collection(settings.MILVUS_COLLECTION)
        collection.load()
        total = collection.num_entities
        print(f"  总分块数: {total}")

        # 查询表格分块
        results = collection.query(
            expr=f'doc_id == "{doc_id}"',
            output_fields=["chunk_id", "text", "metadata"],
            limit=100,
        )
        if results:
            table_chunks = [r for r in results if r.get("metadata", {}).get("chunk_type") == "table"]
            text_chunks = [r for r in results if r.get("metadata", {}).get("chunk_type") != "table"]
            lengths = [len(r.get("text", "")) for r in results]
            print(f"  文档分块数: {len(results)}")
            print(f"  表格分块: {len(table_chunks)}")
            print(f"  文本分块: {len(text_chunks)}")
            if lengths:
                print(f"  分块字符数: max={max(lengths)}, min={min(lengths)}, avg={sum(lengths)//len(lengths)}")
        else:
            print("  (无分块数据)")
    except Exception as exc:
        print(f"  ! Milvus 查询失败: {exc}")

    # 7c. 检索测试
    print("\n[检索测试]")
    try:
        from app.services.embedding_service import embedding_service
        query = "06Cr19Ni10 化学成分 碳含量"
        q_emb = await embedding_service.embed([query])
        dense = q_emb["dense_vectors"][0]
        sparse_raw = q_emb["sparse_indices"][0]
        sparse_milvus = {int(k): float(v) for k, v in zip(sparse_raw["indices"], sparse_raw["values"])}

        results = await vector_store.hybrid_search(dense, sparse_milvus, top_k=3)
        for i, r in enumerate(results):
            text_preview = r.get("text", "")[:80].replace("\n", " ")
            print(f"  Top-{i+1} (score={r.get('score', '?'):.4f}): {text_preview}...")
    except Exception as exc:
        print(f"  ! 检索测试失败: {exc}")

    # 7d. 抽取结果验证（列表结构）
    print("\n[抽取结果验证]")
    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, doc_id)
        data = doc.structured_data or {}

    categories = data.get("categories", {})
    if not categories:
        print("  ! 未找到抽取结果（structured_data 无 categories 键）")
        print(f"  structured_data 顶层键: {list(data.keys())}")
    else:
        total_records = data.get("total_records", 0)
        print(f"  总记录数: {total_records}")
        for cat_name, cat_data in categories.items():
            if isinstance(cat_data, list):
                # 列表结构：多牌号记录
                print(f"\n  【{cat_name}】{len(cat_data)} 条记录")
                if cat_data:
                    # 统计各字段非空率
                    field_names = list(cat_data[0].keys())
                    for fn in field_names:
                        non_empty = sum(1 for r in cat_data if r.get(fn) and r[fn] != "—")
                        print(f"    {fn}: {non_empty}/{len(cat_data)} 非空")
                    # 显示前3条
                    for i, rec in enumerate(cat_data[:3]):
                        preview = ", ".join(f"{k}={v}" for k, v in list(rec.items())[:6])
                        print(f"    [{i+1}] {preview}")
                    if len(cat_data) > 3:
                        print(f"    ... 共 {len(cat_data)} 条")
            elif isinstance(cat_data, dict):
                # 单条记录
                print(f"\n  【{cat_name}】")
                for k, v in cat_data.items():
                    print(f"    {k}: {v}")


# ============================================================
# 辅助
# ============================================================
async def _await_doc_id() -> uuid.UUID:
    global _doc_id
    if _doc_id is not None:
        return _doc_id
    # 从数据库查找最新文档
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Document).where(Document.filename == PDF_FILENAME).order_by(Document.created_at.desc())
        )
        doc = result.scalars().first()
        if doc is None:
            raise RuntimeError(f"找不到文件名为 {PDF_FILENAME} 的文档，请先执行 upload 步骤")
        _doc_id = doc.id
        return _doc_id


async def _await_parent_schema_id() -> uuid.UUID:
    global _parent_schema_id
    if _parent_schema_id is not None:
        return _parent_schema_id
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SchemaConfig).where(SchemaConfig.name == "不锈钢棒材标准信息抽取")
        )
        schema = result.scalars().first()
        if schema is None:
            raise RuntimeError("找不到父分类 Schema，请先执行 schema 步骤")
        _parent_schema_id = schema.id
        return _parent_schema_id


# ============================================================
# 主入口
# ============================================================
async def main(step: str) -> None:
    print(f"流水线步骤: {step}")
    print(f"GPU 显存(初始): {_gpu_mem()}")

    if step in ("all", "cleanup"):
        await cleanup_all()
    if step in ("all", "schema"):
        await create_schema()
    if step in ("all", "upload"):
        await upload_pdf()
    if step in ("all", "parse"):
        await parse_document()
    if step in ("all", "index"):
        await index_document()
    if step in ("all", "extract"):
        await extract_with_retrieval()
    if step in ("all", "verify"):
        await verify_all()

    print(f"\n{'=' * 60}\n  流水线完成: {step}\n  GPU 显存(最终): {_gpu_mem()}\n{'=' * 60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="端到端文档处理流水线")
    parser.add_argument(
        "--step",
        default="all",
        choices=["all", "cleanup", "schema", "upload", "parse", "index", "extract", "verify"],
        help="执行步骤",
    )
    args = parser.parse_args()

    try:
        asyncio.run(main(args.step))
    except KeyboardInterrupt:
        print("\n已中断")
    except Exception:
        traceback.print_exc()
        sys.exit(1)
