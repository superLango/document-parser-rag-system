"""run 创建幂等键：同一内容/通道/parser pin 的重复请求映射到同一个 run。"""

import hashlib


def build_key(
    *,
    prefix: str,
    document_id: str,
    sha256: str,
    channel: str,
    parser_version: str | None = None,
) -> str:
    raw = "|".join(
        [prefix, document_id, sha256, channel, parser_version or "-"]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
