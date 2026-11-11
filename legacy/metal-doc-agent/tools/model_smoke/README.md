# Model smoke tests

These scripts verify the three model services on the model host (1.35).
They are normally run on the model host, using the hansonDoc_RAG backend venv
(PyMuPDF, httpx, FastAPI are already installed there).

## GLM-OCR (9977)

```bash
scp "标准文件/Q-Du 302-2015.pdf" grainuser@192.168.1.35:/tmp/qdu302.pdf
scp tools/model_smoke/glm_ocr_smoke.py grainuser@192.168.1.35:/tmp/
ssh grainuser@192.168.1.35 \
  '/home/grainuser/hansonDoc_RAG/backend/.venv/bin/python /tmp/glm_ocr_smoke.py \
    --pdf /tmp/qdu302.pdf --page 5 --needle 430'
```

Expected: `HTTP 200`, `has_table True`, `has_needle True`.

## Qwen3.5-9B (9989)

```bash
scp tools/model_smoke/qwen_smoke.py grainuser@192.168.1.35:/tmp/
ssh grainuser@192.168.1.35 \
  '/home/grainuser/hansonDoc_RAG/backend/.venv/bin/python /tmp/qwen_smoke.py \
    --base http://127.0.0.1:9989/v1'
```

Expected: `simple: 'ok'`, `has_think: False`, `parsed_ok: True`.

## Layout API (9978)

```bash
scp tools/model_smoke/layout_smoke.py grainuser@192.168.1.35:/tmp/
ssh grainuser@192.168.1.35 \
  '/home/grainuser/hansonDoc_RAG/backend/.venv/bin/python /tmp/layout_smoke.py \
    --image /tmp/glm_smoke_page.png --page 5'
```

Expected: `blocks 28`, `has_table True`, `page_failures []`.

## Client-level smoke (from the laptop)

This exercises the actual `metal_doc_agent.clients` code, not just the raw
services:

```bash
scp grainuser@192.168.1.35:/tmp/glm_smoke_page.png runs/glm_page.png
python tools/model_smoke/client_smoke.py --image runs/glm_page.png
```

Expected: `glm models: ['GLM-OCR']`, `has_table: True`, `qwen parsed: 2A14`,
`layout blocks: 28`, `ALL OK`.

## Qwen extraction smoke (one table / one block)

```bash
export QWEN_BASE_URL=http://192.168.1.35:9989/v1
python tools/model_smoke/qwen_extract_smoke.py \
  --doc "../标准文件/GBT 40303-2021/GBT 40303-2021   GH4169合金棒材通用技术条件.md" \
  --table T3 --block-limit 1
```

Expected: Qwen column mapping, 3 records (普通/优质/高纯), 11 elements each,
range/max comparators and `%` units, 33 evidence pointers.

## Notes

- GLM-OCR must be started with the deploy venv on `PATH`, otherwise flashinfer
  cannot find `ninja` and the engine core fails.
- Qwen3.5-9B needs `chat_template_kwargs.enable_thinking=false`; otherwise the
  response contains `<think>` tags.
- The layout API preloads PP-DocLayoutV3 during startup; `/health` becomes
  `model_loaded: true` only after loading.
