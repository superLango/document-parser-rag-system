# 收尾端到端验证报告

> 生成时间：2026-11-12T03:50:50+00:00
> 环境：compose（生产镜像）
> API：http://localhost:18000

## 1. 汇总

| 套件 | 文档数 | 成功 | 失败 | 记录数 | 字段数 | p50(s) | p95(s) | max(s) |
|---|---|---|---|---|---|---|---|---|
| pdf | 50 | 50 | 0 | 160 | 533 | 10.16 | 12.31 | 16.19 |

### 阶段耗时（秒）

| 套件 | 阶段 | 样本 | p50 | p95 |
|---|---|---|---|---|
| pdf | ocr | 50 | 2.15 | 4.64 |
| pdf | routing | 50 | 0.24 | 0.48 |
| pdf | sandbox | 50 | 0.95 | 1.43 |
| pdf | review | 50 | 6.11 | 6.82 |

## 2. 文档明细

| 套件 | 文档 | 类型 | 状态 | 耗时(s) | 表 | 记录 | 字段 | 审核 | 发现 | 产物 |
|---|---|---|---|---|---|---|---|---|---|---|
| pdf | AMS-QQ-A250-4B.pdf | 美国标准 | STRUCTURED_READY | 12.14 | 6 | 12 | 36 | pass | 0 | 21 |
| pdf | AMS4050K.pdf | 美国标准 | STRUCTURED_READY | 10.17 | 1 | 0 | 0 | pass | 0 | 22 |
| pdf | AMS4108G--.pdf | 美国标准 | STRUCTURED_READY | 10.16 | 1 | 0 | 0 | pass | 0 | 22 |
| pdf | AMS4900S.pdf | 美国标准 | STRUCTURED_READY | 10.16 | 1 | 0 | 0 | pass | 0 | 21 |
| pdf | AMS4901U-过期.pdf | 美国标准 | STRUCTURED_READY | 10.21 | 1 | 0 | 0 | pass | 0 | 21 |
| pdf | AMS4901V.pdf | 美国标准 | STRUCTURED_READY | 10.14 | 1 | 0 | 0 | pass | 0 | 21 |
| pdf | AMS4902L-过期.pdf | 美国标准 | STRUCTURED_READY | 10.21 | 1 | 0 | 0 | pass | 0 | 21 |
| pdf | AMS4902M.pdf | 美国标准 | STRUCTURED_READY | 10.16 | 1 | 0 | 0 | pass | 0 | 21 |
| pdf | AMS4911R-过期.pdf | 美国标准 | STRUCTURED_READY | 10.16 | 1 | 0 | 0 | pass | 0 | 21 |
| pdf | AMS4911S-过期.pdf | 美国标准 | STRUCTURED_READY | 10.18 | 1 | 0 | 0 | pass | 0 | 22 |
| pdf | AMS4911T.pdf | 美国标准 | STRUCTURED_READY | 10.15 | 1 | 0 | 0 | pass | 0 | 22 |
| pdf | AMS4914J.pdf | 美国标准 | STRUCTURED_READY | 10.18 | 1 | 0 | 0 | pass | 0 | 21 |
| pdf | AMS4928U-过期.pdf | 美国标准 | STRUCTURED_READY | 10.17 | 1 | 0 | 0 | pass | 0 | 22 |
| pdf | AMS4928X.pdf | 美国标准 | STRUCTURED_READY | 10.17 | 1 | 0 | 0 | pass | 0 | 23 |
| pdf | AMS4931C-过期.pdf | 美国标准 | STRUCTURED_READY | 10.13 | 1 | 0 | 0 | pass | 0 | 22 |
| pdf | AMS4931H.pdf | 美国标准 | STRUCTURED_READY | 10.14 | 1 | 0 | 0 | pass | 0 | 22 |
| pdf | AMS4943M.pdf | 美国标准 | STRUCTURED_READY | 10.14 | 1 | 0 | 0 | pass | 0 | 23 |
| pdf | AMS4944M-过期.pdf | 美国标准 | STRUCTURED_READY | 8.44 | 1 | 0 | 0 | pass | 0 | 23 |
| pdf | AMS4967N.pdf | 美国标准 | STRUCTURED_READY | 10.11 | 1 | 0 | 0 | pass | 0 | 23 |
| pdf | AMS5618K.pdf | 美国标准 | STRUCTURED_READY | 10.7 | 1 | 0 | 0 | pass | 0 | 22 |
| pdf | ASME SA264-2021-过期.pdf | 美国标准 | STRUCTURED_READY | 10.47 | 0 | 0 | 0 | pass | 0 | 20 |
| pdf | ASME SB265-2021-过期.pdf | 美国标准 | STRUCTURED_READY | 12.16 | 0 | 0 | 0 | pass | 0 | 28 |
| pdf | ASME SB338-2025.pdf | 美国标准 | STRUCTURED_READY | 12.15 | 0 | 0 | 0 | pass | 0 | 24 |
| pdf | ASME SB575-2025.pdf | 美国标准 | STRUCTURED_READY | 12.21 | 0 | 0 | 0 | pass | 0 | 19 |
| pdf | ASTM B338-17(2026)--+.pdf | 美国标准 | STRUCTURED_READY | 10.2 | 0 | 0 | 0 | pass | 0 | 23 |
| pdf | ASTM B381-13(2019)-过期.pdf | 美国标准 | STRUCTURED_READY | 10.13 | 0 | 0 | 0 | pass | 0 | 22 |
| pdf | ASTM B861-24.pdf | 美国标准 | STRUCTURED_READY | 10.14 | 0 | 0 | 0 | pass | 0 | 23 |
| pdf | ASTM B898-20-过期.pdf | 美国标准 | STRUCTURED_READY | 10.23 | 0 | 0 | 0 | pass | 0 | 22 |
| pdf | ASTM F2063-26--.pdf | 美国标准 | STRUCTURED_READY | 10.13 | 0 | 0 | 0 | pass | 0 | 22 |
| pdf | GBT 14845-2026.pdf | 国家标准 | STRUCTURED_READY | 12.18 | 7 | 6 | 27 | warn | 3 | 25 |
| pdf | GBT 14976-2025.pdf | 国家标准 | STRUCTURED_READY | 12.21 | 15 | 36 | 104 | warn | 4 | 45 |
| pdf | GBT 1591-2018.pdf | 国家标准 | STRUCTURED_READY | 12.47 | 16 | 0 | 0 | pass | 0 | 36 |
| pdf | GBT 16598-2013.pdf | 国家标准 | STRUCTURED_READY | 10.1 | 9 | 28 | 90 | warn | 13 | 25 |
| pdf | GBT 2054-2023.pdf | 国家标准 | STRUCTURED_READY | 10.12 | 12 | 17 | 68 | warn | 32 | 29 |
| pdf | GBT 24627-2023.pdf | 国家标准 | STRUCTURED_READY | 10.12 | 4 | 0 | 0 | pass | 0 | 29 |
| pdf | GBT 2965-1996过期.pdf | 国家标准 | STRUCTURED_READY | 10.11 | 0 | 0 | 0 | pass | 0 | 21 |
| pdf | GBT 3280-2015.pdf | 国家标准 | STRUCTURED_READY | 16.19 | 59 | 0 | 0 | pass | 0 | 62 |
| pdf | GBT 3620.1-2016.pdf | 国家标准 | STRUCTURED_READY | 10.13 | 8 | 0 | 0 | pass | 0 | 27 |
| pdf | GBT 3621-1994 过期.pdf | 国家标准 | STRUCTURED_READY | 10.14 | 0 | 0 | 0 | pass | 0 | 22 |
| pdf | GBT 3623-2022.pdf | 国家标准 | STRUCTURED_READY | 8.13 | 5 | 0 | 0 | pass | 0 | 23 |
| pdf | GBT 8547-2019.pdf | 国家标准 | STRUCTURED_READY | 10.14 | 9 | 0 | 0 | pass | 0 | 27 |
| pdf | GBT 8732-2014.pdf | 国家标准 | STRUCTURED_READY | 10.13 | 13 | 12 | 12 | pass | 0 | 29 |
| pdf | GJB 5040-2001 航空用钢锻件规范.pdf | 国军标 | STRUCTURED_READY | 12.13 | 9 | 17 | 34 | pass | 0 | 36 |
| pdf | HB 20079-2012 航空用高强度沉淀硬化不锈钢锻件规范.pdf | 行业标准 | STRUCTURED_READY | 12.19 | 9 | 15 | 88 | warn | 14 | 28 |
| pdf | ISO 5832-2-2018-过期.pdf | 国际标准 | STRUCTURED_READY | 10.14 | 3 | 11 | 39 | warn | 7 | 24 |
| pdf | ISO 5832-3-2021.pdf | 国际标准 | STRUCTURED_READY | 10.15 | 5 | 1 | 4 | warn | 1 | 30 |
| pdf | NB-T 47019.8-2011 锅炉、热交换器用管订货技术条件 第8部分 有色金属 钛和钛合 | 行业标准 | STRUCTURED_READY | 10.17 | 9 | 5 | 31 | warn | 9 | 24 |
| pdf | YST 1077-2015.pdf | 行业标准 | STRUCTURED_READY | 12.31 | 5 | 0 | 0 | pass | 0 | 22 |
| pdf | YST 397-2015.pdf | 行业标准 | STRUCTURED_READY | 12.22 | 3 | 0 | 0 | pass | 0 | 22 |
| pdf | YST 579-2014.pdf | 行业标准 | STRUCTURED_READY | 10.17 | 1 | 0 | 0 | pass | 0 | 20 |

## 3. 分支覆盖

| 分支 | 结果 | 证据 |
|---|---|---|

## 4. 结论

- 文档处理：50 份；失败 0 份。
- 分支覆盖：0 项；失败 0 项。
- 失败分支：无。
