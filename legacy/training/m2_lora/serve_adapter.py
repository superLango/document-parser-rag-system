"""OpenAI-compatible chat-completions shim for Qwen3.5-9B + adapter-v1.

Runs beside the existing vLLM services (9977/9978/9989) on port 9990 so the
engine can point its extraction endpoint at a LoRA-enabled model without
restarting the production Qwen service.

Fixed inference params (``inference_params.json``, ``lora-infer-v1``):
greedy, ``enable_thinking=False``, max_new_tokens 512. Sampling requests are
accepted but ignored (the server always decodes greedily) so pipeline runs stay
reproducible.

Endpoints:
    GET  /health            -> {"status": "ok", ...}
    GET  /v1/models         -> OpenAI-style model list
    POST /v1/chat/completions

Usage on the model host:
    python serve_adapter.py --model /home/grainuser/models/models/Qwen3.5-9B \
      --adapter /home/grainuser/hanson_m2/adapter-v1 --port 9990
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import torch
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer

STATE: dict[str, Any] = {}


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[dict[str, Any]]
    max_tokens: int | None = None
    max_new_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stream: bool = False
    chat_template_kwargs: dict[str, Any] | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--params", default=None)
    parser.add_argument("--port", type=int, default=9990)
    parser.add_argument("--host", default="0.0.0.0")
    return parser.parse_args()


def load(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {
        "max_new_tokens": 512,
        "enable_thinking": False,
        "repetition_penalty": 1.0,
    }
    if args.params:
        params.update(json.loads(open(args.params, encoding="utf-8").read()))

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, dtype=torch.bfloat16, trust_remote_code=True
    ).to("cuda")
    model.config.use_cache = True
    model.eval()

    from peft import PeftModel

    model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()

    adapter_name = Path(args.adapter).name
    STATE.update(
        {
            "model": model,
            "tokenizer": tokenizer,
            "params": params,
            "adapter_name": adapter_name,
            "model_id": f"Qwen3.5-9B-{adapter_name}",
            "lock": threading.Lock(),
        }
    )
    print(
        f"loaded {adapter_name}, max_new_tokens={params['max_new_tokens']} "
        f"enable_thinking={params['enable_thinking']}",
        flush=True,
    )


app = FastAPI()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok" if STATE else "loading",
        "model": STATE.get("model_id"),
        "adapter": STATE.get("adapter_name"),
        "params": STATE.get("params"),
        "device": "cuda",
    }


@app.get("/v1/models")
def models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": STATE.get("model_id", "Qwen3.5-9B-lora"),
                "object": "model",
                "owned_by": "hanson",
            }
        ],
    }


@app.post("/v1/chat/completions")
def chat(request: ChatRequest) -> dict[str, Any]:
    if not STATE:
        raise RuntimeError("model not loaded")

    tokenizer = STATE["tokenizer"]
    model = STATE["model"]
    params = STATE["params"]
    enable_thinking = bool((request.chat_template_kwargs or {}).get("enable_thinking", params["enable_thinking"]))
    prompt = tokenizer.apply_chat_template(
        request.messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=enable_thinking,
    )
    max_new_tokens = request.max_new_tokens or request.max_tokens or params["max_new_tokens"]
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

    started = time.time()
    with STATE["lock"], torch.inference_mode():
        output = model.generate(
            **inputs,
            max_new_tokens=min(max_new_tokens, 2048),
            do_sample=False,
            repetition_penalty=params["repetition_penalty"],
        )
    generated = output[0][inputs["input_ids"].shape[1] :]
    text = tokenizer.decode(generated, skip_special_tokens=True)

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": STATE["model_id"],
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "length"
                if int(generated.shape[0]) >= min(max_new_tokens, 2048)
                else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": int(inputs["input_ids"].shape[1]),
            "completion_tokens": int(generated.shape[0]),
            "total_tokens": int(inputs["input_ids"].shape[1] + generated.shape[0]),
            "elapsed_seconds": round(time.time() - started, 3),
        },
    }


def main() -> None:
    args = parse_args()
    load(args)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
