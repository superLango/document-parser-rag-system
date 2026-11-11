# M4 沙箱确定性报告

> 文档版本：v1.0  
> 编制日期：2026-11-11  
> 所属里程碑：[M4 沙箱服务与执行引擎](M4-sandbox-runtime.md)  
> 结论：在相同输入、相同 `engine_digest + recipe_digest + template_digest` 下，语义产物 100% 字节一致。

---

## 1. 确定性边界

本报告只对**沙箱执行**负责：

```text
OCR 产物 + 配方包 + 模板 + 引擎镜像
        ↓（相同 digest）
result.json / records.json / evidence.jsonl / diagnostics.json
```

不包含：

- OCR 模型输出（GLM/PP-DocLayout 可能受采样、图片编码等影响）。
- `metrics.json` 中的 `duration_ms`、`peak_memory_mb`。
- `manifest.json` 对 `metrics.json` 的哈希，以及 API 层 manifest 的引擎镜像摘要。
- 对象存储 key、run_id、trace_id 等运行标识。

因此确定性比较对象是四个语义产物：`result.json`、`records.json`、`evidence.jsonl`、`diagnostics.json`。

---

## 2. 确定性保障措施

| 措施 | 实现 |
|---|---|
| 规范化 JSON | 所有产物使用 `sort_keys=True`、紧凑分隔符、UTF-8、末尾换行 |
| 稳定排序 | records/evidence 按 `(page_no, table_id, row_index)` 排序；表摘要按 `(page_no, table_id)` |
| 无时间戳 | 语义产物不写入执行时间、主机名、绝对路径 |
| 固定环境 | `PYTHONHASHSEED=0`、`TZ=UTC`、`LANG=C.UTF-8`、`PYTHONDONTWRITEBYTECODE=1` |
| 只读输入 | `/input`、`/recipes`、`/templates` 以只读方式挂载（Docker）或 0555 权限（K8s） |
| 无网络 | Docker `--network none`；K8s deny-all NetworkPolicy（Calico 已实测） |
| 固定引擎 | 执行前记录 engine image digest；请求可按 digest 校验配方/模板 |
| 原子产物 | 先写临时文件再落盘；服务端校验 schema 与 sha256 后才离开沙箱 |

---

## 3. 测试与结果

### 3.1 引擎层（两次独立进程）

测试：`tests/integration/sandbox/test_runtime_contract.py::test_builtin_engine_is_deterministic`

方法：同一 OCR/配方/模板，在两个独立工作区、两个独立 Python 进程中执行，比较四个语义产物字节。

结果：

```text
result.json        identical
records.json       identical
evidence.jsonl     identical
diagnostics.json   identical
（metrics.json / manifest.json 因耗时与哈希被排除）
```

### 3.2 服务层（两次完整执行）

测试：`tests/integration/sandbox/test_service.py::test_service_semantic_outputs_are_deterministic`

方法：`SandboxService.execute` 连续执行两次；每次生成不同的 execution_id 与存储 key，比较上传到对象存储的语义产物。

结果：

```text
result.json        identical
records.json       identical
evidence.jsonl     identical
diagnostics.json   identical
```

### 3.3 E2E（Compose 与 K8s）

同一份 `tests/fixtures/mechanical.md`：

| 环境 | 表数 | 记录数 | 语义产物 |
|---|---:|---:|---|
| Compose + Docker 执行器 | 1 | 2 | `Q355B/Rm=470/A=22`、`Q235B/Rm=400/A=26` |
| K8s + Job 执行器 | 1 | 2 | 同上 |

说明：两次 E2E 使用不同 document_id/run_id，`result.json` 中的 `document` 字段不同，因此不做跨运行字节比较；在相同 document_id 下，语义产物一致。

### 3.4 自动化测试汇总

```text
tests/integration/sandbox/test_runtime_contract.py   5 passed
tests/integration/sandbox/test_service.py            7 passed
tests/integration/sandbox/test_validation.py         5 passed
tests/integration/sandbox/test_docker_executor.py    4 passed（隔离/超时/OOM/非零退出）
```

执行命令：

```bash
python -m pytest tests/integration/sandbox -q
```

Docker 执行器测试需在 Linux 或挂载 `/var/run/docker.sock` 的容器中运行：

```bash
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD":/app -w /app \
  -e PYTHONPATH=/app:/app/packages/contracts/src \
  hanson-new-app:local python -m pytest tests/integration/sandbox/test_docker_executor.py -q
```

---

## 4. 产物样例

`records.json`（节选，已按确定性规则排序）：

```json
{
  "records": [
    {
      "record_id": "T1-R1",
      "table_id": "T1",
      "page_no": 1,
      "grade": "Q355B",
      "conditions": {"规格": "≤16"},
      "properties": {
        "Rm": {"value": 470.0, "raw": "470", "unit": "MPa"},
        "A": {"value": 22.0, "raw": "22", "unit": "%"}
      },
      "evidence_refs": ["T1-R1"]
    },
    {
      "record_id": "T1-R2",
      "table_id": "T1",
      "page_no": 1,
      "grade": "Q235B",
      "conditions": {"规格": "≤16"},
      "properties": {
        "Rm": {"value": 400.0, "raw": "400", "unit": "MPa"},
        "A": {"value": 26.0, "raw": "26", "unit": "%"}
      },
      "evidence_refs": ["T1-R2"]
    }
  ],
  "schema_version": "sandbox-records/1"
}
```

`evidence.jsonl` 每行一条证据，按同一排序规则输出；`diagnostics.json` 对缺失 measure 列等给出稳定 warning（如 `MEASURE_COLUMN_MISSING`），不包含时间或随机 ID。

---

## 5. 已知非确定性来源

| 来源 | 影响 | 处理 |
|---|---|---|
| `metrics.json` 的 `duration_ms` | 每次执行不同 | 排除在确定性比较外 |
| `manifest.json` 对 metrics 的哈希 | 随 metrics 变化 | 排除；语义产物哈希稳定 |
| 引擎镜像 digest | 镜像重建会变化 | 以 manifest 记录；跨镜像不承诺字节一致 |
| OCR 模型输出 | 上游可能不同 | 沙箱以 `ocr.sha256` 校验输入；不承诺 OCR 本身确定性 |
| K8s Job 调度/启动时间 | 只影响 metrics | 不影响语义产物 |

---

## 6. 结论

- 在同一输入与同一 `engine_digest + recipe_digest + template_digest` 下，语义产物字节一致率 **100%**。
- 确定性测试已纳入 `tests/integration/sandbox/`，可在本地与 CI 重复执行。
- 非确定性仅存在于 metrics/manifest 的运行指标与上游 OCR，已明确边界并记录。
