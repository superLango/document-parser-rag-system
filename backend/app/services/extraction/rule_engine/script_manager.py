"""自定义处理脚本管理（按目录加载 / 执行 / I-O 契约）。

- ``SCRIPT_IO_REGISTRY``：各目录（post / validation）的入参 / 出参契约，
  供前端右侧面板展示。
- ``ScriptManager``：从 ``kb_scripts`` 加载启用脚本并按 ``sort_order`` 执行，
  单条脚本失败不阻断整条链路（记录日志并继续）。

I-O 契约（脚本统一 ``def run(args)``）：
- post（抽取后处理）：对抽取结果归一化 / 去重 / 补全。
  - 入参 args：records / category / doc_id
  - 出参 result：{"records"（必填）, "rejected"?（可选）, "meta"?（可选）}
- validation（校验）：对抽取结果做合法性 / 枚举 / 一致性校验。
  - 入参 args：records / category / doc_id
  - 出参 result：{"records"（必填）, "rejected"?（可选）, "meta"?（可选）}

``rejected`` 为可选：脚本只修改不剔除时可不返回，引擎自动按空列表处理。
脚本内可通过注入的 ``kb_tools`` 调用内置能力（后处理 / 校验 / 术语集访问）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.extraction_config import KbRuleGroupItem, KbScript
from app.services.extraction.extraction_models import ExtractionTarget
from app.services.extraction.rule_engine.script_executor import run_script
from app.services.extraction.rule_engine.script_tools import (
    TOOL_CATALOG,
    KbScriptTools,
)

logger = get_logger(__name__)

# 各目录的入参 / 出参契约（供前端右侧"可传入参数 / 返回参数"展示）
SCRIPT_IO_REGISTRY: dict[str, dict[str, Any]] = {
    "post": {
        "name": "抽取后处理",
        "description": "在 LLM 抽取并经过内置规则后执行，对结果做归一化 / 去重 / 补全。",
        "input": [
            {"name": "records", "type": "list[dict]", "desc": "抽取结果记录列表"},
            {"name": "category", "type": "str", "desc": "当前类别名"},
            {"name": "doc_id", "type": "str", "desc": "文档 ID"},
        ],
        "output": [
            {"name": "records", "type": "list[dict]", "desc": "保留的记录列表（必填）"},
            {"name": "rejected", "type": "list[dict]", "desc": "被剔除的记录列表（可选，缺省为空）"},
            {"name": "meta", "type": "dict", "desc": "附加元信息（可选）"},
        ],
        "tools": TOOL_CATALOG,
    },
    "validation": {
        "name": "校验",
        "description": "对抽取结果做合法性 / 枚举 / 一致性校验，剔除不合规记录。",
        "input": [
            {"name": "records", "type": "list[dict]", "desc": "待校验的记录列表"},
            {"name": "category", "type": "str", "desc": "当前类别名"},
            {"name": "doc_id", "type": "str", "desc": "文档 ID"},
        ],
        "output": [
            {"name": "records", "type": "list[dict]", "desc": "通过校验的记录列表（必填）"},
            {"name": "rejected", "type": "list[dict]", "desc": "校验不通过的记录列表（可选，缺省为空）"},
            {"name": "meta", "type": "dict", "desc": "附加元信息（可选）"},
        ],
        "tools": TOOL_CATALOG,
    },
}


class ScriptManager:
    """脚本加载与执行管理器。"""

    async def load_by_folder(
        self,
        db: AsyncSession,
        kb_id: str,
        folder: str,
    ) -> list[KbScript]:
        """加载某目录下启用且排序的脚本。"""
        rows = (
            await db.execute(
                select(KbScript)
                .where(KbScript.kb_id == str(kb_id), KbScript.folder == folder)
                .order_by(KbScript.sort_order, KbScript.created_at)
            )
        ).scalars().all()
        return [r for r in rows if r.enabled]

    async def load_by_category(
        self,
        db: AsyncSession,
        kb_id: str,
        category: str,
        stage: str,
    ) -> list[KbScript]:
        """按类别 + 阶段，从规则组加载启用脚本（按 sort_order 顺序执行）。

        规则项属于某规则组（关联 Schema 模板），运行时按 ``category_name``
        与抽取类别名（feature）匹配。未配置任何规则项时返回空列表（透传）。
        """
        items = (
            await db.execute(
                select(KbRuleGroupItem)
                .where(
                    KbRuleGroupItem.kb_id == str(kb_id),
                    KbRuleGroupItem.category_name == category,
                    KbRuleGroupItem.stage == stage,
                )
                .order_by(
                    KbRuleGroupItem.sort_order, KbRuleGroupItem.created_at
                )
            )
        ).scalars().all()
        if not items:
            return []
        script_ids = [it.script_id for it in items]
        scripts = (
            await db.execute(
                select(KbScript).where(KbScript.id.in_(script_ids))
            )
        ).scalars().all()
        script_map = {s.id: s for s in scripts}
        return [
            script_map[it.script_id]
            for it in items
            if it.script_id in script_map and script_map[it.script_id].enabled
        ]

    async def run_folder(
        self,
        db: AsyncSession,
        kb_id: str,
        folder: str,
        args: dict[str, Any],
        timeout: float = 10,
        target: ExtractionTarget | None = None,
        kb_tool: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """顺序执行某目录下的全部启用脚本，返回结果列表。

        单条脚本失败不阻断后续（记录日志并继续）。
        有 ``target`` 时注入 ``kb_tools`` 工具句柄（供脚本调用内置后处理能力）。
        """
        scripts = await self.load_by_folder(db, kb_id, folder)
        inject: dict[str, Any] = {}
        if target is not None:
            inject["kb_tools"] = KbScriptTools(
                target=target, kb_id=str(kb_id), db=db, kb_tool=kb_tool
            )
        results: list[dict[str, Any]] = []
        for s in scripts:
            result = await run_script(
                s.code, args, timeout=timeout, on_error="skip", inject=inject
            )
            if result is not None:
                results.append({"script_id": str(s.id), "name": s.name, **result})
                # 链式传递：把当前脚本输出的 records 写回 args，作为下一个脚本的输入
                if isinstance(result.get("records"), list):
                    args["records"] = result["records"]
            else:
                logger.warning("脚本执行失败被跳过", script_id=str(s.id), name=s.name)
        return results

    # ------------------------------------------------------------------
    # post / validation 阶段：整理记录
    # ------------------------------------------------------------------
    async def apply_records(
        self,
        db: AsyncSession,
        kb_id: str,
        folder: str,
        records: list[dict[str, Any]],
        category: str,
        doc_id: str,
        timeout: float = 10,
        target: ExtractionTarget | None = None,
        kb_tool: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """执行 post / validation 脚本，返回 (kept_records, rejected_records)。

        按类别从规则组加载该阶段脚本（``load_by_category``），按 ``sort_order``
        顺序执行；未配置任何规则时透传（原样保留）。有 ``target`` 时向命名空间
        注入 ``kb_tools`` 工具句柄（含 db，脚本可调用后处理 / 术语集访问等能力）。
        """
        scripts = await self.load_by_category(db, kb_id, category, folder)
        args: dict[str, Any] = {
            "records": records,
            "category": category,
            "doc_id": doc_id,
        }
        inject: dict[str, Any] = {}
        if target is not None:
            inject["kb_tools"] = KbScriptTools(
                target=target, kb_id=str(kb_id), db=db, kb_tool=kb_tool
            )
        kept: list[dict[str, Any]] = list(records)
        rejected: list[dict[str, Any]] = []
        for s in scripts:
            result = await run_script(
                s.code, args, timeout=timeout, on_error="skip", inject=inject
            )
            if result is None:
                logger.warning(
                    "脚本执行失败被跳过",
                    script_id=str(s.id),
                    name=s.name,
                    category=category,
                    stage=folder,
                )
                continue
            if isinstance(result.get("records"), list):
                kept = result["records"]
                args["records"] = kept  # 链式传递
            if isinstance(result.get("rejected"), list):
                rejected.extend(result["rejected"])
        return kept, rejected


# 模块级单例
script_manager = ScriptManager()