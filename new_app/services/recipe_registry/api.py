# ruff: noqa: B008
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.ocr.contracts import TableGrid

from .matcher import MatchResult, match_table
from .package import RecipeManifest, RecipePackageError, RecipeRef, build_package
from .registry import RecipeRegistry, RegistryError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal")

_registry: RecipeRegistry | None = None


def get_registry() -> RecipeRegistry:
    global _registry
    if _registry is None:
        _registry = RecipeRegistry()
    return _registry


def set_registry(registry: RecipeRegistry) -> None:
    global _registry
    _registry = registry


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


class ResolveIn(BaseModel):
    recipe_id: str
    channel: str = "stable"


class MatchIn(BaseModel):
    table: TableGrid


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
    elif code in {"RECIPE_VERSION_IMMUTABLE", "RECIPE_ALREADY_PROMOTED"}:
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
    manifests = get_registry().active_manifests("stable")
    result = match_table(payload.table, manifests)
    logger.info(
        "recipe match table=%s page=%s recipe=%s status=%s score=%s",
        payload.table.table_id,
        payload.table.page_no,
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
        channel=channel,
    )
