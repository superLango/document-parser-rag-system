"""KB 资源与配置 Schema（E2：LLM 服务）。"""

from pydantic import BaseModel, Field, field_validator


class LLMResourceSave(BaseModel):
    enabled: bool = False
    api_base: str = Field(default="", max_length=500)
    model: str = Field(default="", max_length=200)
    api_key: str = Field(default="", max_length=500)
    timeout: int = Field(default=300, ge=1, le=3600)

    @field_validator("api_base")
    @classmethod
    def _base_url(cls, v: str):
        v = (v or "").strip()
        if v and not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("api_base 需以 http:// 或 https:// 开头")
        return v
