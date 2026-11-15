# 标准文件解析结果与原文核对

> 生成时间：2026-11-12T03:50:50+00:00
> 样本：30 份标准文件

## 1. 汇总

| 指标 | 结果 |
|---|---|
| 结构化成功 | 0/30 |
| 记录数 | 2922 |
| 字段数 | 11901 |
| 原文数据行 | 1904 |
| 零记录文档 | 0 |
| 有表但零记录 | 0 |
| 可文本回查文档 | 27/30 |
| 不可核对字段 | 7459 |
| 牌号在原文命中率 | 73.52% |
| 字段值在原文命中率 | 95.41% |
| 单位存在率 | 98.13% |
| 超合理区间值 | 60 |
| 空记录率 | 0.07% |
| 重复键记录 | 0 |
| 同键多条件 | 555 |

## 1.1 分类别

| 类别 | 文档 | 记录 | 字段 | 零记录 | 有表未解析 |
|---|---|---|---|---|---|
| gold | 30 | 2922 | 11901 | 0 | 0 |

## 2. 文档明细

| 文档 | 类别 | 状态 | 页 | 数据行 | 记录 | 字段 | 牌号命中 | 值命中 | 重复键 |
|---|---|---|---|---|---|---|---|---|---|
| gbt-1591-2018 | gold | HUMAN_REVIEW | 22 | 53 | 115 | 767 | 66% | 45% | 0 |
| gbt-14976-2025 | gold | HUMAN_REVIEW | 31 | 112 | 63 | 408 | 100% | 11% | 0 |
| gbt-3621-2022 | gold | HUMAN_REVIEW | 19 | 0 | 160 | 317 | 0% | 0% | 0 |
| gbt-3623-2022 | gold | HUMAN_REVIEW | 9 | 18 | 32 | 263 | 91% | 86% | 0 |
| gbt-3280-2015 | gold | HUMAN_REVIEW | 48 | 192 | 299 | 1559 | 100% | 41% | 0 |
| gbt-3880-2-2024 | gold | HUMAN_REVIEW | 43 | 1311 | 941 | 3037 | 0% | 0% | 0 |
| gbt-5231-2022 | gold | HUMAN_REVIEW | 30 | 0 | 344 | 2206 | 0% | 0% | 0 |
| gjb-5040-2001 | gold | HUMAN_REVIEW | 22 | 99 | 197 | 554 | 64% | 99% | 0 |
| hb-20079-2012 | gold | HUMAN_REVIEW | 14 | 50 | 42 | 161 | 21% | 96% | 0 |
| iso-5832-3-2021 | gold | HUMAN_REVIEW | 16 | 18 | 22 | 60 | 59% | 100% | 0 |
| ams-qq-a250-4b | gold | HUMAN_REVIEW | 7 | 2 | 37 | 110 | 100% | 95% | 0 |
| ams-4050k | gold | HUMAN_REVIEW | 8 | 0 | 53 | 143 | 4% | 97% | 0 |
| ams-4108g | gold | HUMAN_REVIEW | 8 | 0 | 45 | 132 | 4% | 97% | 0 |
| ams-4911s | gold | HUMAN_REVIEW | 8 | 0 | 14 | 36 | 7% | 94% | 0 |
| gbt-6516-2025 | gold | HUMAN_REVIEW | 11 | 18 | 6 | 92 | 100% | 100% | 0 |
| ams-4967n | gold | HUMAN_REVIEW | 9 | 0 | 51 | 161 | 4% | 94% | 0 |
| ams-5663p | gold | HUMAN_REVIEW | 10 | 0 | 24 | 105 | 4% | 95% | 0 |
| astm-b861-14 | gold | HUMAN_REVIEW | 9 | 1 | 76 | 221 | 100% | 90% | 0 |
| astm-b861-24 | gold | HUMAN_REVIEW | 9 | 0 | 76 | 229 | 100% | 90% | 0 |
| astm-b348-13 | gold | HUMAN_REVIEW | 8 | 0 | 54 | 375 | 100% | 33% | 0 |
| astm-b708-25 | gold | HUMAN_REVIEW | 8 | 0 | 20 | 221 | 0% | 98% | 0 |
| astm-f136-26 | gold | HUMAN_REVIEW | 7 | 0 | 16 | 30 | 50% | 100% | 0 |
| astm-b338-17 | gold | HUMAN_REVIEW | 10 | 0 | 51 | 123 | 100% | 99% | 0 |
| asme-sb265-2025 | gold | HUMAN_REVIEW | 13 | 0 | 13 | 62 | 100% | 100% | 0 |
| asme-sb338-2021 | gold | HUMAN_REVIEW | 10 | 0 | 51 | 124 | 100% | 98% | 0 |
| asme-sb575-2023 | gold | HUMAN_REVIEW | 5 | 0 | 22 | 102 | 100% | 84% | 0 |
| iso-5832-2-2018 | gold | HUMAN_REVIEW | 10 | 10 | 17 | 53 | 100% | 100% | 0 |
| astm-b862-23 | gold | HUMAN_REVIEW | 10 | 0 | 69 | 207 | 100% | 99% | 0 |
| gbt-14845-2026 | gold | HUMAN_REVIEW | 11 | 18 | 9 | 30 | 100% | 100% | 0 |
| gbt-24627-2023 | gold | HUMAN_REVIEW | 15 | 2 | 3 | 13 | 0% | 100% | 0 |

## 3. 问题样本

### gbt-1591-2018

| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |
|---|---|---|---|---|---|
| 10 | Q420NB | KV2 | 34 | ocr_or_normalization | 表３　正火、正火轧制钢的牌号及化学成分 牌号 化学成分（质量分数）／％ 钢级 质量 等级 Ｃ Ｓｉ 不大于 Ｍｎ Ｐａ Ｓａ 不大于 Ｎｂ Ｖ Ｔｉｃ Ｃｒ Ｎｉ Ｃｕ Ｍｏ Ｎ 不大于 Ａｌｓｄ 不 |

### gbt-14976-2025

| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |
|---|---|---|---|---|---|
| 9 | 12Cr18Ni9 | 冷却介质 | 水冷、快冷 | non_numeric_value | d) 尺寸规格; e) 订购的数量(总重量或总长度或支数); f) 交货状态; g) 特殊要求。 6 制造工艺 6. 1 钢的冶炼方法 钢应采用电弧炉加炉外精炼或转炉加炉外精炼方法冶炼,或电渣重熔法冶 |
| 9 | 022Cr19Ni10 | 冷却介质 | 水冷、快冷 | non_numeric_value | d) 尺寸规格; e) 订购的数量(总重量或总长度或支数); f) 交货状态; g) 特殊要求。 6 制造工艺 6. 1 钢的冶炼方法 钢应采用电弧炉加炉外精炼或转炉加炉外精炼方法冶炼,或电渣重熔法冶 |
| 9 | 06Cr19Ni10 | 冷却介质 | 水冷、快冷 | non_numeric_value | d) 尺寸规格; e) 订购的数量(总重量或总长度或支数); f) 交货状态; g) 特殊要求。 6 制造工艺 6. 1 钢的冶炼方法 钢应采用电弧炉加炉外精炼或转炉加炉外精炼方法冶炼,或电渣重熔法冶 |
| 9 | 07Cr19Ni10 | 冷却介质 | 水冷、快冷 | non_numeric_value | d) 尺寸规格; e) 订购的数量(总重量或总长度或支数); f) 交货状态; g) 特殊要求。 6 制造工艺 6. 1 钢的冶炼方法 钢应采用电弧炉加炉外精炼或转炉加炉外精炼方法冶炼,或电渣重熔法冶 |
| 9 | 022Cr19Ni10N | 冷却介质 | 水冷、快冷 | non_numeric_value | d) 尺寸规格; e) 订购的数量(总重量或总长度或支数); f) 交货状态; g) 特殊要求。 6 制造工艺 6. 1 钢的冶炼方法 钢应采用电弧炉加炉外精炼或转炉加炉外精炼方法冶炼,或电渣重熔法冶 |
| 9 | 06Cr19Ni10N | 冷却介质 | 水冷、快冷 | non_numeric_value | d) 尺寸规格; e) 订购的数量(总重量或总长度或支数); f) 交货状态; g) 特殊要求。 6 制造工艺 6. 1 钢的冶炼方法 钢应采用电弧炉加炉外精炼或转炉加炉外精炼方法冶炼,或电渣重熔法冶 |

### gbt-3623-2022

| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |
|---|---|---|---|---|---|
| 4 | TA0 | A | ≥20 | range_or_limit_format | 热加工态、直径为4.5mm的丝材,标记为:丝ta1r4.5mmgb/t3623—××××5技术要求5.1化学成分5.1.1结构件丝的化学成分应符合gb/t3620.1中相应牌号的规定;焊丝的化学成分 |
| 4 | TA0 | Rm | ≥280 | range_or_limit_format | 表１　牌号、状态和规格 牌号 状态 直径 ｍｍ ＴＡ０、ＴＡ１、ＴＡ２、ＴＡ３、ＴＡ１ＧＥＬＩ、ＴＡ１Ｇ、ＴＡ２ＧＥＬＩ、ＴＡ２Ｇ、ＴＡ３ＧＥＬＩ、ＴＡ３Ｇ、 ＴＡ４ＧＥＬＩ、ＴＡ４Ｇ、ＴＡ７、ＴＡ８ |
| 4 | TA0 | Rp0.2 | ≥170 | range_or_limit_format | 表１　牌号、状态和规格 牌号 状态 直径 ｍｍ ＴＡ０、ＴＡ１、ＴＡ２、ＴＡ３、ＴＡ１ＧＥＬＩ、ＴＡ１Ｇ、ＴＡ２ＧＥＬＩ、ＴＡ２Ｇ、ＴＡ３ＧＥＬＩ、ＴＡ３Ｇ、 ＴＡ４ＧＥＬＩ、ＴＡ４Ｇ、ＴＡ７、ＴＡ８ |
| 4 | TA1 | Rm | ≥370 | range_or_limit_format | 表１　牌号、状态和规格 牌号 状态 直径 ｍｍ ＴＡ０、ＴＡ１、ＴＡ２、ＴＡ３、ＴＡ１ＧＥＬＩ、ＴＡ１Ｇ、ＴＡ２ＧＥＬＩ、ＴＡ２Ｇ、ＴＡ３ＧＥＬＩ、ＴＡ３Ｇ、 ＴＡ４ＧＥＬＩ、ＴＡ４Ｇ、ＴＡ７、ＴＡ８ |
| 4 | TA1 | Rp0.2 | ≥250 | range_or_limit_format | ta0余量———————0.100.100.050.030.012ta1余量———————0.200.150.050.030.012ta2余量———————0.250.200.050.050.012t |
| 4 | TA2 | A | ≥15 | range_or_limit_format | 质元素a,不大于tialmnvsnpdmonifeocnhta0余量———————0.100.100.050.030.012ta1余量———————0.200.150.050.030.012ta2余量 |

### gbt-3280-2015

| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |
|---|---|---|---|---|---|
| 26 | 06Cr17Ni7AlTi | HRC | 5 | value_out_of_range | 31(续)统一数字代号牌号钢材厚度mm处理a温度°c规定塑性延伸强度rp0.2/mpa抗拉强度rm/mpa断后b,c伸长率a/%不小于硬度值hrchbw不小于s5157007cr15ni7mo2al0 |
| 44 | 12Cr17Ni7 | 冷却介质 | 水冷、快冷 | non_numeric_value | 附 录 C (资料性附录) 不锈钢的热处理制度   不锈钢的热处理制度见表C. 1~表C. 5。 表C. 1 奥氏体型钢的热处理制度 统一数 字代号 牌号 热处理温度及冷却方式 S30110 12Cr |
| 44 | 022Cr17Ni7 | 冷却介质 | 水冷、快冷 | non_numeric_value | 附 录 C (资料性附录) 不锈钢的热处理制度   不锈钢的热处理制度见表C. 1~表C. 5。 表C. 1 奥氏体型钢的热处理制度 统一数 字代号 牌号 热处理温度及冷却方式 S30110 12Cr |
| 44 | 022Cr17Ni7N | 冷却介质 | 水冷、快冷 | non_numeric_value | 附 录 C (资料性附录) 不锈钢的热处理制度   不锈钢的热处理制度见表C. 1~表C. 5。 表C. 1 奥氏体型钢的热处理制度 统一数 字代号 牌号 热处理温度及冷却方式 S30110 12Cr |
| 44 | 12Cr18Ni9 | 冷却介质 | 水冷、快冷 | non_numeric_value | 附 录 C (资料性附录) 不锈钢的热处理制度   不锈钢的热处理制度见表C. 1~表C. 5。 表C. 1 奥氏体型钢的热处理制度 统一数 字代号 牌号 热处理温度及冷却方式 S30110 12Cr |
| 44 | 12Cr18Ni9Si3 | 冷却介质 | 水冷、快冷 | non_numeric_value | 附 录 C (资料性附录) 不锈钢的热处理制度   不锈钢的热处理制度见表C. 1~表C. 5。 表C. 1 奥氏体型钢的热处理制度 统一数 字代号 牌号 热处理温度及冷却方式 S30110 12Cr |

### gjb-5040-2001

| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |
|---|---|---|---|---|---|
| 3 | 12Cr2Ni4A | 冷却介质 | 空冷、水冷 | non_numeric_value | GJB 5040 - 200 1  件中注明。当需以其它热处理状态供应时，由供需双方商定。 3.3.2 锻件应酸洗或吹砂后供应。当有其它技术要求时，应在合同中注明。 3.4  力学性能 3.4.1   |
| 3 | 30CrMnSiNi2A | 冷却介质 | 空冷、炉冷 | non_numeric_value | GJB 5040 - 200 1  件中注明。当需以其它热处理状态供应时，由供需双方商定。 3.3.2 锻件应酸洗或吹砂后供应。当有其它技术要求时，应在合同中注明。 3.4  力学性能 3.4.1   |
| 3 | 14CrMnSiNi2MoA | 冷却介质 | 空冷、水冷 | non_numeric_value | GJB 5040 - 200 1  件中注明。当需以其它热处理状态供应时，由供需双方商定。 3.3.2 锻件应酸洗或吹砂后供应。当有其它技术要求时，应在合同中注明。 3.4  力学性能 3.4.1   |
| 3 | 4Cr10Si2Mo | 保温温度 | 1000~1040℃；750℃ | grade_not_found | GJB 5040 - 200 1  件中注明。当需以其它热处理状态供应时，由供需双方商定。 3.3.2 锻件应酸洗或吹砂后供应。当有其它技术要求时，应在合同中注明。 3.4  力学性能 3.4.1   |
| 3 | 4Cr10Si2Mo | 冷却介质 | 随炉冷却、炉冷、空冷 | grade_not_found | GJB 5040 - 200 1  件中注明。当需以其它热处理状态供应时，由供需双方商定。 3.3.2 锻件应酸洗或吹砂后供应。当有其它技术要求时，应在合同中注明。 3.4  力学性能 3.4.1   |
| 6 | 45A | HB | 20 | value_out_of_range | 号布民硬度值拌火回火mpa%jmmhbs或hbw不小于11m供应状态315177305595.5-1431215a供应状态345196265595.5-143320a供应状态(正火)380215225 |

### hb-20079-2012

| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |
|---|---|---|---|---|---|
| 5 | 0Cr13Ni8Mo2Al | Al | 0.90~1.35 | grade_not_found | 0-5.02.7~3.3。.5-1.012.02ocr13ni8mo2al~0.05~0.10~o.io~0.008~0.01012.25-7.50-2.00~0.90-~0.01013.258.50 |
| 5 | 0Cr13Ni8Mo2Al | Ni | 7.50~8.50 | grade_not_found | 02511.0~4.0-5.02.7~3.3。.5-1.012.02ocr13ni8mo2al~0.05~0.10~o.io~0.008~0.01012.25-7.50-2.00~0.90-~0.01 |
| 5 | 0Cr15Ni5Cu2Ti | Mo | ≤0.30 | grade_not_found | .90-~0.01013.258.502.骂。1.353ocr15ni5cu2ti~0.08~1.0军三0.7~0.018~0.02013.5~4.8-5.8运0.30-。.03~1.75~--14. |
| 5 | 0Cr15Ni5Cu4Nb | S | ≤0.015 | grade_not_found | 化学成分 化学成分，% 序号 牌号 C  民1n Si  S  P  Cr  Ni  孔10 八l Ti  Cu  Nb+l'a  N  OCrl2Mn5Ni4Mo3A 1  主三0.09 4.4-5 |
| 5 | 0Cr16Ni6 | S | ≤0.015 | grade_not_found | 化学成分 化学成分，% 序号 牌号 C  民1n Si  S  P  Cr  Ni  孔10 八l Ti  Cu  Nb+l'a  N  OCrl2Mn5Ni4Mo3A 1  主三0.09 4.4-5 |
| 6 | 0Cr13Ni8Mo2Al | 冷却介质 | 水冷、油冷、空冷 | grade_not_found | HB 20079-2012  3.3 供应状态 3.3.1  锻件的供应状态应符合表3 的规定。 表3 锻件供应状态 序号 牌号 供应状态 热处理制度 硬度，HB\V  OCr 12Mn5Ni4Mo3 |

### ams-qq-a250-4b

| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |
|---|---|---|---|---|---|
| 2 | A92024 | Cr | ≤0.10 | range_or_limit_format | maximumsilicon-0.50iron-0.50copper3.84.9manganese0.300.9magnesium1.21.8chromium-0.10nickel--zinc-0.2 |
| 2 | A92024 | Cu | 3.8~4.9 | range_or_limit_format | lei.chemicalcomposition1/percentelementminimummaximumsilicon-0.50iron-0.50copper3.84.9manganese0.300 |
| 2 | A92024 | Fe | ≤0.50 | range_or_limit_format | ecifiedintablei.tablei.chemicalcomposition1/percentelementminimummaximumsilicon-0.50iron-0.50copper3 |
| 2 | A92024 | Mn | 0.30~0.9 | range_or_limit_format | position1/percentelementminimummaximumsilicon-0.50iron-0.50copper3.84.9manganese0.300.9magnesium1.21 |
| 2 | A92024 | Si | ≤0.50 | range_or_limit_format | ecifiedintablei.tablei.chemicalcomposition1/percentelementminimummaximumsilicon-0.50iron-0.50copper3 |

### ams-4050k

| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |
|---|---|---|---|---|---|
| 2 | 7050-T7451 | Mg | 1.9~2.6 | range_or_limit_format | positionelementminmaxsilicon--0.12iron--0.15copper2.02.6manganese--0.10magnesium1.92.6chromium--0.04 |
| 2 | 7050-T7451 | Mn | ≤0.10 | range_or_limit_format | 55.table1-compositionelementminmaxsilicon--0.12iron--0.15copper2.02.6manganese--0.10magnesium1.92.6c |
| 2 | 7050-T7451 | Zn | 5.7~6.7 | range_or_limit_format | icon--0.12iron--0.15copper2.02.6manganese--0.10magnesium1.92.6chromium--0.04zinc5.76.7titanium--0.06 |
| 2 | 7050-T7451 | Zr | 0.08~0.15 | range_or_limit_format | 2.6manganese--0.10magnesium1.92.6chromium--0.04zinc5.76.7titanium--0.06zirconium0.080.15otherelement |

### ams-4108g

| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |
|---|---|---|---|---|---|
| 2 | 7050-T7452 | Mg | 1.9~2.6 | range_or_limit_format | positionelementminmaxsilicon--0.12iron--0.15copper2.02.6manganese--0.10magnesium1.92.6chromium--0.04 |
| 2 | 7050-T7452 | Mn | ≤0.10 | range_or_limit_format | 55.table1-compositionelementminmaxsilicon--0.12iron--0.15copper2.02.6manganese--0.10magnesium1.92.6c |
| 2 | 7050-T7452 | Zn | 5.7~6.7 | range_or_limit_format | icon--0.12iron--0.15copper2.02.6manganese--0.10magnesium1.92.6chromium--0.04zinc5.76.7titanium--0.06 |
| 2 | 7050-T7452 | Zr | 0.08~0.15 | range_or_limit_format | 2.6manganese--0.10magnesium1.92.6chromium--0.04zinc5.76.7titanium--0.06zirconium0.080.15otherelement |

### ams-4911s

| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |
|---|---|---|---|---|---|
| 1 | 6Al-4V | 保温温度 | 899 °C；14 °C | ocr_or_normalization | ____________________________________________________________________________________________________ |
| 3 | 6Al-4V | Al | ≥5.50 | grade_not_found | thodsmaybeusedifacceptabletothepurchaser.table1-compositionelementminmaxaluminum5.506.75vanadium3.50 |

### ams-4967n

| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |
|---|---|---|---|---|---|
| 1 | R56400 | 保温温度 | 788 °C；14 °C | ocr_or_normalization | ____________________________________________________________________________________________________ |
| 1 | R56400 | 保温温度 | 954 °C ± 14 °C；538 °C ± 8 °C | ocr_or_normalization | ing,orotherwise,withoutthepriorwrittenpermissionofsae.toplaceadocumentorder:tel:877-606-7323(insideu |
| 3 | R56400 | Al | 5.50~6.75 | grade_not_found | (3.1.1)yttrium(3.1.2)otherelements,each(3.1.2)otherelements,total(3.1.2)titanium5.503.50------------ |
| 3 | R56400 | C | ≤0.08 | grade_not_found | erelements,total(3.1.2)titanium5.503.50----------------remainder6.754.500.300.200.080.050.01250.0050 |
| 3 | R56400 | Fe | ≤0.30 | grade_not_found | .1.2)otherelements,total(3.1.2)titanium5.503.50----------------remainder6.754.500.300.200.080.050.01 |
| 3 | R56400 | H | ≤0.0125(125 ppm) | grade_not_found | ts,total(3.1.2)titanium5.503.50----------------remainder6.754.500.300.200.080.050.01250.0050.100.40( |

### ams-5663p

| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |
|---|---|---|---|---|---|
| 3 | N07718 | Al | 0.20~0.80 | grade_not_found | el50.0055.00molybdenum2.803.30columbium(niobium)4.755.50titanium0.651.15aluminum0.200.80cobalt--1.00 |
| 3 | N07718 | Bi | ≤0.00003(0.3ppm) | grade_not_found | 5aluminum0.200.80cobalt--1.00boron--0.006copper--0.30lead--0.0005(5ppm)bismuth--0.00003(0.3ppm)selen |
| 3 | N07718 | Cr | 17.00~21.00 | grade_not_found | axcarbon--0.08manganese--0.35silicon--0.35phosphorus--0.015sulfur--0.015chromium17.0021.00nickel50.0 |
| 3 | N07718 | Mo | 2.80~3.30 | grade_not_found | --0.35phosphorus--0.015sulfur--0.015chromium17.0021.00nickel50.0055.00molybdenum2.803.30columbium(ni |
| 3 | N07718 | Ti | 0.65~1.15 | grade_not_found | um17.0021.00nickel50.0055.00molybdenum2.803.30columbium(niobium)4.755.50titanium0.651.15aluminum0.20 |

### astm-b861-14

| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |
|---|---|---|---|---|---|
| 4 | 38 | Rp0.2 | 115 | ocr_or_normalization | TABLE 1 Continued Composition, Weight PercentA,B,C,D,E Grade UNS Number Carbon, max. Oxygen range or |

### astm-b861-24

| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |
|---|---|---|---|---|---|
| 4 | 38 | Rp0.2 | 115 | ocr_or_normalization | TABLE 1 Continued Composition, Weight PercentA,B,C,D,E Grade UNS Number Carbon, max. Oxygen range or |

### astm-b708-25

| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |
|---|---|---|---|---|---|
| 2 | ~ | W | 0.05remainder | ocr_or_normalization | 0.0100.0100.0100.0100.010si0.0050.0050.0050.0050.005ti0.0100.0100.0100.0100.010w0.050.059.0–11.02.0– |
| 2 | ~ | W | 0.05remainder | ocr_or_normalization | 0.0100.0100.0100.0100.010si0.0050.0050.0050.0050.005ti0.0100.0100.0100.0100.010w0.050.059.0–11.02.0– |
| 2 | ~ | Nb | 35.0-42.0 | range_or_limit_format | .0015fe0.0100.0100.0100.0100.010mo0.0200.0200.0200.0200.020nb0.1000.1000.1000.5035.0–42.0ni0.0100.01 |
| 2 | ~ | W | 0.050remainder | ocr_or_normalization | 0.0100.0100.0100.0100.010si0.0050.0050.0050.0050.005ti0.0100.0100.0100.0100.010w0.050.059.0–11.02.0– |
| 3 | 90% tantalum-10% t | Rm | 70 000 | value_out_of_range | $0.060in.thick25000(172)15000(103)3090%tantalum–10%tungsten(r05255)sheetandstrip70000(482)60000(414) |
| 3 | 90% tantalum-10% t | Rm | 70 000 | value_out_of_range | $0.060in.thick25000(172)15000(103)3090%tantalum–10%tungsten(r05255)sheetandstrip70000(482)60000(414) |

### astm-b338-17

| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |
|---|---|---|---|---|---|
| 4 | 38 | Rp0.2 | 115 | ocr_or_normalization | TABLE 1 Continued Composition, Weight PercentA,B,C,D,E Grade UNS Number Carbon, max. Oxygen range or |

### asme-sb338-2021

| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |
|---|---|---|---|---|---|
| 5 | 38 | Rp0.2 | 115 | ocr_or_normalization | ASME BPVC.II.B-2021 SB-338 479 TABLE 1 Continued Composition, Weight PercentA,B,C,D,E Grade UNS Numb |
| 5 | 39 | Rm | 75 | ocr_or_normalization | ASME BPVC.II.B-2021 SB-338 479 TABLE 1 Continued Composition, Weight PercentA,B,C,D,E Grade UNS Numb |

### asme-sb575-2023

| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |
|---|---|---|---|---|---|
| 3 | AlloyN06035 | Mo | 7.60-9.00 | range_or_limit_format | 6455alloyn06059alloyn06058alloyn06200alloyn06210alloyn10362alloyn06686molybdenum7.60–9.000.80-1.2015 |
| 3 | AlloyN10276 | Cr | 14.5-16.5 | range_or_limit_format | 06200alloyn06210alloyn10362alloyn06686molybdenum7.60–9.000.80-1.2015.0–17.012.5–14.514.0–17.015.0–16 |
| 3 | AlloyN06022 | Cr | 20.0-22.5 | range_or_limit_format | num7.60–9.000.80-1.2015.0–17.012.5–14.514.0–17.015.0–16.518.5–21.015.0–17.018.0–20.021.5–23.015.0-17 |
| 3 | AlloyN06022 | Mo | 12.5-14.5 | range_or_limit_format | lloyn06200alloyn06210alloyn10362alloyn06686molybdenum7.60–9.000.80-1.2015.0–17.012.5–14.514.0–17.015 |
| 3 | AlloyN06022 | W | 2.5-3.5 | range_or_limit_format | loyn06200alloyn06210alloyn10362alloyn06686molybdenum7.60–9.000.80-1.2015.0–17.012.5–14.514.0–17.015. |
| 3 | AlloyN06455 | Cr | 14.0-18.0 | range_or_limit_format | 0alloyn06210alloyn10362alloyn06686molybdenum7.60–9.000.80-1.2015.0–17.012.5–14.514.0–17.015.0–16.518 |

### astm-b862-23

| 页 | 牌号 | 字段 | 原始值 | 原因 | 原文片段 |
|---|---|---|---|---|---|
| 5 | 34 | Rm | 65 | ocr_or_normalization | TABLE 2 Continued Composition, Weight PercentA,B,C,D,E Grade UNS Number Carbon, max. Oxygen range or |
| 5 | 38 | Rp0.2 | 115 | ocr_or_normalization | TABLE 2 Continued Composition, Weight PercentA,B,C,D,E Grade UNS Number Carbon, max. Oxygen range or |

