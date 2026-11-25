# app_v3 benchmark 数据说明

## 内容

- `docs/`：26 份测试文档 PDF（20 份批量测试 + 6 份早期文档）
- `gold/`：对应的人工对照 JSON（26 份）
- `manifest.json`：文档/金标配对、SHA256、历史 v2 基线指标
- `build_manifest.py`：重建 manifest（可选）

## 26 份文档

### 20 份批量测试（来源：`E:\Desktop\标准抽取20份`）

asme-sb338-2025、ams-4928x、iso-5832-3-2021、hb-20079-2012、gjb-9581-2018、
gjb-2351a-2021、gjb-2296a-2005、gjb-1951a-2020、gbt-14976-2025、gbt-8547-2019、
gbt-5231-2022、gbt-3623-2022、gbt-3620-1-2016、gbt-3077-2015、gbt-2965-2023、
gbt-2054-2023、astm-b348-25、nbt-47019-8-2011、xx454-2022、yst-656-2015

### 6 份早期文档

gbt-713.7-2023、gbt-1591-2018、gbt-3191-1998、gbt-6892-2015、gjb-2294-1995、yst-397-2015

## Git 策略

- PDF 体积约 43MB，**默认不入 git**（本地备份用；见 `app_v3/.gitignore`）；
- gold JSON（约 10MB）与 `manifest.json` 入库，便于评测复现；
- 如需把 PDF 也纳入版本库，可执行 `git add -f app_v3/benchmark/docs`（不建议，仓库会变大）。

## 使用

评测时以 `manifest.json` 为准：

```python
import json
from pathlib import Path
manifest = json.loads(Path("app_v3/benchmark/manifest.json").read_text(encoding="utf-8"))
for doc in manifest["documents"]:
    pdf = Path("app_v3/benchmark") / doc["pdf"]
    gold = Path("app_v3/benchmark") / doc["gold"]
```
