# OCR 引擎切换方案实施文档

## 概述

本项目支持在 **MinerU**（主引擎）与 **PaddleOCR**（备选引擎）之间灵活切换 OCR 引擎。
通过抽象基类 + 适配器 + 路由分发的架构，实现全局配置与请求级覆盖的双层切换机制，
两种引擎输出格式统一为 `{text, layout, pages, page_size, page_results}`，
下游版面分析、术语标准化、Popo 后处理等模块无需改动。

## 架构设计

```
ocr_router (统一入口，模块级单例)
   ├── resolve_engine(engine) → OCREngineBase 实例
   ├── PaddleOCREngine (薄包装现有 OCRService，保留全部后处理)
   └── MinerUEngine (封装 do_parse，middle.json → 统一格式转换)
```

### 核心组件

| 文件 | 职责 |
|------|------|
| `app/services/ocr_engine_base.py` | 抽象基类，定义 `warmup` / `recognize` / `recognize_with_layout` / `recognize_with_layout_batch` / `recognize_pdf` 统一接口 |
| `app/services/paddleocr_engine.py` | PaddleOCR 适配器，薄包装 `OCRService`，保留方向校正、整表重识注释、表格 TSR、公式处理、页眉页脚剔除 |
| `app/services/mineru_service.py` | MinerU 引擎，封装 `do_parse`，转换 `middle.json` 为统一输出格式 |
| `app/services/ocr_router.py` | 路由分发器，按配置/请求参数选择引擎，懒加载双引擎单例 |
| `app/services/ocr_service.py` | PaddleOCR 引擎实现（原有 1610 行，保留全部后处理逻辑） |

### 引擎选择优先级

```
请求级 engine 参数 > settings.OCR_ENGINE 全局配置 > 默认 mineru
```

- `mineru`：MinerU do_parse 直通 PDF（绕过分类与渲染）
- `paddleocr`：PDF 分类 + 分页 OCR + 后处理
- `auto`：默认 mineru，MinerU 不可用时回退 paddleocr

## 环境配置

### 1. 安装 MinerU

```bash
cd /home/hanson/doc_parse_project/backend
source ./venv/bin/activate

# 安装 mineru 3.4.3（锁定版本避免 middle.json 字段漂移）
pip install "mineru[core]==3.4.3"

# 解决 opencv 冲突：mineru 装 opencv-python 5.x，需卸载并重装 contrib
pip uninstall -y opencv-python
pip install --force-reinstall "opencv-contrib-python==4.10.0.84"

# 验证
python -c "from mineru.cli.common import do_parse; print('mineru OK')"
python -c "import cv2; print('cv2:', cv2.__version__); print('xfeatures2d:', hasattr(cv2,'xfeatures2d'))"
```

### 2. 配置项（`.env`）

```bash
# OCR 引擎切换（MinerU 主 / PaddleOCR 备）
# 全局默认引擎：paddleocr / mineru / auto
OCR_ENGINE=mineru

# MinerU 推理后端：pipeline / vlm-engine / vlm-http-client / hybrid-engine / hybrid-http-client
MINERU_BACKEND=pipeline

# MinerU VLM 后端 vLLM 服务端点（仅 vlm-* / hybrid-* 后端使用）
MINERU_VLLM_SERVER_URL=http://localhost:9988/v1

# MinerU OCR 语言
MINERU_LANG=ch

# MinerU 公式/表格识别开关
MINERU_FORMULA_ENABLE=true
MINERU_TABLE_ENABLE=true

# MinerU 输出临时目录（每次任务子目录隔离，用后清理）
MINERU_OUTPUT_DIR=/tmp/mineru_output

# MinerU hybrid 后端 effort（medium/high），仅 hybrid-* 后端生效
MINERU_HYBRID_EFFORT=medium

# MinerU 图像分析（图表/插图理解）
MINERU_IMAGE_ANALYSIS=true
```

### 3. MinerU 后端选择

| 后端 | 显存占用 | 说明 |
|------|----------|------|
| `pipeline`（默认） | ~1.8GB | 本地 PP-OCRv5 + 版面检测，0 额外显存，推荐 |
| `vlm-http-client` | ~0.3GB（vLLM 服务） | VL 识别走 vLLM 服务，版面走本地 |
| `hybrid-http-client` | ~0.3GB（vLLM 服务） | pipeline + vlm 融合，按 effort 调用比例 |

**VLM 后端启动**（可选，仅 `MINERU_BACKEND=vlm-http-client` 时）：

```bash
vllm serve <MinerU-VLM模型路径> --served-model-name mineru-vlm \
    --port 9989 --gpu-memory-utilization 0.3 --trust-remote-code
```

## 启动流程

### 1. 启动 arq worker（终端 1）

按全局 `OCR_ENGINE` 预热对应引擎：

```bash
bash /home/hanson/doc_parse_project/backend/start_worker.sh
```

`start_worker.sh` 已配置 `CUDA_VISIBLE_DEVICES=0` 和 `LD_LIBRARY_PATH`，
对 MinerU pipeline 后端（paddle GPU）同样生效。
`on_startup` 仅预热默认引擎，避免双引擎同时占显存。

### 2. 启动后端（终端 2）

```bash
cd /home/hanson/doc_parse_project/backend && source ./venv/bin/activate
uvicorn app.main:app --port 8000
```

### 3. 启动前端（终端 3）

```bash
cd /home/hanson/doc_parse_project/frontend && pnpm dev
```

前端默认端口 5174（避开 TRAE IDE 占用的 3000 端口）。

## 切换方法

### 方法 1：全局配置（`.env`）

修改 `backend/.env` 中的 `OCR_ENGINE` 字段，重启 arq worker 生效：

```bash
# 切换到 PaddleOCR
OCR_ENGINE=paddleocr

# 切换到 MinerU
OCR_ENGINE=mineru

# 自动模式（默认 mineru，失败回退 paddleocr）
OCR_ENGINE=auto
```

### 方法 2：前端请求级覆盖

Parser 页面工具栏提供 OCR 引擎下拉框（仅未解析时显示）：

- **自动（跟随全局）**：不传 engine，走 `OCR_ENGINE` 全局配置
- **MinerU（推荐）**：请求级指定 mineru
- **PaddleOCR（备选）**：请求级指定 paddleocr

选择持久化到 `localStorage`，刷新页面后保留。点击「开始 OCR 解析」时，
前端将 engine 参数随任务提交请求发送到后端。

### 方法 3：API 直接调用

```bash
curl -X POST http://localhost:8000/api/v1/tasks/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"document_id":"<uuid>","engine":"mineru"}'
```

`engine` 字段可选，取值 `paddleocr` / `mineru` / `auto`，不传时走全局配置。

## 输出格式

两种引擎输出统一为以下结构，下游模块无需区分引擎：

```python
{
    "text": str,                    # 全文文本（markdown）
    "layout": [                     # 跨页版面块列表
        {
            "type": "text|table|figure|title",
            "label": "原始标签",     # 供 layout_router 路由
            "bbox": [x1, y1, x2, y2],
            "text": "该区域识别文本",
            "html": "<table>...",   # 仅 table 块可选
            "latex": "$...$",       # 仅 formula 块可选
            "page": int             # 1-based 页码
        }
    ],
    "pages": int,                   # 总页数
    "page_size": {"width": float, "height": float},  # 首页尺寸
    "page_results": [               # 每页结果（MinerU 路径，供 Popo 后处理）
        {"text": str, "layout": [...], "page": int, "page_size": {...}}
    ]
}
```

## 优化策略

1. **双引擎懒加载**：两个引擎均为懒加载单例，按需实例化。默认 `OCR_ENGINE=mineru`
   时仅 MinerUEngine 加载，PaddleOCREngine 不实例化；避免双引擎同时占显存。

2. **do_parse 串行化**：MinerU `do_parse` 通过 `_infer_lock` 串行化，通过
   `asyncio.to_thread` 投递线程池，避免并发产生临时目录冲突与 paddle GPU 上下文竞争。

3. **临时目录隔离**：每次 do_parse 用 `MINERU_OUTPUT_DIR/<uuid>` 隔离临时目录，
   `finally` 块 `shutil.rmtree` 清理，避免磁盘累积。

4. **middle.json 字段兼容**：`_convert_middle_json` 兼容 `preproc_result.layout_dets`
   与 `layout` 两种字段，应对 MinerU 版本字段漂移。

5. **auto 模式回退**：`auto` 模式默认 mineru，MinerU 抛 `NotImplementedError` 时
   自动回退 paddleocr 路径，保证可用性。

## 对比测试

### 运行对比测试脚本

```bash
cd /home/hanson/doc_parse_project/backend && source ./venv/bin/activate
python scripts/ocr_engine_compare.py \
    --pdf "../test_standard_doc/GB-T1220-2007 不锈钢棒.pdf" \
    --engines paddleocr,mineru \
    --output ../reports/ocr_compare.json
```

### 测试指标

| 指标 | 说明 |
|------|------|
| `elapsed_sec` | 端到端耗时（秒） |
| `text_length` | 全文文本长度 |
| `note_count` | "注" 字出现次数（表格注释召回率代理指标） |
| `annotation_count` | a/b/c 字母注释行数（正则 `^[a-zA-Z]\s+[^\d\s]`） |
| `table_count` | 表格版面块数量 |
| `formula_count` | 公式版面块数量 |
| `vram_peak_mb` | 显存峰值（MB，需 nvidia-smi） |

### 预期改进

- **表格注释召回率**：MinerU ≥ PaddleOCR（MinerU 自带表格 TSR，无需整表重识补丁）
- **显存占用**：MinerU pipeline（~1.8GB）< PaddleOCR vLLM 服务（~6.8GB）
- **处理速度**：MinerU 持平或优于 PaddleOCR

## 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| mineru 安装后 opencv 冲突 | 卸载 opencv-python + `--force-reinstall opencv-contrib-python==4.10.0.84` |
| paddle GPU 上下文冲突 | 双引擎懒加载不共存；MinerU `_infer_lock` 串行化 do_parse |
| middle.json 字段版本漂移 | 锁定 `mineru[core]==3.4.3`；`_convert_middle_json` 兼容双字段 |
| 临时目录累积 | `_do_parse_sync` finally 块 `shutil.rmtree` 清理 |
| starlette 降级（gradio 依赖） | FastAPI 0.139.0 与 starlette 0.52.1 运行时兼容，pip 警告可忽略 |

## 文件清单

### 新增文件

- `backend/app/services/ocr_engine_base.py` — 抽象基类
- `backend/app/services/paddleocr_engine.py` — PaddleOCR 适配器
- `backend/app/services/mineru_service.py` — MinerU 引擎
- `backend/app/services/ocr_router.py` — 路由分发器
- `backend/scripts/ocr_engine_compare.py` — 对比测试脚本
- `docs/ocr-engine-switching.md` — 本文档

### 修改文件

- `backend/app/core/config.py` — 新增 9 个 MinerU 配置项 + 2 个校验器
- `backend/app/tasks/document_tasks.py` — engine 参数 + MinerU/PaddleOCR 分流
- `backend/app/tasks/arq_worker.py` — engine 参数透传 + 双引擎预热
- `backend/app/api/v1/endpoints/tasks.py` — TaskCreateRequest.engine + 透传
- `backend/app/services/ocr_service.py` — 文档字符串说明被 ocr_router 包装
- `backend/.env` / `backend/.env.example` — 同步 MinerU 配置项
- `backend/requirements.txt` — 收紧为 `mineru[core]==3.4.3`
- `frontend/src/api/types.ts` — TaskCreateRequest.engine 字段
- `frontend/src/views/Parser/index.vue` — 引擎下拉框 + submitParse 传参
