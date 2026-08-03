"""
下载 BAAI/bge-m3 和 BAAI/bge-reranker-v2-m3 模型。
优先使用 huggingface_hub.snapshot_download，
若 HF 不可访问则回退到 modelscope.snapshot_download。
模型保存到 ./models 目录下。
"""

import os
import sys
import shutil

# 国内使用 HF 镜像加速
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

MODELS = [
    {
        "repo_id": "zai-org/GLM-OCR",
        "local_dir": os.path.join("models", "glm-ocr"),
    },
    {
        "repo_id": "RedHatAI/Qwen3.5-9B-FP8-dynamic",
        "local_dir": os.path.join("models", "qwen3.5-9b-fp8"),
    },
]


def download_via_huggingface(repo_id, local_dir):
    """使用 huggingface_hub.snapshot_download 下载模型。"""
    from huggingface_hub import snapshot_download

    print(f"[HF] 开始下载 {repo_id} -> {local_dir}")
    path = snapshot_download(
        repo_id=repo_id,
        local_dir=local_dir,
        revision="main",
    )
    print(f"[HF] 下载完成: {path}")
    return path


def download_via_modelscope(repo_id, local_dir):
    """使用 modelscope.snapshot_download 下载模型作为回退方案。"""
    from modelscope import snapshot_download

    print(f"[ModelScope] 开始下载 {repo_id} -> {local_dir}")
    # ModelScope 的 cache_dir 会按 org/model 结构存放，
    # 下载完成后移动/拷贝到目标目录，保证路径一致。
    cache_dir = os.path.abspath("models")
    path = snapshot_download(
        model_id=repo_id,
        cache_dir=cache_dir,
        revision="master",
    )
    print(f"[ModelScope] 原始下载路径: {path}")

    # 如果实际下载路径与目标目录不同，则拷贝过去
    target_dir = os.path.abspath(local_dir)
    if os.path.abspath(path) != target_dir:
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        shutil.copytree(path, target_dir)
        print(f"[ModelScope] 已拷贝到: {target_dir}")
        return target_dir
    return path


def download_model(repo_id, local_dir):
    """优先 HF，失败则回退到 ModelScope。"""
    # 已下载则跳过
    if os.path.isdir(local_dir) and os.listdir(local_dir):
        print(f"[SKIP] {repo_id} 已存在于 {local_dir}，跳过下载。")
        return local_dir

    try:
        return download_via_huggingface(repo_id, local_dir)
    except Exception as e:
        print(f"[WARN] HuggingFace 下载失败: {e}")
        print(f"[INFO] 回退到 ModelScope 下载 {repo_id} ...")
        try:
            return download_via_modelscope(repo_id, local_dir)
        except Exception as e2:
            print(f"[ERROR] ModelScope 下载也失败: {e2}")
            raise


def main():
    print("=" * 60)
    print("开始下载模型")
    print(f"HF_ENDPOINT = {os.environ.get('HF_ENDPOINT')}")
    print("=" * 60)

    results = []
    for m in MODELS:
        repo_id = m["repo_id"]
        local_dir = m["local_dir"]
        print("-" * 60)
        print(f"处理模型: {repo_id}")
        try:
            final_path = download_model(repo_id, local_dir)
            results.append((repo_id, final_path, True))
        except Exception as e:
            print(f"[ERROR] 下载 {repo_id} 最终失败: {e}")
            results.append((repo_id, None, False))

    print("=" * 60)
    print("下载结果汇总:")
    all_ok = True
    for repo_id, path, ok in results:
        status = "成功" if ok else "失败"
        print(f"  [{status}] {repo_id} -> {path}")
        if not ok:
            all_ok = False
    print("=" * 60)

    if not all_ok:
        print("部分模型下载失败，请检查网络或镜像配置。")
        sys.exit(1)
    print("所有模型下载完成！")


if __name__ == "__main__":
    main()
