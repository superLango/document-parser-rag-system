#!/usr/bin/env bash
# 在官方版、微调 V1、微调 V2 之间切换 PP-DocLayoutV3。
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DEFAULT_PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
PROJECT_ROOT=${HANSONDOC_PROJECT_ROOT:-$DEFAULT_PROJECT_ROOT}
ENV_FILE="$PROJECT_ROOT/backend/.env"

declare -A MODEL_DIRS=(
    [official]="pp_doclayoutv3"
    [v1]="pp_doclayoutv3_finetuned_v1"
    [v2]="pp_doclayoutv3_finetuned_v2"
)
declare -A MODEL_HASHES=(
    [official]="5ea422c6cc5fe759a47e1357c35639b58173508e025a3131cbe4b6ac59e2b85e"
    [v1]="5c27e59c325631afb799058f35421c34e66a13442aad7307b5443c3468504eee"
    [v2]="5b76c1ff4b5b0305e8c6f7e09ae71fbe1f64740abb1e67a206e12d6e82c53cc3"
)

usage() {
    cat <<'EOF'
用法：
  bash scripts/select_layout_model.sh official|v1|v2 [--restart] [--dry-run]
  bash scripts/select_layout_model.sh --status

选项：
  --restart  更新后重启 FastAPI、arq Worker 和前端
  --dry-run  仅验证模型并显示将要执行的切换
  --status   显示当前配置，不输出 .env 的其他内容
EOF
}

show_status() {
    local configured
    if [[ ! -f "$ENV_FILE" ]]; then
        printf '配置文件不存在：%s\n' "$ENV_FILE" >&2
        return 1
    fi
    configured=$(sed -n 's/^PARSEKIT_LAYOUT_MODEL_DIR=//p' "$ENV_FILE" | tail -n 1)
    if [[ -z "$configured" ]]; then
        configured="$PROJECT_ROOT/models/pp_doclayoutv3_finetuned_v2（代码默认）"
    fi
    printf '当前版面模型：%s\n' "$configured"
}

if [[ ${1:-} == "--status" ]]; then
    show_status
    exit 0
fi

variant=${1:-}
if [[ -z "$variant" || -z ${MODEL_DIRS[$variant]+x} ]]; then
    usage >&2
    exit 2
fi
shift

restart=false
dry_run=false
while (($# > 0)); do
    case "$1" in
        --restart) restart=true ;;
        --dry-run) dry_run=true ;;
        *)
            printf '未知选项：%s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

model_dir="$PROJECT_ROOT/models/${MODEL_DIRS[$variant]}"
weight="$model_dir/model.safetensors"
expected_hash=${MODEL_HASHES[$variant]}

if [[ ! -f "$ENV_FILE" ]]; then
    printf '配置文件不存在：%s；请先创建 backend/.env。\n' "$ENV_FILE" >&2
    exit 1
fi
if [[ ! -f "$weight" ]]; then
    printf '模型权重不存在：%s\n' "$weight" >&2
    exit 1
fi

actual_hash=$(sha256sum "$weight" | cut -d ' ' -f 1)
if [[ "$actual_hash" != "$expected_hash" ]]; then
    printf '模型校验失败：%s\n期望：%s\n实际：%s\n' \
        "$variant" "$expected_hash" "$actual_hash" >&2
    exit 1
fi

printf '模型校验通过：%s\n目录：%s\nSHA256：%s\n' \
    "$variant" "$model_dir" "$actual_hash"
if [[ "$dry_run" == true ]]; then
    printf 'dry-run：未修改配置，未重启服务。\n'
    exit 0
fi

tmp_file=$(mktemp "${ENV_FILE}.layout-model.XXXXXX")
cleanup() {
    rm -f -- "$tmp_file"
}
trap cleanup EXIT
chmod --reference="$ENV_FILE" "$tmp_file"

awk -v value="$model_dir" '
    BEGIN { updated = 0 }
    /^PARSEKIT_LAYOUT_MODEL_DIR=/ {
        if (!updated) {
            print "PARSEKIT_LAYOUT_MODEL_DIR=" value
            updated = 1
        }
        next
    }
    { print }
    END {
        if (!updated) {
            print "PARSEKIT_LAYOUT_MODEL_DIR=" value
        }
    }
' "$ENV_FILE" > "$tmp_file"
mv -- "$tmp_file" "$ENV_FILE"
trap - EXIT

printf '已更新 %s 中的 PARSEKIT_LAYOUT_MODEL_DIR。\n' "$ENV_FILE"
if [[ "$restart" == true ]]; then
    printf '正在重启 HansonDOC 应用服务……\n'
    bash "$PROJECT_ROOT/scripts/restart_services.sh"
else
    printf '配置将在下次启动时生效；立即生效请运行：bash scripts/restart_services.sh\n'
fi

show_status
