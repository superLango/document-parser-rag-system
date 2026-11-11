# OCR 服务

真实 OCR 与表格结构服务。对外只暴露内部 API，由编排服务调用；公开 API 仍在 `api-gateway`。

## 职责

- 输入文档 bytes，输出 `OcrResult`：页、markdown、表格 `TableGrid`、质量分、告警与产物引用。
- 页图渲染与对象存储落地（`ocr/{document_id}/pages/{n}.png`）。
- HTML 表格结构化：rowspan/colspan 展开、表头路径、跨页续表、重复表头分块。
- 表型识别与数据驱动修复规则。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/internal/ocr/parse` | 从对象存储读取 `storage_key` 后解析 |
| POST | `/internal/ocr/parse-file` | 直接上传文件解析（本地调试，不读对象存储） |

`parse` 请求体：

```json
{
  "document_id": "...",
  "storage_key": "documents/<id>/<name>",
  "filename": "standard.pdf",
  "content_type": "application/pdf",
  "backend": "auto"
}
```

## 适配器

| backend | 适用 | 说明 |
|---|---|---|
| `auto` | 默认 | `.md/.txt` 走 text；配置了 GLM 则 PDF 走 glm；否则走 pdf |
| `text` | `.md/.txt` | 直接解码，不调用模型 |
| `pdf` | `.pdf` | PyMuPDF 渲染页图 + 文本/表格抽取，无模型 |
| `glm` | `.pdf` | OpenAI 兼容多模态接口，逐页输出 Markdown（表格要求 HTML） |
| `mock` | 测试 | 固定样本，用于离线联调 |

配置项：`OCR_BACKEND`、`OCR_DPI`、`GLM_OCR_BASE_URL`、`GLM_OCR_MODEL`、`GLM_OCR_TIMEOUT_SECONDS`。
GLM 未配置时 `auto` 不会选它；显式指定 `glm` 而未配置会返回 `OCR_BACKEND_UNAVAILABLE`。

## 版面

配置 `LAYOUT_BASE_URL`（默认 `http://192.168.1.35:9978`）后，每页页图会送 PP-DocLayoutV3 `/v1/layout`：

- 返回块写入 `OcrResult.layout`（含 `page_no`、`type`、归一化 `bbox`）与 `layout/{n}.json`。
- 版面服务不可达或返回异常时只追加 warning，不影响 OCR 与表格解析。
- 仅对产生页图的 backend（`pdf`/`glm`）生效；`text` 无页图，跳过版面。

## 错误码

| code | 场景 |
|---|---|
| `OCR_BACKEND_UNAVAILABLE` | OCR 服务不可达或未配置 |
| `OCR_BACKEND_ERROR` | OCR 服务返回非 200 或响应格式异常 |
| `OCR_PDF_INVALID` | PDF 无法打开 |
| `OCR_EMPTY_DOCUMENT` | PDF 无页面 |
| `OCR_UNKNOWN_BACKEND` | 未知 backend |
| `OCR_LAYOUT_UNAVAILABLE` | 版面服务不可达 |
| `OCR_LAYOUT_ERROR` | 版面服务返回异常 |

## 产物

| key | 内容 |
|---|---|
| `ocr/{doc}/pages/{n}.png` | 页图 |
| `ocr/{doc}/markdown.md` | 合并后的 markdown |
| `ocr/{doc}/pages.json` | 页元数据 |
| `ocr/{doc}/tables.json` | `TableGrid` 列表 |
| `ocr/{doc}/layout/{n}.json` | 单页版面块（PP-DocLayoutV3 原始响应） |
| `ocr/{doc}/layout.json` | 全部页面合并的版面块 |
| `ocr/{doc}/ocr.json` | 完整 `OcrResult` |

所有产物记录 sha256 与字节数。

## 算法

| 文件 | 说明 |
|---|---|
| `algorithms/normalize.py` | 文本/单位清洗、元素符号识别 |
| `algorithms/table_grid.py` | HTML → `TableGrid`，含合并单元格与跨页合并 |
| `algorithms/profile.py` | 表型识别（化学/力学/检验/尺寸/分类/admin）与方向 |
| `algorithms/repairs.py` | 数据驱动修复规则 |

修复规则文件：`services/ocr/data/table_repairs.json`。

```json
{
  "rules": [
    {
      "rule_id": "example",
      "match": {"standard_no": "GB/T 1591", "table_caption": "表1", "profile": "mechanical_properties"},
      "action": {"type": "rebuild_grid", "rows": 16, "columns": 16}
    }
  ]
}
```

支持的 `action.type`：`rebuild_grid`、`header_rows`、`patch_cells`、`replace_rows`、`delete_rows`、`trim_trailing`。

## 测试

```bash
cd new_app
python -m pytest tests/algorithm -q
python scripts/benchmark/table_benchmark.py
python scripts/benchmark/table_gold_eval.py
```

## 已知限制

- GLM-OCR 已在 `192.168.1.35:9977` 启动并联调通过；启动、停止与排障见 `docs/model-server-glm-ocr.md`。
- 版面依赖同一台机器的 9978 服务；不可用时仅告警，网格与表型仍可产出。
- PDF 原生路径依赖 PyMuPDF 的表格识别，复杂合并表以 OCR 返回的 HTML 为主。
- 跨页合并与表型规则直接沿用旧启发式，需要金标语料继续回归。
