# ruff: noqa: B008
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.ocr.contracts import TableGrid

from .assets import AssetError, AssetManifest, AssetRef, AssetRegistry
from .candidate import CandidateError, build_candidate
from .matcher import MatchResult, match_table
from .package import RecipeManifest, RecipePackageError, RecipeRef, build_package
from .registry import RecipeRegistry, RegistryError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal")

_registry: RecipeRegistry | None = None
_asset_registry: AssetRegistry | None = None


def get_registry() -> RecipeRegistry:
    global _registry
    if _registry is None:
        _registry = RecipeRegistry()
    return _registry


def set_registry(registry: RecipeRegistry) -> None:
    global _registry
    _registry = registry


def get_asset_registry() -> AssetRegistry:
    global _asset_registry
    if _asset_registry is None:
        _asset_registry = AssetRegistry()
    return _asset_registry


def set_asset_registry(registry: AssetRegistry) -> None:
    global _asset_registry
    _asset_registry = registry


class AssetPublishIn(BaseModel):
    manifest: dict
    files: dict[str, str] = {}


class AssetResolveIn(BaseModel):
    kind: str
    asset_id: str
    channel: str = "stable"


class AssetPromoteIn(BaseModel):
    channel: str = "stable"
    actor: str
    note: str = ""


class AssetRollbackIn(BaseModel):
    channel: str = "stable"
    actor: str
    note: str = ""


class AssetDetail(BaseModel):
    manifest: AssetManifest
    files: dict[str, str]


class AssetListItem(BaseModel):
    kind: str
    asset_id: str
    channels: dict[str, str]
    versions: list[AssetRef]


class PromoteIn(BaseModel):
    channel: str = "stable"
    actor: str
    note: str = ""


class RollbackIn(BaseModel):
    channel: str = "stable"
    actor: str
    note: str = ""


class DeprecateIn(BaseModel):
    actor: str
    reason: str = ""


class CandidateIn(BaseModel):
    candidate_version: str
    patch: dict = {}
    actor: str
    note: str = ""


class DiscardIn(BaseModel):
    actor: str
    reason: str = ""


class ResolveIn(BaseModel):
    recipe_id: str
    channel: str = "stable"


class MatchIn(BaseModel):
    table: TableGrid
    channel: str = "stable"


class MatchOut(BaseModel):
    table_id: str
    page_no: int
    result: MatchResult


class RecipeDetail(BaseModel):
    recipe_id: str
    channels: dict[str, str]
    versions: list[RecipeRef]


def _http_error(exc: ValueError, code: str) -> HTTPException:
    if code in {"RECIPE_NOT_FOUND", "RECIPE_NOT_RESOLVED"}:
        status = 404
    elif code in {
        "RECIPE_VERSION_IMMUTABLE",
        "RECIPE_ALREADY_PROMOTED",
        "CANDIDATE_VERSION_INVALID",
    }:
        status = 409
    else:
        status = 400
    return HTTPException(status_code=status, detail={"code": code, "message": str(exc)})


@router.post("/recipes", response_model=RecipeRef, status_code=201)
def publish(payload: dict) -> RecipeRef:
    try:
        manifest = build_package(payload)
        return get_registry().publish(manifest)
    except RecipePackageError as exc:
        raise _http_error(exc, exc.code) from exc
    except RegistryError as exc:
        raise _http_error(exc, exc.code) from exc


@router.get("/recipes", response_model=list[RecipeDetail])
def list_recipes() -> list[RecipeDetail]:
    return [RecipeDetail.model_validate(item) for item in get_registry().list_recipes()]


@router.post("/recipes/resolve", response_model=RecipeRef)
def resolve(payload: ResolveIn) -> RecipeRef:
    try:
        return get_registry().resolve(payload.recipe_id, payload.channel)
    except RegistryError as exc:
        raise _http_error(exc, exc.code) from exc


@router.post("/recipes/match", response_model=MatchOut)
def match(payload: MatchIn) -> MatchOut:
    try:
        manifests = get_registry().active_manifests(payload.channel)
    except RegistryError as exc:
        raise _http_error(exc, exc.code) from exc
    result = match_table(payload.table, manifests)
    logger.info(
        "recipe match table=%s page=%s channel=%s recipe=%s status=%s score=%s",
        payload.table.table_id,
        payload.table.page_no,
        payload.channel,
        result.recipe_id,
        result.status,
        result.score,
    )
    return MatchOut(
        table_id=payload.table.table_id,
        page_no=payload.table.page_no,
        result=result,
    )


@router.get("/recipes/{recipe_id}", response_model=RecipeDetail)
def get_recipe(recipe_id: str) -> RecipeDetail:
    registry = get_registry()
    versions = registry.list_versions(recipe_id)
    if not versions:
        raise HTTPException(
            status_code=404,
            detail={"code": "RECIPE_NOT_FOUND", "message": f"unknown recipe: {recipe_id}"},
        )
    return RecipeDetail(
        recipe_id=recipe_id,
        channels=registry.channels_for(recipe_id),
        versions=versions,
    )


@router.get("/recipes/{recipe_id}/versions/{version}", response_model=RecipeManifest)
def get_version(recipe_id: str, version: str) -> RecipeManifest:
    try:
        return get_registry().get(recipe_id, version)
    except RegistryError as exc:
        raise _http_error(exc, exc.code) from exc


@router.post(
    "/recipes/{recipe_id}/versions/{base_version}/candidate",
    response_model=RecipeRef,
    status_code=201,
)
def build_candidate_version(
    recipe_id: str,
    base_version: str,
    payload: CandidateIn,
) -> RecipeRef:
    try:
        return build_candidate(
            get_registry(),
            recipe_id,
            base_version,
            payload.candidate_version,
            list((payload.patch or {}).get("ops") or []),
            actor=payload.actor,
            note=payload.note,
        )
    except CandidateError as exc:
        raise _http_error(exc, exc.code) from exc
    except RegistryError as exc:
        raise _http_error(exc, exc.code) from exc


@router.post(
    "/recipes/{recipe_id}/versions/{version}/discard",
    response_model=RecipeRef,
)
def discard_candidate(
    recipe_id: str,
    version: str,
    payload: DiscardIn,
) -> RecipeRef:
    try:
        return get_registry().discard(
            recipe_id,
            version,
            actor=payload.actor,
            reason=payload.reason,
        )
    except RegistryError as exc:
        raise _http_error(exc, exc.code) from exc


@router.post(
    "/recipes/{recipe_id}/versions/{version}/promote",
    response_model=RecipeRef,
)
def promote(recipe_id: str, version: str, payload: PromoteIn) -> RecipeRef:
    try:
        return get_registry().promote(
            recipe_id,
            version,
            payload.channel,
            actor=payload.actor,
            note=payload.note,
        )
    except RegistryError as exc:
        raise _http_error(exc, exc.code) from exc


@router.post("/recipes/{recipe_id}/rollback", response_model=RecipeRef)
def rollback(recipe_id: str, payload: RollbackIn) -> RecipeRef:
    try:
        return get_registry().rollback(
            recipe_id,
            payload.channel,
            actor=payload.actor,
            note=payload.note,
        )
    except RegistryError as exc:
        raise _http_error(exc, exc.code) from exc


@router.post(
    "/recipes/{recipe_id}/versions/{version}/deprecate",
    response_model=RecipeRef,
)
def deprecate(recipe_id: str, version: str, payload: DeprecateIn) -> RecipeRef:
    try:
        return get_registry().deprecate(
            recipe_id,
            version,
            actor=payload.actor,
            reason=payload.reason,
        )
    except RegistryError as exc:
        raise _http_error(exc, exc.code) from exc


@router.get("/recipes/{recipe_id}/versions/{version}/resolve", response_model=RecipeRef)
def resolve_version(
    recipe_id: str,
    version: str,
    channel: str = Query(default="stable"),
) -> RecipeRef:
    registry = get_registry()
    try:
        manifest = registry.get(recipe_id, version)
    except RegistryError as exc:
        raise _http_error(exc, exc.code) from exc
    return RecipeRef(
        recipe_id=recipe_id,
        version=version,
        digest=manifest.checksum,
        channel=registry.channel_for(recipe_id, version) or channel,
    )


# -- parsing assets (parser bundles / rule packs) ---------------------------


def _asset_http_error(exc: AssetError, code: str) -> HTTPException:
    if code in {"ASSET_NOT_FOUND", "ASSET_NOT_RESOLVED"}:
        status = 404
    elif code in {"ASSET_VERSION_IMMUTABLE", "ASSET_ALREADY_PROMOTED"}:
        status = 409
    else:
        status = 400
    return HTTPException(status_code=status, detail={"code": code, "message": str(exc)})


@router.get("/assets", response_model=list[AssetListItem])
def list_assets(kind: str | None = Query(default=None)) -> list[AssetListItem]:
    return [
        AssetListItem.model_validate(item)
        for item in get_asset_registry().list_assets(kind)
    ]


@router.post("/assets/resolve", response_model=AssetRef)
def resolve_asset(payload: AssetResolveIn) -> AssetRef:
    try:
        return get_asset_registry().resolve(
            payload.kind, payload.asset_id, payload.channel
        )
    except AssetError as exc:
        raise _asset_http_error(exc, exc.code) from exc


@router.post("/assets", response_model=AssetRef, status_code=201)
def publish_asset(payload: AssetPublishIn) -> AssetRef:
    try:
        manifest = AssetManifest.model_validate(payload.manifest)
        files = {
            path: content.encode("utf-8")
            for path, content in payload.files.items()
        }
        return get_asset_registry().publish(manifest, files)
    except AssetError as exc:
        raise _asset_http_error(exc, exc.code) from exc


@router.get("/assets/{kind}/{asset_id}", response_model=AssetListItem)
def get_asset(kind: str, asset_id: str) -> AssetListItem:
    registry = get_asset_registry()
    versions = registry.list_versions(kind, asset_id)
    if not versions:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "ASSET_NOT_FOUND",
                "message": f"unknown asset: {kind}/{asset_id}",
            },
        )
    return AssetListItem(
        kind=kind,
        asset_id=asset_id,
        channels=registry.channels_for(kind, asset_id),
        versions=versions,
    )


@router.get("/assets/{kind}/{asset_id}/history")
def get_asset_history(kind: str, asset_id: str) -> list[dict]:
    return get_asset_registry().history(kind, asset_id)


@router.get(
    "/assets/{kind}/{asset_id}/versions/{version}",
    response_model=AssetDetail,
)
def get_asset_version(kind: str, asset_id: str, version: str) -> AssetDetail:
    try:
        manifest, files = get_asset_registry().get(kind, asset_id, version)
    except AssetError as exc:
        raise _asset_http_error(exc, exc.code) from exc
    return AssetDetail(
        manifest=manifest,
        files={path: content.decode("utf-8") for path, content in files.items()},
    )


@router.post(
    "/assets/{kind}/{asset_id}/versions/{version}/promote",
    response_model=AssetRef,
)
def promote_asset(
    kind: str, asset_id: str, version: str, payload: AssetPromoteIn
) -> AssetRef:
    try:
        return get_asset_registry().promote(
            kind,
            asset_id,
            version,
            payload.channel,
            actor=payload.actor,
            note=payload.note,
        )
    except AssetError as exc:
        raise _asset_http_error(exc, exc.code) from exc


@router.post("/assets/{kind}/{asset_id}/rollback", response_model=AssetRef)
def rollback_asset(
    kind: str, asset_id: str, payload: AssetRollbackIn
) -> AssetRef:
    try:
        return get_asset_registry().rollback(
            kind,
            asset_id,
            payload.channel,
            actor=payload.actor,
            note=payload.note,
        )
    except AssetError as exc:
        raise _asset_http_error(exc, exc.code) from exc
