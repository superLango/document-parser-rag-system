"""Sandbox execution orchestration: workspace, executor, validation, storage."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from hanson_contracts import (
    ExecutionDiagnostic,
    ExecutionManifest,
    ExecutionMetrics,
    ExecutionOutput,
    ExecutionRequest,
    ExecutionResult,
)

from services.shared.storage import ObjectStore

from .config import Settings
from .executor import Executor, ExecutorError, RawExecution
from .validation import (
    REQUIRED_FILES,
    ROLE_CONTENT_TYPES,
    ValidatedOutputs,
    ValidationError,
    sha256,
    validate_outputs,
)
from .workspace import WorkspaceError, prepare_workspace

logger = logging.getLogger(__name__)


class SandboxService:
    def __init__(self, settings: Settings, store: ObjectStore, executor: Executor) -> None:
        self.settings = settings
        self.store = store
        self.executor = executor

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        if request.engine.image and request.engine.image != self.settings.engine_image:
            return self._rejected(
                request,
                "SANDBOX_ENGINE_MISMATCH",
                f"requested image {request.engine.image!r}, "
                f"service allows {self.settings.engine_image!r}",
            )
        execution_id = uuid.uuid4().hex
        workspace = None
        try:
            workspace = await prepare_workspace(request, self.store, self.settings)
            raw = await self.executor.execute(workspace)
            return await self._finalize(workspace, raw, execution_id)
        except WorkspaceError as exc:
            logger.warning("sandbox workspace rejected for run %s: %s", request.run_id, exc)
            return self._rejected(request, exc.code, str(exc))
        except ExecutorError as exc:
            logger.warning("sandbox executor failed for run %s: %s", request.run_id, exc)
            return self._failed(
                request,
                execution_id,
                exc.code,
                str(exc),
                RawExecution(),
            )
        except Exception as exc:  # noqa: BLE001 - keep the API contract stable
            logger.exception("sandbox execution crashed for run %s", request.run_id)
            return self._failed(
                request, execution_id, "SANDBOX_INTERNAL", str(exc), RawExecution()
            )
        finally:
            if workspace is not None:
                workspace.cleanup()

    async def _finalize(
        self,
        workspace: Any,
        raw: RawExecution,
        execution_id: str,
    ) -> ExecutionResult:
        request = workspace.request
        status = "succeeded"
        error_code: str | None = None
        message = raw.detail
        validated: ValidatedOutputs | None = None

        if raw.timed_out:
            status = "timeout"
            error_code = "SANDBOX_TIMEOUT"
            message = message or "execution exceeded its time budget"
        elif raw.oom:
            status = "oom"
            error_code = "SANDBOX_OOM"
            message = message or "execution exceeded its memory limit"
        elif raw.exit_code == 3:
            status = "invalid_output"
            error_code = "SANDBOX_INVALID_OUTPUT"
        elif raw.exit_code == 124:
            status = "timeout"
            error_code = "SANDBOX_TIMEOUT"
            message = message or "engine reported a timeout"
        elif raw.exit_code != 0:
            status = "failed"
            error_code = "SANDBOX_EXIT_NONZERO"
            message = message or f"engine exited with code {raw.exit_code}"
        else:
            try:
                validated = validate_outputs(
                    raw.files,
                    self.settings.max_output_bytes,
                    self.settings.max_output_files,
                )
            except ValidationError as exc:
                status = "invalid_output"
                error_code = exc.code
                message = str(exc)

        if status != "succeeded" or validated is None:
            return await self._failed(
                request,
                execution_id,
                error_code or "SANDBOX_FAILED",
                message,
                raw,
                status=status,
            )

        outputs = await self._upload_outputs(request.run_id, execution_id, validated)
        diagnostics = [
            ExecutionDiagnostic.model_validate(item) for item in validated.diagnostics
        ]
        metrics = ExecutionMetrics(
            duration_ms=raw.duration_ms,
            exit_code=raw.exit_code,
            memory_limit_mb=request.limits.memory_mb,
            cpu_limit=request.limits.cpu,
            peak_memory_mb=self._peak_memory(validated),
        )
        manifest = ExecutionManifest(
            engine_version=self.settings.engine_version,
            engine_image=self.settings.engine_image,
            engine_image_digest=raw.image_digest,
            runtime=raw.runtime or self.settings.runtime,
            recipe={
                "recipe_id": request.recipe.recipe_id,
                "version": request.recipe.version,
                "digest": request.recipe.digest,
            },
            template={
                "template_id": request.template.template_id,
                "version": request.template.version,
                "digest": request.template.digest,
            },
            inputs=dict(workspace.input_hashes),
            outputs=dict(validated.digests),
            isolation=dict(raw.isolation),
        )
        return ExecutionResult(
            run_id=request.run_id,
            trace_id=request.trace_id,
            status="succeeded",
            outputs=outputs,
            metrics=metrics,
            manifest=manifest,
            diagnostics=diagnostics,
            stderr=raw.stderr[-2000:],
        )

    async def _upload_outputs(
        self,
        run_id: str,
        execution_id: str,
        validated: ValidatedOutputs,
    ) -> dict[str, ExecutionOutput]:
        prefix = f"runs/{run_id}/sandbox/{execution_id}"
        uploads = []
        names = []
        for name in REQUIRED_FILES:
            data = validated.files[name]
            role = name.rsplit(".", 1)[0]
            key = f"{prefix}/{name}"
            uploads.append(
                self.store.put_bytes(key, data, ROLE_CONTENT_TYPES.get(role, "application/json"))
            )
            names.append((role, key, name))
        await asyncio.gather(*uploads)
        return {
            role: ExecutionOutput(
                role=role,
                storage_key=key,
                sha256=validated.digests[name],
                bytes=len(validated.files[name]),
                content_type=ROLE_CONTENT_TYPES.get(role, "application/json"),
            )
            for role, key, name in names
        }

    @staticmethod
    def _peak_memory(validated: ValidatedOutputs) -> int | None:
        try:
            metrics = json.loads(validated.files["metrics.json"])
        except (ValueError, KeyError):
            return None
        value = metrics.get("peak_memory_mb")
        return int(value) if isinstance(value, int) else None

    async def _failed(
        self,
        request: ExecutionRequest,
        execution_id: str,
        error_code: str,
        message: str,
        raw: RawExecution,
        status: str = "failed",
    ) -> ExecutionResult:
        diagnostics_payload = self._diagnostics_payload(error_code, message or error_code, raw)
        outputs: dict[str, ExecutionOutput] = {}
        key = f"runs/{request.run_id}/sandbox/{execution_id}/diagnostics.json"
        try:
            data = (
                raw.files.get("diagnostics.json")
                if raw.files.get("diagnostics.json")
                else diagnostics_payload
            )
            await self.store.put_bytes(key, data, "application/json")
            outputs["diagnostics"] = ExecutionOutput(
                role="diagnostics",
                storage_key=key,
                sha256=sha256(data),
                bytes=len(data),
                content_type="application/json",
            )
        except Exception:  # noqa: BLE001 - failed runs must still return a result
            logger.exception("failed to persist diagnostics for run %s", request.run_id)

        return ExecutionResult(
            run_id=request.run_id,
            trace_id=request.trace_id,
            status=status,  # type: ignore[arg-type]
            error_code=error_code,
            error_message=(message or error_code)[-2000:],
            outputs=outputs,
            metrics=ExecutionMetrics(
                duration_ms=raw.duration_ms,
                exit_code=raw.exit_code,
                memory_limit_mb=request.limits.memory_mb,
                cpu_limit=request.limits.cpu,
            ),
            manifest=ExecutionManifest(
                engine_version=self.settings.engine_version,
                engine_image=self.settings.engine_image,
                engine_image_digest=raw.image_digest,
                runtime=raw.runtime or self.settings.runtime,
                recipe={
                    "recipe_id": request.recipe.recipe_id,
                    "version": request.recipe.version,
                    "digest": request.recipe.digest,
                },
                template={
                    "template_id": request.template.template_id,
                    "version": request.template.version,
                    "digest": request.template.digest,
                },
                isolation=dict(raw.isolation),
            ),
            diagnostics=[
                ExecutionDiagnostic(
                    code=error_code,
                    message=(message or error_code)[:2000],
                    severity="error",
                    detail={
                        "exit_code": raw.exit_code,
                        "timed_out": raw.timed_out,
                        "oom": raw.oom,
                    },
                )
            ],
            stderr=raw.stderr[-2000:],
        )

    @staticmethod
    def _diagnostics_payload(error_code: str, message: str, raw: RawExecution) -> bytes:
        payload = {
            "schema_version": "sandbox-diagnostics/1",
            "diagnostics": [
                {
                    "code": error_code,
                    "message": message[:2000],
                    "severity": "error",
                    "detail": {
                        "exit_code": raw.exit_code,
                        "timed_out": raw.timed_out,
                        "oom": raw.oom,
                        "stderr": raw.stderr[-2000:],
                    },
                }
            ],
        }
        return (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")

    def _rejected(
        self, request: ExecutionRequest, error_code: str, message: str
    ) -> ExecutionResult:
        return ExecutionResult(
            run_id=request.run_id,
            trace_id=request.trace_id,
            status="rejected",
            error_code=error_code,
            error_message=message[-2000:],
            manifest=ExecutionManifest(
                engine_version=self.settings.engine_version,
                engine_image=self.settings.engine_image,
                runtime=self.settings.runtime,
                recipe={
                    "recipe_id": request.recipe.recipe_id,
                    "version": request.recipe.version,
                    "digest": request.recipe.digest,
                },
                template={
                    "template_id": request.template.template_id,
                    "version": request.template.version,
                    "digest": request.template.digest,
                },
            ),
            diagnostics=[
                ExecutionDiagnostic(
                    code=error_code, message=message[:2000], severity="error", detail={}
                )
            ],
        )
