#!/usr/bin/env python
"""下载 BGE-M3 权重到 models/bge-m3（幂等，支持镜像）。

用法：
    python scripts/download_embedding_model.py
环境变量：
    HF_ENDPOINT       HuggingFace 镜像地址（默认 https://hf-mirror.com）
    EMBEDDING_REPO_ID 模型仓库（默认 BAAI/bge-m3）
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "bge-m3"
REPO_ID = os.environ.get("EMBEDDING_REPO_ID", "BAAI/bge-m3")
REQUIRED_FILES = ("config.json", "model.safetensors", "tokenizer.json")


def main() -> int:
    if all((MODEL_DIR / f).exists() for f in REQUIRED_FILES):
        print(f"模型已存在，跳过下载：{MODEL_DIR}")
        return 0

    print(f"开始下载 {REPO_ID} -> {MODEL_DIR}")
    try:
        # 优先 HuggingFace（可经 HF_ENDPOINT 指定镜像）
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=REPO_ID,
            local_dir=str(MODEL_DIR),
            allow_patterns=[
                "config.json",
                "model.safetensors",
                "tokenizer.json",
                "tokenizer_config.json",
                "vocab.txt",
                "sentencepiece.bpe.model",
                "special_tokens_map.json",
                "1_Pooling/config.json",
            ],
        )
    except Exception as exc:
        # HF 不可达时回退 ModelScope（国内网络可用）
        print(f"HF 下载失败（{type(exc).__name__}），回退 ModelScope")
        from modelscope import snapshot_download as ms_download

        ms_download(
            "BAAI/bge-m3",
            local_dir=str(MODEL_DIR),
            allow_file_pattern=[
                "config.json",
                "pytorch_model.bin",
                "tokenizer.json",
                "tokenizer_config.json",
                "vocab.txt",
                "sentencepiece.bpe.model",
                "special_tokens_map.json",
            ],
        )
    missing = [f for f in REQUIRED_FILES if not (MODEL_DIR / f).exists()]
    if missing:
        print(f"下载不完整，缺少：{missing}")
        return 1
    print(f"下载完成：{MODEL_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
