#!/bin/bash
set -euo pipefail

# 从 /opt/mirror-config.env 读取镜像加速配置。
# 如果没有配置文件，直接跳过；仓库根目录 .env 是本地敏感文件，不参与同步脚本。

MIRROR_CONFIG="/opt/mirror-config.env"

if [[ ! -f "$MIRROR_CONFIG" ]]; then
    echo "镜像配置文件不存在: $MIRROR_CONFIG，跳过镜像替换"
    exit 0
fi

set -a
source "$MIRROR_CONFIG"
set +a

replace_image() {
    local src_registry="$1"
    local target_registry="$2"
    local src_pattern="${src_registry//./\\.}"

    if [[ -z "$target_registry" ]]; then
        echo "镜像源 $src_registry 已启用但未配置目标地址，跳过"
        return
    fi

    while IFS= read -r file; do
        sed -i -E "s#(^[[:space:]]*image:[[:space:]]*)${src_pattern}/#\1${target_registry}/#g" "$file"
        echo "已检查 $file: $src_registry -> $target_registry"
    done < <(find ./apps -type f \( -name "docker-compose.yml" -o -name "docker-compose.yaml" \))
}

if [[ "${GHCR_ENABLE:-false}" == "true" ]]; then
    replace_image "ghcr.io" "${GHCR_MIRROR:-}"
fi

if [[ "${QUAY_ENABLE:-false}" == "true" ]]; then
    replace_image "quay.io" "${QUAY_MIRROR:-}"
fi

if [[ "${GCR_ENABLE:-false}" == "true" ]]; then
    replace_image "gcr.io" "${GCR_MIRROR:-}"
fi

if [[ "${K8S_GCR_ENABLE:-false}" == "true" ]]; then
    replace_image "k8s.gcr.io" "${K8S_GCR_MIRROR:-}"
fi

if [[ "${K8S_REG_ENABLE:-false}" == "true" ]]; then
    replace_image "registry.k8s.io" "${K8S_REG_MIRROR:-}"
fi

echo "镜像替换完成。"
