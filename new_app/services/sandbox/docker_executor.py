"""Docker Engine executor.

Uses the Docker Engine HTTP API over the unix socket directly (no docker SDK):
the sandbox service only needs create/start/inspect/logs/archive/kill/remove.
"""

from __future__ import annotations

import asyncio
import io
import json
import tarfile
import time
import uuid
from typing import Any
from urllib.parse import quote

import httpx
from hanson_contracts import RuntimeInfo

from .config import Settings
from .executor import ExecutorError, RawExecution
from .validation import REQUIRED_FILES
from .workspace import Workspace

SANDBOX_USER = "65534:65534"
MAX_LOG_CHARS = 64 * 1024


def _decode_logs(data: bytes) -> tuple[str, str]:
    """Decode Docker's multiplexed log stream (8-byte header per frame)."""
    if not data:
        return "", ""
    stdout: list[bytes] = []
    stderr: list[bytes] = []
    offset = 0
    frames = 0
    while offset + 8 <= len(data):
        stream = data[offset]
        size = int.from_bytes(data[offset + 4 : offset + 8], "big")
        if stream not in (0, 1, 2) or size > len(data) - offset - 8:
            break
        payload = data[offset + 8 : offset + 8 + size]
        if stream == 1:
            stdout.append(payload)
        elif stream == 2:
            stderr.append(payload)
        offset += 8 + size
        frames += 1
    if frames == 0:
        return data.decode("utf-8", "replace"), ""
    return (
        b"".join(stdout).decode("utf-8", "replace"),
        b"".join(stderr).decode("utf-8", "replace"),
    )


def _extract_outputs(data: bytes, limit: int) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        for member in archive.getmembers():
            name = member.name
            while name.startswith("./"):
                name = name[2:]
            if name in {"", ".", "output", "output/"}:
                continue
            if name.startswith("output/"):
                name = name[len("output/") :]
            if member.isdir():
                continue
            if not member.isfile() or member.issym() or member.islnk():
                raise ExecutorError(
                    "SANDBOX_OUTPUT_INVALID", f"unsupported output entry: {member.name}"
                )
            if "/" in name or name not in REQUIRED_FILES:
                raise ExecutorError(
                    "SANDBOX_OUTPUT_INVALID", f"unexpected output file: {name}"
                )
            total += member.size
            if total > limit:
                raise ExecutorError(
                    "SANDBOX_OUTPUT_LIMIT_EXCEEDED", f"outputs exceed {limit} bytes"
                )
            extracted = archive.extractfile(member)
            if extracted is None:
                raise ExecutorError(
                    "SANDBOX_OUTPUT_INVALID", f"cannot read output file: {name}"
                )
            files[name] = extracted.read()
    return files


def _build_tar(workspace: Workspace) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, mode in (
            ("input", 0o555),
            ("recipes", 0o555),
            ("templates", 0o555),
            ("output", 0o777),
        ):
            info = tarfile.TarInfo(name)
            info.type = tarfile.DIRTYPE
            info.mode = mode
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            archive.addfile(info)
        for relative, data in sorted(workspace.files.items()):
            info = tarfile.TarInfo(relative)
            info.size = len(data)
            info.mode = 0o444
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class DockerExecutor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=settings.docker_socket),
            base_url="http://docker",
            timeout=httpx.Timeout(connect=5.0, read=60.0, write=60.0, pool=5.0),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ExecutorError(
                "SANDBOX_UNAVAILABLE", f"docker engine unavailable: {exc}"
            ) from exc

    @staticmethod
    def _message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:500]
        if isinstance(payload, dict):
            return str(payload.get("message") or payload)
        return str(payload)[:500]

    async def _image_info(self) -> dict[str, Any]:
        image = quote(self.settings.engine_image, safe="")
        response = await self._call("GET", f"/images/{image}/json")
        if response.status_code == 404:
            raise ExecutorError(
                "SANDBOX_ENGINE_IMAGE_MISSING",
                f"engine image not found: {self.settings.engine_image}",
            )
        if response.status_code != 200:
            raise ExecutorError(
                "SANDBOX_UNAVAILABLE",
                f"docker image inspect failed: {response.status_code} {self._message(response)}",
            )
        return response.json()

    async def _runtimes(self) -> tuple[dict[str, Any], str]:
        response = await self._call("GET", "/info")
        if response.status_code != 200:
            raise ExecutorError(
                "SANDBOX_UNAVAILABLE", f"docker info failed: {response.status_code}"
            )
        payload = response.json()
        return payload.get("Runtimes") or {}, str(payload.get("DefaultRuntime") or "runc")

    async def info(self) -> RuntimeInfo:
        try:
            runtimes, default_runtime = await self._runtimes()
        except ExecutorError as exc:
            return RuntimeInfo(
                executor="docker",
                runtime=self.settings.runtime,
                engine_image=self.settings.engine_image,
                available=False,
                detail=str(exc),
            )
        runtime = self.settings.runtime or default_runtime
        digest = ""
        image_error = ""
        try:
            digest = str((await self._image_info()).get("Id") or "")
        except ExecutorError as exc:
            image_error = str(exc)
        available = runtime in runtimes and bool(digest)
        return RuntimeInfo(
            executor="docker",
            runtime=runtime,
            engine_image=self.settings.engine_image,
            engine_image_digest=digest,
            available=available,
            isolation=self._isolation(),
            detail=(
                f"runtime={runtime} registered={runtime in runtimes} "
                f"runtimes={sorted(runtimes)} {image_error}"
            ).strip(),
        )

    def _isolation(self) -> dict[str, Any]:
        limits = self.settings
        return {
            "network": "none",
            "read_only_rootfs": True,
            "user": SANDBOX_USER,
            "cap_drop": ["ALL"],
            "no_new_privileges": True,
            "seccomp": "docker-default",
            "pids_limit": limits.default_pids,
            "memory_mb": limits.default_memory_mb,
            "cpu": limits.default_cpu,
            "tmpfs_mb": limits.default_tmpfs_mb,
        }

    async def execute(self, workspace: Workspace) -> RawExecution:
        request = workspace.request
        limits = request.limits
        image = await self._image_info()
        image_digest = str(image.get("Id") or "")
        runtimes, default_runtime = await self._runtimes()
        runtime = self.settings.runtime or default_runtime
        if runtime not in runtimes:
            raise ExecutorError(
                "SANDBOX_RUNTIME_UNAVAILABLE",
                f"docker runtime {runtime!r} is not registered; available={sorted(runtimes)}",
            )

        suffix = uuid.uuid4().hex[:20]
        volume = f"hanson-sbx-{suffix}"
        container_name = f"hanson-sbx-{suffix}"
        isolation = {
            "network": "none",
            "read_only_rootfs": True,
            "user": SANDBOX_USER,
            "cap_drop": ["ALL"],
            "no_new_privileges": True,
            "seccomp": "docker-default",
            "pids_limit": limits.pids,
            "memory_mb": limits.memory_mb,
            "cpu": limits.cpu,
            "tmpfs_mb": limits.tmpfs_mb,
            "runtime": runtime,
        }
        env = [
            "HOME=/tmp",
            "TMPDIR=/tmp",
            "TZ=UTC",
            "LANG=C.UTF-8",
            "LC_ALL=C.UTF-8",
            "PYTHONHASHSEED=0",
            "PYTHONDONTWRITEBYTECODE=1",
            "HANSON_REQUEST=/work/input/request.json",
            f"HANSON_ENGINE_VERSION={self.settings.engine_version}",
            f"HANSON_ENGINE_IMAGE={self.settings.engine_image}",
            f"HANSON_ENGINE_IMAGE_DIGEST={image_digest}",
            f"HANSON_RUNTIME={runtime}",
            f"HANSON_ISOLATION={json.dumps(isolation, sort_keys=True, separators=(',', ':'))}",
            "HANSON_EMIT_ENVELOPE=0",
        ]
        host_config: dict[str, Any] = {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "Memory": int(limits.memory_mb) * 1024 * 1024,
            "MemorySwap": int(limits.memory_mb) * 1024 * 1024,
            "NanoCpus": int(float(limits.cpu) * 1_000_000_000),
            "PidsLimit": int(limits.pids),
            "OomKillDisable": False,
            "Tmpfs": {"/tmp": f"rw,noexec,nosuid,size={int(limits.tmpfs_mb)}m"},
            "Binds": [f"{volume}:/work"],
            "Runtime": runtime,
            "Init": True,
            "Privileged": False,
            "IpcMode": "private",
            "AutoRemove": False,
            "RestartPolicy": {"Name": "no"},
        }
        container_id = ""
        started = time.monotonic()
        timed_out = False
        try:
            response = await self._call(
                "POST",
                "/volumes/create",
                json={"Name": volume, "Labels": {"hanson.sandbox": "1"}},
            )
            if response.status_code not in (200, 201):
                raise ExecutorError(
                    "SANDBOX_UNAVAILABLE",
                    f"docker volume create failed: {response.status_code}",
                )
            response = await self._call(
                "POST",
                "/containers/create",
                params={"name": container_name},
                json={
                    "Image": self.settings.engine_image,
                    "User": SANDBOX_USER,
                    "WorkingDir": "/work",
                    "Env": env,
                    "Tty": False,
                    "OpenStdin": False,
                    "NetworkDisabled": True,
                    "Labels": {
                        "hanson.sandbox": "1",
                        "hanson.run_id": request.run_id,
                    },
                    "HostConfig": host_config,
                },
            )
            if response.status_code not in (200, 201):
                message = self._message(response)
                code = (
                    "SANDBOX_RUNTIME_UNAVAILABLE"
                    if "runtime" in message.lower()
                    else "SANDBOX_UNAVAILABLE"
                )
                raise ExecutorError(code, f"docker create failed: {message}")
            container_id = str(response.json().get("Id") or "")
            if not container_id:
                raise ExecutorError("SANDBOX_UNAVAILABLE", "docker create returned no id")

            response = await self._call(
                "PUT",
                f"/containers/{container_id}/archive",
                params={"path": "/work"},
                content=_build_tar(workspace),
                headers={"Content-Type": "application/x-tar"},
            )
            if response.status_code not in (200, 204):
                raise ExecutorError(
                    "SANDBOX_UNAVAILABLE",
                    f"docker archive upload failed: {response.status_code} "
                    f"{self._message(response)}",
                )
            response = await self._call("POST", f"/containers/{container_id}/start")
            if response.status_code not in (200, 204):
                raise ExecutorError(
                    "SANDBOX_UNAVAILABLE",
                    f"docker start failed: {response.status_code} {self._message(response)}",
                )

            deadline = time.monotonic() + float(limits.timeout_seconds)
            while True:
                state = await self._state(container_id)
                if not state.get("Running") and not state.get("Restarting"):
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    await self._terminate(container_id)
                    break
                await asyncio.sleep(0.2)
            duration_ms = int((time.monotonic() - started) * 1000)
            state = await self._state(container_id)
            exit_code = int(state.get("ExitCode") or 0)
            oom = bool(state.get("OOMKilled"))
            logs = await self._logs(container_id)
            files = await self._outputs(container_id)
            return RawExecution(
                exit_code=exit_code,
                oom=oom,
                timed_out=timed_out,
                files=files,
                stdout=logs[0],
                stderr=logs[1],
                duration_ms=duration_ms,
                image_digest=image_digest,
                runtime=runtime,
                isolation=isolation,
                detail=str(state.get("Error") or ""),
            )
        finally:
            if container_id:
                await self._ignore("DELETE", f"/containers/{container_id}", params={"force": 1})
            await self._ignore("DELETE", f"/volumes/{volume}", params={"force": 1})

    async def _state(self, container_id: str) -> dict[str, Any]:
        response = await self._call("GET", f"/containers/{container_id}/json")
        if response.status_code == 404:
            return {"Running": False, "ExitCode": 0}
        if response.status_code != 200:
            raise ExecutorError(
                "SANDBOX_UNAVAILABLE", f"docker inspect failed: {response.status_code}"
            )
        return dict(response.json().get("State") or {})

    async def _terminate(self, container_id: str) -> None:
        await self._ignore("POST", f"/containers/{container_id}/kill", params={"signal": "SIGTERM"})
        deadline = time.monotonic() + self.settings.kill_grace_seconds
        while time.monotonic() < deadline:
            state = await self._state(container_id)
            if not state.get("Running"):
                return
            await asyncio.sleep(0.2)
        await self._ignore("POST", f"/containers/{container_id}/kill", params={"signal": "SIGKILL"})
        for _ in range(25):
            state = await self._state(container_id)
            if not state.get("Running"):
                return
            await asyncio.sleep(0.2)

    async def _logs(self, container_id: str) -> tuple[str, str]:
        response = await self._call(
            "GET",
            f"/containers/{container_id}/logs",
            params={"stdout": 1, "stderr": 1, "tail": 200},
        )
        if response.status_code != 200:
            return "", ""
        stdout, stderr = _decode_logs(response.content)
        return stdout[-MAX_LOG_CHARS:], stderr[-MAX_LOG_CHARS:]

    async def _outputs(self, container_id: str) -> dict[str, bytes]:
        response = await self._call(
            "GET", f"/containers/{container_id}/archive", params={"path": "/work/output"}
        )
        if response.status_code == 404:
            return {}
        if response.status_code != 200:
            raise ExecutorError(
                "SANDBOX_OUTPUT_UNAVAILABLE",
                f"docker output archive failed: {response.status_code}",
            )
        return _extract_outputs(response.content, self.settings.max_output_bytes)

    async def _ignore(self, method: str, path: str, **kwargs: Any) -> None:
        try:
            await self._client.request(method, path, **kwargs)
        except httpx.HTTPError:
            pass
