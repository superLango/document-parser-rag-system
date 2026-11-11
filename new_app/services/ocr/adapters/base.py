from dataclasses import dataclass, field
from typing import Protocol

from ..contracts import OcrRequest, OcrResult


class OcrBackendError(RuntimeError):
    """Stable error codes for the OCR stage."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class AdapterOutput:
    result: OcrResult
    assets: dict[str, bytes] = field(default_factory=dict)


class OcrPort(Protocol):
    name: str

    async def parse(self, data: bytes, request: OcrRequest) -> AdapterOutput: ...
