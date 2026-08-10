# Phase 6 评测报告

## 汇总指标
| 指标 | 值 | 门禁阈值 | 判定 |
|---|---|---|--|
| task_success_rate | 1.0 | 0.95 | 通过 |
| layout_recall | 0.8974 | 0.8 | 通过 |
| layout_precision | 0.9278 | 0.7 | 通过 |
| title_accuracy | 0.8695652173913043 | 0.7 | 通过 |
| ocr_page_accuracy | 1.0 | 0.85 | 通过 |
| table_restore_rate | 1.0 | 0.8 | 通过 |

## 样本明细
| 样本 | 成功 | 耗时(s) | 页数 | 版面块 | recall | precision |
|---|---|---|---|---|---|---|
| 462a2e2857face94b2c800d3a8492740.pdf | 是 | 6.163 | 13 | 144 | None | None |
| GB-T1220-2007 不锈钢棒.pdf | 是 | 8.85 | 31 | 212 | None | None |
| GJB3325A-2019.pdf | 是 | 2.169 | 9 | 124 | None | None |
| LSAM-JD01-0016  优质GH4169合金锻制棒材.pdf | 是 | 1.734 | 11 | 135 | None | None |
| a62820a10c1c33f40ede554498d7bdf1.pdf | 是 | 1.872 | 12 | 135 | None | None |
| c8f1e134282d41dcc40b5243f4e9a98d.pdf | 是 | 2.165 | 14 | 126 | None | None |
| synth_blank_mix.pdf | 是 | 0.318 | 2 | 3 | 1.0 | 1.0 |
| synth_cover_body.pdf | 是 | 0.603 | 4 | 11 | 1.0 | 0.9090909090909091 |
| synth_footnote.pdf | 是 | 0.329 | 2 | 4 | 0.6666666666666666 | 1.0 |
| synth_formula.pdf | 是 | 0.323 | 2 | 4 | 0.3333333333333333 | 0.5 |
| synth_header_complex.pdf | 是 | 0.477 | 3 | 9 | 1.0 | 1.0 |
| synth_image_caption.pdf | 是 | 0.331 | 2 | 4 | 0.6666666666666666 | 1.0 |
| synth_long_multi.pdf | 是 | 1.141 | 8 | 16 | 1.0 | 1.0 |
| synth_mixed_layout.pdf | 是 | 0.462 | 3 | 15 | 1.0 | 1.0 |
| synth_scanned_style.pdf | 是 | 0.318 | 2 | 0 | None | None |
| synth_table_crosspage.pdf | 是 | 0.585 | 3 | 4 | 1.0 | 1.0 |
| synth_table_mixed.pdf | 是 | 0.478 | 3 | 7 | 1.0 | 1.0 |
| synth_text_single.pdf | 是 | 0.464 | 3 | 9 | 1.0 | 0.7777777777777778 |
| synth_text_two_column.pdf | 是 | 0.477 | 3 | 9 | 1.0 | 1.0 |
| synth_toc_chapters.pdf | 是 | 0.603 | 4 | 8 | 1.0 | 0.875 |