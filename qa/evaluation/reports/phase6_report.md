# Phase 6 评测报告

## 汇总指标
| 指标 | 值 | 门禁阈值 | 判定 |
|---|---|---|--|
| task_success_rate | 1.0 | 0.95 | 通过 |
| layout_recall | 0.8718 | 0.8 | 通过 |
| layout_precision | 0.8424 | 0.7 | 通过 |
| title_accuracy | 0.9130434782608695 | 0.7 | 通过 |
| ocr_page_accuracy | 0.96 | 0.85 | 通过 |
| table_restore_rate | 1.0 | 0.8 | 通过 |

## 样本明细
| 样本 | 成功 | 耗时(s) | 页数 | 版面块 | recall | precision |
|---|---|---|---|---|---|---|
| 462a2e2857face94b2c800d3a8492740.pdf | 是 | 4.973 | 13 | 196 | None | None |
| GB-T1220-2007 不锈钢棒.pdf | 是 | 8.482 | 31 | 348 | None | None |
| GJB3325A-2019.pdf | 是 | 2.055 | 9 | 209 | None | None |
| LSAM-JD01-0016  优质GH4169合金锻制棒材.pdf | 是 | 1.664 | 11 | 180 | None | None |
| a62820a10c1c33f40ede554498d7bdf1.pdf | 是 | 1.77 | 12 | 191 | None | None |
| c8f1e134282d41dcc40b5243f4e9a98d.pdf | 是 | 2.129 | 14 | 166 | None | None |
| synth_blank_mix.pdf | 是 | 0.263 | 2 | 2 | 0.6666666666666666 | 1.0 |
| synth_cover_body.pdf | 是 | 0.523 | 4 | 11 | 1.0 | 0.9090909090909091 |
| synth_footnote.pdf | 是 | 0.262 | 2 | 6 | 0.6666666666666666 | 0.6666666666666666 |
| synth_formula.pdf | 是 | 0.263 | 2 | 6 | 0.3333333333333333 | 0.3333333333333333 |
| synth_header_complex.pdf | 是 | 0.414 | 3 | 9 | 1.0 | 1.0 |
| synth_image_caption.pdf | 是 | 0.265 | 2 | 4 | 0.6666666666666666 | 1.0 |
| synth_long_multi.pdf | 是 | 1.04 | 8 | 16 | 1.0 | 1.0 |
| synth_mixed_layout.pdf | 是 | 0.405 | 3 | 15 | 1.0 | 1.0 |
| synth_scanned_style.pdf | 是 | 0.268 | 2 | 2 | None | None |
| synth_table_crosspage.pdf | 是 | 0.418 | 3 | 6 | 1.0 | 0.6666666666666666 |
| synth_table_mixed.pdf | 是 | 0.406 | 3 | 7 | 1.0 | 1.0 |
| synth_text_single.pdf | 是 | 0.397 | 3 | 8 | 1.0 | 0.875 |
| synth_text_two_column.pdf | 是 | 0.4 | 3 | 9 | 1.0 | 1.0 |
| synth_toc_chapters.pdf | 是 | 0.531 | 4 | 14 | 1.0 | 0.5 |