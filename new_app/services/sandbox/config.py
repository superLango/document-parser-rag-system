from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from services.shared.storage import StorageConfig

SERVICE_DIR = Path(__file__).resolve().parent
REGISTRY_DATA = SERVICE_DIR.parent / "recipe_registry" / "data"


class Settings(BaseSettings):
    executor: str = "docker"
    runtime: str = "runc"
    engine_image: str = "hanson-sandbox-runtime:local"
    engine_version: str = "sandbox-engine/1"
    docker_socket: str = "/var/run/docker.sock"
    workspace_root: Path = Path("/tmp/hanson-sandbox")
    recipe_data_dir: Path = REGISTRY_DATA / "recipes"
    template_data_dir: Path = REGISTRY_DATA / "templates"
    max_input_bytes: int = 64 * 1024 * 1024
    max_output_bytes: int = 16 * 1024 * 1024
    max_output_files: int = 16
    default_cpu: float = 1.0
    default_memory_mb: int = 512
    default_pids: int = 128
    default_timeout_seconds: int = 120
    default_tmpfs_mb: int = 64
    kill_grace_seconds: float = 5.0
    kubernetes_namespace: str = "hanson-standard"
    kubernetes_service_account: str = "sandbox"
    kubernetes_workspace_mb: int = 256
    object_storage_endpoint: str = Field(
        default="http://localhost:19000", validation_alias="OBJECT_STORAGE_ENDPOINT"
    )
    object_storage_bucket: str = Field(
        default="hanson-docs", validation_alias="OBJECT_STORAGE_BUCKET"
    )
    object_storage_access_key: str = Field(
        default="minioadmin", validation_alias="OBJECT_STORAGE_ACCESS_KEY"
    )
    object_storage_secret_key: str = Field(
        default="minioadmin", validation_alias="OBJECT_STORAGE_SECRET_KEY"
    )
    local_storage_dir: Path = Field(
        default=Path("/tmp/hanson-new-app"), validation_alias="LOCAL_STORAGE_DIR"
    )

    model_config = SettingsConfigDict(
        env_prefix="SANDBOX_", env_file=".env", extra="ignore", populate_by_name=True
    )

    def limits_defaults(self) -> dict[str, float | int]:
        return {
            "cpu": self.default_cpu,
            "memory_mb": self.default_memory_mb,
            "pids": self.default_pids,
            "timeout_seconds": self.default_timeout_seconds,
            "tmpfs_mb": self.default_tmpfs_mb,
        }

    def storage_config(self) -> StorageConfig:
        return StorageConfig(
            endpoint=self.object_storage_endpoint,
            bucket=self.object_storage_bucket,
            access_key=self.object_storage_access_key,
            secret_key=self.object_storage_secret_key,
            local_dir=self.local_storage_dir,
        )


settings = Settings()
