# M8 新旧效果对比报告

> 生成时间：2026-11-12T04:01:10+00:00
> 样本：60 份（旧结果表重建为输入）
> 结论：**未达标**

## 1. 指标

| 指标 | 结果 | 门槛 |
|---|---|---|
| Field F1 | 0.4933 | ≥ 0.80 |
| Value match | 0.9508 | ≥ 0.90 |
| 静默错误率 | 0.0492 | ≤ 0.05 |
| 覆盖率 | 1.0000 | ≥ 0.90 |
| p95 延迟 | 9.22s | ≤ 120.00s |
| 证据命中率 | 1.0000 | 参考 |
| 失败运行 | 0 | 0 |

- 旧字段：2932；新字段：2914；共同字段：1442
- Precision 0.4949 / Recall 0.4918

## 2. 文档明细

| 文档 | 类型 | 旧字段 | 新字段 | 共同 | 值匹配 | F1 | 静默错误 | 耗时(s) | 状态 |
|---|---|---|---|---|---|---|---|---|---|
| 05ecccc8ad8d | chemical | 36 | 38 | 34 | 0.94 | 0.919 | 2 | 8.2 | STRUCTURED_READY |
| 0684efec05a5 | chemical | 15 | 18 | 12 | 1.00 | 0.727 | 0 | 8.2 | STRUCTURED_READY |
| 0715f18cf44c | chemical | 57 | 56 | 30 | 0.97 | 0.531 | 1 | 8.3 | STRUCTURED_READY |
| 075993d8bda5 | chemical | 20 | 4 | 4 | 1.00 | 0.333 | 0 | 8.2 | STRUCTURED_READY |
| 0c87affede6e | mechanical | 45 | 18 | 4 | 1.00 | 0.127 | 0 | 8.2 | STRUCTURED_READY |
| 100e43ba7722 | chemical | 17 | 16 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| 10aef59a5c91 | chemical | 16 | 16 | 16 | 1.00 | 1.000 | 0 | 8.2 | STRUCTURED_READY |
| 1738d3d4f8f7 | chemical | 14 | 9 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| 1741e4503e46 | mechanical | 33 | 33 | 9 | 1.00 | 0.273 | 0 | 8.1 | STRUCTURED_READY |
| 1741e4503e46 | mechanical | 33 | 33 | 9 | 1.00 | 0.273 | 0 | 8.2 | STRUCTURED_READY |
| 17d722e0e9d9 | chemical | 20 | 26 | 18 | 1.00 | 0.783 | 0 | 8.1 | STRUCTURED_READY |
| 187d5d3857cc | chemical | 14 | 21 | 14 | 1.00 | 0.800 | 0 | 8.2 | STRUCTURED_READY |
| 1c4cf85c9255 | chemical | 16 | 10 | 0 | 0.00 | 0.000 | 0 | 7.2 | STRUCTURED_READY |
| 208851e12800 | chemical | 16 | 15 | 7 | 1.00 | 0.452 | 0 | 8.3 | STRUCTURED_READY |
| 22b1476b150e | chemical | 14 | 20 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| 27c4e67d00ff | chemical | 34 | 29 | 25 | 0.92 | 0.794 | 2 | 8.2 | STRUCTURED_READY |
| 2ad6ce310e68 | chemical | 16 | 12 | 10 | 0.90 | 0.714 | 1 | 8.3 | STRUCTURED_READY |
| 2af08cbfcabe | chemical | 17 | 12 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| 3081c0f9b98d | chemical | 16 | 12 | 11 | 1.00 | 0.786 | 0 | 8.1 | STRUCTURED_READY |
| 4417071b32c1 | chemical | 81 | 112 | 81 | 0.74 | 0.839 | 21 | 8.1 | STRUCTURED_READY |
| 521854804389 | chemical | 16 | 16 | 16 | 1.00 | 1.000 | 0 | 8.1 | STRUCTURED_READY |
| 564ae4f40b9a | chemical | 67 | 76 | 56 | 1.00 | 0.783 | 0 | 8.3 | STRUCTURED_READY |
| 59bebdcf7e10 | chemical | 19 | 3 | 3 | 1.00 | 0.273 | 0 | 8.2 | STRUCTURED_READY |
| 5c7ee8be97c4 | chemical | 154 | 219 | 48 | 0.65 | 0.257 | 17 | 9.3 | STRUCTURED_READY |
| 608333b8e2df | mechanical | 10 | 6 | 6 | 1.00 | 0.750 | 0 | 8.2 | STRUCTURED_READY |
| 65c7cfb83be7 | chemical | 162 | 192 | 143 | 0.97 | 0.808 | 4 | 10.4 | STRUCTURED_READY |
| 67a742b20c66 | chemical | 18 | 35 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| 6db6bab71842 | chemical | 15 | 10 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| 7069f774d8d4 | chemical | 24 | 22 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| 728e72b0f2e6 | chemical | 16 | 15 | 7 | 1.00 | 0.452 | 0 | 8.2 | STRUCTURED_READY |
| 7319bf3dde60 | chemical | 30 | 30 | 25 | 0.80 | 0.833 | 5 | 8.2 | STRUCTURED_READY |
| 7373a8d9a442 | chemical | 32 | 55 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| 74aec6bf7405 | chemical | 16 | 15 | 7 | 1.00 | 0.452 | 0 | 8.2 | STRUCTURED_READY |
| 754a537ea3f9 | mechanical | 38 | 40 | 12 | 1.00 | 0.308 | 0 | 8.2 | STRUCTURED_READY |
| 775043b53873 | chemical | 22 | 23 | 20 | 1.00 | 0.889 | 0 | 8.2 | STRUCTURED_READY |
| 78a0de4c51a2 | mechanical | 122 | 110 | 98 | 1.00 | 0.845 | 0 | 8.1 | STRUCTURED_READY |
| 7ad79a9408c9 | chemical | 37 | 33 | 20 | 1.00 | 0.571 | 0 | 8.2 | STRUCTURED_READY |
| 92e35be4e585 | chemical | 16 | 42 | 16 | 1.00 | 0.552 | 0 | 8.2 | STRUCTURED_READY |
| 9d1ae7d941e0 | chemical | 44 | 3 | 3 | 1.00 | 0.128 | 0 | 8.2 | STRUCTURED_READY |
| a5fbc645696b | chemical | 20 | 4 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| a671647676ee | other | 24 | 146 | 0 | 0.00 | 0.000 | 0 | 9.2 | STRUCTURED_READY |
| ae7a1887a2e0 | chemical | 22 | 12 | 0 | 0.00 | 0.000 | 0 | 7.2 | STRUCTURED_READY |
| b50805e0ab63 | chemical | 18 | 14 | 2 | 0.50 | 0.125 | 1 | 8.2 | STRUCTURED_READY |
| b8c365836b9c | chemical | 24 | 5 | 4 | 1.00 | 0.276 | 0 | 8.2 | STRUCTURED_READY |
| bc0fd7f758e5 | chemical | 17 | 32 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| bc6e766f5cb7 | chemical | 18 | 1 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| be26fecfa3a0 | chemical | 18 | 14 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| bf295b3df1a7 | chemical | 17 | 24 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| cdbfe0b1485a | chemical | 16 | 16 | 16 | 1.00 | 1.000 | 0 | 7.2 | STRUCTURED_READY |
| d26323581f40 | mechanical | 80 | 80 | 48 | 0.67 | 0.600 | 16 | 8.2 | STRUCTURED_READY |
| da33e8657541 | chemical | 16 | 11 | 11 | 0.91 | 0.815 | 1 | 8.2 | STRUCTURED_READY |
| da6e78317ae0 | chemical | 232 | 375 | 229 | 1.00 | 0.754 | 0 | 9.3 | STRUCTURED_READY |
| de2adf26e9dd | chemical | 45 | 43 | 43 | 1.00 | 0.977 | 0 | 8.2 | STRUCTURED_READY |
| de301f981df7 | mechanical | 19 | 10 | 9 | 1.00 | 0.621 | 0 | 8.2 | STRUCTURED_READY |
| e0ac84b49ef6 | chemical | 16 | 20 | 16 | 1.00 | 0.889 | 0 | 8.2 | STRUCTURED_READY |
| ec684db9f609 | chemical | 17 | 12 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| fc367075184b | chemical | 23 | 27 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| pdf__GBT3308 | chemical | 812 | 568 | 300 | 1.00 | 0.435 | 0 | 9.2 | STRUCTURED_READY |
| pdf__JX-25-0 | chemical | 25 | 17 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| pdf__gbt1591 | other | 65 | 28 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |

## 3. 差异样例

```text
05ecccc8ad8d 仅旧: ~/B, ~/C
05ecccc8ad8d 仅新: 日期/B, 更改人/B, 更改内容及说明/B, 状态/B
0684efec05a5 仅旧: ~/RM, ~/RP0.2, ~/Z
0684efec05a5 仅新: 最小/C, 最小/Fe, 最小/H, 最小/N, 最小/O, 最小/Y
0715f18cf44c 仅旧: 30CR3SINIMOVA/A@淬火, 30CR3SINIMOVA/B, 30CR3SINIMOVA/KIC@淬火, 30CR3SINIMOVA/KV2@淬火, 30CR3SINIMOVA/RM@淬火, 30CR3SINIMOVA/RP0.2@淬火, 30CR3SINIMOVA/Z@淬火, 30SI2MNCRMOVE/KV2
0715f18cf44c 仅新: 30CR3SINIMOVA/Cu, 30CR3SINIMOVA/HBW@退火, 30CR3SINIMOVA/KU2, 30CR3SINIMOVA/RM, 30CR3SINIMOVA/RP0.2, 30CR3SINIMOVA/Z, 30SI2MNCRMOVE/HBW@退火, 30SI2MNCRMOVE/HBW@高温
075993d8bda5 仅旧: 650/A, 650/HB, 650/RM, 650/RP0.2, 650/Z, 化学成分/Al, 化学成分/C, 化学成分/Co
075993d8bda5 仅新: 
0c87affede6e 仅旧: 250/A, 250/RM, 250/RP0.2, 250/Z, 500/A, 500/HB, 500/KV2, 500/RM
0c87affede6e 仅新: 基/Al, 基/C, 基/Fe, 基/H, 基/Mo, 基/N, 基/O, 基/Si
100e43ba7722 仅旧: SS316L/A, SS316L/B, SS316L/C, SS316L/Co, SS316L/Cr, SS316L/Cu, SS316L/Mn, SS316L/Mo
100e43ba7722 仅新: 元素/C, 元素/Cr, 元素/Mn, 元素/Mo, 元素/Ni, 元素/P, 元素/S, 元素/Si
10aef59a5c91 仅旧: 
10aef59a5c91 仅新: 
1738d3d4f8f7 仅旧: 1738/A, 1738/Al, 1738/C, 1738/H, 1738/Mo, 1738/N, 1738/O, 1738/RM
1738d3d4f8f7 仅新: 基/Al, 基/C, 基/H, 基/Mo, 基/N, 基/O, 基/Si, 基/Sn
1741e4503e46 仅旧: 25CR2MOVA/A@切向, 25CR2MOVA/A@纵向, 25CR2MOVA/HB@切向, 25CR2MOVA/HB@纵向, 25CR2MOVA/KU2@切向, 25CR2MOVA/KV2@切向, 25CR2MOVA/KV2@纵向, 25CR2MOVA/RM@切向
1741e4503e46 仅新: 25CR2MOVA/C, 25CR2MOVA/Cr, 25CR2MOVA/Cu, 25CR2MOVA/KU2, 25CR2MOVA/Mn, 25CR2MOVA/Mo, 25CR2MOVA/N, 25CR2MOVA/Ni
1741e4503e46 仅旧: 25CR2MOVA/A@切向, 25CR2MOVA/A@纵向, 25CR2MOVA/HB@切向, 25CR2MOVA/HB@纵向, 25CR2MOVA/KU2@切向, 25CR2MOVA/KV2@切向, 25CR2MOVA/KV2@纵向, 25CR2MOVA/RM@切向
1741e4503e46 仅新: 25CR2MOVA/C, 25CR2MOVA/Cr, 25CR2MOVA/Cu, 25CR2MOVA/KU2, 25CR2MOVA/Mn, 25CR2MOVA/Mo, 25CR2MOVA/N, 25CR2MOVA/Ni
17d722e0e9d9 仅旧: ~/B, ~/C
17d722e0e9d9 仅新: 日期/B, 日期/C, 更改人/B, 更改人/C, 更改内容及说明/B, 更改内容及说明/C, 状态/B, 状态/C
187d5d3857cc 仅旧: 
187d5d3857cc 仅新: 类别/C, 类别/Cr, 类别/Mn, 类别/Ni, 类别/P, 类别/S, 类别/Si
1c4cf85c9255 仅旧: TA15/A, TA15/Al, TA15/C, TA15/Fe, TA15/H, TA15/HB, TA15/KV2, TA15/Mo
1c4cf85c9255 仅新: 基/Al, 基/C, 基/Fe, 基/H, 基/Mo, 基/N, 基/O, 基/Si
208851e12800 仅旧: 化学成分/C, 化学成分/Cr, 化学成分/Mn, 化学成分/Si, 淬火温度880℃~900℃，油冷，回火温度510℃~570℃，油冷/室温/A@室温, 淬火温度880℃~900℃，油冷，回火温度510℃~570℃，油冷/室温/KV2@室温, 淬火温度880℃~900℃，油冷，回火温度510℃~570℃，油冷/室温/RM@室温, 淬火温度880℃~900℃，油冷，回火温度510℃~570℃，油冷/室温/RP0.2@室温
208851e12800 仅新: 30CRMNSIA/Cu, 30CRMNSIA/Mo, 30CRMNSIA/Ni, 30CRMNSIA/V, 允许偏差/C, 允许偏差/Cr, 允许偏差/Mn, 允许偏差/Si
22b1476b150e 仅旧: 1476/A, 1476/KV2, 1476/RM, 1476/ReH, 1476/Z, ~/C, ~/Cr, ~/H
22b1476b150e 仅新: MAX/C, MAX/Cr, MAX/Mn, MAX/Mo, MAX/Ni, MAX/P, MAX/S, MAX/Si
27c4e67d00ff 仅旧: GH4169D/A, GH4169D/A@室温, GH4169D/HB@室温, GH4169D/RM, GH4169D/RM@室温, GH4169D/RP0.2, GH4169D/RP0.2@室温, GH4169D/Z
27c4e67d00ff 仅新: 公差/C, 公差/H, 弦向/RP0.2, 弦向/RP0.2@室温
2ad6ce310e68 仅旧: 淬火830~860℃，油冷回火550~680℃，空冷/A@淬火, 淬火830~860℃，油冷回火550~680℃，空冷/KV2@淬火, 淬火830~860℃，油冷回火550~680℃，空冷/RM@淬火, 淬火830~860℃，油冷回火550~680℃，空冷/RP0.2@淬火, 淬火830~860℃，油冷回火550~680℃，空冷/Z@淬火, 热处理方式：正火温度870±20℃，淬火温度850±10℃/HRC
2ad6ce310e68 仅新: ≤2.5级/B, ≤2.5级/C
2af08cbfcabe 仅旧: wt%/化学成分/C, wt%/化学成分/Co, wt%/化学成分/Cr, wt%/化学成分/Cu, wt%/化学成分/Fe, wt%/化学成分/Mn, wt%/化学成分/Mo, wt%/化学成分/Ni
2af08cbfcabe 仅新: 元素/Cr, 元素/Cu, 元素/Fe, 元素/Mo, 元素/Ni, 元素/Ti, 含量/Cr, 含量/Cu
3081c0f9b98d 仅旧: 200℃/A, 200℃/RM, 200℃/RP0.2, 室温/KV2, 室温/RP0.2
3081c0f9b98d 仅新: 室温/Z
4417071b32c1 仅旧: 
4417071b32c1 仅新: 022CR17NI12MO2/B, 022CR17NI12MO2/Co, 022CR17NI12MO2/N, 022CR17NI12MO2/Ti, 022CR19NI10/B, 022CR19NI10/Co, 022CR19NI10/Mo, 022CR19NI10/N
521854804389 仅旧: 
521854804389 仅新: 
564ae4f40b9a 仅旧: 022CR17NI12MO2/Cr, 022CR17NI12MO2/KV2, 022CR19NI10/KV2, 026CR18NI12MO2N/KV2, 026CR19NI10N/KV2, 06CR17NI12MO2/KV2, 06CR19NI10/KV2, 08CR18NI11T/KV2
564ae4f40b9a 仅新: 022CR19NI10/B, 022CR19NI10/Co, 022CR19NI10/Mo, 022CR19NI10/N, 022CR19NI10/Ti, 026CR19NI10N/B, 026CR19NI10N/Co, 026CR19NI10N/Mo
59bebdcf7e10 仅旧: A105NTEXTCIRCLED3/A, A105NTEXTCIRCLED3/Cr, A105NTEXTCIRCLED3/Cu, A105NTEXTCIRCLED3/HB, A105NTEXTCIRCLED3/Mo, A105NTEXTCIRCLED3/Ni, A105NTEXTCIRCLED3/P, A105NTEXTCIRCLED3/RM
59bebdcf7e10 仅新: 
5c7ee8be97c4 仅旧: 07CR18NI11NB/HB, 07CR18NI11NB/HRC, 07CR18NI11NB/RP0.2, 07CR19NI11TI/HB, 07CR19NI11TI/HRC, 07CR19NI11TI/RP0.2, 07CR22NI25W3CU3CO2MONBN/HB, 07CR22NI25W3CU3CO2MONBN/HRC
5c7ee8be97c4 仅新: 07CR18NI11NB/HBW, 07CR18NI11NB/KV2, 07CR18NI11NB/P, 07CR18NI11NB/REL, 07CR18NI11NB/S, 07CR19NI10/A, 07CR19NI10/HBW, 07CR19NI10/HV
608333b8e2df 仅旧: 6061/KV2, 6061/KV2@纵向, 6061/RP0.2, 6061/RP0.2@纵向
608333b8e2df 仅新: 
65c7cfb83be7 仅旧: 0℃/-/A, 0℃/E, 350℃/rp0.2/mpa/A, a.对于1级和2级棒材，也可以为a%>=12，且z>=45%。b.所列规定值为单个最小值。/E@最小, a仅对1级棒材。b仅对2、3级棒材。c仅对以固溶状态交货的棒材。d所列规定值为单个最小值。/A@最小, a所列规定值为单个最小值。/E@最小, ~/C, ~/Cr
65c7cfb83be7 仅新: 05CR16NI4MO/Cu, 05CR17NI4CU4NB/Mo, 05CR19NI10/Mo, 06CR15NI25TI2MOALVB/Cu, 06CR17NI12MO2/Cu, 06CR19NI10/Cu, 06CR19NI10/Mo, 12CR12NI3MO2VN/Cu
67a742b20c66 仅旧: 750/A, 750/RP0.2, 750/Z, 800/A, 800/RP0.2, 800/Z, ~/Al, ~/C
67a742b20c66 仅新: NI/Al, NI/Co, NI/Cr, NI/Mo, NI/Nb, NI/Ti, NI/V, NI/W
6db6bab71842 仅旧: 500/A, 500/RM, 500/RP0.2, 500/Z, 化学成分/Al, 化学成分/C, 化学成分/Fe, 化学成分/H
6db6bab71842 仅新: 余量/Al, 余量/C, 余量/Fe, 余量/H, 余量/Mo, 余量/N, 余量/O, 余量/Si
7069f774d8d4 仅旧: ~/B, ~/C, 元素含量 WT.% 最大/B, 元素含量 WT.% 最大/C, 元素含量 WT.% 最大/Cr, 元素含量 WT.% 最大/Cu, 元素含量 WT.% 最大/Mn, 元素含量 WT.% 最大/Mo
7069f774d8d4 仅新: 最大/B, 最大/C, 最大/Cr, 最大/Cu, 最大/Mn, 最大/Mo, 最大/N, 最大/Ni
728e72b0f2e6 仅旧: 0974/A@室温, 0974/C, 0974/Cr, 0974/KV2@室温, 0974/Mn, 0974/RM@室温, 0974/RP0.2@室温, 0974/Si
728e72b0f2e6 仅新: 30CRMNSIA/Cu, 30CRMNSIA/Mo, 30CRMNSIA/Ni, 30CRMNSIA/V, 允许偏差/C, 允许偏差/Cr, 允许偏差/Mn, 允许偏差/Si
7319bf3dde60 仅旧: ~/C, 成品分析/Al, 成品分析/N, 熔炼分析/Al, 熔炼分析/N
7319bf3dde60 仅新: ~/H, ~/N, ~/P, 成品分析/Na, 熔炼分析/Na
7373a8d9a442 仅旧: 元素含量，WT.% MAX/B, 元素含量，WT.% MAX/Cr, 元素含量，WT.% MAX/Cu, 元素含量，WT.% MAX/Mn, 元素含量，WT.% MAX/Mo, 元素含量，WT.% MAX/Ni, 元素含量，WT.% MAX/W, 元素含量，WT.% MIN/B
7373a8d9a442 仅新: 0/C, 0/Co, 0/N, 0/Nb, 0/P, 0/S, 0/Ta, 0/Ti
74aec6bf7405 仅旧: 4782/A@室温, 4782/C, 4782/Cr, 4782/KV2@室温, 4782/Mn, 4782/RM@室温, 4782/RP0.2@室温, 4782/Si
74aec6bf7405 仅新: 30CRMNSIA/Cu, 30CRMNSIA/Mo, 30CRMNSIA/Ni, 30CRMNSIA/V, 允许偏差/C, 允许偏差/Cr, 允许偏差/Mn, 允许偏差/Si
754a537ea3f9 仅旧: 25CR2MOVA/A@切向, 25CR2MOVA/A@纵向, 25CR2MOVA/HB@切向, 25CR2MOVA/HB@纵向, 25CR2MOVA/KU2@切向, 25CR2MOVA/KV2@切向, 25CR2MOVA/KV2@纵向, 25CR2MOVA/RM@切向
754a537ea3f9 仅新: 18CR2NI4WA/C, 18CR2NI4WA/Cr, 18CR2NI4WA/Cu, 18CR2NI4WA/Mn, 18CR2NI4WA/Mo, 18CR2NI4WA/N, 18CR2NI4WA/Ni, 18CR2NI4WA/P
775043b53873 仅旧: 成品分析/H, 熔炼分析/H
775043b53873 仅新: ~/H, ~/N, ~/P
78a0de4c51a2 仅旧: TA0/RP0.2, TA1/RP0.2, TA10/RP0.2, TA13/RP0.2, TA15/RP0.2, TA19/RP0.2, TA2/RP0.2, TA3/RP0.2
78a0de4c51a2 仅新: TA15/持久应力, TA19/持久应力, TA6/持久应力, TA7/持久应力, TC1/持久应力, TC10/持久应力, TC11A/持久应力, TC12/持久应力
7ad79a9408c9 仅旧: 18MNCRNIM/KV2, 18MNCRNIMO(W)*/C, 18MNCRNIMO(W)*/Ce, 18MNCRNIMO(W)*/Cr, 18MNCRNIMO(W)*/Cu, 18MNCRNIMO(W)*/Mn, 18MNCRNIMO(W)*/Mo, 18MNCRNIMO(W)*/Ni
7ad79a9408c9 仅新: 18MNCRNIMO(W)/C, 18MNCRNIMO(W)/Cr, 18MNCRNIMO(W)/Cu, 18MNCRNIMO(W)/Mn, 18MNCRNIMO(W)/Mo, 18MNCRNIMO(W)/Ni, 18MNCRNIMO(W)/P, 18MNCRNIMO(W)/S
92e35be4e585 仅旧: 
92e35be4e585 仅新: col2/B, col2/C, col2/RE, col3/B, col3/C, col3/RE, col4/B, col4/C
9d1ae7d941e0 仅旧: 350/A, 350/RM, 350/RP0.2, 350/Z, 450/A, 450/RM, 450/RP0.2, 450/Z
9d1ae7d941e0 仅新: 
a5fbc645696b 仅旧: 750/A, 750/RM, 750/RP0.2, 750/Z, 化学成分/Al, 化学成分/C, 化学成分/Fe, 化学成分/H
a5fbc645696b 仅新: 室温/A, 室温/RM, 室温/RP0.2, 室温/Z
a671647676ee 仅旧: L245MH/BMH/CEV, L245NH/BH/CEV, L245QH/BQH/CEV, L290MH/X42MH/CEV, L290NH/X42NH/CEV, L290QH/X42QH/CEV, L320MH/X46MH/CEV, L320NH/X46NH/CEV
a671647676ee 仅新: E.在50MM的标距长度上/REL, E.在50MM的标距长度上/RM, E.在50MM的标距长度上/ReH, L245MH/BMH/C, L245MH/BMH/Mn, L245MH/BMH/Nb, L245MH/BMH/P, L245MH/BMH/REL
ae7a1887a2e0 仅旧: BEST项目屏蔽块用316L(N)不锈钢锻件委外技术协议/RM, 会审/日期：齐远2026.07.15/RM, 化学成分/B, 化学成分/C, 化学成分/Co, 化学成分/Cr, 化学成分/Cu, 化学成分/Fe
ae7a1887a2e0 仅新: 元素/C, 元素/Cr, 元素/Mn, 元素/Mo, 元素/Ni, 元素/Si, 标准/C, 标准/Cr
b50805e0ab63 仅旧: 3658/A, 3658/C, 3658/Co, 3658/Cr, 3658/Cu, 3658/Fe, 3658/Mn, 3658/Mo
b50805e0ab63 仅新: 元素/C, 元素/Cr, 元素/Mn, 元素/P, 元素/S, 元素/Si, 含量,%/C, 含量,%/Cr
b8c365836b9c 仅旧: 800/A, 800/RM, 800/Z, B 不大于/B, C 不大于/B, CE 不大于/B, COL9/B, FE 不大于/B
b8c365836b9c 仅新: 室温/Z
bc0fd7f758e5 仅旧: 750/650/A, 750/650/RM, 750/650/RP0.2, 750/650/Z, 800/650/A, 800/650/RM, 800/650/RP0.2, 800/650/Z
bc0fd7f758e5 仅新: NI/Al, NI/Co, NI/Cr, NI/Mo, NI/Nb, NI/Ti, NI/V, NI/W
bc6e766f5cb7 仅旧: ~/A, ~/RM, 化学成分/Al, 化学成分/B, 化学成分/C, 化学成分/Ce, 化学成分/Co, 化学成分/Cr
bc6e766f5cb7 仅新: RT/B
be26fecfa3a0 仅旧: 0486/A, 0486/Al, 0486/C, 0486/Fe, 0486/H, 0486/HB, 0486/KV2, 0486/Mo
be26fecfa3a0 仅新: 元素/Al, 元素/Mo, 元素/Si, 元素/Sn, 元素/Ti, 元素/W, 元素/Zr, 含量/%/Al
bf295b3df1a7 仅旧: ~/Al, ~/B, ~/C, ~/Co, ~/Cr, ~/Cu, ~/Fe, ~/HB
bf295b3df1a7 仅新: MAX/Al, MAX/B, MAX/C, MAX/Co, MAX/Cr, MAX/Cu, MAX/Fe, MAX/Mn
cdbfe0b1485a 仅旧: 
cdbfe0b1485a 仅新: 
d26323581f40 仅旧: -/A, -/HB, -/RM, -/ReH, -/Z, 17CRNIMO6/KV2, 20CR2NI418CR2NI4WA/KV2, 20CRMNMO12CRNI320CRNI2MO/KV2
d26323581f40 仅新: 17CRNIMO6/V, 20/A, 20/HB, 20/RM, 20/ReH, 20/Z, 20CR2NI418CR2NI4WA/V, 20CRMNMO12CRNI320CRNI2MO/V
da33e8657541 仅旧: <=-60℃/A, <=-60℃/HB, <=-60℃/KV2, <=-60℃/RM, <=-60℃/RP0.2
da33e8657541 仅新: 
da6e78317ae0 仅旧: GH4033/KU2, GH4133/KU2, GH4133B/KU2
da6e78317ae0 仅新: GH1016A/Ag, GH1016A/Al, GH1016A/As, GH1016A/Bi, GH1016A/Co, GH1016A/Cu, GH1016A/Pb, GH1016A/Sb
de2adf26e9dd 仅旧: 1J22/B, TU2/Cu
de2adf26e9dd 仅新: 
de301f981df7 仅旧: ~/A, ~/HB, ~/KV2, ~/RM, ~/RP0.2, 淬火：990~1010℃油冷回火：>=700℃空冷/A@淬火, 淬火：990~1010℃油冷回火：>=700℃空冷/HB@淬火, 淬火：990~1010℃油冷回火：>=700℃空冷/KV2@淬火
de301f981df7 仅新: ~/B
e0ac84b49ef6 仅旧: 
e0ac84b49ef6 仅新: ~/B, ~/H, ~/N, ~/P
ec684db9f609 仅旧: wt%/化学成分/Al, wt%/化学成分/B, wt%/化学成分/C, wt%/化学成分/Co, wt%/化学成分/Cr, wt%/化学成分/Cu, wt%/化学成分/Fe, wt%/化学成分/Mn
ec684db9f609 仅新: 元素/C, 元素/Cr, 元素/Mo, 元素/Ni, 元素/Ti, 元素/W, 含量/C, 含量/Cr
fc367075184b 仅旧: wt%/化学成分/Al, wt%/化学成分/As, wt%/化学成分/B, wt%/化学成分/Bi, wt%/化学成分/C, wt%/化学成分/Ca, wt%/化学成分/Cr, wt%/化学成分/Cu
fc367075184b 仅新: 元素/C, 元素/Cr, 元素/Mn, 元素/Mo, 元素/Ni, 元素/P, 元素/S, 元素/Si
pdf__GBT3308 仅旧: 12CR1MOV/A, 12CR1MOV/HB, 12CR1MOV/KV2, 12CR1MOV/P, 12CR1MOV/RM, 12CR1MOV/S, 12CR1MOV/Z, 12CRM/KU2
pdf__GBT3308 仅新: %/Al, %/C, %/Cr, %/Mn, %/Mo, %/Nb, %/Ni, %/P
pdf__JX-25-0 仅旧: GH4698/A@室温, GH4698/Al, GH4698/As, GH4698/B, GH4698/C, GH4698/Ce, GH4698/Cr, GH4698/Fe
pdf__JX-25-0 仅新: 16H/HB@室温, 8H/HB@室温, 保温4H/HB@室温, 元素/C, 元素/Cr, 元素/Mn, 元素/Ni, 元素/P
pdf__gbt1591 仅旧: Q355/KV2@纵向, Q355M/KV2@纵向, Q355MB/CEV, Q355MB/Pcm, Q355MC/CEV, Q355MC/Pcm, Q355MD/CEV, Q355MD/Pcm
pdf__gbt1591 仅新: Q355/A, Q355/KV2, Q355M/KV2, Q355M/Pcm, Q355N/KV2, Q390/A, Q390/KV2, Q390M/KV2
```

## 4. 说明

- 两侧使用同一份表结构：旧 `result.json` 的 tables 重建为 HTML 后输入新系统，OCR/版面识别差异不在本样本内。
- 字段键为 `(牌号, 指标, 条件)`；同一键多值时逐一比较并取最佳匹配。
- 数值比较优先使用解析后的 value（1e-6 容差），缺失时比较归一化 raw。
- 结论用于 Q4 数据导入门禁：达标不导入旧文档；未达标输出差异清单并确认导入范围。
