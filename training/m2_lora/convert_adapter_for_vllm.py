"""Rewrite a PEFT adapter so vLLM can bind it to Qwen3.5's language model.

vLLM resolves LoRA tensors by full module path. For ``Qwen3_5ForConditional
Generation`` the text backbone lives under ``language_model.model.layers`` while
PEFT saved this adapter with ``base_model.model.model.layers``. vLLM strips the
``base_model.model.`` prefix and then fails to find the module, logging
``No LoRA weights found for module language_model.model.layers.N..., skipping``.

This script rewrites the key prefix and copies ``adapter_config.json`` so the
converted directory can be served with ``--lora-modules name=<dir>``.

Usage (on the model host):
    python convert_adapter_for_vllm.py \
      --src /home/grainuser/hanson_m2/adapter-v4 \
      --dst /home/grainuser/hanson_m2/adapter-v4-vllm
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from safetensors.torch import load_file, save_file

OLD = "base_model.model.model.layers."
NEW = "base_model.model.language_model.model.layers."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", required=True)
    parser.add_argument("--dst", required=True)
    args = parser.parse_args()

    src = Path(args.src)
    dst = Path(args.dst)
    dst.mkdir(parents=True, exist_ok=True)

    tensors = load_file(str(src / "adapter_model.safetensors"))
    renamed = {}
    converted = 0
    untouched = []
    for key, value in tensors.items():
        if key.startswith(OLD):
            renamed[NEW + key[len(OLD) :]] = value
            converted += 1
        else:
            renamed[key] = value
            untouched.append(key)
    save_file(renamed, str(dst / "adapter_model.safetensors"), metadata={"format": "pt"})

    for name in ("adapter_config.json", "tokenizer_config.json", "tokenizer.json"):
        candidate = src / name
        if candidate.exists():
            shutil.copy2(candidate, dst / name)

    print(
        {
            "tensors": len(tensors),
            "converted": converted,
            "untouched": len(untouched),
            "dst": str(dst),
        }
    )
    for key in untouched[:5]:
        print("untouched:", key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
