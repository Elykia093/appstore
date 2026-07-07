# 1Panel 私有应用商店

本仓库是面向个人使用的 [1Panel](https://github.com/1Panel-dev/1Panel) 本地应用商店，包含当前需要维护的 7 个应用模板，可同步到 1Panel 的本地应用目录后安装使用。

本仓库基于 [1Panel 官方应用商店](https://github.com/1Panel-dev/appstore) 的目录结构整理，不是官方应用源。安装前请自行确认镜像来源、端口、持久化目录和安全风险。

### 1Panel 私有应用商店收录标准：

- 当前实际需要维护的应用，不追求大而全
- 项目来源或镜像来源可公开追溯
- 能通过 Docker Compose 在 1Panel 本地应用中部署
- 支持数据库的应用优先使用 PostgreSQL
- 敏感配置只通过 1Panel 表单变量或运行环境注入，不写入仓库

## 应用列表

| 应用 | 类型 | 项目/镜像来源 | 存储口径 |
| --- | --- | --- | --- |
| [Anheyu](./apps/anheyu/README.md) | 博客与内容管理 | [项目来源](https://github.com/anzhiyu-c/anheyu-app) | PostgreSQL + Redis |
| [CPA / CLIProxyAPI](./apps/cpa/README.md) | AI CLI 代理 | [项目来源](https://github.com/router-for-me/CLIProxyAPI) | PostgreSQL |
| [Octopus](./apps/octopus/README.md) | LLM API 聚合 | [项目来源](https://github.com/bestruirui/octopus) | PostgreSQL |
| [Lsky Pro](./apps/lsky/README.md) | 图床 | [lsky-pro 镜像](https://github.com/walrus8364/lsky-pro/pkgs/container/lsky-pro) | PostgreSQL，可选 Redis |
| [Metapi](./apps/metapi/README.md) | AI 网关聚合 | [项目来源](https://github.com/cita-777/metapi) | 本地数据目录 |
| [AxonHub](./apps/axonhub/README.md) | AI 开发与管理平台 | [项目来源](https://github.com/looplj/axonhub) | PostgreSQL |
| [LX Sync Server](./apps/lx-sync-server/README.md) | LX Music 同步服务端 | [项目来源](https://github.com/XCQ0607/lxserver) | 本地数据目录 |

## 仓库结构

```text
.
├── data.yaml
├── logo.png
├── apps/
│   └── <app>/
│       ├── data.yml
│       ├── logo.png
│       ├── README.md
│       └── <version>/
│           ├── data.yml
│           └── docker-compose.yml
├── mirror.sh
├── renovate.json
└── scripts/
```

- `data.yaml` 是应用商店根元数据，定义名称、标题和分类标签。
- `apps/<app>/data.yml` 是应用元数据，`apps/<app>/<version>/data.yml` 是版本表单配置。
- `apps/<app>/<version>/docker-compose.yml` 是 1Panel 安装时使用的编排模板。
- `mirror.sh` 只读取 `/opt/mirror-config.env`，用于按需替换镜像仓库前缀。
- `scripts/` 中的校验与同步脚本用于 CI、Renovate 和本地维护。

## 当前编排口径

| 应用 | 1Panel 版本目录 | 镜像 | 默认端口映射 | 持久化与配置 |
| --- | --- | --- | --- | --- |
| Anheyu | `1.8.21` | `anheyu/pro:1.8.21` | `8091:8091` | `./data`、`./themes`、`./static`、`./backup` |
| CPA / CLIProxyAPI | `7.2.51` | `eceasy/cli-proxy-api:v7.2.51` | `8317:8317` | `./config.yaml`、`./auths`、`./logs` |
| Octopus | `0.9.28` | `bestrui/octopus:v0.9.28` | `8080:8080` | `./data`，PostgreSQL DSN 由环境变量注入 |
| Lsky Pro | `2.1` | `ghcr.io/walrus8364/lsky-pro:latest` | `8000:80` | `./data:/var/www/html`，PostgreSQL/Redis/Admin/License 由环境变量注入 |
| Metapi | `1.3.0` | `1467078763/metapi:v1.3.0` | `4000:4000` | `./data:/app/data` |
| AxonHub | `1.0.0-beta4` | `looplj/axonhub:v1.0.0-beta4` | `18090:8090` | `./config.yml`、`./data`，内置 `/health` 健康检查 |
| LX Sync Server | `1.9.4` | `ghcr.io/xcq0607/lxserver:v1.9.4` | `9527:9527` | `./data`、`./logs`、`./cache`、`./music`，WebDAV 参数由环境变量注入 |

说明：

- 版本目录必须写真实应用版本号，不使用 `latest` 作为目录名。
- 所有镜像都带 digest pin，安装时仍可追溯到不可变镜像内容。
- Lsky 的镜像公开 tag 只有 `latest`、`amd64`、`arm64`，所以 1Panel 版本目录写真实应用版本 `2.1`，compose 保留 `latest@sha256`。
- 仓库根目录 `.env` 只作为本地文件存在，不参与安装模板和镜像替换逻辑。

## 同步到 1Panel

默认 1Panel 安装目录为 `/opt/1panel`。如果你的安装目录不同，请调整 `LOCAL_APPS_DIR`。

```bash
#!/bin/bash
set -euo pipefail

GIT_REPO="https://github.com/Elykia093/appstore.git"
TMP_DIR="/opt/1panel/resource/apps/local/appstore-localApps"
LOCAL_APPS_DIR="/opt/1panel/resource/apps/local"

trap 'rm -rf "$TMP_DIR"' EXIT

rm -rf "$TMP_DIR"
git clone --depth=1 "$GIT_REPO" "$TMP_DIR"

cd "$TMP_DIR"
if [[ -f ./mirror.sh ]]; then
    chmod +x ./mirror.sh
    ./mirror.sh
fi
cd - >/dev/null

mkdir -p "$LOCAL_APPS_DIR"
for app_path in "$TMP_DIR/apps/"*; do
    [ -d "$app_path" ] || continue
    app_name="$(basename "$app_path")"
    rm -rf "$LOCAL_APPS_DIR/$app_name"
    cp -r "$app_path" "$LOCAL_APPS_DIR/$app_name"
done

echo "Sync completed."
```

同步完成后，在 1Panel 应用商店刷新本地应用列表。

## 镜像加速

`mirror.sh` 会读取 `/opt/mirror-config.env`，按需替换 `docker-compose.yml` 中的镜像仓库前缀。没有该文件时会直接跳过，不影响安装。

```ini
GHCR_ENABLE=true
GHCR_MIRROR=ghcr.io.mirror

QUAY_ENABLE=false
QUAY_MIRROR=quay.io.mirror

GCR_ENABLE=false
GCR_MIRROR=gcr.io.mirror

K8S_GCR_ENABLE=false
K8S_GCR_MIRROR=k8s.gcr.io.mirror

K8S_REG_ENABLE=false
K8S_REG_MIRROR=registry.k8s.io.mirror
```

## 自动更新

本仓库使用 Renovate 和 GitHub Actions 维护镜像与版本目录：

- `Renovate` 扫描 `apps/*/*/docker-compose.yml` 中的 Docker 镜像。
- `renovate-app-version.yml` 在 Renovate 分支中同步 1Panel 版本目录和本 README 的编排表。
- `Check App Updates` 每天额外核查 7 个应用的 GitHub latest release 与 registry digest；发现落后时只写入 Job Summary，不把工作流标为失败。
- `Validate App Store` 校验目录结构、compose 镜像、README 表格同步和脚本语法。

如果需要让 Renovate 分支继续自动触发后续工作流，建议配置 `RENOVATE_TOKEN` 或 `MERGE_ADMIN_TOKEN`。只使用默认 `GITHUB_TOKEN` 时，GitHub 会抑制由该 token 推送分支后的部分工作流触发。

## 创建本地应用

可参考 1Panel 官方文档：[如何提交自己想要的应用](https://github.com/1Panel-dev/appstore/wiki/%E5%A6%82%E4%BD%95%E6%8F%90%E4%BA%A4%E8%87%AA%E5%B7%B1%E6%83%B3%E8%A6%81%E7%9A%84%E5%BA%94%E7%94%A8)。

也可以参考 [1Panel App Store Skills](https://github.com/1Panel-dev/1Panel-appstore-skills)，其中包含 1Panel 本地应用包的打包规范、模板和校验步骤。

## 维护校验

修改应用模板或 README 后运行：

```bash
python scripts/validate-appstore.py
python scripts/sync-readme-app-table.py --check
python scripts/check-updates.py --no-fail
```

## 问题反馈

如发现本仓库模板配置错误或需要调整应用，请在 [本仓库 Issues](https://github.com/Elykia093/appstore/issues) 反馈。1Panel 本体问题请前往 [1Panel 主项目](https://github.com/1Panel-dev/1Panel/issues)。
