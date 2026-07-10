from modelscope import snapshot_download
# 国内ModelScope仓库，PaddleOCR-VL完整权重
model_path = snapshot_download(
    "Qwen/Qwen3.6-35B-A3B-FP8",
    cache_dir="./models",
    revision="master"
)
print("模型完整本地路径：", model_path)
