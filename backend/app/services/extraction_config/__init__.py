"""抽取配置中心服务包。"""

from app.services.extraction_config.resolver import (
    ExtractionConfigResolver,
    ExtractionDomainConfig,
)

__all__ = ["ExtractionConfigResolver", "ExtractionDomainConfig"]