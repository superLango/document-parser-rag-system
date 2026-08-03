"""Phase 2 类别构建模块。

从 sm_feature 全量出发，用每个 feature 的 item+method 作为 query 检索
doc_five_dim，有召回且置信度达标则保留该 feature。
"""
