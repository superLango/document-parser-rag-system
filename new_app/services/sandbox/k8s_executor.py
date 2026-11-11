"""Kubernetes Job executor.

Each execution becomes a short-lived Job with an isolated pod: non-root,
read-only root filesystem, all capabilities dropped, RuntimeDefault seccomp,
resource limits, no service-account token and a deny-all NetworkPolicy target.

Inputs are shipped in a per-execution ConfigMap (1 MiB object limit), outputs
are returned by the runtime as a base64 envelope on stdout. This keeps the
executor free of shared storage and works with the kind cluster used in CI.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from hanson_contracts import RuntimeInfo

from .config import Settings
from .executor import ExecutorError, RawExecution
from .validation import REQUIRED_FILES
from .workspace import Workspace

ENVELOPE_PREFIX = "HANSON_ENVELOPE "
MAX_LOG_CHARS = 64 * 1024
MAX_CONFIGMAP_BYTES = 800_000


def _pod_env(
    settings: Settings, workspace: Workspace, isolation: dict[str, Any]
) -> list[dict[str, str]]:
    request = workspace.request
    return [
        {"name": "HOME", "value": "/tmp"},
        {"name": "TMPDIR", "value": "/tmp"},
        {"name": "TZ", "value": "UTC"},
        {"name": "LANG", "value": "C.UTF-8"},
        {"name": "LC_ALL", "value": "C.UTF-8"},
        {"name": "PYTHONHASHSEED", "value": "0"},
        {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"},
        {"name": "HANSON_REQUEST", "value": "/work/input/request.json"},
        {"name": "HANSON_ENGINE_VERSION", "value": settings.engine_version},
        {"name": "HANSON_ENGINE_IMAGE", "value": settings.engine_image},
        {"name": "HANSON_ENGINE_IMAGE_DIGEST", "value": ""},
        {"name": "HANSON_RUNTIME", "value": "containerd"},
        {"name": "HANSON_ISOLATION", "value": json.dumps(isolation, sort_keys=True)},
        {"name": "HANSON_EMIT_ENVELOPE", "value": "1"},
        {"name": "HANSON_MAX_ENVELOPE_BYTES", "value": str(settings.max_output_bytes)},
        {"name": "HANSON_RUN_ID", "value": request.run_id},
    ]


class KubernetesExecutor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        host = os.environ.get("KUBERNETES_SERVICE_HOST", "")
        port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
        self.namespace = settings.kubernetes_namespace
        self._base_url = f"https://{host}:{port}" if host else ""
        token_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
        ca_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
        token = token_path.read_text(encoding="utf-8").strip() if token_path.exists() else ""
        verify: str | bool = str(ca_path) if ca_path.exists() else True
        self._client = httpx.AsyncClient(
            base_url=self._base_url or "https://kubernetes.default.svc",
            headers={"Authorization": f"Bearer {token}"} if token else {},
            verify=verify,
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if not self._base_url:
            raise ExecutorError(
                "SANDBOX_UNAVAILABLE", "not running inside a Kubernetes cluster"
            )
        try:
            return await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ExecutorError(
                "SANDBOX_UNAVAILABLE", f"kubernetes api unavailable: {exc}"
            ) from exc

    @staticmethod
    def _message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:500]
        if isinstance(payload, dict):
            return str(payload.get("message") or payload)[:500]
        return str(payload)[:500]

    def _isolation(self, request_limits: Any) -> dict[str, Any]:
        return {
            "network": "deny-all (NetworkPolicy)",
            "read_only_rootfs": True,
            "user": "65534:65534",
            "cap_drop": ["ALL"],
            "no_new_privileges": True,
            "seccomp": "RuntimeDefault",
            "pids_limit": getattr(request_limits, "pids", self.settings.default_pids),
            "memory_mb": getattr(request_limits, "memory_mb", self.settings.default_memory_mb),
            "cpu": getattr(request_limits, "cpu", self.settings.default_cpu),
            "automount_service_account_token": False,
            "runtime": "containerd",
        }

    async def info(self) -> RuntimeInfo:
        if not self._base_url:
            return RuntimeInfo(
                executor="kubernetes",
                runtime="containerd",
                engine_image=self.settings.engine_image,
                available=False,
                detail="not running inside a Kubernetes cluster",
            )
        response = await self._call("GET", f"/api/v1/namespaces/{self.namespace}")
        available = response.status_code == 200
        detail = (
            f"namespace={self.namespace}"
            if available
            else f"namespace check failed: {response.status_code} {self._message(response)}"
        )
        return RuntimeInfo(
            executor="kubernetes",
            runtime="containerd",
            engine_image=self.settings.engine_image,
            available=available,
            isolation=self._isolation(None),
            detail=detail,
        )

    def _envelope(self, workspace: Workspace) -> str:
        files = {
            relative: base64.b64encode(data).decode("ascii")
            for relative, data in sorted(workspace.files.items())
        }
        payload = {
            "schema_version": "sandbox-workspace/1",
            "files": files,
            "dirs": ["input", "recipes", "templates"],
        }
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_CONFIGMAP_BYTES:
            raise ExecutorError(
                "SANDBOX_INPUT_TOO_LARGE",
                f"kubernetes executor input exceeds {MAX_CONFIGMAP_BYTES} bytes",
            )
        return encoded

    async def execute(self, workspace: Workspace) -> RawExecution:
        request = workspace.request
        limits = request.limits
        if not self._base_url:
            raise ExecutorError("SANDBOX_UNAVAILABLE", "not running inside a Kubernetes cluster")
        name = f"hanson-sbx-{uuid.uuid4().hex[:20]}"
        isolation = self._isolation(limits)
        env = _pod_env(self.settings, workspace, isolation)
        security_context = {
            "runAsNonRoot": True,
            "runAsUser": 65534,
            "runAsGroup": 65534,
            "fsGroup": 65534,
            "fsGroupChangePolicy": "OnRootMismatch",
            "seccompProfile": {"type": "RuntimeDefault"},
        }
        container_security = {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "runAsNonRoot": True,
            "capabilities": {"drop": ["ALL"]},
        }
        resources = {
            "requests": {"cpu": "50m", "memory": "64Mi"},
            "limits": {
                "cpu": str(max(0.05, float(limits.cpu))),
                "memory": f"{int(limits.memory_mb)}Mi",
            },
        }
        prepare_resources = {
            "requests": {"cpu": "10m", "memory": "32Mi"},
            "limits": {"cpu": "200m", "memory": "128Mi"},
        }
        labels = {"app": "hanson-sandbox-job"}
        annotations = {"hanson.io/run-id": request.run_id}
        envelope = self._envelope(workspace)

        created_configmap = False
        created_job = False
        started = time.monotonic()
        try:
            response = await self._call(
                "POST",
                f"/api/v1/namespaces/{self.namespace}/configmaps",
                json={
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {
                        "name": name,
                        "namespace": self.namespace,
                        "labels": labels,
                        "annotations": annotations,
                    },
                    "data": {"envelope.json": envelope},
                },
            )
            if response.status_code not in (200, 201):
                raise ExecutorError(
                    "SANDBOX_UNAVAILABLE",
                    f"configmap create failed: {response.status_code} {self._message(response)}",
                )
            created_configmap = True

            job = {
                "apiVersion": "batch/v1",
                "kind": "Job",
                "metadata": {
                    "name": name,
                    "namespace": self.namespace,
                    "labels": labels,
                    "annotations": annotations,
                },
                "spec": {
                    "completions": 1,
                    "parallelism": 1,
                    "backoffLimit": 0,
                    "activeDeadlineSeconds": int(limits.timeout_seconds) + 20,
                    "template": {
                        "metadata": {"labels": labels, "annotations": annotations},
                        "spec": {
                            "restartPolicy": "Never",
                            "automountServiceAccountToken": False,
                            "enableServiceLinks": False,
                            "hostNetwork": False,
                            "hostPID": False,
                            "hostIPC": False,
                            "terminationGracePeriodSeconds": 5,
                            "securityContext": security_context,
                            "initContainers": [
                                {
                                    "name": "prepare",
                                    "image": self.settings.engine_image,
                                    "imagePullPolicy": "IfNotPresent",
                                    "command": ["python", "-B", "/engine/prepare.py"],
                                    "env": [
                                        {
                                            "name": "HANSON_CONFIG",
                                            "value": "/config/envelope.json",
                                        }
                                    ],
                                    "securityContext": container_security,
                                    "resources": prepare_resources,
                                    "volumeMounts": [
                                        {"name": "work", "mountPath": "/work"},
                                        {"name": "tmp", "mountPath": "/tmp"},
                                        {
                                            "name": "config",
                                            "mountPath": "/config",
                                            "readOnly": True,
                                        },
                                    ],
                                }
                            ],
                            "containers": [
                                {
                                    "name": "engine",
                                    "image": self.settings.engine_image,
                                    "imagePullPolicy": "IfNotPresent",
                                    "command": ["python", "-B", "/engine/runner.py"],
                                    "env": env,
                                    "securityContext": container_security,
                                    "resources": resources,
                                    "volumeMounts": [
                                        {"name": "work", "mountPath": "/work"},
                                        {"name": "tmp", "mountPath": "/tmp"},
                                    ],
                                }
                            ],
                            "volumes": [
                                {
                                    "name": "work",
                                    "emptyDir": {
                                        "sizeLimit": (
                                            f"{int(self.settings.kubernetes_workspace_mb)}Mi"
                                        )
                                    },
                                },
                                {
                                    "name": "tmp",
                                    "emptyDir": {
                                        "sizeLimit": f"{int(limits.tmpfs_mb)}Mi"
                                    },
                                },
                                {"name": "config", "configMap": {"name": name}},
                            ],
                        },
                    },
                },
            }
            response = await self._call(
                "POST", f"/apis/batch/v1/namespaces/{self.namespace}/jobs", json=job
            )
            if response.status_code not in (200, 201):
                code = (
                    "SANDBOX_RBAC_DENIED"
                    if response.status_code == 403
                    else "SANDBOX_UNAVAILABLE"
                )
                raise ExecutorError(
                    code,
                    f"job create failed: {response.status_code} {self._message(response)}",
                )
            created_job = True

            deadline = time.monotonic() + float(limits.timeout_seconds) + 30
            timed_out = False
            job_status: dict[str, Any] = {}
            while True:
                status = await self._job_status(name)
                job_status = status.get("status") or {}
                if int(job_status.get("succeeded") or 0) >= 1:
                    break
                if int(job_status.get("failed") or 0) >= 1 and not job_status.get("active"):
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                await asyncio.sleep(0.3)

            pod = await self._pod_for_job(name)
            pod_status = (pod.get("status") or {}) if pod else {}
            terminated = self._terminated(pod, "engine")
            exit_code = int((terminated or {}).get("exitCode") or 0)
            reason = str((terminated or {}).get("reason") or "")
            oom = reason == "OOMKilled" or exit_code == 137
            image_digest = self._image_digest(pod, "engine")
            logs = await self._pod_logs(pod, "engine") if pod else ""
            prepare_logs = await self._pod_logs(pod, "prepare") if pod else ""
            envelope_payload = self._parse_envelope(logs)
            files: dict[str, bytes] = {}
            status = "failed"
            error_code = ""
            message = ""
            if envelope_payload:
                status = str(envelope_payload.get("status") or "failed")
                error_code = str(envelope_payload.get("error_code") or "")
                message = str(envelope_payload.get("message") or "")
                files = self._decode_files(envelope_payload.get("files") or {})
            if timed_out:
                status = "timeout"
                error_code = error_code or "SANDBOX_TIMEOUT"
                exit_code = 124
            elif oom:
                status = "oom"
                error_code = error_code or "SANDBOX_OOM"
                exit_code = 137
            elif status == "succeeded" and exit_code != 0:
                status = "failed"
            if status == "succeeded":
                exit_code = 0
            stderr = "\n".join(
                part for part in (logs if not envelope_payload else "", prepare_logs) if part
            )[-MAX_LOG_CHARS:]
            return RawExecution(
                exit_code=exit_code,
                oom=oom,
                timed_out=timed_out,
                files=files,
                stdout=logs[-MAX_LOG_CHARS:],
                stderr=stderr,
                duration_ms=int((time.monotonic() - started) * 1000),
                image_digest=image_digest,
                runtime="containerd",
                isolation=isolation,
                detail=(
                    f"job status={json.dumps(job_status, sort_keys=True)} "
                    f"pod phase={pod_status.get('phase')} reason={reason} "
                    f"{error_code} {message}"
                ).strip(),
            )
        finally:
            if created_job:
                await self._ignore(
                    "DELETE",
                    f"/apis/batch/v1/namespaces/{self.namespace}/jobs/{name}",
                    params={"propagationPolicy": "Background"},
                )
            if created_configmap:
                await self._ignore(
                    "DELETE", f"/api/v1/namespaces/{self.namespace}/configmaps/{name}"
                )

    async def _job_status(self, name: str) -> dict[str, Any]:
        response = await self._call(
            "GET", f"/apis/batch/v1/namespaces/{self.namespace}/jobs/{name}"
        )
        if response.status_code == 404:
            return {}
        if response.status_code != 200:
            raise ExecutorError(
                "SANDBOX_UNAVAILABLE",
                f"job status failed: {response.status_code} {self._message(response)}",
            )
        return response.json()

    async def _pod_for_job(self, name: str) -> dict[str, Any] | None:
        response = await self._call(
            "GET",
            f"/api/v1/namespaces/{self.namespace}/pods",
            params={"labelSelector": f"job-name={name}"},
        )
        if response.status_code != 200:
            return None
        items = response.json().get("items") or []
        return items[0] if items else None

    @staticmethod
    def _terminated(pod: dict[str, Any] | None, container: str) -> dict[str, Any] | None:
        if not pod:
            return None
        for status in pod.get("status", {}).get("containerStatuses") or []:
            if status.get("name") == container:
                return (status.get("state") or {}).get("terminated")
        return None

    @staticmethod
    def _image_digest(pod: dict[str, Any] | None, container: str) -> str:
        if not pod:
            return ""
        for status in pod.get("status", {}).get("containerStatuses") or []:
            if status.get("name") == container:
                image_id = str(status.get("imageID") or "")
                if "@" in image_id:
                    return image_id.split("@", 1)[1]
                return image_id
        return ""

    async def _pod_logs(self, pod: dict[str, Any] | None, container: str) -> str:
        if not pod:
            return ""
        pod_name = str((pod.get("metadata") or {}).get("name") or "")
        if not pod_name:
            return ""
        response = await self._call(
            "GET",
            f"/api/v1/namespaces/{self.namespace}/pods/{pod_name}/log",
            params={
                "container": container,
                "limitBytes": 9 * 1024 * 1024,
                "tailLines": 10000,
            },
        )
        if response.status_code != 200:
            return ""
        return response.text

    @staticmethod
    def _parse_envelope(logs: str) -> dict[str, Any] | None:
        payload: dict[str, Any] | None = None
        for line in logs.splitlines():
            if not line.startswith(ENVELOPE_PREFIX):
                continue
            try:
                candidate = json.loads(line[len(ENVELOPE_PREFIX) :])
            except ValueError:
                continue
            if isinstance(candidate, dict):
                payload = candidate
        return payload

    def _decode_files(self, encoded: dict[str, Any]) -> dict[str, bytes]:
        files: dict[str, bytes] = {}
        total = 0
        for name, content in encoded.items():
            if name not in REQUIRED_FILES:
                raise ExecutorError(
                    "SANDBOX_OUTPUT_INVALID", f"unexpected output file: {name}"
                )
            try:
                data = base64.b64decode(str(content), validate=True)
            except ValueError as exc:
                raise ExecutorError(
                    "SANDBOX_OUTPUT_INVALID", f"invalid base64 for {name}: {exc}"
                ) from exc
            total += len(data)
            if total > self.settings.max_output_bytes:
                raise ExecutorError(
                    "SANDBOX_OUTPUT_LIMIT_EXCEEDED",
                    f"outputs exceed {self.settings.max_output_bytes} bytes",
                )
            files[name] = data
        return files

    async def _ignore(self, method: str, path: str, **kwargs: Any) -> None:
        try:
            await self._client.request(method, path, **kwargs)
        except httpx.HTTPError:
            pass
