"""Platform API (P0): auth, knowledge bases, documents, tasks, API keys, audit.

Security posture (closes audit findings A1/A2):

* every platform endpoint requires a Bearer access token or an ``X-API-Key``;
* API keys are hashed at rest, scoped and revocable;
* share links are short-lived HMAC-signed tokens bound to one document;
* there is no superuser/RLS bypass; membership is checked in every handler.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import threading
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote as url_quote

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from metal_doc_agent.artifacts import write_artifact_manifest
from metal_doc_agent.canonicalize import (
    DICTIONARY_FILENAMES,
    JsonDictionaryAdapter,
    dictionary_file_for_type,
    find_new_term,
    load_dictionary_path,
    reapply_alignment,
    review_new_term,
    split_dictionary,
    write_dictionary_parts,
)
from metal_doc_agent.canonicalize.review import (
    load_override,
    save_dictionary,
)
from metal_doc_agent.canonicalize.terms import load_new_terms, save_new_terms
from metal_doc_agent.contracts import DocumentResult, Evidence
from metal_doc_agent.jobs import JobStore
from metal_doc_agent.observability import engine_metrics, readiness, render_family
from metal_doc_agent.preview import build_preview, load_layout, page_image_path
from metal_doc_agent.review import (
    FeedbackStore,
    ReviewEvent as EngineReviewEvent,
    apply_events,
    diff_records,
    field_risks,
    parse_field_path,
    risk_summary,
)
from metal_doc_agent.runner import run_job
from metal_doc_agent.schema_projection import (
    load_dictionary_index_path,
    load_template,
    project_hanson_schema,
)
from metal_doc_agent.settings import Settings

from .access import (
    KB_ROLE_RANK,
    Principal,
    accessible_kb_ids,
    default_workspace,
    kb_ids_from_text,
    kb_ids_to_text,
    kb_role,
    require_kb_role,
    require_workspace_role,
    workspace_role,
)
from .config import PlatformSettings
from .db import build_engine, build_session_factory, init_db, verify_migrations
from .export import result_table_schema, table_export_bytes
from .modules import (
    MODULES,
    ensure_module_kb,
    find_module_kb,
    module_role,
    module_spec,
    module_stats,
    module_workspace_id,
    resolve_module,
)
from .models import (
    ApiKey,
    AuditLog,
    Document,
    DocumentTask,
    FieldReviewEvent,
    IntegrationTask,
    Invitation,
    KnowledgeBase,
    KnowledgeBaseMember,
    ReviewEvent,
    User,
    Workspace,
    WorkspaceMember,
    new_id,
    utcnow,
)
from .schemas import (
    ApiKeyCreate,
    ApiKeyOut,
    AuditLogOut,
    DocumentFeedbackRequest,
    DocumentOut,
    DocumentReviewOut,
    DocumentReviewRequest,
    DocumentRiskOut,
    DictionaryAliasCreate,
    DictionaryEntryCreate,
    DictionaryEntryUpdate,
    DictionarySyncRequest,
    FieldDiffOut,
    FieldReviewBatchRequest,
    FieldReviewOut,
    FieldReviewRequest,
    InvitationAcceptOut,
    InvitationCreate,
    InvitationOut,
    KnowledgeBaseCreate,
    KnowledgeBaseMemberCreate,
    KnowledgeBaseMemberOut,
    KnowledgeBaseMemberUpdate,
    KnowledgeBaseOut,
    KnowledgeBaseUpdate,
    LoginRequest,
    ModuleOut,
    NewTermReviewRequest,
    PasswordChange,
    ProfileUpdate,
    ReviewEventOut,
    ShareOut,
    TaskOut,
    TokenResponse,
    UserAdminOut,
    UserAdminUpdate,
    UserCreate,
    UserOut,
    WorkspaceCreate,
    WorkspaceMemberCreate,
    WorkspaceMemberOut,
    WorkspaceMemberUpdate,
    WorkspaceOut,
    WorkspaceUpdate,
)
from .security import (
    LoginLimiter,
    create_access_token,
    create_share_token,
    decode_access_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    verify_password,
    verify_share_token,
)
from .results import (
    clauses_payload,
    ensure_results_synced,
    evidence_payload,
    find_evidence,
    items_payload,
    records_payload,
    sync_results,
)

ALLOWED_SUFFIXES = {".md", ".pdf"}
WRITE_SCOPE = "documents:write"
READ_SCOPE = "documents:read"


def client_address(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip() or "-"
    return request.client.host if request.client else "-"


def create_platform_router(
    settings: PlatformSettings,
    engine_settings: Settings | None = None,
    app: Any | None = None,
) -> APIRouter:
    engine = build_engine(settings)
    if settings.db_auto_create:
        init_db(engine)
    else:
        verify_migrations(engine)
    session_factory = build_session_factory(engine)
    engine_settings = engine_settings or Settings.from_env()
    store = JobStore(Path(engine_settings.data_dir) / "jobs")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    dictionary_lock = threading.Lock()
    anonymous_lock = threading.Lock()
    login_limiter = LoginLimiter(
        max_failures=settings.login_max_failures,
        window_seconds=settings.login_window_seconds,
        lockout_seconds=settings.login_lockout_seconds,
    )

    def dictionary_root() -> Path:
        return Path(settings.engine_root) / "configs" / "dictionaries"

    def dictionary_paths() -> tuple[Path, Path]:
        """Legacy monolithic dictionary paths (fallback only)."""

        root = settings.engine_root
        return (
            root / "configs" / "business_dictionary.hanson.json",
            root / "configs" / "business_dictionary.local.json",
        )

    def ensure_global_dictionary() -> Path:
        root = dictionary_root()
        if root.is_dir() and any(
            (root / name).exists() for name in DICTIONARY_FILENAMES.values()
        ):
            return root
        base, override = dictionary_paths()
        if not base.exists():
            raise HTTPException(
                status_code=500,
                detail=f"business dictionary not configured: {base}",
            )
        dictionary = JsonDictionaryAdapter(
            base, override if override.exists() else None
        ).load()
        write_dictionary_parts(root, dictionary)
        return root

    def load_global_dictionary():
        return load_dictionary_path(ensure_global_dictionary())

    def kb_dictionary_path(kb_id: str) -> Path:
        return Path(engine_settings.data_dir) / "dictionaries" / kb_id

    def has_split_dictionary(path: Path) -> bool:
        return path.is_dir() and any(
            (path / name).exists() for name in DICTIONARY_FILENAMES.values()
        )

    def ensure_kb_dictionary(kb_id: str) -> Path:
        path = kb_dictionary_path(kb_id)
        marker = path / ".dictionary_source_version"
        if has_split_dictionary(path):
            # 仅在全局词典版本变化时同步 KB 副本；KB 内的人工别名/词条
            # 会改变它自己的 version，不能据此判断需要覆盖。
            try:
                global_dictionary = load_global_dictionary()
                recorded = (
                    marker.read_text(encoding="utf-8").strip()
                    if marker.exists()
                    else ""
                )
                if not recorded:
                    existing = load_dictionary_path(path)
                    if existing.version == global_dictionary.version:
                        marker.write_text(global_dictionary.version, encoding="utf-8")
                        return path
                if recorded != global_dictionary.version:
                    backup = path.parent / (
                        f"{path.name}.bak-"
                        f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
                    )
                    shutil.copytree(path, backup)
                    write_dictionary_parts(path, global_dictionary)
                    marker.write_text(global_dictionary.version, encoding="utf-8")
            except Exception:  # noqa: BLE001 - keep parsing on dictionary errors
                pass
            return path
        legacy = path.with_suffix(".json")
        if legacy.exists():
            dictionary = JsonDictionaryAdapter(legacy, None).load()
        else:
            dictionary = load_global_dictionary()
        write_dictionary_parts(path, dictionary)
        marker.write_text(dictionary.version, encoding="utf-8")
        return path

    def load_kb_dictionary(kb_id: str):
        return load_dictionary_path(ensure_kb_dictionary(kb_id))

    def document_dictionary_path(document: Document) -> str | None:
        if not document.kb_id:
            return None
        path = kb_dictionary_path(document.kb_id)
        if has_split_dictionary(path):
            return str(path)
        legacy = path.with_suffix(".json")
        return str(legacy) if legacy.exists() else None

    def document_dictionary_index(document: Document):
        return load_dictionary_index_path(document_dictionary_path(document))

    def load_engine_dictionary():
        return load_global_dictionary()

    def dictionary_payload(
        kb: KnowledgeBase,
        entry_type: str | None,
        q: str | None,
        limit: int,
    ) -> dict:
        dictionary = load_kb_dictionary(kb.id)
        entries = [
            entry
            for entry in dictionary.entries
            if (not entry_type or entry.type == entry_type)
            and (
                not q
                or q in entry.business_name
                or any(q in alias for alias in entry.aliases)
            )
        ]
        counts = Counter(entry.type for entry in dictionary.entries)
        return {
            "kb_id": kb.id,
            "version": dictionary.version,
            "source": dictionary.source,
            "counts": {
                "categories": counts["category"],
                "items": counts["item"],
                "methods": counts["method"],
            },
            "total": len(entries),
            "entries": [
                entry.model_dump(mode="json") for entry in entries[:limit]
            ],
        }

    def pending_terms_payload(db: Session, kb: KnowledgeBase, limit: int) -> dict:
        items: list[dict] = []
        for state in store.list(limit=100000):
            path = Path(state.out_dir) / "new_terms.json"
            if not path.exists():
                continue
            document = db.scalar(
                select(Document).where(Document.job_id == state.job_id)
            )
            if document is None or document.kb_id != kb.id:
                continue
            try:
                terms = load_new_terms(path)
            except (ValueError, OSError):
                continue
            for term in terms.terms:
                if term.status != "pending" or term.type == "category":
                    continue
                items.append(
                    {
                        "document_id": document.id,
                        "job_id": state.job_id,
                        "type": term.type,
                        "raw": term.raw,
                        "family": term.family,
                        "facets": term.facets,
                    }
                )
                if len(items) >= limit:
                    break
            if len(items) >= limit:
                break
        return {"kb_id": kb.id, "total": len(items), "items": items}

    def add_kb_alias(
        db: Session,
        principal: Principal,
        kb: KnowledgeBase,
        payload: DictionaryAliasCreate,
    ) -> dict:
        path = ensure_kb_dictionary(kb.id)
        alias = payload.alias.strip()
        with dictionary_lock:
            file = dictionary_file_for_type(path, payload.type)
            if not file.exists():
                raise HTTPException(status_code=404, detail="dictionary not found")
            raw = json.loads(file.read_text(encoding="utf-8"))
            entries = raw.get("entries") or []
            target = next(
                (
                    entry
                    for entry in entries
                    if entry.get("type") == payload.type
                    and entry.get("business_code") == payload.business_code
                ),
                None,
            )
            if target is None:
                raise HTTPException(status_code=404, detail="dictionary entry not found")
            aliases = set(target.get("aliases") or [])
            aliases.add(alias)
            target["aliases"] = sorted(aliases, key=len, reverse=True)
            raw["version"] = f"{raw.get('version', 'v1')}.{kb.id[:6]}"
            file.write_text(
                json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        audit(
            db,
            principal,
            "dictionary.alias",
            "knowledge_base",
            kb.id,
            {"type": payload.type, "business_code": payload.business_code, "alias": alias},
            workspace_id=kb.workspace_id,
        )
        db.commit()
        return {
            "kb_id": kb.id,
            "type": payload.type,
            "business_code": payload.business_code,
            "alias": alias,
            "aliases": target["aliases"],
            "version": load_kb_dictionary(kb.id).version,
        }

    DICTIONARY_PATH_TYPES = {
        "categories": "category",
        "items": "item",
        "methods": "method",
    }

    def dictionary_entry_type(dictionary_type: str) -> str:
        try:
            return DICTIONARY_PATH_TYPES[dictionary_type]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="dictionary not found") from exc

    def read_dictionary_file(kb_id: str, entry_type: str) -> tuple[Path, dict]:
        path = ensure_kb_dictionary(kb_id)
        file = dictionary_file_for_type(path, entry_type)
        return file, json.loads(file.read_text(encoding="utf-8"))

    def write_dictionary_file(file: Path, raw: dict) -> str:
        raw["version"] = f"{raw.get('version', 'v1')}.{utcnow().strftime('%Y%m%d%H%M%S')}"
        file.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return raw["version"]

    def next_dictionary_code(entries: list[dict], entry_type: str) -> str:
        prefix = {
            "category": "CATEGORY",
            "item": "ITEM",
            "method": "METHOD",
        }[entry_type]
        numbers: list[int] = []
        for entry in entries:
            code = str(entry.get("business_code") or "")
            if code.startswith(f"{prefix}:"):
                try:
                    numbers.append(int(code.split(":", 1)[1]))
                except ValueError:
                    continue
        return f"{prefix}:{max(numbers, default=0) + 1}"

    def validate_dictionary_entry(
        kb_id: str,
        entry_type: str,
        payload: DictionaryEntryCreate,
        entries: list[dict],
    ) -> None:
        if entry_type == "item":
            category_code = payload.category_code
            if not category_code:
                raise HTTPException(
                    status_code=422,
                    detail="检测项目必须指定 category_code",
                )
            _, categories = read_dictionary_file(kb_id, "category")
            if not any(
                entry.get("business_code") == category_code
                and entry.get("status", "active") == "active"
                for entry in categories.get("entries") or []
            ):
                raise HTTPException(
                    status_code=422,
                    detail=f"项目大类不存在或已停用：{category_code}",
                )
        if entry_type == "method" and not payload.standard_no:
            raise HTTPException(
                status_code=422, detail="试验方法必须指定 standard_no"
            )
        if payload.business_code and any(
            entry.get("business_code") == payload.business_code for entry in entries
        ):
            raise HTTPException(status_code=409, detail="business_code 已存在")

    if app is not None:
        shutdown = getattr(app.router, "on_shutdown", None)
        if shutdown is not None:
            shutdown.append(engine.dispose)

    router = APIRouter(tags=["platform"])
    router._platform_engine = engine  # type: ignore[attr-defined]

    def get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    def anonymous_principal(db: Session) -> Principal:
        """嵌入式免登录模式使用的固定访客身份。"""

        username = settings.anonymous_username or "embed_guest"
        user = db.scalar(
            select(User).where(
                User.username == username, User.deleted_at.is_(None)
            )
        )
        if user is None:
            with anonymous_lock:
                user = db.scalar(
                    select(User).where(
                        User.username == username, User.deleted_at.is_(None)
                    )
                )
                if user is None:
                    user = User(
                        username=username,
                        display_name="内嵌访客",
                        hashed_password=hash_password(secrets.token_urlsafe(32)),
                        role="editor",
                    )
                    db.add(user)
                    try:
                        db.commit()
                    except IntegrityError:
                        db.rollback()
                        user = db.scalar(
                            select(User).where(User.username == username)
                        )
                    else:
                        db.refresh(user)
        if user is None or not user.is_active or user.deleted_at is not None:
            raise HTTPException(
                status_code=500, detail="anonymous user init failed"
            )
        return Principal(user.id, "user", {"*"}, user, anonymous=True)

    def get_principal(
        request: Request, db: Session = Depends(get_db)
    ) -> Principal:
        if not settings.require_auth:
            # 配置未要求登录：所有接口统一使用内嵌访客身份，不再解析
            # Authorization/X-API-Key，也不做 scope / 角色 / 知识库校验。
            return anonymous_principal(db)
        authorization = request.headers.get("Authorization", "")
        if authorization.lower().startswith("bearer "):
            payload = decode_access_token(
                settings.secret_key, authorization[7:].strip()
            )
            user_id = payload.get("sub") if payload else None
            user = db.get(User, user_id) if user_id else None
            if user is None or not user.is_active or user.deleted_at is not None:
                # 嵌入免登录模式下，过期/失效的本地令牌不应把 iframe 逼到登录页。
                if not settings.require_auth:
                    return anonymous_principal(db)
                raise HTTPException(status_code=401, detail="invalid access token")
            return Principal(user.id, "user", {"*"}, user)

        raw_key = request.headers.get("X-API-Key")
        if raw_key:
            api_key = db.scalar(
                select(ApiKey).where(ApiKey.hashed_key == hash_api_key(raw_key))
            )
            if api_key is None or api_key.revoked_at is not None:
                raise HTTPException(status_code=401, detail="invalid API key")
            creator = db.get(User, api_key.created_by)
            if (
                creator is None
                or not creator.is_active
                or creator.deleted_at is not None
                or not api_key.workspace_id
            ):
                raise HTTPException(status_code=401, detail="invalid API key")
            scopes = {
                scope.strip()
                for scope in (api_key.scopes or "").split(",")
                if scope.strip()
            }
            return Principal(
                api_key.created_by,
                "api_key",
                scopes,
                None,
                workspace_id=api_key.workspace_id,
                kb_ids=kb_ids_from_text(api_key.kb_ids),
            )

        if not settings.require_auth:
            return anonymous_principal(db)

        raise HTTPException(
            status_code=401,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    def require_scope(principal: Principal, scope: str) -> None:
        if not settings.require_auth:
            return
        if "*" in principal.scopes or scope in principal.scopes:
            return
        raise HTTPException(status_code=403, detail=f"missing scope: {scope}")

    def service_ready(base_url: str | None, path: str) -> bool:
        if not base_url:
            return False
        try:
            with httpx.Client(timeout=3.0, trust_env=False) as client:
                response = client.get(f"{base_url.rstrip('/')}{path}")
            return response.status_code < 500
        except httpx.HTTPError:
            return False

    def layout_service_ready(base_url: str | None) -> bool:
        if not base_url:
            return False
        try:
            with httpx.Client(timeout=3.0, trust_env=False) as client:
                response = client.get(f"{base_url.rstrip('/')}/health")
            if response.status_code >= 500:
                return False
            payload = response.json()
            return payload.get("status") == "ok" and bool(
                payload.get("loaded", True)
            )
        except (httpx.HTTPError, ValueError):
            return False

    def model_service_checks() -> dict[str, bool]:
        checks: dict[str, bool] = {}
        if engine_settings.ocr_backend != "mock":
            checks["model_ocr"] = service_ready(
                engine_settings.glm_ocr_base_url, "/models"
            )
        if engine_settings.layout_service_url:
            checks["model_layout"] = layout_service_ready(
                engine_settings.layout_service_url
            )
        if engine_settings.extractor_backend != "mock":
            checks["model_extractor"] = service_ready(
                engine_settings.qwen_base_url, "/models"
            )
        if engine_settings.sft_base_url:
            checks["model_sft"] = service_ready(
                engine_settings.sft_base_url, "/models"
            )
        return checks

    def audit(
        db: Session,
        principal: Principal,
        action: str,
        target_type: str = "",
        target_id: str = "",
        detail: dict | None = None,
        workspace_id: str = "",
    ) -> None:
        if not workspace_id and target_id:
            if target_type == "workspace":
                workspace_id = target_id
            elif target_type == "knowledge_base":
                kb = db.get(KnowledgeBase, target_id)
                workspace_id = kb.workspace_id if kb else ""
            elif target_type == "document":
                document = db.get(Document, target_id)
                if document is not None:
                    kb = db.get(KnowledgeBase, document.kb_id)
                    workspace_id = kb.workspace_id if kb else ""
            elif target_type == "task":
                link = db.scalar(
                    select(DocumentTask).where(DocumentTask.job_id == target_id)
                )
                if link is not None:
                    document = db.get(Document, link.document_id)
                    if document is not None:
                        kb = db.get(KnowledgeBase, document.kb_id)
                        workspace_id = kb.workspace_id if kb else ""
            elif target_type == "api_key":
                key = db.get(ApiKey, target_id)
                workspace_id = key.workspace_id if key else ""
        db.add(
            AuditLog(
                actor_id=principal.actor_id,
                actor_type=principal.actor_type,
                workspace_id=workspace_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                detail=json.dumps(detail or {}, ensure_ascii=False),
            )
        )

    def kb_or_404(
        db: Session,
        kb_id: str,
        principal: Principal,
        minimum: str = "viewer",
    ) -> KnowledgeBase:
        kb = db.get(KnowledgeBase, kb_id)
        if kb is None or kb.deleted_at is not None:
            raise HTTPException(status_code=404, detail="knowledge base not found")
        require_kb_role(db, principal, kb, minimum)
        return kb

    def resolve_document_kb(
        db: Session,
        principal: Principal,
        kb_id: str | None,
        module_key: str | None,
        minimum: str = "viewer",
    ) -> KnowledgeBase:
        """文档与任务接口统一入口：优先按 module，兼容旧的 kb_id。"""

        if module_key:
            return resolve_module(db, principal, module_key, minimum)
        if kb_id:
            return kb_or_404(db, kb_id, principal, minimum)
        raise HTTPException(status_code=422, detail="module or kb_id is required")

    def kb_out(
        db: Session, kb: KnowledgeBase, principal: Principal | None = None
    ) -> KnowledgeBaseOut:
        count = db.scalar(
            select(func.count(Document.id)).where(
                Document.kb_id == kb.id, Document.deleted_at.is_(None)
            )
        )
        member_count = db.scalar(
            select(func.count(KnowledgeBaseMember.id)).where(
                KnowledgeBaseMember.kb_id == kb.id
            )
        )
        role = ""
        if principal is not None:
            role = kb_role(db, principal, kb) or ""
        return KnowledgeBaseOut(
            id=kb.id,
            workspace_id=kb.workspace_id,
            name=kb.name,
            description=kb.description,
            owner_id=kb.owner_id,
            role=role,
            created_at=kb.created_at,
            document_count=int(count or 0),
            member_count=int(member_count or 0),
        )

    def workspace_out(
        db: Session, workspace: Workspace, principal: Principal
    ) -> WorkspaceOut:
        role = (
            "owner"
            if principal.anonymous
            else (workspace_role(db, principal.actor_id, workspace.id) or "member")
        )
        member_count = db.scalar(
            select(func.count(WorkspaceMember.id)).where(
                WorkspaceMember.workspace_id == workspace.id
            )
        )
        kb_count = db.scalar(
            select(func.count(KnowledgeBase.id)).where(
                KnowledgeBase.workspace_id == workspace.id,
                KnowledgeBase.deleted_at.is_(None),
            )
        )
        return WorkspaceOut(
            id=workspace.id,
            name=workspace.name,
            description=workspace.description,
            owner_id=workspace.owner_id,
            role=role,
            member_count=int(member_count or 0),
            kb_count=int(kb_count or 0),
            created_at=workspace.created_at,
        )

    def workspace_or_404(
        db: Session, workspace_id: str, principal: Principal
    ) -> Workspace:
        workspace = db.get(Workspace, workspace_id)
        if workspace is None or workspace.deleted_at is not None:
            raise HTTPException(status_code=404, detail="workspace not found")
        require_workspace_role(db, principal, workspace_id)
        return workspace

    def user_or_404(db: Session, user_id: str) -> User:
        user = db.get(User, user_id)
        if user is None or user.deleted_at is not None:
            raise HTTPException(status_code=404, detail="user not found")
        return user

    def require_platform_admin(principal: Principal) -> None:
        if not settings.require_auth:
            return
        if (
            principal.actor_type != "user"
            or principal.user is None
            or principal.user.role != "admin"
        ):
            raise HTTPException(status_code=403, detail="admin role required")

    def invitation_status(invitation: Invitation) -> str:
        if invitation.revoked_at is not None:
            return "revoked"
        if invitation.accepted_at is not None:
            return "accepted"
        if invitation.expires_at <= utcnow():
            return "expired"
        return "pending"

    def invitation_out(
        invitation: Invitation, token: str | None = None
    ) -> InvitationOut:
        return InvitationOut(
            id=invitation.id,
            workspace_id=invitation.workspace_id,
            role=invitation.role,
            note=invitation.note,
            status=invitation_status(invitation),
            expires_at=invitation.expires_at,
            accepted_at=invitation.accepted_at,
            revoked_at=invitation.revoked_at,
            created_at=invitation.created_at,
            token=token,
        )

    def workspace_member_out(
        member: WorkspaceMember, user: User
    ) -> WorkspaceMemberOut:
        return WorkspaceMemberOut(
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=member.role,
            created_at=member.created_at,
        )

    def user_admin_out(user: User) -> UserAdminOut:
        return UserAdminOut(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
        )

    def task_out(
        state: Any, document: Document | None, link: DocumentTask | None
    ) -> TaskOut:
        return TaskOut(
            document_id=document.id if document else (link.document_id if link else ""),
            kb_id=document.kb_id if document else None,
            job_id=state.job_id if state else (link.job_id if link else ""),
            kind=link.kind if link else "standard_extraction",
            version=link.version if link else 1,
            locked=link.locked if link else False,
            status=state.status if state else (document.status if document else "queued"),
            stage=state.stage if state else "created",
            progress=state.progress if state else 0,
            error=state.error if state else None,
            failure_code=getattr(state, "failure_code", None) if state else None,
            result_status=state.result_status if state else None,
            summary=state.summary if state else {},
            source_name=document.file_name if document else None,
            created_at=(link.created_at.isoformat() if link else None)
            or (state.created_at if state else None),
        )

    def document_or_404(
        db: Session,
        document_id: str,
        principal: Principal,
        minimum: str = "viewer",
    ) -> Document:
        document = db.get(Document, document_id)
        if document is None or document.deleted_at is not None:
            raise HTTPException(status_code=404, detail="document not found")
        kb_or_404(db, document.kb_id, principal, minimum)
        return document

    def document_out(db: Session, document: Document) -> DocumentOut:
        kb = db.get(KnowledgeBase, document.kb_id)
        state = store.get(document.job_id) if document.job_id else None
        link = (
            db.scalar(
                select(DocumentTask).where(
                    DocumentTask.job_id == document.job_id
                )
            )
            if document.job_id
            else None
        )
        history_count = db.scalar(
            select(func.count(DocumentTask.id)).where(
                DocumentTask.document_id == document.id
            )
        )
        file_size = 0
        try:
            file_size = Path(document.source_path).stat().st_size
        except OSError:
            file_size = 0
        page_count = int((state.summary or {}).get("pages") or 0) if state else 0
        latest_schema = (
            "产品标准抽取模板"
            if state is not None and state.status in {"succeeded", "review"}
            else None
        )
        standard_no = document.standard_no
        title = document.title
        if state is not None and (not standard_no or not title):
            # Uploads keep a hash name; show the cover-page identity as soon
            # as the engine result exists, before the DB backfill runs.
            try:
                metadata = read_json(state, ("result.json",)).get("document") or {}
            except HTTPException:
                metadata = {}
            standard_no = standard_no or metadata.get("standard_no")
            if not title or title == Path(document.file_name).stem:
                title = metadata.get("title") or title
        return DocumentOut(
            id=document.id,
            kb_id=document.kb_id,
            workspace_id=kb.workspace_id if kb else None,
            file_name=document.file_name,
            sha256=document.sha256,
            status=state.status if state else document.status,
            job_id=document.job_id,
            review_status=document.review_status or "draft",
            review_version=document.review_version or 1,
            confirmed_job_id=document.confirmed_job_id,
            confirmed_by=document.confirmed_by,
            confirmed_at=document.confirmed_at,
            results_job_id=document.results_job_id,
            results_synced_at=document.results_synced_at,
            standard_no=standard_no,
            title=title,
            created_at=document.created_at,
            file_size=file_size,
            page_count=page_count,
            latest_schema_name=latest_schema,
            history_count=max(0, int(history_count or 0) - 1),
            task=task_out(state, document, link) if state else None,
        )

    def pending_new_terms(state: Any) -> int:
        path = Path(state.out_dir) / "new_terms.json"
        if not path.exists():
            return 0
        try:
            terms = load_new_terms(path)
        except (ValueError, OSError):
            return 0
        return sum(
            1
            for term in terms.terms
            if term.status == "pending" and term.type != "category"
        )

    def require_job(document: Document) -> Any:
        if not document.job_id:
            raise HTTPException(status_code=409, detail="document has no parse task")
        state = store.get(document.job_id)
        if state is None:
            raise HTTPException(status_code=409, detail="parse task not ready")
        return state

    def artifact_file(state: Any, names: tuple[str, ...]) -> Path:
        root = Path(state.out_dir)
        for name in names:
            path = root / name
            if path.exists():
                return path
        raise HTTPException(
            status_code=409,
            detail={"error": "artifact not ready", "stage": state.stage, "names": names},
        )

    def read_json(state: Any, names: tuple[str, ...]) -> Any:
        return json.loads(artifact_file(state, names).read_text(encoding="utf-8"))

    def read_jsonl(state: Any, name: str, limit: int) -> list[Any]:
        rows: list[Any] = []
        for line in artifact_file(state, (name,)).read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
            if len(rows) >= limit:
                break
        return rows

    # ------------------------------------------------------- M4 field review

    def field_review_rows(
        db: Session, document_id: str, job_id: str | None = None
    ) -> list[FieldReviewEvent]:
        query = select(FieldReviewEvent).where(
            FieldReviewEvent.document_id == document_id
        )
        if job_id:
            query = query.where(FieldReviewEvent.job_id == job_id)
        return list(
            db.execute(query.order_by(FieldReviewEvent.created_at.asc()))
            .scalars()
            .all()
        )

    def engine_field_events(rows: list[FieldReviewEvent]) -> list[EngineReviewEvent]:
        return [
            EngineReviewEvent(
                event_id=row.id,
                doc_id=row.document_id,
                job_id=row.job_id,
                field_path=row.field_path,
                action=row.action,
                old_value=row.old_value or {},
                new_value=row.new_value,
                reason=row.reason or "",
                reviewer=row.reviewer,
                created_at=row.created_at.isoformat(),
            )
            for row in rows
        ]

    def current_records(db: Session, document: Document, state: Any) -> list[dict]:
        rows = records_payload(db, document, state)
        if rows:
            return rows
        return read_json(state, ("result.json",)).get("records") or []

    def reviewed_records(db: Session, document: Document, state: Any) -> list[dict]:
        records = current_records(db, document, state)
        events = engine_field_events(field_review_rows(db, document.id, state.job_id))
        return apply_events(records, events) if events else records

    def load_document_result(state: Any) -> DocumentResult:
        payload = read_json(state, ("result.json",))
        return DocumentResult.model_validate(payload)

    def document_export_response(
        db: Session, document: Document, state: Any, export_format: str
    ) -> Response:
        try:
            schema = project_document_schema(db, document, state)
        except HTTPException:
            # Projection needs the schema template; export still has to work
            # for jobs that only produced result.json.
            schema = result_table_schema(read_json(state, ("result.json",)))
        try:
            content, media_type, extension = table_export_bytes(
                export_format, schema
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        filename = f"{document.id}-{export_format}.{extension}"
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    def load_document_evidence(state: Any) -> list[Evidence]:
        rows = read_jsonl(state, "evidence.jsonl", 100000)
        return [Evidence.model_validate(row) for row in rows]

    def assert_field_exists(records: list[dict], field_path: str) -> None:
        parsed = parse_field_path(field_path)
        if parsed is None:
            raise HTTPException(status_code=422, detail=f"invalid field_path: {field_path}")
        record_part, prop = parsed
        record = None
        if record_part.isdigit() and int(record_part) < len(records):
            record = records[int(record_part)]
        else:
            record = next(
                (
                    item
                    for item in records
                    if str(item.get("record_id")) == record_part
                ),
                None,
            )
        if record is None or prop not in (record.get("properties") or {}):
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "unknown field",
                    "field_path": field_path,
                    "record_id": record_part,
                    "records": [str(item.get("record_id")) for item in records[:5]],
                    "properties": list((record or {}).get("properties") or {})[:5],
                },
            )

    def create_field_event(
        db: Session,
        document: Document,
        state: Any,
        payload: FieldReviewRequest,
        principal: Principal,
        records: list[dict],
    ) -> FieldReviewEvent:
        assert_field_exists(records, payload.field_path)
        try:
            event = EngineReviewEvent(
                doc_id=document.id,
                job_id=state.job_id,
                field_path=payload.field_path,
                action=payload.action,
                old_value=payload.old_value,
                new_value=payload.new_value,
                reason=payload.reason,
                reviewer=principal.actor_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        row = FieldReviewEvent(
            id=event.event_id,
            document_id=document.id,
            job_id=state.job_id,
            version=document.review_version or 1,
            field_path=event.field_path,
            action=event.action,
            old_value=payload.old_value,
            new_value=event.new_value,
            reason=event.reason,
            reviewer=event.reviewer,
        )
        db.add(row)
        FeedbackStore(settings.engine_data_dir / "feedback").append(event)
        return row


    # ---------------------------------------------------------------- auth

    @router.get("/v1/auth/config")
    def auth_config() -> dict:
        """公开的运行配置：前端据此决定是否强制跳转登录页。"""

        return {
            "require_auth": settings.require_auth,
            "anonymous": not settings.require_auth,
            "anonymous_username": settings.anonymous_username,
            "allow_embed": settings.allow_embed,
        }

    @router.post("/v1/auth/login", response_model=TokenResponse)
    def login(
        payload: LoginRequest,
        request: Request,
        db: Session = Depends(get_db),
    ) -> TokenResponse:
        limiter_key = (
            f"{payload.username.strip().lower()}|{client_address(request)}"
        )
        retry_after = login_limiter.check(limiter_key)
        if retry_after:
            raise HTTPException(
                status_code=429,
                detail="too many login attempts; try again later",
                headers={"Retry-After": str(retry_after)},
            )
        user = db.scalar(
            select(User).where(
                User.username == payload.username, User.deleted_at.is_(None)
            )
        )
        if user is None or not user.is_active or not verify_password(
            payload.password, user.hashed_password
        ):
            retry_after = login_limiter.record_failure(limiter_key)
            if retry_after:
                raise HTTPException(
                    status_code=429,
                    detail="too many login attempts; try again later",
                    headers={"Retry-After": str(retry_after)},
                )
            raise HTTPException(status_code=401, detail="invalid username or password")
        login_limiter.reset(limiter_key)
        token = create_access_token(
            settings.secret_key, user.id, settings.access_token_minutes
        )
        audit(db, Principal(user.id, "user", {"*"}, user), "auth.login")
        db.commit()
        return TokenResponse(
            access_token=token,
            expires_in=settings.access_token_minutes * 60,
            user=UserOut.model_validate(user),
        )

    @router.get("/v1/auth/me")
    def me(principal: Principal = Depends(get_principal)) -> dict:
        if principal.user is not None:
            return {
                "actor_type": "user",
                "user": UserOut.model_validate(principal.user).model_dump(),
            }
        return {
            "actor_type": "api_key",
            "actor_id": principal.actor_id,
            "scopes": sorted(principal.scopes),
        }

    @router.get("/v1/business-dictionary")
    def business_dictionary(
        entry_type: str | None = Query(default=None, alias="type"),
        q: str | None = Query(default=None),
        limit: int = Query(200, ge=1, le=2000),
        principal: Principal = Depends(get_principal),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        dictionary = load_engine_dictionary()
        entries = [
            entry
            for entry in dictionary.entries
            if (not entry_type or entry.type == entry_type)
            and (
                not q
                or q in entry.business_name
                or any(q in alias for alias in entry.aliases)
            )
        ]
        counts = Counter(entry.type for entry in dictionary.entries)
        return {
            "version": dictionary.version,
            "source": dictionary.source,
            "counts": {
                "categories": counts["category"],
                "items": counts["item"],
                "methods": counts["method"],
            },
            "total": len(entries),
            "entries": [
                entry.model_dump(mode="json") for entry in entries[:limit]
            ],
        }

    @router.get("/v1/knowledge-bases/{kb_id}/dictionary")
    def kb_business_dictionary(
        kb_id: str,
        entry_type: str | None = Query(default=None, alias="type"),
        q: str | None = Query(default=None),
        limit: int = Query(200, ge=1, le=2000),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        kb = kb_or_404(db, kb_id, principal)
        return dictionary_payload(kb, entry_type, q, limit)

    @router.get("/v1/knowledge-bases/{kb_id}/dictionary/pending")
    def kb_pending_dictionary_terms(
        kb_id: str,
        limit: int = Query(500, ge=1, le=2000),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        require_scope(principal, READ_SCOPE)
        kb = kb_or_404(db, kb_id, principal)
        return pending_terms_payload(db, kb, limit)

    @router.post("/v1/knowledge-bases/{kb_id}/dictionary/aliases")
    def add_kb_dictionary_alias(
        kb_id: str,
        payload: DictionaryAliasCreate,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        require_scope(principal, WRITE_SCOPE)
        kb = kb_or_404(db, kb_id, principal, minimum="editor")
        return add_kb_alias(db, principal, kb, payload)

    # ---------------------------------------------------------------- modules

    def module_out(
        db: Session, spec: Any, kb: KnowledgeBase | None, role: str = ""
    ) -> ModuleOut:
        return ModuleOut(
            key=spec.key,
            name=spec.name,
            summary=spec.summary,
            description=spec.description,
            status=spec.status,
            input_types=list(spec.input_types),
            highlights=list(spec.highlights),
            kb_id=kb.id if kb else None,
            role=role,
            created_at=kb.created_at if kb else None,
            **module_stats(db, kb),
        )

    @router.get("/v1/modules", response_model=list[ModuleOut])
    def list_modules(
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> list[ModuleOut]:
        require_scope(principal, READ_SCOPE)
        workspace_id = module_workspace_id(db, principal)
        items: list[ModuleOut] = []
        created = False
        for spec in MODULES.values():
            if spec.status != "active":
                items.append(module_out(db, spec, find_module_kb(db, workspace_id, spec.key)))
                continue
            kb, made = ensure_module_kb(
                db, workspace_id, spec.key, principal.actor_id
            )
            created = created or made
            role = module_role(db, principal, kb)
            if role is None:
                continue
            items.append(module_out(db, spec, kb, role))
        if created:
            db.commit()
        return items

    @router.get("/v1/modules/{module_key}", response_model=ModuleOut)
    def get_module(
        module_key: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> ModuleOut:
        require_scope(principal, READ_SCOPE)
        spec = module_spec(module_key)
        if spec.status != "active":
            module_workspace_id(db, principal)
            return module_out(db, spec, None)
        kb = resolve_module(db, principal, module_key)
        return module_out(db, spec, kb, module_role(db, principal, kb) or "")

    @router.get("/v1/modules/{module_key}/dictionary")
    def module_business_dictionary(
        module_key: str,
        entry_type: str | None = Query(default=None, alias="type"),
        q: str | None = Query(default=None),
        limit: int = Query(200, ge=1, le=2000),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        kb = resolve_module(db, principal, module_key)
        return {"module": module_key, **dictionary_payload(kb, entry_type, q, limit)}

    @router.get("/v1/modules/{module_key}/dictionary/pending")
    def module_pending_dictionary_terms(
        module_key: str,
        limit: int = Query(500, ge=1, le=2000),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        require_scope(principal, READ_SCOPE)
        kb = resolve_module(db, principal, module_key)
        return {"module": module_key, **pending_terms_payload(db, kb, limit)}

    @router.post("/v1/modules/{module_key}/dictionary/aliases")
    def add_module_dictionary_alias(
        module_key: str,
        payload: DictionaryAliasCreate,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        require_scope(principal, WRITE_SCOPE)
        kb = resolve_module(db, principal, module_key, minimum="editor")
        return {"module": module_key, **add_kb_alias(db, principal, kb, payload)}

    @router.get("/v1/modules/{module_key}/dictionaries/coverage")
    def module_dictionary_coverage(
        module_key: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        require_scope(principal, READ_SCOPE)
        kb = resolve_module(db, principal, module_key)
        dictionary = load_kb_dictionary(kb.id)
        counts = Counter(entry.type for entry in dictionary.entries)
        pending = pending_terms_payload(db, kb, 2000)
        pending_counts = Counter(item["type"] for item in pending["items"])
        versions = {}
        for entry_type in DICTIONARY_FILENAMES:
            file = dictionary_file_for_type(ensure_kb_dictionary(kb.id), entry_type)
            try:
                versions[entry_type] = json.loads(
                    file.read_text(encoding="utf-8")
                ).get("version")
            except (OSError, ValueError):
                versions[entry_type] = None
        return {
            "module": module_key,
            "kb_id": kb.id,
            "dictionary_version": dictionary.version,
            "versions": versions,
            "counts": {
                "categories": counts["category"],
                "items": counts["item"],
                "methods": counts["method"],
            },
            "pending": {
                "total": pending["total"],
                "categories": pending_counts["category"],
                "items": pending_counts["item"],
                "methods": pending_counts["method"],
            },
        }

    @router.get("/v1/modules/{module_key}/dictionaries/{dictionary_type}")
    def module_dictionary_type(
        module_key: str,
        dictionary_type: str,
        q: str | None = Query(default=None),
        limit: int = Query(200, ge=1, le=2000),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        require_scope(principal, READ_SCOPE)
        entry_type = dictionary_entry_type(dictionary_type)
        kb = resolve_module(db, principal, module_key)
        return {
            "module": module_key,
            "dictionary_type": dictionary_type,
            "type": entry_type,
            **dictionary_payload(kb, entry_type, q, limit),
        }

    @router.post(
        "/v1/modules/{module_key}/dictionaries/{dictionary_type}/entries",
        status_code=201,
    )
    def create_module_dictionary_entry(
        module_key: str,
        dictionary_type: str,
        payload: DictionaryEntryCreate,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        require_scope(principal, WRITE_SCOPE)
        entry_type = dictionary_entry_type(dictionary_type)
        kb = resolve_module(db, principal, module_key, minimum="editor")
        file, raw = read_dictionary_file(kb.id, entry_type)
        entries = raw.setdefault("entries", [])
        validate_dictionary_entry(kb.id, entry_type, payload, entries)
        code = payload.business_code or next_dictionary_code(entries, entry_type)
        category_name = payload.category_name
        if entry_type == "item" and not category_name and payload.category_code:
            _, categories = read_dictionary_file(kb.id, "category")
            category = next(
                (
                    entry
                    for entry in categories.get("entries") or []
                    if entry.get("business_code") == payload.category_code
                ),
                None,
            )
            category_name = category.get("business_name") if category else None
        entry = {
            "business_code": code,
            "business_name": payload.business_name,
            "type": entry_type,
            "family": payload.family,
            "facets": payload.facets,
            "aliases": sorted(set(payload.aliases), key=len, reverse=True),
            "standard_no": payload.standard_no,
            "category_code": payload.category_code,
            "category_name": category_name,
            "status": "active",
            "version": raw.get("version"),
        }
        entries.append(entry)
        version = write_dictionary_file(file, raw)
        entry["version"] = version
        audit(
            db,
            principal,
            "dictionary.entry.create",
            f"dictionary_{entry_type}",
            code,
            {"business_name": payload.business_name},
            workspace_id=kb.workspace_id,
        )
        db.commit()
        return {
            "module": module_key,
            "type": entry_type,
            "entry": entry,
            "version": version,
        }

    @router.patch(
        "/v1/modules/{module_key}/dictionaries/{dictionary_type}/entries/{business_code}"
    )
    def update_module_dictionary_entry(
        module_key: str,
        dictionary_type: str,
        business_code: str,
        payload: DictionaryEntryUpdate,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        require_scope(principal, WRITE_SCOPE)
        entry_type = dictionary_entry_type(dictionary_type)
        kb = resolve_module(db, principal, module_key, minimum="editor")
        file, raw = read_dictionary_file(kb.id, entry_type)
        target = next(
            (
                entry
                for entry in raw.get("entries") or []
                if entry.get("business_code") == business_code
            ),
            None,
        )
        if target is None:
            raise HTTPException(status_code=404, detail="dictionary entry not found")
        updates = {
            key: value
            for key, value in payload.model_dump(exclude_unset=True).items()
            if value is not None
        }
        if "aliases" in updates:
            updates["aliases"] = sorted(
                set(updates["aliases"]), key=len, reverse=True
            )
        target.update(updates)
        version = write_dictionary_file(file, raw)
        target["version"] = version
        audit(
            db,
            principal,
            "dictionary.entry.update",
            f"dictionary_{entry_type}",
            business_code,
            updates,
            workspace_id=kb.workspace_id,
        )
        db.commit()
        return {
            "module": module_key,
            "type": entry_type,
            "entry": target,
            "version": version,
        }

    @router.get("/v1/business-dictionary/pending")
    def pending_dictionary_terms(
        limit: int = Query(500, ge=1, le=2000),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        require_platform_admin(principal)
        items: list[dict] = []
        for state in store.list(limit=100000):
            path = Path(state.out_dir) / "new_terms.json"
            if not path.exists():
                continue
            try:
                terms = load_new_terms(path)
            except (ValueError, OSError):
                continue
            document = db.scalar(
                select(Document).where(Document.job_id == state.job_id)
            )
            for term in terms.terms:
                if term.status != "pending" or term.type == "category":
                    continue
                items.append(
                    {
                        "document_id": document.id if document else None,
                        "job_id": state.job_id,
                        "type": term.type,
                        "raw": term.raw,
                        "family": term.family,
                        "facets": term.facets,
                    }
                )
                if len(items) >= limit:
                    break
            if len(items) >= limit:
                break
        return {"total": len(items), "items": items}

    @router.post("/v1/business-dictionary/sync")
    def sync_business_dictionary(
        payload: DictionarySyncRequest | None = None,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        require_platform_admin(principal)
        dictionary = load_engine_dictionary()
        counts = Counter(entry.type for entry in dictionary.entries)
        audit(
            db,
            principal,
            "dictionary.sync",
            "business_dictionary",
            dictionary.version,
            {"source": payload.source if payload else "snapshot"},
        )
        db.commit()
        return {
            "source": payload.source if payload else "snapshot",
            "version": dictionary.version,
            "counts": {
                "categories": counts["category"],
                "items": counts["item"],
                "methods": counts["method"],
            },
            "total": len(dictionary.entries),
            "synced_at": utcnow().isoformat(),
        }

    @router.post("/v1/business-dictionary/aliases")
    def add_dictionary_alias(
        payload: DictionaryAliasCreate,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> dict:
        require_platform_admin(principal)
        root = ensure_global_dictionary()
        alias = payload.alias.strip()
        with dictionary_lock:
            file = dictionary_file_for_type(root, payload.type)
            raw = json.loads(file.read_text(encoding="utf-8"))
            target = next(
                (
                    entry
                    for entry in raw.get("entries") or []
                    if entry.get("type") == payload.type
                    and entry.get("business_code") == payload.business_code
                ),
                None,
            )
            if target is None:
                raise HTTPException(
                    status_code=404, detail="dictionary entry not found"
                )
            aliases = set(target.get("aliases") or [])
            aliases.add(alias)
            target["aliases"] = sorted(aliases, key=len, reverse=True)
            raw["version"] = f"{raw.get('version', 'v1')}.{payload.business_code[-6:]}"
            file.write_text(
                json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        audit(
            db,
            principal,
            "dictionary.alias.add",
            "business_dictionary",
            payload.business_code,
            {"type": payload.type, "alias": alias},
        )
        db.commit()
        merged = load_engine_dictionary()
        applied = next(
            (
                entry
                for entry in merged.entries
                if entry.type == payload.type
                and entry.business_code == payload.business_code
            ),
            None,
        )
        return {
            "version": raw["version"],
            "entry": applied.model_dump(mode="json") if applied else None,
        }

    # ------------------------------------------------------------ workspaces

    @router.post("/v1/workspaces", response_model=WorkspaceOut, status_code=201)
    def create_workspace(
        payload: WorkspaceCreate,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> WorkspaceOut:
        require_scope(principal, WRITE_SCOPE)
        if principal.actor_type != "user" or principal.user is None:
            raise HTTPException(status_code=403, detail="user token required")
        workspace = Workspace(
            id=new_id(),
            name=payload.name.strip(),
            description=payload.description.strip(),
            owner_id=principal.actor_id,
        )
        db.add(workspace)
        db.flush()
        db.add(
            WorkspaceMember(
                id=new_id(),
                workspace_id=workspace.id,
                user_id=principal.actor_id,
                role="owner",
            )
        )
        audit(
            db,
            principal,
            "workspace.create",
            "workspace",
            workspace.id,
            workspace_id=workspace.id,
        )
        db.commit()
        db.refresh(workspace)
        return workspace_out(db, workspace, principal)

    @router.get("/v1/workspaces", response_model=list[WorkspaceOut])
    def list_workspaces(
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> list[WorkspaceOut]:
        require_scope(principal, READ_SCOPE)
        if principal.actor_type != "user":
            raise HTTPException(status_code=403, detail="user token required")
        if principal.anonymous:
            # 免登录模式不做成员过滤，返回全部工作空间。
            rows = (
                db.execute(
                    select(Workspace)
                    .where(Workspace.deleted_at.is_(None))
                    .order_by(Workspace.created_at.asc())
                )
                .scalars()
                .all()
            )
            return [workspace_out(db, workspace, principal) for workspace in rows]
        rows = (
            db.execute(
                select(Workspace)
                .join(
                    WorkspaceMember,
                    WorkspaceMember.workspace_id == Workspace.id,
                )
                .where(
                    WorkspaceMember.user_id == principal.actor_id,
                    Workspace.deleted_at.is_(None),
                )
                .order_by(Workspace.created_at.asc())
            )
            .scalars()
            .all()
        )
        return [workspace_out(db, workspace, principal) for workspace in rows]

    @router.get("/v1/workspaces/{workspace_id}", response_model=WorkspaceOut)
    def get_workspace(
        workspace_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> WorkspaceOut:
        require_scope(principal, READ_SCOPE)
        return workspace_out(
            db, workspace_or_404(db, workspace_id, principal), principal
        )

    @router.patch("/v1/workspaces/{workspace_id}", response_model=WorkspaceOut)
    def update_workspace(
        workspace_id: str,
        payload: WorkspaceUpdate,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> WorkspaceOut:
        require_scope(principal, WRITE_SCOPE)
        workspace = workspace_or_404(db, workspace_id, principal)
        require_workspace_role(db, principal, workspace_id, minimum="admin")
        if payload.name is not None:
            workspace.name = payload.name.strip()
        if payload.description is not None:
            workspace.description = payload.description.strip()
        audit(
            db,
            principal,
            "workspace.update",
            "workspace",
            workspace.id,
            workspace_id=workspace.id,
        )
        db.commit()
        db.refresh(workspace)
        return workspace_out(db, workspace, principal)

    @router.delete("/v1/workspaces/{workspace_id}", status_code=204)
    def delete_workspace(
        workspace_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Response:
        require_scope(principal, WRITE_SCOPE)
        workspace = workspace_or_404(db, workspace_id, principal)
        require_workspace_role(db, principal, workspace_id, minimum="owner")
        workspace.deleted_at = utcnow()
        for kb in db.scalars(
            select(KnowledgeBase).where(
                KnowledgeBase.workspace_id == workspace.id,
                KnowledgeBase.deleted_at.is_(None),
            )
        ).all():
            kb.deleted_at = utcnow()
        audit(
            db,
            principal,
            "workspace.delete",
            "workspace",
            workspace.id,
            workspace_id=workspace.id,
        )
        db.commit()
        return Response(status_code=204)

    @router.get(
        "/v1/workspaces/{workspace_id}/members",
        response_model=list[WorkspaceMemberOut],
    )
    def list_workspace_members(
        workspace_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> list[WorkspaceMemberOut]:
        require_scope(principal, READ_SCOPE)
        workspace_or_404(db, workspace_id, principal)
        rows = db.execute(
            select(WorkspaceMember, User)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(WorkspaceMember.created_at.asc())
        ).all()
        return [workspace_member_out(member, user) for member, user in rows]

    @router.post(
        "/v1/workspaces/{workspace_id}/members",
        response_model=WorkspaceMemberOut,
        status_code=201,
    )
    def add_workspace_member(
        workspace_id: str,
        payload: WorkspaceMemberCreate,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> WorkspaceMemberOut:
        require_scope(principal, WRITE_SCOPE)
        workspace_or_404(db, workspace_id, principal)
        require_workspace_role(db, principal, workspace_id, minimum="admin")
        user = _resolve_user(db, payload.username, payload.user_id)
        existing = db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user.id,
            )
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="user is already a member")
        member = WorkspaceMember(
            id=new_id(),
            workspace_id=workspace_id,
            user_id=user.id,
            role=payload.role,
        )
        db.add(member)
        audit(
            db,
            principal,
            "workspace.member.add",
            "workspace",
            workspace_id,
            {"user_id": user.id, "role": payload.role},
            workspace_id=workspace_id,
        )
        db.commit()
        db.refresh(member)
        return workspace_member_out(member, user)

    @router.patch(
        "/v1/workspaces/{workspace_id}/members/{user_id}",
        response_model=WorkspaceMemberOut,
    )
    def update_workspace_member(
        workspace_id: str,
        user_id: str,
        payload: WorkspaceMemberUpdate,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> WorkspaceMemberOut:
        require_scope(principal, WRITE_SCOPE)
        workspace_or_404(db, workspace_id, principal)
        actor_role = require_workspace_role(
            db, principal, workspace_id, minimum="admin"
        )
        target = user_or_404(db, user_id)
        member = db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
        if member is None:
            raise HTTPException(status_code=404, detail="workspace member not found")
        if payload.role == "owner" and actor_role != "owner":
            raise HTTPException(status_code=403, detail="owner role required")
        if member.role == "owner" and actor_role != "owner":
            raise HTTPException(status_code=403, detail="owner role required")
        if member.role == "owner" and payload.role != "owner":
            owners = db.scalar(
                select(func.count(WorkspaceMember.id)).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.role == "owner",
                )
            )
            if int(owners or 0) <= 1:
                raise HTTPException(
                    status_code=409, detail="workspace must keep at least one owner"
                )
        member.role = payload.role
        audit(
            db,
            principal,
            "workspace.member.update",
            "workspace",
            workspace_id,
            {"user_id": target.id, "role": payload.role},
            workspace_id=workspace_id,
        )
        db.commit()
        db.refresh(member)
        return workspace_member_out(member, target)

    @router.delete(
        "/v1/workspaces/{workspace_id}/members/{user_id}", status_code=204
    )
    def remove_workspace_member(
        workspace_id: str,
        user_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Response:
        require_scope(principal, WRITE_SCOPE)
        workspace_or_404(db, workspace_id, principal)
        actor_role = require_workspace_role(
            db, principal, workspace_id, minimum="admin"
        )
        member = db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
        if member is None:
            raise HTTPException(status_code=404, detail="workspace member not found")
        if member.role == "owner":
            if actor_role != "owner":
                raise HTTPException(status_code=403, detail="owner role required")
            owners = db.scalar(
                select(func.count(WorkspaceMember.id)).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.role == "owner",
                )
            )
            if int(owners or 0) <= 1:
                raise HTTPException(
                    status_code=409, detail="workspace must keep at least one owner"
                )
        db.delete(member)
        audit(
            db,
            principal,
            "workspace.member.remove",
            "workspace",
            workspace_id,
            {"user_id": user_id},
            workspace_id=workspace_id,
        )
        db.commit()
        return Response(status_code=204)

    @router.post(
        "/v1/workspaces/{workspace_id}/invitations",
        response_model=InvitationOut,
        status_code=201,
    )
    def create_invitation(
        workspace_id: str,
        payload: InvitationCreate,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> InvitationOut:
        require_scope(principal, WRITE_SCOPE)
        workspace_or_404(db, workspace_id, principal)
        require_workspace_role(db, principal, workspace_id, minimum="admin")
        token = secrets.token_urlsafe(32)
        minutes = payload.expires_minutes or settings.invitation_minutes
        invitation = Invitation(
            id=new_id(),
            workspace_id=workspace_id,
            invited_by=principal.actor_id,
            role=payload.role,
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            note=payload.note.strip()[:255],
            expires_at=utcnow() + timedelta(minutes=minutes),
        )
        db.add(invitation)
        audit(
            db,
            principal,
            "workspace.invitation.create",
            "workspace",
            workspace_id,
            {"role": payload.role, "expires_minutes": minutes},
            workspace_id=workspace_id,
        )
        db.commit()
        db.refresh(invitation)
        return invitation_out(invitation, token)

    @router.get(
        "/v1/workspaces/{workspace_id}/invitations",
        response_model=list[InvitationOut],
    )
    def list_invitations(
        workspace_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> list[InvitationOut]:
        require_scope(principal, READ_SCOPE)
        workspace_or_404(db, workspace_id, principal)
        require_workspace_role(db, principal, workspace_id, minimum="admin")
        rows = db.scalars(
            select(Invitation)
            .where(Invitation.workspace_id == workspace_id)
            .order_by(Invitation.created_at.desc())
        ).all()
        return [invitation_out(invitation) for invitation in rows]

    @router.delete(
        "/v1/workspaces/{workspace_id}/invitations/{invitation_id}",
        status_code=204,
    )
    def revoke_invitation(
        workspace_id: str,
        invitation_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Response:
        require_scope(principal, WRITE_SCOPE)
        workspace_or_404(db, workspace_id, principal)
        require_workspace_role(db, principal, workspace_id, minimum="admin")
        invitation = db.get(Invitation, invitation_id)
        if invitation is None or invitation.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="invitation not found")
        if invitation_status(invitation) == "accepted":
            raise HTTPException(status_code=409, detail="invitation already accepted")
        invitation.revoked_at = utcnow()
        audit(
            db,
            principal,
            "workspace.invitation.revoke",
            "workspace",
            workspace_id,
            {"invitation_id": invitation_id},
            workspace_id=workspace_id,
        )
        db.commit()
        return Response(status_code=204)

    @router.post(
        "/v1/invitations/{token}/accept",
        response_model=InvitationAcceptOut,
    )
    def accept_invitation(
        token: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> InvitationAcceptOut:
        if principal.actor_type != "user" or principal.user is None:
            raise HTTPException(status_code=403, detail="user token required")
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        invitation = db.scalar(
            select(Invitation).where(Invitation.token_hash == token_hash)
        )
        if invitation is None:
            raise HTTPException(status_code=404, detail="invitation not found")
        status = invitation_status(invitation)
        if status != "pending":
            raise HTTPException(
                status_code=409, detail=f"invitation is {status}"
            )
        workspace = db.get(Workspace, invitation.workspace_id)
        if workspace is None or workspace.deleted_at is not None:
            raise HTTPException(status_code=404, detail="workspace not found")
        existing = db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == principal.actor_id,
            )
        )
        if existing is not None:
            raise HTTPException(
                status_code=409, detail="already a workspace member"
            )
        db.add(
            WorkspaceMember(
                id=new_id(),
                workspace_id=workspace.id,
                user_id=principal.actor_id,
                role=invitation.role,
            )
        )
        invitation.accepted_at = utcnow()
        invitation.accepted_by = principal.actor_id
        audit(
            db,
            principal,
            "workspace.invitation.accept",
            "workspace",
            workspace.id,
            {"invitation_id": invitation.id, "role": invitation.role},
            workspace_id=workspace.id,
        )
        db.commit()
        return InvitationAcceptOut(
            workspace_id=workspace.id,
            workspace_name=workspace.name,
            role=invitation.role,
        )

    # ---------------------------------------------------------------- users

    @router.post("/v1/users", response_model=UserAdminOut, status_code=201)
    def create_user_account(
        payload: UserCreate,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> UserAdminOut:
        require_platform_admin(principal)
        existing = db.scalar(
            select(User).where(User.username == payload.username)
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="username already exists")
        user = User(
            id=new_id(),
            username=payload.username.strip(),
            display_name=payload.display_name.strip(),
            hashed_password=hash_password(payload.password),
            role=payload.role,
            is_active=True,
        )
        db.add(user)
        audit(
            db,
            principal,
            "user.create",
            "user",
            user.id,
            {"username": user.username, "role": user.role},
        )
        db.commit()
        db.refresh(user)
        return user_admin_out(user)

    @router.get("/v1/users", response_model=list[UserAdminOut])
    def list_user_accounts(
        q: str | None = Query(default=None),
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> list[UserAdminOut]:
        require_platform_admin(principal)
        stmt = select(User).where(User.deleted_at.is_(None))
        if q:
            pattern = f"%{q.strip()}%"
            stmt = stmt.where(
                (User.username.ilike(pattern)) | (User.display_name.ilike(pattern))
            )
        rows = db.scalars(
            stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)
        ).all()
        return [user_admin_out(user) for user in rows]

    @router.patch("/v1/users/{user_id}", response_model=UserAdminOut)
    def update_user_account(
        user_id: str,
        payload: UserAdminUpdate,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> UserAdminOut:
        require_platform_admin(principal)
        user = user_or_404(db, user_id)
        if payload.is_active is False:
            if user.id == principal.actor_id:
                raise HTTPException(
                    status_code=409, detail="cannot deactivate yourself"
                )
            if user.role == "admin":
                active_admins = db.scalar(
                    select(func.count(User.id)).where(
                        User.role == "admin",
                        User.is_active.is_(True),
                        User.deleted_at.is_(None),
                    )
                )
                if int(active_admins or 0) <= 1:
                    raise HTTPException(
                        status_code=409, detail="must keep at least one active admin"
                    )
        if payload.role == "user" and user.role == "admin":
            active_admins = db.scalar(
                select(func.count(User.id)).where(
                    User.role == "admin",
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                )
            )
            if int(active_admins or 0) <= 1:
                raise HTTPException(
                    status_code=409, detail="must keep at least one active admin"
                )
        if payload.display_name is not None:
            user.display_name = payload.display_name.strip()
        if payload.role is not None:
            user.role = payload.role
        if payload.is_active is not None:
            user.is_active = payload.is_active
        if payload.password:
            user.hashed_password = hash_password(payload.password)
        audit(
            db,
            principal,
            "user.update",
            "user",
            user.id,
            {
                "role": user.role,
                "is_active": user.is_active,
                "password_reset": bool(payload.password),
            },
        )
        db.commit()
        db.refresh(user)
        return user_admin_out(user)

    @router.patch("/v1/auth/me", response_model=UserOut)
    def update_profile(
        payload: ProfileUpdate,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> UserOut:
        if principal.actor_type != "user" or principal.user is None:
            raise HTTPException(status_code=403, detail="user token required")
        principal.user.display_name = payload.display_name.strip()
        audit(
            db,
            principal,
            "user.profile.update",
            "user",
            principal.actor_id,
        )
        db.commit()
        db.refresh(principal.user)
        return UserOut.model_validate(principal.user)

    @router.post("/v1/auth/password", status_code=204)
    def change_password(
        payload: PasswordChange,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Response:
        if principal.actor_type != "user" or principal.user is None:
            raise HTTPException(status_code=403, detail="user token required")
        if not verify_password(
            payload.old_password, principal.user.hashed_password
        ):
            raise HTTPException(status_code=401, detail="old password is incorrect")
        principal.user.hashed_password = hash_password(payload.new_password)
        audit(
            db,
            principal,
            "user.password.change",
            "user",
            principal.actor_id,
        )
        db.commit()
        return Response(status_code=204)

    # ------------------------------------------------------- knowledge base

    @router.post(
        "/v1/knowledge-bases", response_model=KnowledgeBaseOut, status_code=201
    )
    def create_knowledge_base(
        payload: KnowledgeBaseCreate,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> KnowledgeBaseOut:
        require_scope(principal, WRITE_SCOPE)
        if principal.actor_type != "user" or principal.user is None:
            raise HTTPException(status_code=403, detail="user token required")
        if payload.workspace_id:
            require_workspace_role(db, principal, payload.workspace_id)
            workspace_id = payload.workspace_id
        else:
            workspace = default_workspace(db, principal.user)
            workspace_id = workspace.id
        kb = KnowledgeBase(
            workspace_id=workspace_id,
            name=payload.name.strip(),
            description=payload.description.strip(),
            owner_id=principal.actor_id,
        )
        db.add(kb)
        db.flush()
        db.add(
            KnowledgeBaseMember(
                kb_id=kb.id, user_id=principal.actor_id, role="owner"
            )
        )
        audit(
            db,
            principal,
            "kb.create",
            "knowledge_base",
            kb.id,
            {"workspace_id": workspace_id},
            workspace_id=workspace_id,
        )
        db.commit()
        db.refresh(kb)
        try:
            ensure_kb_dictionary(kb.id)
        except (OSError, ValueError):
            pass
        return kb_out(db, kb, principal)

    @router.get("/v1/knowledge-bases", response_model=list[KnowledgeBaseOut])
    def list_knowledge_bases(
        workspace_id: str | None = Query(default=None),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> list[KnowledgeBaseOut]:
        require_scope(principal, READ_SCOPE)
        if workspace_id:
            require_workspace_role(db, principal, workspace_id)
            kb_ids = [
                kb.id
                for kb in db.scalars(
                    select(KnowledgeBase).where(
                        KnowledgeBase.workspace_id == workspace_id,
                        KnowledgeBase.deleted_at.is_(None),
                    )
                ).all()
                if kb_role(db, principal, kb) is not None
            ]
        else:
            kb_ids = accessible_kb_ids(db, principal)
        if not kb_ids:
            return []
        rows = (
            db.execute(
                select(KnowledgeBase)
                .where(KnowledgeBase.id.in_(kb_ids))
                .order_by(KnowledgeBase.created_at.desc())
            )
            .scalars()
            .all()
        )
        return [kb_out(db, kb, principal) for kb in rows]

    @router.get(
        "/v1/knowledge-bases/{kb_id}", response_model=KnowledgeBaseOut
    )
    def get_knowledge_base(
        kb_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> KnowledgeBaseOut:
        require_scope(principal, READ_SCOPE)
        return kb_out(db, kb_or_404(db, kb_id, principal), principal)

    @router.patch(
        "/v1/knowledge-bases/{kb_id}", response_model=KnowledgeBaseOut
    )
    def update_knowledge_base(
        kb_id: str,
        payload: KnowledgeBaseUpdate,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> KnowledgeBaseOut:
        require_scope(principal, WRITE_SCOPE)
        kb = kb_or_404(db, kb_id, principal, minimum="owner")
        if payload.name is not None:
            kb.name = payload.name.strip()
        if payload.description is not None:
            kb.description = payload.description.strip()
        audit(
            db,
            principal,
            "kb.update",
            "knowledge_base",
            kb.id,
            workspace_id=kb.workspace_id,
        )
        db.commit()
        db.refresh(kb)
        return kb_out(db, kb, principal)

    @router.delete("/v1/knowledge-bases/{kb_id}", status_code=204)
    def delete_knowledge_base(
        kb_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Response:
        require_scope(principal, WRITE_SCOPE)
        kb = kb_or_404(db, kb_id, principal, minimum="owner")
        kb.deleted_at = utcnow()
        audit(
            db,
            principal,
            "kb.delete",
            "knowledge_base",
            kb.id,
            workspace_id=kb.workspace_id,
        )
        db.commit()
        return Response(status_code=204)

    @router.get(
        "/v1/knowledge-bases/{kb_id}/members",
        response_model=list[KnowledgeBaseMemberOut],
    )
    def list_kb_members(
        kb_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> list[KnowledgeBaseMemberOut]:
        require_scope(principal, READ_SCOPE)
        kb = kb_or_404(db, kb_id, principal)
        rows = db.execute(
            select(KnowledgeBaseMember, User)
            .join(User, User.id == KnowledgeBaseMember.user_id)
            .where(KnowledgeBaseMember.kb_id == kb.id)
            .order_by(KnowledgeBaseMember.created_at.asc())
        ).all()
        return [
            KnowledgeBaseMemberOut(
                user_id=user.id,
                username=user.username,
                display_name=user.display_name,
                role=member.role,
                created_at=member.created_at,
            )
            for member, user in rows
        ]

    @router.post(
        "/v1/knowledge-bases/{kb_id}/members",
        response_model=KnowledgeBaseMemberOut,
        status_code=201,
    )
    def add_kb_member(
        kb_id: str,
        payload: KnowledgeBaseMemberCreate,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> KnowledgeBaseMemberOut:
        require_scope(principal, WRITE_SCOPE)
        kb = kb_or_404(db, kb_id, principal, minimum="owner")
        user = _resolve_user(db, payload.username, payload.user_id)
        require_workspace_role(db, Principal(user.id, "user", {"*"}, user), kb.workspace_id)
        existing = db.scalar(
            select(KnowledgeBaseMember).where(
                KnowledgeBaseMember.kb_id == kb.id,
                KnowledgeBaseMember.user_id == user.id,
            )
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="user is already a KB member")
        member = KnowledgeBaseMember(
            kb_id=kb.id, user_id=user.id, role=payload.role
        )
        db.add(member)
        audit(
            db,
            principal,
            "kb.member.add",
            "knowledge_base",
            kb.id,
            {"user_id": user.id, "role": payload.role},
            workspace_id=kb.workspace_id,
        )
        db.commit()
        db.refresh(member)
        return KnowledgeBaseMemberOut(
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=member.role,
            created_at=member.created_at,
        )

    @router.patch(
        "/v1/knowledge-bases/{kb_id}/members/{user_id}",
        response_model=KnowledgeBaseMemberOut,
    )
    def update_kb_member(
        kb_id: str,
        user_id: str,
        payload: KnowledgeBaseMemberUpdate,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> KnowledgeBaseMemberOut:
        require_scope(principal, WRITE_SCOPE)
        kb = kb_or_404(db, kb_id, principal, minimum="owner")
        user = user_or_404(db, user_id)
        member = db.scalar(
            select(KnowledgeBaseMember).where(
                KnowledgeBaseMember.kb_id == kb.id,
                KnowledgeBaseMember.user_id == user.id,
            )
        )
        if member is None:
            raise HTTPException(status_code=404, detail="KB member not found")
        if user.id == kb.owner_id and payload.role != "owner":
            raise HTTPException(
                status_code=409, detail="the KB owner must keep the owner role"
            )
        member.role = payload.role
        audit(
            db,
            principal,
            "kb.member.update",
            "knowledge_base",
            kb.id,
            {"user_id": user.id, "role": payload.role},
            workspace_id=kb.workspace_id,
        )
        db.commit()
        db.refresh(member)
        return KnowledgeBaseMemberOut(
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=member.role,
            created_at=member.created_at,
        )

    @router.delete(
        "/v1/knowledge-bases/{kb_id}/members/{user_id}", status_code=204
    )
    def remove_kb_member(
        kb_id: str,
        user_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Response:
        require_scope(principal, WRITE_SCOPE)
        kb = kb_or_404(db, kb_id, principal, minimum="owner")
        if user_id == kb.owner_id:
            raise HTTPException(
                status_code=409, detail="the KB owner cannot be removed"
            )
        member = db.scalar(
            select(KnowledgeBaseMember).where(
                KnowledgeBaseMember.kb_id == kb.id,
                KnowledgeBaseMember.user_id == user_id,
            )
        )
        if member is None:
            raise HTTPException(status_code=404, detail="KB member not found")
        db.delete(member)
        audit(
            db,
            principal,
            "kb.member.remove",
            "knowledge_base",
            kb.id,
            {"user_id": user_id},
            workspace_id=kb.workspace_id,
        )
        db.commit()
        return Response(status_code=204)

    def _resolve_user(
        db: Session, username: str | None, user_id: str | None
    ) -> User:
        if user_id:
            return user_or_404(db, user_id)
        if username:
            user = db.scalar(
                select(User).where(
                    User.username == username, User.deleted_at.is_(None)
                )
            )
            if user is None:
                raise HTTPException(status_code=404, detail="user not found")
            return user
        raise HTTPException(status_code=422, detail="username or user_id required")

    # ------------------------------------------------------------ documents

    @router.post("/v1/documents", response_model=DocumentOut, status_code=201)
    async def upload_document(
        response: Response,
        file: UploadFile = File(...),
        kb_id: str | None = Form(None),
        module: str | None = Form(None),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> DocumentOut:
        require_scope(principal, WRITE_SCOPE)
        target_kb = resolve_document_kb(
            db, principal, kb_id, module, minimum="editor"
        )
        kb_id = target_kb.id
        file_name = Path(file.filename or "upload").name
        suffix = Path(file_name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(
                status_code=415, detail=f"unsupported file type: {suffix or 'none'}"
            )
        data = await file.read()
        if not data:
            raise HTTPException(status_code=422, detail="empty upload")
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="upload exceeds size limit")

        sha256 = hashlib.sha256(data).hexdigest()
        existing = db.scalar(
            select(Document).where(
                Document.kb_id == kb_id,
                Document.sha256 == sha256,
                Document.deleted_at.is_(None),
            )
        )
        if existing is not None:
            response.status_code = 200
            return document_out(db, existing)

        document_id = new_id()
        target_dir = settings.upload_dir / kb_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{document_id}-{file_name}"
        target.write_bytes(data)

        document = Document(
            id=document_id,
            kb_id=kb_id,
            file_name=file_name,
            source_path=str(target),
            sha256=sha256,
            status="uploaded",
            created_by=principal.actor_id,
        )
        db.add(document)
        audit(
            db,
            principal,
            "document.upload",
            "document",
            document_id,
            {"file_name": file_name, "sha256": sha256},
        )
        db.commit()
        db.refresh(document)
        return document_out(db, document)

    @router.get("/v1/documents", response_model=list[DocumentOut])
    def list_documents(
        kb_id: str | None = Query(None),
        module: str | None = Query(None),
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        q: str | None = Query(default=None),
        status: str | None = Query(default=None),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> list[DocumentOut]:
        require_scope(principal, READ_SCOPE)
        target_kb = resolve_document_kb(db, principal, kb_id, module)
        kb_id = target_kb.id
        stmt = select(Document).where(
            Document.kb_id == kb_id, Document.deleted_at.is_(None)
        )
        if q:
            stmt = stmt.where(Document.file_name.ilike(f"%{q.strip()}%"))
        stmt = stmt.order_by(Document.created_at.desc())
        if status:
            documents = [
                document_out(db, document)
                for document in db.execute(stmt).scalars().all()
            ]
            matched = [doc for doc in documents if doc.status == status]
            return matched[offset : offset + limit]
        rows = (
            db.execute(stmt.limit(limit).offset(offset))
            .scalars()
            .all()
        )
        return [document_out(db, document) for document in rows]

    @router.get("/v1/documents/{document_id}", response_model=DocumentOut)
    def get_document(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> DocumentOut:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        return document_out(db, document)

    @router.delete("/v1/documents/{document_id}", status_code=204)
    def delete_document(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Response:
        require_scope(principal, WRITE_SCOPE)
        document = document_or_404(
            db, document_id, principal, minimum="owner"
        )
        if document.job_id:
            state = store.get(document.job_id)
            if state is not None and state.status in {"queued", "running"}:
                raise HTTPException(
                    status_code=409,
                    detail="document is parsing; cancel or wait before deleting",
                )
        document.deleted_at = utcnow()
        audit(db, principal, "document.delete", "document", document.id)
        db.commit()
        return Response(status_code=204)

    def start_document_parse(
        db: Session,
        document: Document,
        principal: Principal,
        background: BackgroundTasks,
        *,
        force: bool = False,
    ) -> tuple[TaskOut, bool]:
        """Create or reuse a parse job for a document and enqueue it.

        Shared by the regular parse endpoint and the one-stop integration
        endpoints so both paths keep identical versioning and job semantics.
        """

        reparse = force or (document.review_status or "draft") == "confirmed"
        if document.job_id and not reparse:
            current = store.get(document.job_id)
            if current is not None and current.status in {
                "queued",
                "running",
                "succeeded",
                "review",
            }:
                link = db.scalar(
                    select(DocumentTask).where(
                        DocumentTask.job_id == document.job_id
                    )
                )
                return task_out(current, document, link), False

        if force and document.job_id:
            current = store.get(document.job_id)
            if current is not None and current.status in {"queued", "running"}:
                raise HTTPException(
                    status_code=409,
                    detail="document is parsing; wait before forcing a reparse",
                )

        if reparse:
            document.review_version = (document.review_version or 1) + 1
            document.review_status = "draft"
        version = document.review_version or 1

        job_id = new_id()[:12]
        idempotency_key = (
            f"document:{document.id}:{document.sha256}"
            if version <= 1
            else f"document:{document.id}:{document.sha256}:v{version}"
        )
        dictionary_path = None
        if document.kb_id:
            try:
                dictionary_path = str(ensure_kb_dictionary(document.kb_id))
            except (OSError, ValueError):
                dictionary_path = None
        state, created = store.reserve(
            job_id=job_id,
            idempotency_key=idempotency_key,
            source_name=document.file_name,
            source_sha256=document.sha256,
            doc_path=document.source_path,
            options={
                "ocr": engine_settings.ocr_backend,
                "extractor": engine_settings.extractor_backend,
                "template": "product_full",
                **({"dictionary_path": dictionary_path} if dictionary_path else {}),
            },
        )
        document.job_id = state.job_id
        document.status = "queued"
        link = db.scalar(
            select(DocumentTask).where(DocumentTask.job_id == state.job_id)
        )
        if link is None:
            link = DocumentTask(
                document_id=document.id,
                job_id=state.job_id,
                kind="standard_extraction",
                version=version,
            )
            db.add(link)
        audit(
            db,
            principal,
            "document.reparse" if reparse else "document.parse",
            "document",
            document.id,
            {"job_id": state.job_id, "version": version},
        )
        db.commit()
        if created and settings.inline_jobs:
            background.add_task(run_job, store, state.job_id, engine_settings)
        return task_out(state, document, link), True

    @router.post(
        "/v1/documents/{document_id}/parse",
        response_model=TaskOut,
        status_code=202,
    )
    def parse_document(
        document_id: str,
        background: BackgroundTasks,
        response: Response,
        force: bool = Query(default=False),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> TaskOut:
        require_scope(principal, WRITE_SCOPE)
        document = document_or_404(
            db, document_id, principal, minimum="editor"
        )
        result, created = start_document_parse(
            db, document, principal, background, force=force
        )
        if not created:
            response.status_code = 200
        return result

    @router.post(
        "/v1/documents/{document_id}/share", response_model=ShareOut
    )
    def share_document(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> ShareOut:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(
            db, document_id, principal, minimum="editor"
        )
        token, expires = create_share_token(
            settings.secret_key, document.id, settings.share_token_minutes
        )
        audit(db, principal, "document.share", "document", document.id)
        db.commit()
        return ShareOut(token=token, expires_at=expires, path=f"/v1/share/{token}")

    # --------------------------------------------------------- integration
    # 一站式对接兼容层：保持 hansonDoc_RAG 的方法、路径、参数与响应信封不变。
    # 写接口（upload/retrigger）走当前平台鉴权；状态/结果按 task_id 作为凭证读取。

    def integration_envelope(
        request: Request, data: Any = None, message: str = "success"
    ) -> dict:
        return {
            "code": 0,
            "message": message,
            "data": data,
            "trace_id": getattr(request.state, "request_id", "") or "",
        }

    def integration_uuid(value: str, field: str) -> str:
        try:
            return uuid.UUID(str(value)).hex
        except (ValueError, AttributeError, TypeError) as exc:
            raise HTTPException(
                status_code=400, detail=f"{field} 不是合法 UUID"
            ) from exc

    def integration_task_id(value: str) -> str:
        try:
            return str(uuid.UUID(str(value)))
        except (ValueError, AttributeError, TypeError) as exc:
            raise HTTPException(
                status_code=400, detail="task_id 不是合法 UUID"
            ) from exc

    def integration_format_id(value: str | None) -> str | None:
        if not value:
            return None
        try:
            return str(uuid.UUID(str(value)))
        except (ValueError, AttributeError, TypeError):
            return value

    def integration_template():
        try:
            return load_template(
                Path(settings.engine_root)
                / "configs"
                / "schema_templates"
                / "product_standard.json"
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def integration_task_or_404(db: Session, task_id: str) -> IntegrationTask:
        task = db.scalar(
            select(IntegrationTask).where(
                IntegrationTask.task_id == integration_task_id(task_id)
            )
        )
        if task is None:
            raise HTTPException(status_code=404, detail="对接任务不存在")
        return task

    def integration_document(
        db: Session, task: IntegrationTask
    ) -> Document | None:
        if not task.document_id:
            return None
        document = db.get(Document, task.document_id)
        if document is None or document.deleted_at is not None:
            return None
        return document

    def integration_state_values(
        state: Any,
    ) -> tuple[str, str, int, int, str]:
        if state is None:
            return "pending", "pending", 0, 0, ""
        progress = int(getattr(state, "progress", 0) or 0)
        status = str(getattr(state, "status", "queued"))
        error = str(getattr(state, "error", "") or "")
        if status == "queued":
            return "pending", "pending", 0, 0, error
        if status == "failed":
            ocr_done = progress >= 45
            return (
                "completed" if ocr_done else "failed",
                "failed" if ocr_done else "pending",
                100 if ocr_done else progress,
                progress,
                error or "解析失败",
            )
        if status in {"succeeded", "review"}:
            return "completed", "completed", 100, 100, ""
        if progress <= 45:
            return "processing", "pending", max(progress, 1), 0, error
        return "completed", "running", 100, progress, error

    def integration_result_version(
        db: Session, document: Document | None, task: IntegrationTask
    ) -> int | None:
        if document is not None and document.job_id:
            link = db.scalar(
                select(DocumentTask).where(
                    DocumentTask.job_id == document.job_id
                )
            )
            if link is not None:
                return link.version
        return task.result_version

    def integration_task_view(
        db: Session, task: IntegrationTask, *, persist: bool = False
    ) -> dict:
        document = integration_document(db, task)
        state = (
            store.get(document.job_id)
            if document is not None and document.job_id
            else None
        )
        ocr_status, extract_status, ocr_progress, extract_progress, error = (
            integration_state_values(state)
        )
        result_version = integration_result_version(db, document, task)
        if persist:
            changed = False
            for name, value in (
                ("ocr_status", ocr_status),
                ("ocr_progress", ocr_progress),
                ("extract_status", extract_status),
                ("extract_progress", extract_progress),
                ("error", error),
                ("result_version", result_version),
            ):
                if getattr(task, name) != value:
                    setattr(task, name, value)
                    changed = True
            if changed:
                task.updated_at = utcnow()
                db.commit()
        return {
            "task_id": task.task_id,
            "kb_id": integration_format_id(task.kb_id),
            "document_id": integration_format_id(task.document_id),
            "prompt_id": task.prompt_id,
            "schema_template_id": task.schema_template_id,
            "filename": task.filename,
            "ocr_status": ocr_status,
            "ocr_progress": ocr_progress,
            "extract_status": extract_status,
            "extract_progress": extract_progress,
            "error": error,
            "result_version": result_version,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        }

    @router.post("/api/v1/integration/upload")
    async def integration_upload(
        request: Request,
        background: BackgroundTasks,
        file: UploadFile = File(...),
        kb_id: str = Query(...),
        prompt_id: str = Query(...),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, WRITE_SCOPE)
        kb = kb_or_404(
            db, integration_uuid(kb_id, "kb_id"), principal, minimum="editor"
        )
        prompt_key = integration_uuid(prompt_id, "prompt_id")
        prompt_value = integration_format_id(prompt_key) or prompt_key
        filename = Path(file.filename or "document.pdf").name
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="仅支持 PDF 文件")
        if len(filename.encode("utf-8")) > 255:
            raise HTTPException(status_code=400, detail="文件名过长")
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="文件为空")
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="文件超过大小限制")

        sha256 = hashlib.sha256(data).hexdigest()
        document = db.scalar(
            select(Document).where(
                Document.kb_id == kb.id,
                Document.sha256 == sha256,
                Document.deleted_at.is_(None),
            )
        )
        if document is None:
            document_id = new_id()
            target_dir = settings.upload_dir / kb.id
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{document_id}-{filename}"
            target.write_bytes(data)
            document = Document(
                id=document_id,
                kb_id=kb.id,
                file_name=filename,
                source_path=str(target),
                sha256=sha256,
                status="uploaded",
                created_by=principal.actor_id,
            )
            db.add(document)
            db.flush()

        template = integration_template()
        task = IntegrationTask(
            task_id=str(uuid.uuid4()),
            kb_id=kb.id,
            document_id=document.id,
            prompt_id=prompt_value,
            schema_template_id=(
                template.template_id if template is not None else prompt_value
            ),
            filename=filename,
            ocr_status="processing",
            extract_status="pending",
            created_by=principal.actor_id,
        )
        db.add(task)
        db.flush()
        start_document_parse(db, document, principal, background, force=False)
        task.ocr_status = "processing"
        task.extract_status = "pending"
        task.ocr_progress = 0
        task.extract_progress = 0
        task.error = ""
        task.result_version = None
        task.updated_at = utcnow()
        audit(
            db,
            principal,
            "integration.upload",
            "integration_task",
            task.task_id,
            {"document_id": document.id, "file_name": filename},
        )
        db.commit()
        db.refresh(task)
        return integration_envelope(
            request,
            integration_task_view(db, task),
            "任务已创建，正在异步执行 OCR 解析与结构化抽取",
        )

    @router.get("/api/v1/integration/tasks/{task_id}/status")
    def integration_status(
        request: Request,
        task_id: str,
        db: Session = Depends(get_db),
    ) -> Any:
        task = integration_task_or_404(db, task_id)
        return integration_envelope(
            request, integration_task_view(db, task, persist=True)
        )

    @router.get("/api/v1/integration/tasks/{task_id}/result")
    def integration_result(
        request: Request,
        task_id: str,
        db: Session = Depends(get_db),
    ) -> Any:
        task = integration_task_or_404(db, task_id)
        document = integration_document(db, task)
        if document is None or not document.job_id:
            return integration_envelope(request, None)
        state = store.get(document.job_id)
        if state is None:
            return integration_envelope(request, None)

        template = integration_template()
        base = {
            "schema_template_id": (
                template.template_id if template is not None
                else task.schema_template_id
            ),
            "schema_name": template.name if template is not None else "",
            "status": "completed" if state.status in {"succeeded", "review"} else (
                "failed" if state.status == "failed" else "running"
            ),
            "progress": int(getattr(state, "progress", 0) or 0),
            "categories": [],
            "summary": {},
            "timing": {},
            "version": integration_result_version(db, document, task),
            "error": getattr(state, "error", None),
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        }
        if state.status not in {"succeeded", "review"}:
            return integration_envelope(request, base)

        payload = project_document_schema(db, document, state)
        categories = []
        total_records = 0
        for category in payload.get("categories", []):
            rows = category.get("rows") or []
            total_records += len(rows)
            categories.append(
                {
                    "feature": category.get("display_name")
                    or category.get("name")
                    or category.get("key")
                    or "",
                    "records": rows,
                    "rejected": [],
                    "missing_fields": category.get("missing_fields") or [],
                    "hit_count": len(rows),
                }
            )
        timing = {}
        try:
            trace = read_json(state, ("trace.json",))
            timing = {"total_sec": round(float(trace.get("elapsed_ms") or 0) / 1000.0, 2)}
        except HTTPException:
            pass
        base.update(
            {
                "schema_template_id": (
                    template.template_id if template is not None
                    else task.schema_template_id
                ),
                "schema_name": template.name if template is not None else "",
                "status": "completed",
                "progress": 100,
                "categories": categories,
                "summary": {
                    "total_records": total_records,
                    "kept_categories": sum(
                        1 for category in categories if category["records"]
                    ),
                },
                "timing": timing,
                "error": None,
                "updated_at": (
                    task.updated_at.isoformat() if task.updated_at else None
                ),
            }
        )
        return integration_envelope(request, base)

    @router.post("/api/v1/integration/tasks/{task_id}/retrigger")
    def integration_retrigger(
        request: Request,
        task_id: str,
        background: BackgroundTasks,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, WRITE_SCOPE)
        task = integration_task_or_404(db, task_id)
        kb_or_404(db, task.kb_id, principal, minimum="editor")
        document = integration_document(db, task)
        if document is None:
            raise HTTPException(status_code=400, detail="任务无关联文档，无法重触发")
        task.ocr_status = "processing"
        task.ocr_progress = 0
        task.extract_status = "pending"
        task.extract_progress = 0
        task.error = ""
        task.result_version = None
        task.updated_at = utcnow()
        db.flush()
        start_document_parse(db, document, principal, background, force=True)
        db.commit()
        db.refresh(task)
        return integration_envelope(
            request,
            integration_task_view(db, task),
            "任务已重新触发",
        )

    @router.get("/api/v1/integration/tasks/{task_id}/session-token")
    def integration_session_token(
        request: Request,
        task_id: str,
        db: Session = Depends(get_db),
    ) -> Any:
        task = integration_task_or_404(db, task_id)
        document = integration_document(db, task)
        if document is None:
            raise HTTPException(status_code=404, detail="任务无关联文档")
        token, expires = create_share_token(
            settings.secret_key, document.id, settings.share_token_minutes
        )
        return integration_envelope(
            request,
            {
                "task_id": task.task_id,
                "token": token,
                "document_id": integration_format_id(document.id),
                "kb_id": integration_format_id(task.kb_id),
                "expires_at": expires.isoformat(),
                "path": f"/share/{token}",
            },
            "会话令牌已签发",
        )

    @router.get("/v1/documents/{document_id}/items")
    def document_items(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        state = require_job(document)
        if ensure_results_synced(db, document, state):
            return items_payload(db, document, state)
        return read_json(
            state, ("item_inventory_aligned.json", "item_inventory.json")
        )

    @router.get("/v1/documents/{document_id}/records")
    def document_records(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        state = require_job(document)
        if ensure_results_synced(db, document, state):
            return reviewed_records(db, document, state)
        return read_json(state, ("result.json",)).get("records") or []

    @router.get("/v1/documents/{document_id}/alignment")
    def document_alignment(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        return read_json(require_job(document), ("alignment.json",))

    @router.post("/v1/documents/{document_id}/results/sync", status_code=202)
    def document_results_sync(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, WRITE_SCOPE)
        document = document_or_404(
            db, document_id, principal, minimum="editor"
        )
        state = require_job(document)
        if state.status not in {"succeeded", "review"}:
            raise HTTPException(status_code=409, detail="results not ready")
        try:
            counts = sync_results(db, document, state)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail="artifacts not ready") from exc
        audit(
            db,
            principal,
            "document.results.sync",
            "document",
            document.id,
            counts,
        )
        db.commit()
        return counts

    @router.get("/v1/documents/{document_id}/result")
    def document_result(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        state = require_job(document)
        payload = read_json(state, ("result.json",))
        payload["records"] = reviewed_records(db, document, state)
        return payload

    # ------------------------------------------------------------- feedback

    @router.get("/v1/system/features")
    def system_features() -> dict[str, Any]:
        return {"selfheal": bool(settings.selfheal_enabled)}

    def selfheal_call(
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 60.0,
    ) -> Any:
        if not settings.selfheal_enabled:
            raise HTTPException(status_code=404, detail="self-heal disabled")
        try:
            with httpx.Client(timeout=timeout, trust_env=False) as client:
                response = client.request(
                    method,
                    f"{settings.selfheal_base_url}{path}",
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=503, detail=f"self-heal unavailable: {exc}"
            ) from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail") or response.text
            except ValueError:
                detail = response.text
            raise HTTPException(status_code=response.status_code, detail=detail)
        return response.json()

    def selfheal_text(
        method: str,
        path: str,
        *,
        timeout: float = 60.0,
    ) -> str:
        if not settings.selfheal_enabled:
            raise HTTPException(status_code=404, detail="self-heal disabled")
        try:
            with httpx.Client(timeout=timeout, trust_env=False) as client:
                response = client.request(
                    method, f"{settings.selfheal_base_url}{path}"
                )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=503, detail=f"self-heal unavailable: {exc}"
            ) from exc
        if response.status_code >= 400:
            raise HTTPException(
                status_code=response.status_code, detail=response.text
            )
        return response.text

    def selfheal_scope(document: Document) -> tuple[str, str]:
        state = require_job(document)
        result = read_json(state, ("result.json",))
        engine_doc_id = str((result.get("document") or {}).get("doc_id") or "")
        if not engine_doc_id:
            raise HTTPException(status_code=409, detail="result has no document id")
        return engine_doc_id, state.job_id

    def selfheal_owned_feedback(
        document: Document, feedback_id: str
    ) -> dict[str, Any]:
        engine_doc_id, _ = selfheal_scope(document)
        detail = selfheal_call("GET", f"/v1/selfheal/feedback/{feedback_id}")
        if (detail.get("feedback") or {}).get("doc_id") != engine_doc_id:
            raise HTTPException(status_code=404, detail="feedback not found")
        return detail

    def learned_rules_path() -> Path:
        return Path(settings.engine_data_dir) / "repairs" / "table_repairs.json"

    def load_learned_rules() -> dict[str, Any]:
        path = learned_rules_path()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def save_learned_rules(payload: dict[str, Any]) -> None:
        path = learned_rules_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def result_document_key(result: dict[str, Any]) -> str:
        metadata = result.get("document") or {}
        standard_no = str(metadata.get("standard_no") or "")
        if standard_no:
            return "".join(char for char in standard_no.upper() if char.isalnum())
        return str(metadata.get("doc_id") or "")

    def result_table_signature(
        result: dict[str, Any], table_id: str
    ) -> str | None:
        from metal_doc_agent.contracts import TableGrid
        from metal_doc_agent.tablegrid.repairs import table_signature

        table = next(
            (
                item
                for item in result.get("tables") or []
                if str(item.get("table_id")) == str(table_id)
            ),
            None,
        )
        if table is None:
            return None
        try:
            return table_signature(TableGrid.model_validate(table))
        except ValueError:
            return None

    def save_learned_repair(
        result: dict[str, Any],
        repair: dict[str, Any],
    ) -> dict[str, Any]:
        table_id = str(repair.get("table_id") or "")
        spec = repair.get("spec")
        if not table_id or not isinstance(spec, dict) or not spec:
            return {}
        data = load_learned_rules()
        document_key = result_document_key(result)
        documents = data.setdefault("documents", {})
        documents.setdefault(document_key, {})[table_id] = spec
        outcome: dict[str, Any] = {"document_rule_saved": True}
        signature = result_table_signature(result, table_id)
        if signature:
            templates = data.setdefault("templates", {})
            existing = templates.get(signature) or {}
            same_spec = existing.get("spec") == spec
            status = (
                "approved"
                if existing.get("status") == "approved" and same_spec
                else "pending"
            )
            templates[signature] = {
                "table_id": table_id,
                "spec": spec,
                "status": status,
                "source_doc_id": str(
                    (result.get("document") or {}).get("doc_id") or ""
                ),
                "updated_at": utcnow().isoformat(),
            }
            outcome.update(
                template_signature=signature,
                template_status=status,
            )
        save_learned_rules(data)
        return outcome

    @router.get("/v1/documents/{document_id}/feedback")
    def document_feedback_list(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        engine_doc_id, _ = selfheal_scope(document)
        return selfheal_call(
            "GET",
            f"/v1/selfheal/feedback?doc_id={url_quote(engine_doc_id)}",
        )

    @router.post("/v1/documents/{document_id}/feedback")
    def document_feedback_create(
        document_id: str,
        payload: DocumentFeedbackRequest,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, WRITE_SCOPE)
        document = document_or_404(db, document_id, principal)
        engine_doc_id, job_id = selfheal_scope(document)
        target = {
            key: value
            for key, value in {
                "record_id": payload.record_id,
                "property": payload.property,
                "table_id": payload.table_id,
                "feature": payload.feature,
                "page_no": payload.page_no,
                "grade": payload.grade,
                "condition": payload.condition,
            }.items()
            if value not in (None, "")
        }
        outcome = selfheal_call(
            "POST",
            "/v1/selfheal/feedback",
            {
                "doc_id": engine_doc_id,
                "job_id": job_id,
                "user_id": principal.actor_id,
                "category": payload.category,
                "target": target,
                "description": payload.description,
                "expected_value": payload.expected_value,
                "source_quote": payload.source_quote,
            },
            # Free-text feedback may call the locating model before returning.
            timeout=180.0,
        )
        audit(
            db,
            principal,
            "document.feedback.create",
            "document",
            document.id,
            {
                "feedback_id": (outcome.get("feedback") or {}).get("feedback_id"),
                "category": payload.category,
            },
        )
        db.commit()
        return outcome

    @router.get("/v1/documents/{document_id}/feedback/{feedback_id}")
    def document_feedback_detail(
        document_id: str,
        feedback_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        return selfheal_owned_feedback(document, feedback_id)

    @router.post("/v1/documents/{document_id}/feedback/{feedback_id}/process")
    def document_feedback_process(
        document_id: str,
        feedback_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, WRITE_SCOPE)
        document = document_or_404(db, document_id, principal)
        selfheal_owned_feedback(document, feedback_id)
        outcome = selfheal_call(
            "POST",
            f"/v1/selfheal/feedback/{feedback_id}/process",
            timeout=900.0,
        )
        audit(
            db,
            principal,
            "document.feedback.process",
            "document",
            document.id,
            {"feedback_id": feedback_id, "status": outcome.get("status")},
        )
        db.commit()
        return outcome

    @router.get("/v1/documents/{document_id}/feedback/{feedback_id}/repair")
    def document_feedback_repair(
        document_id: str,
        feedback_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        selfheal_owned_feedback(document, feedback_id)
        return selfheal_call(
            "GET", f"/v1/selfheal/feedback/{feedback_id}/repair"
        )

    @router.post("/v1/documents/{document_id}/feedback/{feedback_id}/apply")
    def document_feedback_apply(
        document_id: str,
        feedback_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, WRITE_SCOPE)
        document = document_or_404(db, document_id, principal)
        selfheal_owned_feedback(document, feedback_id)
        if (document.review_status or "draft") == "confirmed":
            raise HTTPException(
                status_code=409, detail="文档已确认，请先重新打开审核后再应用修复"
            )
        state = require_job(document)
        job_dir = Path(state.out_dir)
        repair = selfheal_call(
            "GET", f"/v1/selfheal/feedback/{feedback_id}/repair"
        )
        if not repair.get("available"):
            raise HTTPException(status_code=409, detail="没有可应用的修复结果")
        kind = str(repair.get("kind") or "table_fix")
        result = selfheal_call(
            "GET",
            f"/v1/selfheal/feedback/{feedback_id}"
            f"/artifact?name=result.json&kind={kind}",
            timeout=180.0,
        )
        current = read_json(state, ("result.json",))
        current_doc_id = str((current.get("document") or {}).get("doc_id") or "")
        new_doc_id = str((result.get("document") or {}).get("doc_id") or "")
        if current_doc_id and new_doc_id and current_doc_id != new_doc_id:
            raise HTTPException(status_code=409, detail="修复结果不属于该文档")
        quality = result.get("quality") or {}
        if quality.get("status") == "fail":
            raise HTTPException(status_code=409, detail="修复结果未通过质量检查")

        backup = job_dir / f"result.before-feedback-{feedback_id}.json"
        if not backup.exists():
            backup.write_text(
                json.dumps(current, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        (job_dir / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        for name in (
            "item_inventory_aligned.json",
            "item_inventory.json",
            "outline.json",
            "cross_standard_merge.json",
        ):
            try:
                payload = selfheal_call(
                    "GET",
                    f"/v1/selfheal/feedback/{feedback_id}"
                    f"/artifact?name={name}&kind={kind}",
                    timeout=120.0,
                )
            except HTTPException as exc:
                if exc.status_code == 404:
                    continue
                raise
            (job_dir / name).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        for name in ("evidence.jsonl", "clauses.jsonl"):
            try:
                text = selfheal_text(
                    "GET",
                    f"/v1/selfheal/feedback/{feedback_id}"
                    f"/artifact-text?name={name}&kind={kind}",
                    timeout=120.0,
                )
            except HTTPException as exc:
                if exc.status_code == 404:
                    continue
                raise
            (job_dir / name).write_text(text, encoding="utf-8")

        counts = sync_results(db, document, state)
        # Learn from the pre-repair snapshot so the template signature matches
        # the raw extraction of a sibling document, not the already-fixed output.
        learning_source = current
        try:
            snapshot = json.loads(backup.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            snapshot = None
        if isinstance(snapshot, dict):
            learning_source = snapshot
        learned = save_learned_repair(learning_source, repair)
        try:
            rule_learning = selfheal_call(
                "POST",
                f"/v1/selfheal/feedback/{feedback_id}/learn",
                timeout=180.0,
            )
        except HTTPException:
            rule_learning = {"status": "skipped", "reason": "学习服务不可用"}
        audit(
            db,
            principal,
            "document.feedback.apply",
            "document",
            document.id,
            {
                "feedback_id": feedback_id,
                "kind": kind,
                "counts": counts,
                "summary": repair.get("summary"),
                **learned,
            },
        )
        db.commit()
        return {
            "applied": True,
            "feedback_id": feedback_id,
            "kind": kind,
            "summary": repair.get("summary"),
            "counts": counts,
            "backup": str(backup),
            **learned,
            "rule_learning": rule_learning,
        }

    @router.get("/v1/system/template-repairs")
    def list_template_repairs(
        principal: Principal = Depends(get_principal),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        data = load_learned_rules()
        templates = data.get("templates") or {}
        return {
            "items": [
                {"signature": signature, **value}
                for signature, value in templates.items()
            ]
        }

    @router.post("/v1/system/template-repairs/{signature}/approve")
    def approve_template_repair(
        signature: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, WRITE_SCOPE)
        data = load_learned_rules()
        templates = data.get("templates") or {}
        template = templates.get(signature)
        if template is None:
            raise HTTPException(status_code=404, detail="template repair not found")
        template["status"] = "approved"
        template["updated_at"] = utcnow().isoformat()
        save_learned_rules(data)
        audit(
            db,
            principal,
            "template_repair.approve",
            "template_repair",
            signature,
            {"table_id": template.get("table_id")},
        )
        db.commit()
        return {"signature": signature, **template}

    def project_document_schema(
        db: Session, document: Document, state: Any
    ) -> dict:
        """Project one document's artifacts onto the hansonDoc slim schema."""

        template_path = (
            Path(settings.engine_root)
            / "configs"
            / "schema_templates"
            / "product_standard.json"
        )
        timing_seconds = 0.0
        try:
            trace = read_json(state, ("trace.json",))
            timing_seconds = float(trace.get("elapsed_ms") or 0) / 1000.0
        except HTTPException:
            pass
        try:
            payload = project_hanson_schema(
                Path(state.out_dir),
                load_template(template_path),
                index=document_dictionary_index(document),
                timing_seconds=timing_seconds,
                records=reviewed_records(db, document, state),
            )
            # The engine fills missing methods from normative references after
            # projection. Mirror that step here so the platform view matches
            # the job's schema_result.json instead of dropping those methods.
            try:
                from metal_doc_agent.contracts import Page
                from metal_doc_agent.method_binding import fill_projected_methods

                pages_path = Path(state.out_dir) / "pages.json"
                if pages_path.exists():
                    pages = [
                        Page.model_validate(item)
                        for item in json.loads(
                            pages_path.read_text(encoding="utf-8")
                        )
                    ]
                    fill_projected_methods(payload, pages)
            except Exception:  # noqa: BLE001 - method fill is best effort
                pass
            return payload
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail="artifacts not ready") from exc

    @router.get("/v1/documents/{document_id}/result/schema")
    def document_schema_result(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        state = require_job(document)
        if state.status not in {"succeeded", "review"}:
            raise HTTPException(status_code=409, detail="results not ready")
        return project_document_schema(db, document, state)

    def cross_standard_path(state: Any, name: str) -> Path:
        return Path(state.out_dir) / name

    def cross_standard_tasks(state: Any) -> list[dict]:
        path = cross_standard_path(state, "cross_standard_tasks.json")
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def cross_standard_state(state: Any, name: str, default: Any) -> Any:
        path = cross_standard_path(state, name)
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    @router.get("/v1/documents/{document_id}/cross-standard/tasks")
    def cross_standard_task_list(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        state = require_job(document)
        tasks = cross_standard_tasks(state)
        ignored = set(
            cross_standard_state(state, "cross_standard_ignored.json", [])
        )
        overrides = {
            item.get("task_id"): item
            for item in cross_standard_state(
                state, "cross_standard_overrides.json", []
            )
            if isinstance(item, dict)
        }
        for task in tasks:
            task_id = task.get("task_id")
            if task_id in ignored:
                task["status"] = "ignored"
            elif task_id in overrides:
                task["status"] = "confirmed"
                task["merge"] = {
                    "target_field": "标准要求",
                    "requirement": overrides[task_id].get("requirement"),
                    "applied": True,
                    "conflict": False,
                    "confirmed_by": overrides[task_id].get("confirmed_by"),
                }
        summary = {
            "total": len(tasks),
            "resolved": sum(
                1
                for task in tasks
                if task.get("status") in {"resolved", "confirmed"}
            ),
            "candidate": sum(
                1 for task in tasks if task.get("status") == "candidate"
            ),
            "needs_source": sum(
                1 for task in tasks if task.get("status") == "needs_source"
            ),
            "not_found": sum(
                1 for task in tasks if task.get("status") == "not_found"
            ),
            "expanded": sum(1 for task in tasks if task.get("expansion")),
        }
        return {"tasks": tasks, "summary": summary}

    @router.post(
        "/v1/documents/{document_id}/cross-standard/tasks/{task_id}/ignore"
    )
    def cross_standard_ignore(
        document_id: str,
        task_id: str,
        payload: dict | None = Body(default=None),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, WRITE_SCOPE)
        document = document_or_404(db, document_id, principal, minimum="editor")
        state = require_job(document)
        ignored = cross_standard_state(
            state, "cross_standard_ignored.json", []
        )
        if task_id not in ignored:
            ignored.append(task_id)
        cross_standard_path(state, "cross_standard_ignored.json").write_text(
            json.dumps(ignored, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        audit(
            db,
            principal,
            "cross_standard.ignore",
            "document",
            document.id,
            {"task_id": task_id, "reason": (payload or {}).get("reason", "")},
        )
        return {"task_id": task_id, "status": "ignored"}

    @router.post(
        "/v1/documents/{document_id}/cross-standard/tasks/{task_id}/confirm"
    )
    def cross_standard_confirm(
        document_id: str,
        task_id: str,
        payload: dict = Body(...),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, WRITE_SCOPE)
        document = document_or_404(db, document_id, principal, minimum="editor")
        state = require_job(document)
        tasks = cross_standard_tasks(state)
        task = next(
            (item for item in tasks if item.get("task_id") == task_id), None
        )
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        overrides = cross_standard_state(
            state, "cross_standard_overrides.json", []
        )
        expansion = task.get("expansion") or {}
        extracted = (expansion.get("extracted") or [{}])[0]
        entry = {
            "task_id": task_id,
            "inspection_item": payload.get("inspection_item")
            or task.get("inspection_item"),
            "field": payload.get("field") or extracted.get("field"),
            "requirement": payload.get("requirement")
            or extracted.get("requirement"),
            "provenance": payload.get("provenance") or task.get("provenance") or [],
            "confirmed_by": principal.actor_id,
        }
        if not entry.get("requirement"):
            raise HTTPException(status_code=400, detail="requirement is empty")
        overrides = [
            item for item in overrides if item.get("task_id") != task_id
        ] + [entry]
        cross_standard_path(
            state, "cross_standard_overrides.json"
        ).write_text(
            json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        ignored = [
            item
            for item in cross_standard_state(
                state, "cross_standard_ignored.json", []
            )
            if item != task_id
        ]
        cross_standard_path(state, "cross_standard_ignored.json").write_text(
            json.dumps(ignored, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        audit(
            db,
            principal,
            "cross_standard.confirm",
            "document",
            document.id,
            {"task_id": task_id, "requirement": entry.get("requirement")},
        )
        return {"task_id": task_id, "status": "confirmed", "merge": entry}

    @router.post(
        "/v1/documents/{document_id}/cross-standard/tasks/{task_id}/expand"
    )
    def cross_standard_expand(
        document_id: str,
        task_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, WRITE_SCOPE)
        document = document_or_404(db, document_id, principal, minimum="editor")
        state = require_job(document)
        tasks = cross_standard_tasks(state)
        if not any(item.get("task_id") == task_id for item in tasks):
            raise HTTPException(status_code=404, detail="task not found")
        from metal_doc_agent.contracts import CrossStandardTask
        from metal_doc_agent.cross_standard_expand import expand_tasks

        parsed = [CrossStandardTask.model_validate(item) for item in tasks]
        summary = expand_tasks(
            Path(state.out_dir),
            Path(settings.engine_root),
            parsed,
        )
        updated = [item.model_dump(mode="json") for item in parsed]
        cross_standard_path(state, "cross_standard_tasks.json").write_text(
            json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        audit(
            db,
            principal,
            "cross_standard.expand",
            "document",
            document.id,
            {"task_id": task_id, "summary": summary},
        )
        return {"summary": summary, "tasks": updated}

    @router.get("/v1/documents/{document_id}/result/versions")
    def document_result_versions(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> list[dict]:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        links = (
            db.execute(
                select(DocumentTask)
                .where(DocumentTask.document_id == document.id)
                .order_by(DocumentTask.created_at.desc())
            )
            .scalars()
            .all()
        )
        versions: list[dict] = []
        for link in links:
            state = store.get(link.job_id)
            schema = {}
            if state is not None:
                path = Path(state.out_dir) / "schema_result.json"
                if path.exists():
                    try:
                        schema = json.loads(path.read_text(encoding="utf-8"))
                    except ValueError:
                        schema = {}
            categories = schema.get("categories") or []
            versions.append(
                {
                    "job_id": link.job_id,
                    "version": link.version,
                    "status": state.status if state else "unknown",
                    "created_at": (
                        link.created_at.isoformat()
                        if link.created_at
                        else (state.created_at if state else "")
                    ),
                    "schema_name": schema.get("schema_name")
                    or "产品标准抽取模板",
                    "category_count": len(categories),
                    "record_count": sum(
                        len(category.get("records") or []) for category in categories
                    ),
                    "locked": link.locked,
                }
            )
        return versions

    @router.get("/v1/documents/{document_id}/export")
    def export_document(
        document_id: str,
        format: str = Query("csv"),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Response:
        require_scope(principal, READ_SCOPE)
        if format not in {"csv", "xlsx"}:
            raise HTTPException(status_code=422, detail="unsupported export format")
        document = document_or_404(db, document_id, principal)
        state = require_job(document)
        return document_export_response(db, document, state, format)

    @router.get("/v1/documents/{document_id}/new-terms")
    def document_new_terms(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        payload = read_json(require_job(document), ("new_terms.json",))
        # 大类级别不产生新词候选，历史任务产物中的 category 也不对外展示。
        payload["terms"] = [
            term for term in payload.get("terms", []) if term.get("type") != "category"
        ]
        return payload

    @router.get(
        "/v1/documents/{document_id}/reviews",
        response_model=list[ReviewEventOut],
    )
    def document_reviews(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> list[ReviewEventOut]:
        require_scope(principal, READ_SCOPE)
        document_or_404(db, document_id, principal)
        rows = (
            db.execute(
                select(ReviewEvent)
                .where(ReviewEvent.document_id == document_id)
                .order_by(ReviewEvent.created_at.desc())
            )
            .scalars()
            .all()
        )
        return [ReviewEventOut.model_validate(row) for row in rows]

    @router.get(
        "/v1/documents/{document_id}/field-reviews",
        response_model=list[FieldReviewOut],
    )
    def list_field_reviews(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> list[FieldReviewOut]:
        require_scope(principal, READ_SCOPE)
        document_or_404(db, document_id, principal)
        rows = field_review_rows(db, document_id)
        return [FieldReviewOut.model_validate(row) for row in reversed(rows)]

    @router.post(
        "/v1/documents/{document_id}/field-reviews",
        response_model=FieldReviewOut,
        status_code=201,
    )
    def create_field_review(
        document_id: str,
        payload: FieldReviewRequest,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> FieldReviewOut:
        if principal.actor_type != "user":
            raise HTTPException(status_code=403, detail="user token required")
        require_scope(principal, WRITE_SCOPE)
        document = document_or_404(
            db, document_id, principal, minimum="editor"
        )
        state = require_job(document)
        if (document.review_status or "draft") == "confirmed":
            raise HTTPException(
                status_code=409,
                detail="document is confirmed and locked; re-split to start a new version",
            )
        if state.status not in {"succeeded", "review"}:
            raise HTTPException(
                status_code=409,
                detail=f"parse task is not ready for review: {state.status}",
            )
        records = current_records(db, document, state)
        row = create_field_event(db, document, state, payload, principal, records)
        audit(
            db,
            principal,
            f"document.field_review.{payload.action}",
            "document",
            document.id,
            {
                "field_path": payload.field_path,
                "version": document.review_version or 1,
                "job_id": state.job_id,
            },
        )
        db.commit()
        return FieldReviewOut.model_validate(row)

    @router.post(
        "/v1/documents/{document_id}/field-reviews/batch",
        response_model=list[FieldReviewOut],
    )
    def create_field_reviews_batch(
        document_id: str,
        payload: FieldReviewBatchRequest,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> list[FieldReviewOut]:
        if principal.actor_type != "user":
            raise HTTPException(status_code=403, detail="user token required")
        require_scope(principal, WRITE_SCOPE)
        if not payload.events:
            raise HTTPException(status_code=422, detail="batch requires at least one event")
        if len(payload.events) > 200:
            raise HTTPException(status_code=422, detail="batch exceeds 200 events")
        document = document_or_404(
            db, document_id, principal, minimum="editor"
        )
        state = require_job(document)
        if (document.review_status or "draft") == "confirmed":
            raise HTTPException(
                status_code=409,
                detail="document is confirmed and locked; re-split to start a new version",
            )
        records = current_records(db, document, state)
        rows = [
            create_field_event(db, document, state, item, principal, records)
            for item in payload.events
        ]
        audit(
            db,
            principal,
            "document.field_review.batch",
            "document",
            document.id,
            {"events": len(rows), "version": document.review_version or 1},
        )
        db.commit()
        return [FieldReviewOut.model_validate(row) for row in rows]

    @router.get(
        "/v1/documents/{document_id}/field-diff",
        response_model=list[FieldDiffOut],
    )
    def field_diff(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> list[FieldDiffOut]:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        state = require_job(document)
        rows = field_review_rows(db, document.id, state.job_id)
        machine = current_records(db, document, state)
        return [
            FieldDiffOut.model_validate(item)
            for item in diff_records(machine, engine_field_events(rows))
        ]

    @router.get(
        "/v1/documents/{document_id}/review-risks",
        response_model=DocumentRiskOut,
    )
    def review_risks(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> DocumentRiskOut:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        state = require_job(document)
        summary = risk_summary(
            load_document_result(state), load_document_evidence(state)
        )
        return DocumentRiskOut(
            document_id=document.id,
            level=summary["level"],
            counts=summary["counts"],
            high_risk_fields=summary["high_risk_fields"],
            fields=summary["fields"],
        )

    @router.post(
        "/v1/documents/{document_id}/review",
        response_model=DocumentReviewOut,
    )
    def review_document(
        document_id: str,
        payload: DocumentReviewRequest,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> DocumentReviewOut:
        if principal.actor_type != "user":
            raise HTTPException(status_code=403, detail="user token required")
        require_scope(principal, WRITE_SCOPE)
        document = document_or_404(
            db, document_id, principal, minimum="editor"
        )
        state = require_job(document)
        status = document.review_status or "draft"
        if status == "confirmed":
            raise HTTPException(
                status_code=409,
                detail="document is confirmed and locked; re-split to start a new version",
            )
        if state.status not in {"succeeded", "review"}:
            raise HTTPException(
                status_code=409,
                detail=f"parse task is not ready for review: {state.status}",
            )

        pending = pending_new_terms(state)
        if payload.action == "submit":
            document.review_status = "review"
            message = "已提交复核"
        else:
            if status != "review":
                raise HTTPException(
                    status_code=409,
                    detail="submit the document for review first",
                )
            if pending:
                raise HTTPException(
                    status_code=409,
                    detail=f"{pending} pending new terms must be resolved before confirmation",
                )
            reviewed = {
                row.field_path for row in field_review_rows(db, document.id, state.job_id)
            }
            risks = field_risks(
                load_document_result(state), load_document_evidence(state)
            )
            blocked = [
                risk for risk in risks
                if risk.level == "high" and risk.field_path not in reviewed
            ]
            if blocked:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "high_risk_fields_unreviewed",
                        "count": len(blocked),
                        "fields": [risk.to_dict() for risk in blocked[:10]],
                    },
                )
            document.review_status = "confirmed"
            document.confirmed_job_id = document.job_id
            document.confirmed_by = principal.actor_id
            document.confirmed_at = utcnow()
            link = db.scalar(
                select(DocumentTask).where(
                    DocumentTask.job_id == document.job_id
                )
            )
            if link is not None:
                link.locked = True
            message = f"已确认并锁定 v{document.review_version or 1}"

        audit(
            db,
            principal,
            f"document.review.{payload.action}",
            "document",
            document.id,
            {
                "version": document.review_version or 1,
                "job_id": document.job_id,
                "pending_new_terms": pending,
                "reason": payload.reason,
            },
        )
        db.commit()
        return DocumentReviewOut(
            document_id=document.id,
            review_status=document.review_status,
            review_version=document.review_version or 1,
            job_id=document.job_id,
            confirmed_job_id=document.confirmed_job_id,
            pending_new_terms=pending,
            confirmed_by=document.confirmed_by,
            confirmed_at=document.confirmed_at,
            message=message,
        )

    @router.post("/v1/documents/{document_id}/new-terms/review")
    def review_document_term(
        document_id: str,
        payload: NewTermReviewRequest,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        if principal.actor_type != "user":
            raise HTTPException(status_code=403, detail="user token required")
        require_scope(principal, WRITE_SCOPE)
        document = document_or_404(
            db, document_id, principal, minimum="editor"
        )
        if (document.review_status or "draft") == "confirmed":
            raise HTTPException(
                status_code=409,
                detail="document is confirmed and locked; re-split to start a new version",
            )
        state = require_job(document)
        out_dir = Path(state.out_dir)
        terms_path = out_dir / "new_terms.json"
        if payload.type == "category":
            raise HTTPException(
                status_code=422,
                detail="大类级别不产生新词候选，请直接维护项目大类词典",
            )
        if not terms_path.exists():
            raise HTTPException(status_code=409, detail="new terms not ready")
        store = load_new_terms(terms_path)
        term = find_new_term(store, payload.type, payload.raw)
        if term is None:
            raise HTTPException(status_code=404, detail="new term not found")

        applied_code: str | None = None
        matched = False
        with dictionary_lock:
            if payload.action == "reject":
                term.status = "rejected"
                save_new_terms(store, terms_path)
                updated = store
                term_status = "rejected"
            else:
                if document.kb_id:
                    dictionary = load_kb_dictionary(document.kb_id)
                    override_path = ensure_kb_dictionary(document.kb_id)
                else:
                    dictionary = load_engine_dictionary()
                    _, override_path = dictionary_paths()
                try:
                    merged, applied_code, term_status = review_new_term(
                        dictionary,
                        override_path,
                        term,
                        payload.action,
                        business_code=payload.business_code,
                        business_name=payload.business_name,
                        target_code=payload.target_code,
                        category_code=payload.category_code,
                        category_name=payload.category_name,
                        standard_no=payload.standard_no,
                    )
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                result, updated = reapply_alignment(
                    out_dir,
                    merged,
                    category_mode=engine_settings.dictionary_category_mode,
                )
                write_artifact_manifest(
                    out_dir, job_id=state.job_id, doc_id=document.id
                )
                document.results_job_id = None
                matched = any(
                    match.canonical_id == applied_code
                    for match in (
                        *result.item_matches,
                        *result.property_matches,
                        *result.method_matches,
                    )
                )

            event = ReviewEvent(
                document_id=document.id,
                term_type=payload.type,
                raw=payload.raw,
                action=payload.action,
                target_code=payload.target_code,
                business_code=applied_code or payload.business_code,
                business_name=payload.business_name,
                actor_id=principal.actor_id,
                reason=payload.reason,
            )
            db.add(event)
            audit(
                db,
                principal,
                f"new_term.{payload.action}",
                "document",
                document.id,
                {
                    "type": payload.type,
                    "raw": payload.raw,
                    "target_code": payload.target_code,
                    "business_code": applied_code or payload.business_code,
                    "matched": matched,
                },
            )
            db.commit()

        return {
            "action": payload.action,
            "type": payload.type,
            "raw": payload.raw,
            "term_status": term_status,
            "applied_code": applied_code,
            "matched": matched,
            "new_terms": updated.model_dump(mode="json"),
        }

    @router.get("/v1/documents/{document_id}/evidence")
    def document_evidence(
        document_id: str,
        limit: int = Query(1000, ge=1, le=20000),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        state = require_job(document)
        if ensure_results_synced(db, document, state):
            return evidence_payload(db, document, state, limit)
        return read_jsonl(state, "evidence.jsonl", limit)

    @router.get("/v1/documents/{document_id}/evidence/{evidence_id}")
    def document_evidence_item(
        document_id: str,
        evidence_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        state = require_job(document)
        if ensure_results_synced(db, document, state):
            row = find_evidence(db, document, state, evidence_id)
            if row is not None:
                return row
            raise HTTPException(status_code=404, detail="evidence not found")
        path = artifact_file(state, ("evidence.jsonl",))
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("evidence_id") == evidence_id:
                return row
        raise HTTPException(status_code=404, detail="evidence not found")

    @router.get("/v1/documents/{document_id}/clauses")
    def document_clauses(
        document_id: str,
        limit: int = Query(2000, ge=1, le=20000),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        state = require_job(document)
        if ensure_results_synced(db, document, state):
            return clauses_payload(db, document, state)[:limit]
        return read_jsonl(state, "clauses.jsonl", limit)

    @router.get("/v1/documents/{document_id}/links")
    def document_links(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        return read_json(require_job(document), ("links.json",))

    @router.get("/v1/documents/{document_id}/coverage-audit")
    def document_coverage_audit(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        return read_json(require_job(document), ("coverage_audit.json",))

    @router.get("/v1/documents/{document_id}/preview")
    def document_preview(
        document_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        state = require_job(document)
        try:
            preview = build_preview(state.out_dir, document.id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail="preview not ready") from exc
        for page in preview["pages"]:
            page_no = page["page_no"]
            page["image_url"] = (
                f"/v1/documents/{document.id}/pages/{page_no}/image"
                if page.get("image")
                else None
            )
            page["layout_url"] = (
                f"/v1/documents/{document.id}/pages/{page_no}/layout"
                if page.get("layout")
                else None
            )
        return preview

    @router.get("/v1/documents/{document_id}/pages/{page_no}/image")
    def document_page_image(
        document_id: str,
        page_no: int,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        path = page_image_path(require_job(document).out_dir, page_no)
        if path is None:
            raise HTTPException(status_code=404, detail="page image not found")
        return FileResponse(path, media_type="image/png", filename=path.name)

    @router.get("/v1/documents/{document_id}/pages/{page_no}/layout")
    def document_page_layout(
        document_id: str,
        page_no: int,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Any:
        require_scope(principal, READ_SCOPE)
        document = document_or_404(db, document_id, principal)
        try:
            return load_layout(require_job(document).out_dir, page_no)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="layout not available") from exc

    # ---------------------------------------------------------------- share

    @router.get("/v1/share/{token}")
    def shared_document(token: str, db: Session = Depends(get_db)) -> Any:
        document_id = verify_share_token(settings.secret_key, token)
        if document_id is None:
            raise HTTPException(status_code=401, detail="invalid or expired share token")
        document = db.get(Document, document_id)
        if document is None or document.deleted_at is not None:
            raise HTTPException(status_code=404, detail="document not found")

        bundle: dict[str, Any] = {"document": document_out(db, document)}
        if document.job_id and store.get(document.job_id) is not None:
            state = store.get(document.job_id)
            bundle["task"] = task_out(state, document, None)
            for key, names in (
                ("items", ("item_inventory_aligned.json", "item_inventory.json")),
                ("alignment", ("alignment.json",)),
                ("new_terms", ("new_terms.json",)),
            ):
                try:
                    bundle[key] = read_json(state, names)
                except HTTPException:
                    continue
            if document.results_job_id == state.job_id:
                bundle["records"] = reviewed_records(db, document, state)
                bundle["clauses"] = clauses_payload(db, document, state)
                bundle["evidence"] = evidence_payload(
                    db, document, state, 5000
                )
            else:
                try:
                    bundle["records"] = (
                        read_json(state, ("result.json",)).get("records") or []
                    )
                except HTTPException:
                    bundle["records"] = []
                try:
                    bundle["clauses"] = read_jsonl(state, "clauses.jsonl", 2000)
                except HTTPException:
                    bundle["clauses"] = []
                try:
                    bundle["evidence"] = read_jsonl(state, "evidence.jsonl", 5000)
                except HTTPException:
                    bundle["evidence"] = []
            if bundle.get("records"):
                try:
                    template_path = (
                        Path(settings.engine_root)
                        / "configs"
                        / "schema_templates"
                        / "product_standard.json"
                    )
                    bundle["schema"] = project_hanson_schema(
                        Path(state.out_dir),
                        load_template(template_path),
                        index=document_dictionary_index(document),
                        records=bundle["records"],
                    )
                except (FileNotFoundError, ValueError):
                    pass
        return bundle

    @router.get("/v1/share/{token}/export")
    def shared_document_export(
        token: str,
        format: str = Query("csv"),
        db: Session = Depends(get_db),
    ) -> Response:
        if format not in {"csv", "xlsx"}:
            raise HTTPException(status_code=422, detail="unsupported export format")
        document_id = verify_share_token(settings.secret_key, token)
        if document_id is None:
            raise HTTPException(status_code=401, detail="invalid or expired share token")
        document = db.get(Document, document_id)
        if document is None or document.deleted_at is not None:
            raise HTTPException(status_code=404, detail="document not found")
        state = require_job(document)
        return document_export_response(db, document, state, format)

    # ---------------------------------------------------------------- tasks

    @router.get("/v1/tasks", response_model=list[TaskOut])
    def list_tasks(
        kb_id: str | None = Query(None),
        module: str | None = Query(None),
        status: str | None = Query(None),
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> list[TaskOut]:
        require_scope(principal, READ_SCOPE)
        stmt = (
            select(DocumentTask, Document)
            .join(Document, DocumentTask.document_id == Document.id)
            .where(Document.deleted_at.is_(None))
        )
        if module or kb_id:
            target_kb = resolve_document_kb(db, principal, kb_id, module)
            stmt = stmt.where(Document.kb_id == target_kb.id)
        else:
            kb_ids = accessible_kb_ids(db, principal)
            if not kb_ids:
                return []
            stmt = stmt.where(Document.kb_id.in_(kb_ids))
        stmt = stmt.order_by(DocumentTask.created_at.desc())
        if status:
            tasks = [
                task_out(store.get(link.job_id), document, link)
                for link, document in db.execute(stmt).all()
            ]
            matched = [task for task in tasks if task.status == status]
            return matched[offset : offset + limit]
        rows = db.execute(stmt.limit(limit).offset(offset)).all()
        return [
            task_out(store.get(link.job_id), document, link)
            for link, document in rows
        ]

    @router.get("/v1/tasks/{job_id}", response_model=TaskOut)
    def get_task(
        job_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> TaskOut:
        require_scope(principal, READ_SCOPE)
        link = db.scalar(
            select(DocumentTask).where(DocumentTask.job_id == job_id)
        )
        if link is None:
            raise HTTPException(status_code=404, detail="task not found")
        document = db.get(Document, link.document_id)
        if document is None or document.deleted_at is not None:
            raise HTTPException(status_code=404, detail="document not found")
        kb_or_404(db, document.kb_id, principal)
        return task_out(store.get(job_id), document, link)

    @router.post(
        "/v1/tasks/{job_id}/retry", response_model=TaskOut, status_code=202
    )
    def retry_task(
        job_id: str,
        background: BackgroundTasks,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> TaskOut:
        require_scope(principal, WRITE_SCOPE)
        link = db.scalar(
            select(DocumentTask).where(DocumentTask.job_id == job_id)
        )
        if link is None:
            raise HTTPException(status_code=404, detail="task not found")
        document = db.get(Document, link.document_id)
        if document is None or document.deleted_at is not None:
            raise HTTPException(status_code=404, detail="document not found")
        kb_or_404(db, document.kb_id, principal, minimum="editor")
        if link.locked:
            raise HTTPException(
                status_code=409,
                detail="task is locked by a confirmed document version",
            )
        state = store.get(job_id)
        if state is None:
            raise HTTPException(status_code=404, detail="task not found")
        if state.status not in {"failed", "review"}:
            raise HTTPException(
                status_code=409, detail=f"task status {state.status} cannot be retried"
            )
        reset = store.reset_for_retry(job_id)
        document.results_job_id = None
        audit(db, principal, "task.retry", "task", job_id)
        db.commit()
        if settings.inline_jobs:
            background.add_task(run_job, store, job_id, engine_settings)
        return task_out(reset, document, link)

    @router.post(
        "/v1/tasks/{job_id}/cancel", response_model=TaskOut, status_code=202
    )
    def cancel_task(
        job_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> TaskOut:
        require_scope(principal, WRITE_SCOPE)
        link = db.scalar(
            select(DocumentTask).where(DocumentTask.job_id == job_id)
        )
        if link is None:
            raise HTTPException(status_code=404, detail="task not found")
        document = db.get(Document, link.document_id)
        if document is None or document.deleted_at is not None:
            raise HTTPException(status_code=404, detail="document not found")
        kb_or_404(db, document.kb_id, principal, minimum="editor")
        if link.locked:
            raise HTTPException(
                status_code=409,
                detail="task is locked by a confirmed document version",
            )
        state = store.get(job_id)
        if state is None:
            raise HTTPException(status_code=404, detail="task not found")
        if state.status != "queued":
            raise HTTPException(
                status_code=409,
                detail=f"only queued tasks can be cancelled (current={state.status})",
            )
        if store.claim(job_id) is None:
            raise HTTPException(
                status_code=409, detail="task is already running; wait for it to finish"
            )
        try:
            store.update(
                job_id,
                status="running",
                stage="error",
                error="cancelled by user",
                failure_code="cancelled",
            )
            cancelled = store.update(
                job_id,
                status="failed",
                stage="error",
                error="cancelled by user",
                failure_code="cancelled",
            )
        finally:
            store.release_claim(job_id)
        audit(db, principal, "task.cancel", "task", job_id)
        db.commit()
        return task_out(cancelled, document, link)

    # ------------------------------------------------------------ api keys

    @router.post("/v1/api-keys", response_model=ApiKeyOut, status_code=201)
    def create_api_key(
        payload: ApiKeyCreate,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> ApiKeyOut:
        if principal.actor_type != "user" or principal.user is None:
            raise HTTPException(status_code=403, detail="user token required")
        if payload.workspace_id:
            require_workspace_role(db, principal, payload.workspace_id)
            workspace_id = payload.workspace_id
        else:
            workspace_id = default_workspace(db, principal.user).id
        kb_ids: list[str] = []
        if payload.kb_ids:
            for kb_id in payload.kb_ids:
                kb = kb_or_404(db, kb_id, principal)
                if kb.workspace_id != workspace_id:
                    raise HTTPException(
                        status_code=422, detail="KB is outside the API key workspace"
                    )
                kb_ids.append(kb.id)
        raw, prefix, hashed = generate_api_key()
        scopes = sorted({scope.strip() for scope in payload.scopes if scope.strip()})
        key = ApiKey(
            name=payload.name.strip(),
            prefix=prefix,
            hashed_key=hashed,
            scopes=",".join(scopes),
            workspace_id=workspace_id,
            kb_ids=kb_ids_to_text(kb_ids),
            created_by=principal.actor_id,
        )
        db.add(key)
        audit(
            db,
            principal,
            "api_key.create",
            "api_key",
            key.id,
            {"name": key.name, "scopes": scopes, "kb_ids": kb_ids},
            workspace_id=workspace_id,
        )
        db.commit()
        db.refresh(key)
        return ApiKeyOut(
            id=key.id,
            name=key.name,
            prefix=key.prefix,
            scopes=scopes,
            workspace_id=key.workspace_id,
            kb_ids=kb_ids_from_text(key.kb_ids) or [],
            created_at=key.created_at,
            revoked_at=None,
            key=raw,
        )

    @router.get("/v1/api-keys", response_model=list[ApiKeyOut])
    def list_api_keys(
        workspace_id: str | None = Query(default=None),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> list[ApiKeyOut]:
        if principal.actor_type != "user":
            raise HTTPException(status_code=403, detail="user token required")
        if workspace_id:
            require_workspace_role(db, principal, workspace_id)
        if principal.anonymous:
            stmt = select(ApiKey)
        else:
            stmt = select(ApiKey).where(ApiKey.created_by == principal.actor_id)
        if workspace_id:
            stmt = stmt.where(ApiKey.workspace_id == workspace_id)
        rows = (
            db.execute(stmt.order_by(ApiKey.created_at.desc()))
            .scalars()
            .all()
        )
        return [
            ApiKeyOut(
                id=key.id,
                name=key.name,
                prefix=key.prefix,
                scopes=[scope for scope in (key.scopes or "").split(",") if scope],
                workspace_id=key.workspace_id,
                kb_ids=kb_ids_from_text(key.kb_ids) or [],
                created_at=key.created_at,
                revoked_at=key.revoked_at,
            )
            for key in rows
        ]

    @router.delete("/v1/api-keys/{key_id}", status_code=204)
    def revoke_api_key(
        key_id: str,
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Response:
        if principal.actor_type != "user":
            raise HTTPException(status_code=403, detail="user token required")
        key = db.get(ApiKey, key_id)
        if key is None or (
            not principal.anonymous and key.created_by != principal.actor_id
        ):
            raise HTTPException(status_code=404, detail="api key not found")
        key.revoked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        audit(db, principal, "api_key.revoke", "api_key", key.id)
        db.commit()
        return Response(status_code=204)

    # --------------------------------------------------------------- audit

    @router.get("/platform/ready")
    def platform_ready(response: Response, db: Session = Depends(get_db)) -> dict:
        checks: dict[str, bool] = {}
        try:
            db.execute(select(1)).first()
            checks["database"] = True
        except Exception:  # noqa: BLE001 - readiness must not raise
            checks["database"] = False
        if not settings.db_auto_create:
            try:
                verify_migrations(engine)
                checks["migrations"] = True
            except Exception:  # noqa: BLE001 - readiness must not raise
                checks["migrations"] = False
        engine_check = readiness(engine_settings.project_root, engine_settings.data_dir)
        checks.update(engine_check["checks"])
        checks.update(model_service_checks())
        status = "ok" if all(checks.values()) else "degraded"
        if status != "ok":
            response.status_code = 503
        return {
            "status": status,
            "environment": settings.environment,
            "checks": checks,
        }

    @router.get("/platform/metrics")
    def platform_metrics(db: Session = Depends(get_db)) -> Any:
        lines = engine_metrics(
            JobStore(Path(engine_settings.data_dir) / "jobs"),
            Path(engine_settings.data_dir) / "queues",
        ).splitlines()
        review_counts = dict(
            db.execute(
                select(Document.review_status, func.count())
                .where(Document.deleted_at.is_(None))
                .group_by(Document.review_status)
            ).all()
        )
        lines.extend(
            render_family(
                "platform_documents",
                [
                    ({"status": status}, int(review_counts.get(status, 0)))
                    for status in ("draft", "review", "confirmed")
                ],
            )
        )
        action_counts = dict(
            db.execute(
                select(FieldReviewEvent.action, func.count()).group_by(
                    FieldReviewEvent.action
                )
            ).all()
        )
        lines.extend(
            render_family(
                "platform_field_review_events",
                [
                    ({"action": action}, int(action_counts.get(action, 0)))
                    for action in ("accept", "edit", "reject")
                ],
            )
        )
        error_counts = getattr(app.state, "error_counts", {}) if app is not None else {}
        if error_counts:
            lines.extend(
                render_family(
                    "platform_errors_total",
                    [
                        (
                            {"status": str(status), "route": route},
                            int(count),
                        )
                        for (status, route), count in sorted(error_counts.items())
                    ],
                )
            )
        return PlainTextResponse(
            "\n".join(lines) + "\n", media_type="text/plain; version=0.0.4"
        )

    @router.get("/v1/audit-logs", response_model=list[AuditLogOut])
    def list_audit_logs(
        workspace_id: str | None = Query(default=None),
        action: str | None = Query(default=None),
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> list[AuditLogOut]:
        if not settings.require_auth or (
            principal.actor_type == "user"
            and principal.user is not None
            and principal.user.role == "admin"
        ):
            pass
        else:
            if not workspace_id:
                raise HTTPException(
                    status_code=403,
                    detail="workspace_id is required for workspace audit",
                )
            require_workspace_role(
                db, principal, workspace_id, minimum="admin"
            )
        stmt = select(AuditLog)
        if workspace_id:
            stmt = stmt.where(AuditLog.workspace_id == workspace_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        rows = (
            db.execute(
                stmt.order_by(AuditLog.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            .scalars()
            .all()
        )
        return [AuditLogOut.model_validate(row) for row in rows]

    return router
