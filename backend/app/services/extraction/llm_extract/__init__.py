"""Phase 4 LLM 抽取模块。

双线路 LLM 抽取：
- 线路 A（LangExtract）：output_schema 强约束 + 类别内并发
- 线路 B（glmocr）：短/长文本分流 + 表格边界感知分批
"""
