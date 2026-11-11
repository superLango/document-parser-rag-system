# 收尾端到端验证报告

> 生成时间：2026-11-11T19:43:52+00:00
> 环境：compose（生产镜像）
> API：http://localhost:18000

## 1. 汇总

| 套件 | 文档数 | 成功 | 失败 | 记录数 | 字段数 | p50(s) | p95(s) | max(s) |
|---|---|---|---|---|---|---|---|---|
| pdf | 40 | 30 | 10 | 1143 | 1608 | 100.66 | 278.14 | 287.89 |

### 阶段耗时（秒）

| 套件 | 阶段 | 样本 | p50 | p95 |
|---|---|---|---|---|
| pdf | ocr | 40 | 49.35 | 277.75 |
| pdf | routing | 31 | 0.28 | 0.42 |
| pdf | sandbox | 30 | 0.92 | 1.22 |
| pdf | review | 29 | 38.7 | 137.14 |

## 2. 文档明细

| 套件 | 文档 | 类型 | 状态 | 耗时(s) | 表 | 记录 | 字段 | 审核 | 发现 | 产物 |
|---|---|---|---|---|---|---|---|---|---|---|
| pdf | 0a01e5deee2049768116740ba489608c-sample-r7.pdf | 采购规范/技术协议 | STRUCTURED_READY | 81.08 | 2 | 8 | 0 | warn | 18 | 26 |
| pdf | 0ca26f51bdc748b6a3e65bdd0fd8a9c1-GB-T1220-2007 不 | 采购规范/技术协议 | FAILED | 250.96 | 0 | 0 | 0 | - | 0 | 0 |
| pdf | 1083bfd3f2a14009a239857f166afb8d-23_MAS7097 B 压气 | 采购规范/技术协议 | FAILED | 271.15 | 0 | 0 | 0 | - | 0 | 0 |
| pdf | 13f7cdcc4d29446abf8f8aa960e18497-29_70_410JX(通用） | 采购规范/技术协议 | FAILED | 187.97 | 0 | 0 | 0 | - | 0 | 0 |
| pdf | 1a83a40edef0432a86b11230e1239378-jx25_035.pdf | 采购规范/技术协议 | STRUCTURED_READY | 16.17 | 5 | 15 | 31 | warn | 48 | 32 |
| pdf | 211798bb89bc4eae9edb94f33f30d545-38_105.YJ(R)-18 | 采购规范/技术协议 | STRUCTURED_READY | 155.0 | 9 | 40 | 7 | warn | 56 | 32 |
| pdf | 25e827d2e3dd477a89e60f1b3d15b17d-qdu_p5.pdf | 采购规范/技术协议 | STRUCTURED_READY | 26.27 | 1 | 3 | 12 | warn | 5 | 16 |
| pdf | 27cfc37bc5834181a5c5531985a1b1bd-mas7079.pdf | 采购规范/技术协议 | STRUCTURED_READY | 36.32 | 5 | 25 | 0 | warn | 35 | 38 |
| pdf | 2ad48220270e4e48921dde253d03ee2d-26_04Cr13Ni5Mo不 | 采购规范/技术协议 | STRUCTURED_READY | 24.22 | 2 | 2 | 0 | warn | 3 | 18 |
| pdf | 4df6cc52bac2456fb761fdc642a9202d-GBT 6892-2015 一 | 采购规范/技术协议 | FAILED | 277.68 | 0 | 0 | 0 | - | 0 | 0 |
| pdf | 55f0c10618c14b1e9b5cc85e92548486-gbt1591_2018.pd | 采购规范/技术协议 | STRUCTURED_READY | 70.51 | 16 | 94 | 22 | warn | 98 | 58 |
| pdf | 5baa524122a7478a89ef34ac16f38825-gbt3191.pdf | 采购规范/技术协议 | STRUCTURED_READY | 12.18 | 0 | 0 | 0 | pass | 0 | 36 |
| pdf | 6ebf8a83fffb4384b55bc6bc2959d670-27_2409285_2409 | 采购规范/技术协议 | STRUCTURED_READY | 187.27 | 8 | 10 | 0 | warn | 20 | 30 |
| pdf | 73bb36f665344df2b8446206b0eeffc8-gjb5301_2004.pd | 采购规范/技术协议 | STRUCTURED_READY | 247.89 | 20 | 138 | 375 | warn | 302 | 56 |
| pdf | 808e2c05fa83447587ded2580f4cd04f-gbt40303_2021.p | 采购规范/技术协议 | FAILED | 278.14 | 0 | 0 | 0 | - | 0 | 0 |
| pdf | 857d97ee51a241869bcd3c5e5c63d769-7、Q／S10-0351-20 | 采购规范/技术协议 | STRUCTURED_READY | 58.48 | 5 | 23 | 11 | warn | 37 | 38 |
| pdf | 8c4bfd4705ba4dc8a864b3c630dc8d1f-39_TG.JT.00.031 | 采购规范/技术协议 | STRUCTURED_READY | 72.55 | 5 | 15 | 6 | warn | 34 | 32 |
| pdf | 90cab5276786441e8d980164a0cd0bd2-13_DFHM-QCD-070 | 采购规范/技术协议 | STRUCTURED_READY | 48.35 | 8 | 30 | 2 | warn | 40 | 32 |
| pdf | 9500fa12e3304a629080ba0463de8cb5-gbt33084_2016.p | 采购规范/技术协议 | STRUCTURED_READY | 12.17 | 8 | 132 | 568 | warn | 546 | 50 |
| pdf | AMS-QQ-A250-4B.pdf | 美国标准 | STRUCTURED_READY | 94.61 | 6 | 16 | 0 | warn | 36 | 28 |
| pdf | AMS4945J.pdf | 美国标准 | STRUCTURED_READY | 16.19 | 1 | 1 | 0 | warn | 2 | 34 |
| pdf | ASME SB338-2021-过期.pdf | 美国标准 | STRUCTURED_READY | 8.13 | 0 | 0 | 0 | pass | 0 | 34 |
| pdf | ASTM B381-21-过期.pdf | 美国标准 | STRUCTURED_READY | 8.11 | 0 | 0 | 0 | pass | 0 | 30 |
| pdf | GB 24627-2009过期.pdf | 国家标准 | STRUCTURED_READY | 118.73 | 9 | 1 | 1 | warn | 2 | 32 |
| pdf | GBT 24627-2023.pdf | 国家标准 | STRUCTURED_READY | 22.24 | 4 | 5 | 0 | warn | 10 | 44 |
| pdf | GBT 3462-2017.pdf | 国家标准 | STRUCTURED_READY | 18.21 | 3 | 4 | 0 | warn | 8 | 26 |
| pdf | GBT 3880.1-2012过期.pdf | 国家标准 | FAILED | 278.01 | 0 | 0 | 0 | - | 0 | 0 |
| pdf | GGX-FJLA-1-22.pdf | 企业标准 | STRUCTURED_READY | 287.89 | 17 | 52 | 56 | warn | 66 | 52 |
| pdf | GJB 1538A-2008过期.pdf | 国军标 | FAILED | 278.09 | 0 | 0 | 0 | - | 0 | 0 |
| pdf | GJB 2294A-2014航空用不锈钢及耐热钢棒规范.pdf | 国军标 | STRUCTURED_READY | 245.59 | 20 | 179 | 385 | warn | 396 | 52 |
| pdf | GJB 3423A-2015.pdf | 国军标 | STRUCTURED_READY | 217.45 | 10 | 77 | 12 | warn | 150 | 34 |
| pdf | HB 20079-2012 航空用高强度沉淀硬化不锈钢锻件规范.pdf | 行业标准 | REVIEW_FAILED | 58.44 | 0 | 0 | 0 | - | 0 | 0 |
| pdf | ISO 5832-2-2018-过期.pdf | 国际标准 | STRUCTURED_READY | 100.66 | 3 | 13 | 15 | warn | 47 | 34 |
| pdf | YST 255-2009.pdf | 行业标准 | STRUCTURED_READY | 167.08 | 5 | 35 | 0 | warn | 54 | 26 |
| pdf | b3c725e08212403bb51a5febf2e30baa-20_411_ZWB-TSD- | 采购规范/技术协议 | STRUCTURED_READY | 221.42 | 5 | 35 | 0 | warn | 71 | 36 |
| pdf | b8a241429d7c4e56bd3cde8aeb451e99-48_GJB 2294A-20 | 采购规范/技术协议 | FAILED | 277.75 | 0 | 0 | 0 | - | 0 | 0 |
| pdf | ba99e438f3f9400cae4391cfed95466e-50_2408274--技术（ | 采购规范/技术协议 | FAILED | 233.67 | 0 | 0 | 0 | - | 0 | 0 |
| pdf | c16f405fd6224083a044339a732e1d2e-49__内部_CBQB903- | 采购规范/技术协议 | STRUCTURED_READY | 52.57 | 9 | 23 | 0 | warn | 33 | 60 |
| pdf | cbe5ea86b0f04611af0ced51f644e842-33_QJ502B-2014. | 采购规范/技术协议 | STRUCTURED_READY | 283.76 | 11 | 109 | 105 | warn | 206 | 36 |
| pdf | e417ae6063fd4892a95a8461e0d8d0d8-32_55_Q_12X 239 | 采购规范/技术协议 | STRUCTURED_READY | 213.44 | 7 | 58 | 0 | warn | 83 | 32 |

## 3. 分支覆盖

| 分支 | 结果 | 证据 |
|---|---|---|
| health_gateway | 通过 | "200" |
| upload_empty_file | 通过 | "400" |
| upload_dedupe | 通过 | "237d684f-eb59-4b40-927a-93b0a91878ec" |
| create_run_invalid_channel | 通过 | "422" |
| unknown_document_run | 通过 | "404" |
| unknown_run_get | 通过 | "404" |
| unknown_recipe | 通过 | "404" |
| dictionary_query | 通过 | "200" |
| cancel_run | 通过 | "{\"id\":\"7024ea69-a878-420e-b21a-f8732dd5f380\",\"document_id\":\"237d684f-eb59-4b40-927a-93b0a91878ec\",\"document_ve |
| result_after_cancel | 通过 | "200" |
| records_after_cancel | 通过 | "404" |
| happy_path | 通过 | "STRUCTURED_READY" |
| timeline_stage_order | 通过 | ["ocr", "routing", "sandbox", "review"] |
| artifacts_present | 通过 | 14 |
| missing_page_image | 通过 | "404" |
| review_gate_blocks_deterministic_error | 通过 | {"status": "REVIEW_FAILED", "error_code": "REVIEW_FAILED", "review": "fail"} |
| sse_event_stream | 通过 | ["done", "run.completed", "run.stage.completed", "run.stage.started"] |
| delete_document_with_active_run | 通过 | {"delete": 204, "document": 404, "run": "deleted"} |

## 4. 结论

- 文档处理：40 份；失败 10 份。
- 分支覆盖：18 项；失败 0 项。
- 失败分支：无。
