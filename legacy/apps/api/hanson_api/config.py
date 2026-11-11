"""Platform runtime settings (P0).

The platform owns its own database, uploads and signing secret; the engine keeps
its existing ``METAL_DOC_*`` settings. No model endpoint is needed here.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENGINE_ROOT = PROJECT_ROOT / "metal-doc-agent"


@dataclass(frozen=True)
class PlatformSettings:
    data_dir: Path
    database_url: str
    secret_key: str
    upload_dir: Path
    access_token_minutes: int = 480
    share_token_minutes: int = 15
    max_upload_bytes: int = 50 * 1024 * 1024
    engine_data_dir: Path = ENGINE_ROOT / "data"
    engine_root: Path = ENGINE_ROOT
    inline_jobs: bool = True
    # 是否需要登录。默认不要求登录（嵌入/一站式对接场景）。
    # 需要按用户/API Key 做权限隔离时显式设置 require_auth=True。
    require_auth: bool = False
    anonymous_username: str = "embed_guest"
    # 允许 iframe 嵌入。`from_env` 默认 True（嵌入部署）；
    # 手工构造时默认 False，保持安全响应头。
    allow_embed: bool = False
    environment: str = "dev"
    db_auto_create: bool = True
    login_max_failures: int = 5
    login_window_seconds: int = 300
    login_lockout_seconds: int = 300
    invitation_minutes: int = 10080
    # Self-heal feedback plane (default off). When enabled the platform only
    # proxies feedback requests; it never repairs artifacts itself.
    selfheal_enabled: bool = False
    selfheal_base_url: str = "http://host.docker.internal:8100"

    @property
    def production(self) -> bool:
        return self.environment in {"prod", "production"}

    @classmethod
    def from_env(cls) -> "PlatformSettings":
        data_dir = Path(
            os.environ.get("HANSON_PLATFORM_DATA")
            or PROJECT_ROOT / "data" / "platform"
        )
        data_dir.mkdir(parents=True, exist_ok=True)
        database_url = os.environ.get("HANSON_DATABASE_URL") or (
            f"sqlite:///{(data_dir / 'platform.db').as_posix()}"
        )
        secret_key = os.environ.get("HANSON_SECRET_KEY") or _load_or_create_secret(
            data_dir / "secret.key"
        )
        engine_data = Path(
            os.environ.get("METAL_DOC_DATA") or ENGINE_ROOT / "data"
        )
        environment = (os.environ.get("HANSON_ENV") or "dev").strip().lower()
        production = environment in {"prod", "production"}
        db_auto_create = _env_bool("HANSON_DB_AUTO_CREATE", not production)
        return cls(
            data_dir=data_dir,
            database_url=database_url,
            secret_key=secret_key,
            upload_dir=data_dir / "uploads",
            access_token_minutes=int(
                os.environ.get("HANSON_ACCESS_TOKEN_MINUTES", "480")
            ),
            share_token_minutes=int(
                os.environ.get("HANSON_SHARE_TOKEN_MINUTES", "15")
            ),
            max_upload_bytes=int(
                os.environ.get("HANSON_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024))
            ),
            engine_data_dir=engine_data,
            engine_root=Path(os.environ.get("HANSON_ENGINE_ROOT") or ENGINE_ROOT),
            inline_jobs=_env_bool("HANSON_INLINE_JOBS", True),
            require_auth=_env_bool("HANSON_REQUIRE_AUTH", False),
            anonymous_username=(
                os.environ.get("HANSON_ANONYMOUS_USERNAME") or "embed_guest"
            ).strip(),
            allow_embed=_env_bool("HANSON_ALLOW_EMBED", True),
            environment=environment,
            db_auto_create=db_auto_create,
            login_max_failures=int(
                os.environ.get("HANSON_LOGIN_MAX_FAILURES", "5")
            ),
            login_window_seconds=int(
                os.environ.get("HANSON_LOGIN_WINDOW_SECONDS", "300")
            ),
            login_lockout_seconds=int(
                os.environ.get("HANSON_LOGIN_LOCKOUT_SECONDS", "300")
            ),
            invitation_minutes=int(
                os.environ.get("HANSON_INVITATION_MINUTES", "10080")
            ),
            selfheal_enabled=_env_bool("SELFHEAL_ENABLED", False),
            selfheal_base_url=(
                os.environ.get("SELFHEAL_BASE_URL")
                or "http://host.docker.internal:8100"
            ).rstrip("/"),
        )


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_or_create_secret(path: Path) -> str:
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_hex(32)
    path.write_text(value + "\n", encoding="utf-8")
    return value
