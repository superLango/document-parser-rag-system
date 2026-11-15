# M8 新旧效果对比报告

> 生成时间：2026-11-12T14:04:43+00:00
> 样本：60 份（旧结果表重建为输入）
> 结论：**未达标**

## 1. 指标

| 指标 | 结果 | 门槛 |
|---|---|---|
| Field F1 | 0.6020 | ≥ 0.80 |
| Value match | 0.9745 | ≥ 0.90 |
| 静默错误率 | 0.0255 | ≤ 0.05 |
| 覆盖率 | 1.0000 | ≥ 0.90 |
| p95 延迟 | 10.30s | ≤ 120.00s |
| 证据命中率 | 1.0000 | 参考 |
| 失败运行 | 0 | 0 |

- 旧字段：2932；新字段：3201；共同字段：1846
- Precision 0.5767 / Recall 0.6296

## 2. 文档明细

| 文档 | 类型 | 旧字段 | 新字段 | 共同 | 值匹配 | F1 | 静默错误 | 耗时(s) | 状态 |
|---|---|---|---|---|---|---|---|---|---|
| 05ecccc8ad8d | chemical | 36 | 34 | 34 | 0.94 | 0.971 | 2 | 10.3 | STRUCTURED_READY |
| 0684efec05a5 | chemical | 15 | 24 | 12 | 1.00 | 0.615 | 0 | 8.2 | STRUCTURED_READY |
| 0715f18cf44c | chemical | 57 | 49 | 41 | 1.00 | 0.774 | 0 | 8.3 | STRUCTURED_READY |
| 075993d8bda5 | chemical | 20 | 16 | 5 | 1.00 | 0.278 | 0 | 8.3 | STRUCTURED_READY |
| 0c87affede6e | mechanical | 45 | 26 | 12 | 0.83 | 0.338 | 2 | 8.3 | STRUCTURED_READY |
| 100e43ba7722 | chemical | 17 | 9 | 0 | 0.00 | 0.000 | 0 | 9.2 | STRUCTURED_READY |
| 10aef59a5c91 | chemical | 16 | 16 | 16 | 1.00 | 1.000 | 0 | 8.2 | STRUCTURED_READY |
| 1738d3d4f8f7 | chemical | 14 | 9 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| 1741e4503e46 | mechanical | 33 | 37 | 26 | 1.00 | 0.743 | 0 | 8.3 | STRUCTURED_READY |
| 1741e4503e46 | mechanical | 33 | 37 | 26 | 1.00 | 0.743 | 0 | 8.3 | STRUCTURED_READY |
| 17d722e0e9d9 | chemical | 20 | 18 | 18 | 1.00 | 0.947 | 0 | 8.3 | STRUCTURED_READY |
| 187d5d3857cc | chemical | 14 | 7 | 0 | 0.00 | 0.000 | 0 | 9.2 | STRUCTURED_READY |
| 1c4cf85c9255 | chemical | 16 | 10 | 0 | 0.00 | 0.000 | 0 | 7.2 | STRUCTURED_READY |
| 208851e12800 | chemical | 16 | 7 | 7 | 1.00 | 0.609 | 0 | 9.2 | STRUCTURED_READY |
| 22b1476b150e | chemical | 14 | 9 | 9 | 1.00 | 0.783 | 0 | 8.2 | STRUCTURED_READY |
| 27c4e67d00ff | chemical | 34 | 27 | 14 | 0.93 | 0.459 | 1 | 9.3 | STRUCTURED_READY |
| 2ad6ce310e68 | chemical | 16 | 12 | 10 | 0.90 | 0.714 | 1 | 8.2 | STRUCTURED_READY |
| 2af08cbfcabe | chemical | 17 | 10 | 0 | 0.00 | 0.000 | 0 | 9.2 | STRUCTURED_READY |
| 3081c0f9b98d | chemical | 16 | 13 | 13 | 1.00 | 0.897 | 0 | 8.2 | STRUCTURED_READY |
| 4417071b32c1 | chemical | 81 | 82 | 81 | 0.91 | 0.994 | 7 | 8.3 | STRUCTURED_READY |
| 521854804389 | chemical | 16 | 16 | 16 | 1.00 | 1.000 | 0 | 8.2 | STRUCTURED_READY |
| 564ae4f40b9a | chemical | 67 | 93 | 62 | 1.00 | 0.775 | 0 | 8.2 | STRUCTURED_READY |
| 59bebdcf7e10 | chemical | 19 | 11 | 11 | 1.00 | 0.733 | 0 | 9.3 | STRUCTURED_READY |
| 5c7ee8be97c4 | chemical | 154 | 356 | 58 | 1.00 | 0.228 | 0 | 10.3 | STRUCTURED_READY |
| 608333b8e2df | mechanical | 10 | 8 | 8 | 1.00 | 0.889 | 0 | 8.3 | STRUCTURED_READY |
| 65c7cfb83be7 | chemical | 162 | 178 | 143 | 0.97 | 0.841 | 4 | 10.3 | STRUCTURED_READY |
| 67a742b20c66 | chemical | 18 | 12 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| 6db6bab71842 | chemical | 15 | 23 | 4 | 1.00 | 0.210 | 0 | 8.2 | STRUCTURED_READY |
| 7069f774d8d4 | chemical | 24 | 22 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| 728e72b0f2e6 | chemical | 16 | 7 | 7 | 1.00 | 0.609 | 0 | 8.2 | STRUCTURED_READY |
| 7319bf3dde60 | chemical | 30 | 26 | 24 | 0.83 | 0.857 | 4 | 8.3 | STRUCTURED_READY |
| 7373a8d9a442 | chemical | 32 | 58 | 0 | 0.00 | 0.000 | 0 | 8.3 | STRUCTURED_READY |
| 74aec6bf7405 | chemical | 16 | 7 | 7 | 1.00 | 0.609 | 0 | 8.2 | STRUCTURED_READY |
| 754a537ea3f9 | mechanical | 38 | 63 | 27 | 1.00 | 0.535 | 0 | 9.3 | STRUCTURED_READY |
| 775043b53873 | chemical | 22 | 19 | 18 | 1.00 | 0.878 | 0 | 8.3 | STRUCTURED_READY |
| 78a0de4c51a2 | mechanical | 122 | 131 | 122 | 1.00 | 0.964 | 0 | 9.3 | STRUCTURED_READY |
| 7ad79a9408c9 | chemical | 37 | 42 | 21 | 1.00 | 0.532 | 0 | 8.2 | STRUCTURED_READY |
| 92e35be4e585 | chemical | 16 | 32 | 16 | 1.00 | 0.667 | 0 | 9.3 | STRUCTURED_READY |
| 9d1ae7d941e0 | chemical | 44 | 26 | 4 | 1.00 | 0.114 | 0 | 8.2 | STRUCTURED_READY |
| a5fbc645696b | chemical | 20 | 7 | 3 | 1.00 | 0.222 | 0 | 8.3 | STRUCTURED_READY |
| a671647676ee | other | 24 | 165 | 12 | 1.00 | 0.127 | 0 | 8.3 | STRUCTURED_READY |
| ae7a1887a2e0 | chemical | 22 | 6 | 0 | 0.00 | 0.000 | 0 | 8.3 | STRUCTURED_READY |
| b50805e0ab63 | chemical | 18 | 6 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| b8c365836b9c | chemical | 24 | 12 | 4 | 1.00 | 0.222 | 0 | 8.2 | STRUCTURED_READY |
| bc0fd7f758e5 | chemical | 17 | 11 | 0 | 0.00 | 0.000 | 0 | 9.3 | STRUCTURED_READY |
| bc6e766f5cb7 | chemical | 18 | 10 | 0 | 0.00 | 0.000 | 0 | 8.2 | STRUCTURED_READY |
| be26fecfa3a0 | chemical | 18 | 18 | 0 | 0.00 | 0.000 | 0 | 8.3 | STRUCTURED_READY |
| bf295b3df1a7 | chemical | 17 | 19 | 9 | 0.00 | 0.500 | 9 | 9.3 | STRUCTURED_READY |
| cdbfe0b1485a | chemical | 16 | 16 | 16 | 1.00 | 1.000 | 0 | 7.2 | STRUCTURED_READY |
| d26323581f40 | mechanical | 80 | 150 | 48 | 0.67 | 0.417 | 16 | 10.3 | STRUCTURED_READY |
| da33e8657541 | chemical | 16 | 11 | 11 | 0.91 | 0.815 | 1 | 8.2 | STRUCTURED_READY |
| da6e78317ae0 | chemical | 232 | 304 | 152 | 1.00 | 0.567 | 0 | 9.3 | STRUCTURED_READY |
| de2adf26e9dd | chemical | 45 | 43 | 43 | 1.00 | 0.977 | 0 | 8.3 | STRUCTURED_READY |
| de301f981df7 | mechanical | 19 | 9 | 9 | 1.00 | 0.643 | 0 | 8.3 | STRUCTURED_READY |
| e0ac84b49ef6 | chemical | 16 | 17 | 16 | 1.00 | 0.970 | 0 | 8.2 | STRUCTURED_READY |
| ec684db9f609 | chemical | 17 | 6 | 0 | 0.00 | 0.000 | 0 | 9.2 | STRUCTURED_READY |
| fc367075184b | chemical | 23 | 19 | 0 | 0.00 | 0.000 | 0 | 7.2 | STRUCTURED_READY |
| pdf__GBT3308 | chemical | 812 | 735 | 651 | 1.00 | 0.842 | 0 | 9.3 | STRUCTURED_READY |
| pdf__JX-25-0 | chemical | 25 | 26 | 0 | 0.00 | 0.000 | 0 | 8.3 | STRUCTURED_READY |
| pdf__gbt1591 | other | 65 | 29 | 0 | 0.00 | 0.000 | 0 | 8.3 | STRUCTURED_READY |

## 3. 差异样例

```text
05ecccc8ad8d 仅旧: ~/B, ~/C
05ecccc8ad8d 仅新: 
0684efec05a5 仅旧: ~/RM, ~/RP0.2, ~/Z
0684efec05a5 仅新: 101.60~152.40/A, 101.60~152.40/RM, 101.60~152.40/ReH, 101.60~152.40/Z, 50.80/A, 50.80/RM, 50.80/ReH, 50.80/Z
0715f18cf44c 仅旧: 30CR3SINIMOVA/A, 30CR3SINIMOVA/B, 30CR3SINIMOVA/KIC@淬火, 30CR3SINIMOVA/KV2@淬火, 30SI2MNCRMOVE/KV2, 30SI2MNCRMOVE31SI2MNCRMOVE/B, 30SI2MNCRMOVE31SI2MNCRMOVE/C, 30SI2MNCRMOVEA/KIC@淬火
0715f18cf44c 仅新: 30CR3SINIMOVA/HB@退火, 30CR3SINIMOVA/KU2@淬火, 30SI2MNCRMOVE/HB@退火, 30SI2MNCRMOVE/HB@高温, 30SI2MNCRMOVEA/KU2@淬火, 31SI2MNCRMOVE/HB@退火, 31SI2MNCRMOVE/HB@高温, 31SI2MNCRMOVEA/KU2@淬火
075993d8bda5 仅旧: 650/A, 650/HB, 650/RM, 650/RP0.2, 650/Z, 化学成分/Al, 化学成分/C, 化学成分/Co
075993d8bda5 仅新: 元素/Al, 含量%/Al, 含量%/C, 含量%/Co, 含量%/Cr, 含量%/Fe, 含量%/Mo, 含量%/Nb
0c87affede6e 仅旧: 250/A, 250/RM, 250/RP0.2, 250/Z, 500/A, 500/HB, 500/KV2, 500/RM
0c87affede6e 仅新: 基/Al, 基/C, 基/Fe, 基/H, 基/Mo, 基/N, 基/O, 基/Si
100e43ba7722 仅旧: SS316L/A, SS316L/B, SS316L/C, SS316L/Co, SS316L/Cr, SS316L/Cu, SS316L/Mn, SS316L/Mo
100e43ba7722 仅新: 元素/Mo, 含量/C, 含量/Cr, 含量/Mn, 含量/Mo, 含量/Ni, 含量/P, 含量/S
10aef59a5c91 仅旧: 
10aef59a5c91 仅新: 
1738d3d4f8f7 仅旧: 1738/A, 1738/Al, 1738/C, 1738/H, 1738/Mo, 1738/N, 1738/O, 1738/RM
1738d3d4f8f7 仅新: 基/Al, 基/C, 基/H, 基/Mo, 基/N, 基/O, 基/Si, 基/Sn
1741e4503e46 仅旧: 25CR2MOVA/KV2@切向, 25CR2MOVA/KV2@纵向, 40CRNIMOA/KV2@切向, 40CRNIMOA/KV2@纵向, ~/Cu, ~/Mo, ~/V
1741e4503e46 仅新: 25CR2MOVA/C, 25CR2MOVA/Cr, 25CR2MOVA/Cu, 25CR2MOVA/KU2@纵向, 25CR2MOVA/Mn, 25CR2MOVA/Mo, 25CR2MOVA/Ni, 25CR2MOVA/P
1741e4503e46 仅旧: 25CR2MOVA/KV2@切向, 25CR2MOVA/KV2@纵向, 40CRNIMOA/KV2@切向, 40CRNIMOA/KV2@纵向, ~/Cu, ~/Mo, ~/V
1741e4503e46 仅新: 25CR2MOVA/C, 25CR2MOVA/Cr, 25CR2MOVA/Cu, 25CR2MOVA/KU2@纵向, 25CR2MOVA/Mn, 25CR2MOVA/Mo, 25CR2MOVA/Ni, 25CR2MOVA/P
17d722e0e9d9 仅旧: ~/B, ~/C
17d722e0e9d9 仅新: 
187d5d3857cc 仅旧: 成品分析/C, 成品分析/Cr, 成品分析/Mn, 成品分析/Ni, 成品分析/P, 成品分析/S, 成品分析/Si, 熔炼分析/C
187d5d3857cc 仅新: ~/C, ~/Cr, ~/Mn, ~/Ni, ~/P, ~/S, ~/Si
1c4cf85c9255 仅旧: TA15/A, TA15/Al, TA15/C, TA15/Fe, TA15/H, TA15/HB, TA15/KV2, TA15/Mo
1c4cf85c9255 仅新: 基/Al, 基/C, 基/Fe, 基/H, 基/Mo, 基/N, 基/O, 基/Si
208851e12800 仅旧: 化学成分/C, 化学成分/Cr, 化学成分/Mn, 化学成分/Si, 淬火温度880℃~900℃，油冷，回火温度510℃~570℃，油冷/室温/A@室温, 淬火温度880℃~900℃，油冷，回火温度510℃~570℃，油冷/室温/KV2@室温, 淬火温度880℃~900℃，油冷，回火温度510℃~570℃，油冷/室温/RM@室温, 淬火温度880℃~900℃，油冷，回火温度510℃~570℃，油冷/室温/RP0.2@室温
208851e12800 仅新: 
22b1476b150e 仅旧: 1476/A, 1476/KV2, 1476/RM, 1476/ReH, 1476/Z
22b1476b150e 仅新: 
27c4e67d00ff 仅旧: GH4169D/A, GH4169D/A@室温, GH4169D/HB@室温, GH4169D/RM, GH4169D/RM@室温, GH4169D/RP0.2, GH4169D/RP0.2@室温, GH4169D/Z
27c4e67d00ff 仅新: 公差/C, 公差/H, 尺寸，mm/C, 尺寸，mm/H, 弦向/A, 弦向/A@室温, 弦向/HB@室温, 弦向/RM
2ad6ce310e68 仅旧: 淬火830~860℃，油冷回火550~680℃，空冷/A@淬火, 淬火830~860℃，油冷回火550~680℃，空冷/KV2@淬火, 淬火830~860℃，油冷回火550~680℃，空冷/RM@淬火, 淬火830~860℃，油冷回火550~680℃，空冷/RP0.2@淬火, 淬火830~860℃，油冷回火550~680℃，空冷/Z@淬火, 热处理方式：正火温度870±20℃，淬火温度850±10℃/HRC
2ad6ce310e68 仅新: ≤2.5级/B, ≤2.5级/C
2af08cbfcabe 仅旧: wt%/化学成分/C, wt%/化学成分/Co, wt%/化学成分/Cr, wt%/化学成分/Cu, wt%/化学成分/Fe, wt%/化学成分/Mn, wt%/化学成分/Mo, wt%/化学成分/Ni
2af08cbfcabe 仅新: 含量/Cr, 含量/Cu, 含量/Fe, 含量/Mo, 含量/Ni, 含量/Ti, 固溶处理/A@室温, 固溶处理/KU2@室温
3081c0f9b98d 仅旧: 200℃/A, 200℃/RM, 200℃/RP0.2
3081c0f9b98d 仅新: 
4417071b32c1 仅旧: 
4417071b32c1 仅新: 06CR18NI11TI/KV2
521854804389 仅旧: 
521854804389 仅新: 
564ae4f40b9a 仅旧: 022CR17NI12MO2/Cr, 08CR18NI11T/KV2, 08CR18NI11T/KV2@纵向, 08CR18NI12MO2T/KV2, 08CR18NI12MO2T/KV2@纵向
564ae4f40b9a 仅新: 022CR17NI12MO2/A, 022CR17NI12MO2/RM, 022CR17NI12MO2/RP0.2, 022CR19NI10/A, 022CR19NI10/RM, 022CR19NI10/RP0.2, 026CR18NI12MO2N/A, 026CR18NI12MO2N/RM
59bebdcf7e10 仅旧: A105NTEXTCIRCLED3/A, A105NTEXTCIRCLED3/RM, A105NTEXTCIRCLED3/RP0.2, A105NTEXTCIRCLED3/Z, 化学成份/A, 化学成份/RM, 机械性能/A, 机械性能/RM
59bebdcf7e10 仅新: 
5c7ee8be97c4 仅旧: 07CR18NI11NB/HRC, 07CR19NI11TI/HRC, 07CR22NI25W3CU3CO2MONBN/HRC, 07CR23NI15CU4NBN/HRC, 07CR25NI21/HRC, 07CR25NI21NBN/HRC, 07CR2MOW2VNBB/KV2@纵向, 08CR18NI11NBFG/HRC
5c7ee8be97c4 仅新: 07CR18NI11NB/C, 07CR18NI11NB/Cr, 07CR18NI11NB/Mn, 07CR18NI11NB/Nb, 07CR18NI11NB/Ni, 07CR18NI11NB/P, 07CR18NI11NB/S, 07CR18NI11NB/Si
608333b8e2df 仅旧: 6061/KV2, 6061/KV2@纵向
608333b8e2df 仅新: 
65c7cfb83be7 仅旧: 0℃/-/A, 0℃/E, 350℃/rp0.2/mpa/A, a.对于1级和2级棒材，也可以为a%>=12，且z>=45%。b.所列规定值为单个最小值。/E@最小, a仅对1级棒材。b仅对2、3级棒材。c仅对以固溶状态交货的棒材。d所列规定值为单个最小值。/A@最小, a所列规定值为单个最小值。/E@最小, ~/C, ~/Cr
65c7cfb83be7 仅新: 150C/C, 150C/Cr, 150C/Mn, 150C/Mo, 150C/P, 150C/S, 150C/Si, 150C/V
67a742b20c66 仅旧: 750/A, 750/RP0.2, 750/Z, 800/A, 800/RP0.2, 800/Z, ~/Al, ~/C
67a742b20c66 仅新: al/Te, co/Te, cr/Sb, cr/Te, mo/Te, nb/Te, ti/Te, v/Te
6db6bab71842 仅旧: 化学成分/Al, 化学成分/C, 化学成分/Fe, 化学成分/H, 化学成分/Mo, 化学成分/N, 化学成分/O, 化学成分/Si
6db6bab71842 仅新: 余量/Al, 余量/C, 余量/Fe, 余量/H, 余量/Mo, 余量/N, 余量/O, 余量/Si
7069f774d8d4 仅旧: ~/B, ~/C, 元素含量 WT.% 最大/B, 元素含量 WT.% 最大/C, 元素含量 WT.% 最大/Cr, 元素含量 WT.% 最大/Cu, 元素含量 WT.% 最大/Mn, 元素含量 WT.% 最大/Mo
7069f774d8d4 仅新: 元素含量wt.%最大/B@最大, 元素含量wt.%最大/C@最大, 元素含量wt.%最大/Cr@最大, 元素含量wt.%最大/Cu@最大, 元素含量wt.%最大/Mn@最大, 元素含量wt.%最大/Mo@最大, 元素含量wt.%最大/N@最大, 元素含量wt.%最大/Ni@最大
728e72b0f2e6 仅旧: 0974/A@室温, 0974/C, 0974/Cr, 0974/KV2@室温, 0974/Mn, 0974/RM@室温, 0974/RP0.2@室温, 0974/Si
728e72b0f2e6 仅新: 
7319bf3dde60 仅旧: ~/B, ~/C, 成品分析/Al, 成品分析/N, 熔炼分析/Al, 熔炼分析/N
7319bf3dde60 仅新: 成品分析/Na, 熔炼分析/Na
7373a8d9a442 仅旧: 元素含量，WT.% MAX/B, 元素含量，WT.% MAX/Cr, 元素含量，WT.% MAX/Cu, 元素含量，WT.% MAX/Mn, 元素含量，WT.% MAX/Mo, 元素含量，WT.% MAX/Ni, 元素含量，WT.% MAX/W, 元素含量，WT.% MIN/B
7373a8d9a442 仅新: 0/C, 0/Co, 0/N, 0/Nb, 0/P, 0/S, 0/Ta, 0/Ti
74aec6bf7405 仅旧: 4782/A@室温, 4782/C, 4782/Cr, 4782/KV2@室温, 4782/Mn, 4782/RM@室温, 4782/RP0.2@室温, 4782/Si
74aec6bf7405 仅新: 
754a537ea3f9 仅旧: 18CR2NI4WA/KU2, 25CR2MOVA/KV2@切向, 25CR2MOVA/KV2@纵向, 40CRNIMOA/KV2@切向, 40CRNIMOA/KV2@纵向, ~/B, ~/Cu, ~/Mo
754a537ea3f9 仅新: 18CR2NI4WA/A@切向, 18CR2NI4WA/A@纵向, 18CR2NI4WA/C, 18CR2NI4WA/Cr, 18CR2NI4WA/Cu, 18CR2NI4WA/HB@切向, 18CR2NI4WA/HB@纵向, 18CR2NI4WA/KU2@切向
775043b53873 仅旧: ~/B, ~/C, 成品分析/H, 熔炼分析/H
775043b53873 仅新: 室温/HB
78a0de4c51a2 仅旧: 
78a0de4c51a2 仅新: TA6/持久应力, TA7/持久应力, TC1/持久应力, TC10/持久应力, TC12/持久应力, TC2/持久应力, TC4/持久应力, TC6/持久应力
7ad79a9408c9 仅旧: 18MNCRNIM/KV2, 18MNCRNIMO(W)*/C, 18MNCRNIMO(W)*/Ce, 18MNCRNIMO(W)*/Cr, 18MNCRNIMO(W)*/Cu, 18MNCRNIMO(W)*/Mn, 18MNCRNIMO(W)*/Mo, 18MNCRNIMO(W)*/Ni
7ad79a9408c9 仅新: 18MNCRNIMO(W)/C, 18MNCRNIMO(W)/Cr, 18MNCRNIMO(W)/Cu, 18MNCRNIMO(W)/Mn, 18MNCRNIMO(W)/Mo, 18MNCRNIMO(W)/Ni, 18MNCRNIMO(W)/P, 18MNCRNIMO(W)/S
92e35be4e585 仅旧: 
92e35be4e585 仅新: col2/B, col2/C, col2/RE, col3/B, col3/C, col3/RE, col4/B, col4/C
9d1ae7d941e0 仅旧: 350/A, 350/RM, 350/RP0.2, 350/Z, 450/A, 450/RM, 450/RP0.2, 450/Z
9d1ae7d941e0 仅新: 成品分析/B, 成品分析/C, 成品分析/Cr, 成品分析/Cu, 成品分析/Mn, 成品分析/Mo, 成品分析/Ni, 成品分析/P
a5fbc645696b 仅旧: 750/Z, 化学成分/Al, 化学成分/C, 化学成分/Fe, 化学成分/H, 化学成分/Mo, 化学成分/N, 化学成分/Nb
a5fbc645696b 仅新: 室温/A, 室温/RM, 室温/RP0.2, 室温/Z
a671647676ee 仅旧: ~/A, ~/B, ~/C, ~/Mn, ~/Nb, ~/P, ~/RM, ~/RP0.2
a671647676ee 仅新: L245MH/BMH/A, L245MH/BMH/C, L245MH/BMH/Mn, L245MH/BMH/Nb, L245MH/BMH/P, L245MH/BMH/REL, L245MH/BMH/RM, L245MH/BMH/ReH
ae7a1887a2e0 仅旧: BEST项目屏蔽块用316L(N)不锈钢锻件委外技术协议/RM, 会审/日期：齐远2026.07.15/RM, 化学成分/B, 化学成分/C, 化学成分/Co, 化学成分/Cr, 化学成分/Cu, 化学成分/Fe
ae7a1887a2e0 仅新: 标准/C, 标准/Cr, 标准/Mn, 标准/Mo, 标准/Ni, 标准/Si
b50805e0ab63 仅旧: 3658/A, 3658/C, 3658/Co, 3658/Cr, 3658/Cu, 3658/Fe, 3658/Mn, 3658/Mo
b50805e0ab63 仅新: 含量,%/C, 含量,%/Cr, 含量,%/Mn, 含量,%/P, 含量,%/S, 含量,%/Si
b8c365836b9c 仅旧: 800/A, 800/RM, 800/Z, B 不大于/B, C 不大于/B, CE 不大于/B, COL9/B, FE 不大于/B
b8c365836b9c 仅新: 含量,%/Al, 含量,%/Cr, 含量,%/Mo, 含量,%/Nb, 含量,%/Ni, 含量,%/Ti, 含量,%/W, 室温/KU2
bc0fd7f758e5 仅旧: 750/650/A, 750/650/RM, 750/650/RP0.2, 750/650/Z, 800/650/A, 800/650/RM, 800/650/RP0.2, 800/650/Z
bc0fd7f758e5 仅新: 750/A, 750/RM, 750/RP0.2, 750/Z, 800/A, 800/RM, 800/RP0.2, 800/Z
bc6e766f5cb7 仅旧: ~/A, ~/RM, 化学成分/Al, 化学成分/B, 化学成分/C, 化学成分/Ce, 化学成分/Co, 化学成分/Cr
bc6e766f5cb7 仅新: RT/A, RT/RM, 含量/Al, 含量/C, 含量/Co, 含量/Cr, 含量/Mo, 含量/Ni
be26fecfa3a0 仅旧: 0486/A, 0486/Al, 0486/C, 0486/Fe, 0486/H, 0486/HB, 0486/KV2, 0486/Mo
be26fecfa3a0 仅新: 20/A, 20/RM, 20/Z, 500/RM, 500/持久时间, 550/A, 550/RM, 550/Z
bf295b3df1a7 仅旧: ~/Al, ~/B, ~/Cu, ~/Fe, ~/HB, ~/Ni, ~/RM, ~/Ti
bf295b3df1a7 仅新: max/Al, max/B, max/Cu, max/Fe, max/Ni, max/Ti, min/Al, min/B
cdbfe0b1485a 仅旧: 
cdbfe0b1485a 仅新: 
d26323581f40 仅旧: -/A, -/HB, -/RM, -/ReH, -/Z, 17CRNIMO6/KV2, 20CR2NI418CR2NI4WA/KV2, 20CRMNMO12CRNI320CRNI2MO/KV2
d26323581f40 仅新: 1000/A, 1000/HB, 1000/KU2, 1000/RM, 1000/ReH, 1000/Z, 1050/A, 1050/HB
da33e8657541 仅旧: <=-60℃/A, <=-60℃/HB, <=-60℃/KV2, <=-60℃/RM, <=-60℃/RP0.2
da33e8657541 仅新: 
da6e78317ae0 仅旧: GH1016A/B, GH1016A/Ce, GH1016A/Nb, GH1016A/V, GH1140/Al, GH1140/Ce, GH1140/Ti, GH2036/Nb
da6e78317ae0 仅新: GH1016A/A, GH1016A/A@室温, GH1016A/HB, GH1016A/HB@室温, GH1016A/RM, GH1016A/RM@室温, GH1016A/Z, GH1016A/Z@室温
de2adf26e9dd 仅旧: 1J22/B, TU2/Cu
de2adf26e9dd 仅新: 
de301f981df7 仅旧: ~/A, ~/HB, ~/KV2, ~/RM, ~/RP0.2, 淬火：990~1010℃油冷回火：>=700℃空冷/A@淬火, 淬火：990~1010℃油冷回火：>=700℃空冷/HB@淬火, 淬火：990~1010℃油冷回火：>=700℃空冷/KV2@淬火
de301f981df7 仅新: 
e0ac84b49ef6 仅旧: 
e0ac84b49ef6 仅新: 室温/HB
ec684db9f609 仅旧: wt%/化学成分/Al, wt%/化学成分/B, wt%/化学成分/C, wt%/化学成分/Co, wt%/化学成分/Cr, wt%/化学成分/Cu, wt%/化学成分/Fe, wt%/化学成分/Mn
ec684db9f609 仅新: 含量/C, 含量/Cr, 含量/Mo, 含量/Ni, 含量/Ti, 含量/W
fc367075184b 仅旧: wt%/化学成分/Al, wt%/化学成分/As, wt%/化学成分/B, wt%/化学成分/Bi, wt%/化学成分/C, wt%/化学成分/Ca, wt%/化学成分/Cr, wt%/化学成分/Cu
fc367075184b 仅新: 元素/P, 内控/C, 内控/Cr, 内控/Mn, 内控/Mo, 内控/Ni, 内控/P, 内控/S
pdf__GBT3308 仅旧: 12CR1MOV/KV2, 12CRM/KU2, 12CRMO/KV2@回火, 12CRMOV/KV2, 15C/KU2, 15CR/KV2@回火, 15CRNIMOV/KV2, 18CR2NI4W/KV2@淬火
pdf__GBT3308 仅新: 12CR1MOV/RP0.2, 12CRMO/KU2@回火, 12CRMO/RP0.2@回火, 12CRMOV/RP0.2, 15CR/KU2@回火, 15CR/RP0.2@回火, 15CR2NI2/RP0.2@淬火, 15CRMO/RP0.2
pdf__JX-25-0 仅旧: GH4698/A@室温, GH4698/Al, GH4698/As, GH4698/B, GH4698/C, GH4698/Ce, GH4698/Cr, GH4698/Fe
pdf__JX-25-0 仅新: 16H/A@室温, 16H/HB@室温, 16H/KU5@室温, 16H/RM@室温, 16H/RP0.2@室温, 16H/Z@室温, 8H/A@室温, 8H/HB@室温
pdf__gbt1591 仅旧: Q355/KV2@纵向, Q355M/KV2@纵向, Q355MB/CEV, Q355MB/Pcm, Q355MC/CEV, Q355MC/Pcm, Q355MD/CEV, Q355MD/Pcm
pdf__gbt1591 仅新: Q355/A, Q355/KV2, Q355M/CEV, Q355M/KV2, Q355M/Pcm, Q355N/KV2, Q390/A, Q390/KV2
```

## 4. 说明

- 两侧使用同一份表结构：旧 `result.json` 的 tables 重建为 HTML 后输入新系统，OCR/版面识别差异不在本样本内。
- 字段键为 `(牌号, 指标, 条件)`；同一键多值时逐一比较并取最佳匹配。
- 数值比较优先使用解析后的 value（1e-6 容差），缺失时比较归一化 raw。
- 结论用于 Q4 数据导入门禁：达标不导入旧文档；未达标输出差异清单并确认导入范围。
