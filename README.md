# 1Panel 私有 App Store

这是一个基于他人 1Panel 第三方应用商店整理的私有精简仓库，用于收纳个人需要的一组容器化应用与预设配置，基于 [1Panel](https://github.com/1Panel-dev/1Panel) 的 App Store 架构。

当前仅保留以下应用：

| 1Panel 应用 | 对应项目/镜像 | 存储口径 |
| --- | --- | --- |
| Anheyu (`anheyu`) | [anzhiyu-c/anheyu-app](https://github.com/anzhiyu-c/anheyu-app) | PostgreSQL + Redis |
| CPA / CLIProxyAPI (`cpa`) | [router-for-me/CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) | PostgreSQL |
| Octopus (`octopus`) | [bestruirui/octopus](https://github.com/bestruirui/octopus) | PostgreSQL |
| Lsky Pro (`lsky`) | `ghcr.io/walrus8364/lsky-pro:latest` | PostgreSQL，可选 Redis |
| Metapi (`metapi`) | [cita-777/metapi](https://github.com/cita-777/metapi) | 本地数据目录 |
| AxonHub (`axonhub`) | [looplj/axonhub](https://github.com/looplj/axonhub) | PostgreSQL |
| LX Sync Server (`lx-sync-server`) | [XCQ0607/lxserver](https://github.com/XCQ0607/lxserver) | 本地数据目录 |

---

## 当前编排口径

本仓库模板已按当前 1Panel 服务器上的实际 Docker Compose 编排对齐，敏感值仅保留为 1Panel 表单变量，不写入仓库。

| 应用 | 镜像 | 默认端口映射 | 持久化与配置 |
| --- | --- | --- | --- |
| Anheyu | `anheyu/pro:latest` | `8091:8091` | `./data`、`./themes`、`./static`、`./backup` |
| CPA / CLIProxyAPI | `eceasy/cli-proxy-api:latest` | `8317:8317` | `./config.yaml`、`./auths`、`./logs` |
| Octopus | `bestrui/octopus:latest` | `8080:8080` | `./data`，PostgreSQL DSN 由环境变量注入 |
| Lsky Pro | `ghcr.io/walrus8364/lsky-pro:latest` | `8000:80` | `./data:/var/www/html`，PostgreSQL/Redis/Admin/License 由环境变量注入 |
| Metapi | `1467078763/metapi:latest` | `4000:4000` | `./data:/app/data` |
| AxonHub | `looplj/axonhub:latest` | `18090:8090` | `./config.yml`、`./data`，内置 `/health` 健康检查 |
| LX Sync Server | `ghcr.io/xcq0607/lxserver:latest` | `9527:9527` | `./data`、`./logs`，WebDAV 参数由环境变量注入 |

说明：

- 有 PostgreSQL 能力的应用优先使用 PostgreSQL：Anheyu、CPA、Octopus、Lsky、AxonHub。
- Lsky 的实际运行容器还会从环境文件注入数据库与 Redis 相关变量，本模板改为 1Panel 表单变量直接注入，避免保存真实 `.env`。
- Octopus 服务器上的 compose 已是 `bestrui/octopus:latest`，但当前运行容器仍可能是旧镜像，重建容器后才会完全对齐。
- 多个模板使用 `latest` 是为了贴合现有编排；生产环境如需严格可追溯发布，建议改为不可变版本或镜像 digest。

---

## 自动更新检测

本仓库使用 Renovate 检测 `apps/*/*/docker-compose.yml` 中的 Docker 镜像：

- Renovate 只扫描应用模板里的 Docker Compose 文件，不处理旧仓库残留应用或 GitHub Actions 依赖。
- 对 `latest` 这类浮动标签启用 digest pin，镜像内容变化时会生成 digest 更新 PR。
- 对显式版本标签，Renovate 更新镜像标签后会触发 `renovate-app-version.yml`，同步 1Panel 版本目录。
- 对 `latest` 标签，只更新 compose 中的镜像摘要，不自动把 1Panel 版本目录重命名为 `latest`。
- Renovate PR 合并到 `main` 后，会由 `sync-to-cnb.yml` 通过 `push main` 触发 CNB 同步；未配置 CNB 变量时自动跳过。

---

## ✅ 应用收录标准

本仓库优先收录以下类型的容器应用：

- 常用工具或服务：覆盖个人或开发者日常使用频繁的项目
- 官方 Docker 镜像优先：确保稳定与安全
- PostgreSQL 优先：目标应用支持数据库时优先使用 PostgreSQL
- 简洁配置模板：配套清晰的 Docker Compose 和 formFields 文件，方便一键部署

---

## 🛠 使用说明

你可以将本仓库作为第三方 App Store 添加至 1Panel，即可在 Web 面板中浏览、安装、管理其中的应用。

### 添加第三方应用仓库

参考官方文档：[📚 如何添加第三方应用仓库](https://github.com/1Panel-dev/appstore/wiki/%E5%A6%82%E4%BD%95%E6%8F%90%E4%BA%A4%E8%87%AA%E5%B7%B1%E6%83%B3%E8%A6%81%E7%9A%84%E5%BA%94%E7%94%A8)

---

## 🔄 同步更新脚本

以下是自动同步 App 应用至 1Panel 的脚本，适用于开发或部署用户。

### 全量同步脚本

```bash
#!/bin/bash
set -euo pipefail
IFS=$'\n\t'

GIT_REPO="https://github.com/Elykia093/appstore.git"
TMP_DIR="/opt/1panel/resource/apps/local/appstore-localApps"
LOCAL_APPS_DIR="/opt/1panel/resource/apps/local"

trap 'rm -rf "$TMP_DIR"' EXIT

echo "📥 Cloning appstore repo..."
[ -d "$TMP_DIR" ] && rm -rf "$TMP_DIR"
git clone "$GIT_REPO" "$TMP_DIR"

echo "🔄 Mirroring apps..."
cd "$TMP_DIR"
if [[ -f ./mirror.sh ]]; then
    chmod +x ./mirror.sh
    ./mirror.sh
else
    echo "⚠️ mirror.sh not found, skipping mirroring"
fi
cd -

mkdir -p "$LOCAL_APPS_DIR"

for app_path in "$TMP_DIR/apps/"*; do
    [ -d "$app_path" ] || continue
    app_name=$(basename "$app_path")
    local_app_path="$LOCAL_APPS_DIR/$app_name"

    echo "🔁 Updating app: $app_name"
    [ -d "$local_app_path" ] && rm -rf "$local_app_path"
    cp -r "$app_path" "$local_app_path"
done

echo "✅ Sync completed."
```

------

## 😎 单应用同步

如果你想同步部分应用，可以采用以下脚本：

```bash
#!/bin/bash
set -euo pipefail
IFS=$'\n\t'

# ========= 配置：要安装的应用列表 =========
APPS_TO_INSTALL=(
    "anheyu"
    "cpa"
    "octopus"
    "lsky"
    "metapi"
    "axonhub"
    "lx-sync-server"
)

# ========= 常量 =========
GIT_REPO="https://github.com/Elykia093/appstore.git"
TMP_DIR="/opt/1panel/resource/apps/local/appstore-localApps"
LOCAL_APPS_DIR="/opt/1panel/resource/apps/local"

trap 'rm -rf "$TMP_DIR"' EXIT

echo "📥 Cloning appstore repo..."
[ -d "$TMP_DIR" ] && rm -rf "$TMP_DIR"
git clone "$GIT_REPO" "$TMP_DIR"

echo "🔄 Running mirror.sh (if exists)..."
cd "$TMP_DIR"
if [[ -f ./mirror.sh ]]; then
    chmod +x ./mirror.sh
    ./mirror.sh || echo "⚠️ mirror.sh 执行失败，继续..."
else
    echo "⚠️ mirror.sh not found, skipping mirroring"
fi
cd - >/dev/null

mkdir -p "$LOCAL_APPS_DIR"

# ========= 遍历安装列表 =========
for app_name in "${APPS_TO_INSTALL[@]}"; do
    app_path="$TMP_DIR/apps/$app_name"
    local_app_path="$LOCAL_APPS_DIR/$app_name"

    if [[ ! -d "$app_path" ]]; then
        echo "❌ 应用 $app_name 不存在于仓库，跳过"
        continue
    fi

    echo "🔁 Updating app: $app_name"
    [ -d "$local_app_path" ] && rm -rf "$local_app_path"
    cp -r "$app_path" "$local_app_path"
done

echo "✅ Selected apps sync completed."
```

## 🎡 镜像加速配置

在国内环境下，部分容器镜像源（如 `ghcr.io`、`gcr.io`、`quay.io` 等）可能会出现访问缓慢或被墙的情况。

你可以通过本镜像库独有的 **镜像映射配置文件** 来自动替换 `docker-compose.yml` 中的镜像地址，提升下载速度。

**注意该方式可能仅仅适用于本应用商店。**

### 1️⃣ 配置文件路径

镜像配置文件固定放在：

```bash
/opt/mirror-config.env
```

如果需要配置对应镜像，请自行创建以上文件，然后写入以下内容。

### 2️⃣ 配置文本

```ini
# ====== GHCR (GitHub Container Registry) ======
# 是否经常被墙：是
GHCR_ENABLE=true
GHCR_MIRROR=ghcr.io.mirror

# ====== Quay.io (RedHat/Community images) ======
# 是否经常被墙：是
QUAY_ENABLE=false
QUAY_MIRROR=quay.io.mirror

# ====== GCR (Google Container Registry) ======
# 是否经常被墙：是
GCR_ENABLE=false
GCR_MIRROR=gcr.io.mirror

# ====== k8s.gcr.io (旧 Kubernetes 镜像仓库) ======
# 是否经常被墙：是
K8S_GCR_ENABLE=false
K8S_GCR_MIRROR=k8s.gcr.io.mirror

# ====== registry.k8s.io (新 Kubernetes 镜像仓库) ======
# 是否经常被墙：是
K8S_REG_ENABLE=false
K8S_REG_MIRROR=registry.k8s.io.mirror
```

> 💡 **说明**：
>
> - `*_ENABLE` 为 `true` 时才会进行替换。
> - `*_MIRROR` 填写你可用的镜像源地址。
> - 不存在该配置文件时，脚本会跳过替换步骤，不会影响后续流程。

### 3️⃣ 自动替换逻辑

`mirror.sh` 只读取 `/opt/mirror-config.env`。没有该配置文件时会直接跳过镜像替换，不依赖仓库根目录 `.env`。

在克隆仓库后，按照本仓库的脚本，会在应用目录下执行 `mirror.sh` 进行镜像源替换。

这样即使镜像源被墙，也能快速替换为你配置的加速地址。

> **目前还在测试中**：由于目前还在测试中，所以可能会出现一些问题。如果出现问题，请及时反馈。

---

## 📮 问题反馈

如发现配置错误或希望调整应用，欢迎在 Issues 区提交反馈：

- 🛠 [本仓库 Issues](https://github.com/Elykia093/appstore/issues)

> ⚠️ 本项目仅对仓库中提供的应用内容提供支持。1Panel 本体问题请前往 [1Panel 主项目](https://github.com/1Panel-dev/1Panel/issues) 提问。

------

## ✨ 项目维护

- 维护者：Elykia093
- 仓库地址：https://github.com/Elykia093/appstore

------

## 🧩 想添加自己的应用？

欢迎参考官方教程，构建你自己的 App Store 仓库：

👉 [📘 官方指南：如何提交自己想要的应用](https://github.com/1Panel-dev/appstore/wiki/如何提交自己想要的应用)
