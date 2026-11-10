"""LoRA SFT for Qwen3.5-9B on the M2 extraction tasks.

Runs on the model host (GB10). Prompt tokens are masked with -100; only the
assistant JSON contributes to the loss.

Usage:
    python train_lora.py \
      --model /home/grainuser/models/models/Qwen3.5-9B \
      --train data/sft-v1/train.jsonl \
      --eval data/sft-v1/eval.jsonl \
      --output /home/grainuser/hanson_m2/adapter-v1
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import torch
from datasets import load_dataset
from peft import LoraConfig, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForSeq2Seq,
    Trainer,
    TrainingArguments,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--train", required=True)
    parser.add_argument("--eval", default=None)
    parser.add_argument("--output", required=True)
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--max-seq", type=int, default=2048)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--logging-steps", type=int, default=5)
    parser.add_argument("--save-steps", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
    )
    model.to("cuda")
    model.config.use_cache = False
    model.gradient_checkpointing_enable()

    lora = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    dataset = load_dataset(
        "json",
        data_files={
            "train": args.train,
            **({"eval": args.eval} if args.eval else {}),
        },
    )

    def encode(example: dict[str, Any]) -> dict[str, Any]:
        messages = example["messages"]
        prompt = tokenizer.apply_chat_template(
            messages[:2], tokenize=False, add_generation_prompt=True
        )
        full_text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=False
        )
        prompt_ids = tokenizer(prompt, add_special_tokens=False).input_ids
        encoded = tokenizer(
            full_text,
            truncation=True,
            max_length=args.max_seq,
            add_special_tokens=False,
        )
        labels = list(encoded["input_ids"])
        prompt_len = min(len(prompt_ids), len(labels))
        for index in range(prompt_len):
            labels[index] = -100
        if all(label == -100 for label in labels):
            return {"input_ids": [], "attention_mask": [], "labels": []}
        encoded["labels"] = labels
        return encoded

    train_dataset = dataset["train"].map(encode, remove_columns=dataset["train"].column_names)
    train_dataset = train_dataset.filter(lambda row: len(row["input_ids"]) > 0)
    eval_dataset = None
    if args.eval:
        eval_dataset = dataset["eval"].map(encode, remove_columns=dataset["eval"].column_names)
        eval_dataset = eval_dataset.filter(lambda row: len(row["input_ids"]) > 0)

    collator = DataCollatorForSeq2Seq(
        tokenizer=tokenizer, model=model, padding=True, label_pad_token_id=-100
    )
    training_args = TrainingArguments(
        output_dir=str(output),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch,
        per_device_eval_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_steps=3,
        logging_steps=args.logging_steps,
        save_strategy="steps" if args.save_steps > 0 else "epoch",
        **({"save_steps": args.save_steps} if args.save_steps > 0 else {}),
        eval_strategy="epoch" if eval_dataset is not None else "no",
        bf16=True,
        gradient_checkpointing=True,
        report_to=[],
        remove_unused_columns=False,
        dataloader_num_workers=2,
        save_total_limit=2,
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=collator,
    )
    started = time.time()
    resume_from = None
    if args.resume:
        checkpoints = sorted(
            output.glob("checkpoint-*"), key=lambda path: int(path.name.split("-")[1])
        )
        resume_from = str(checkpoints[-1]) if checkpoints else None
        print(f"resume_from={resume_from}")
    trainer.train(resume_from_checkpoint=resume_from)
    elapsed = round(time.time() - started, 1)
    model.save_pretrained(str(output))
    tokenizer.save_pretrained(str(output))

    report = {
        "model": args.model,
        "train_samples": len(train_dataset),
        "eval_samples": len(eval_dataset) if eval_dataset is not None else 0,
        "epochs": args.epochs,
        "batch": args.batch,
        "grad_accum": args.grad_accum,
        "lr": args.lr,
        "max_seq": args.max_seq,
        "lora": {
            "r": args.lora_r,
            "alpha": args.lora_alpha,
            "dropout": args.lora_dropout,
        },
        "elapsed_seconds": elapsed,
        "final_metrics": trainer.state.log_history[-1] if trainer.state.log_history else {},
    }
    (output / "run_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
