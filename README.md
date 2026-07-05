<p align="center">
  <img src="./logo.png" width="96" alt="1Panel App Store">
</p>

<h1 align="center">1Panel 私有 App Store</h1>

<p align="center">
  <img src="https://img.shields.io/badge/Maintainer-Elykia093-blue.svg" alt="Maintainer">
  <img src="https://img.shields.io/badge/Apps-7-success.svg" alt="Apps">
  <img src="https://img.shields.io/badge/Platform-1Panel%20v2-orange.svg" alt="1Panel v2">
  <img src="https://img.shields.io/badge/Database-PostgreSQL-336791.svg" alt="PostgreSQL">
</p>

<p align="center">
  <a href="#应用列表">应用列表</a> |
  <a href="#当前编排口径">编排口径</a> |
  <a href="#同步到-1panel">同步到 1Panel</a> |
  <a href="#自动更新">自动更新</a>
</p>

## 仓库介绍

这是一个面向个人使用的 1Panel 第三方本地应用商店，只保留当前需要维护的 7 个容器应用。仓库基于 [1Panel App Store](https://github.com/1Panel-dev/appstore) 结构整理，模板已按实际 Docker Compose 编排收敛，敏感值通过 1Panel 表单变量注入，不写入仓库。

本仓库不是官方应用源，也不保证上游镜像一定适合所有环境。安装前请自行确认镜像来源、端口、持久化目录和安全风险。

## 应用列表

<table>
<tr>
<td width="33%" align="center">
<a href="./apps/anheyu/README.md">
<img src="./apps/anheyu/logo.png" width="56" height="56" alt="Anheyu"><br>
<b>Anheyu</b>
</a><br>
现代化博客与内容管理系统<br>
<kbd>PostgreSQL</kbd> <kbd>Redis</kbd><br>
<a href="https://github.com/anzhiyu-c/anheyu-app">项目来源</a>
</td>
<td width="33%" align="center">
<a href="./apps/cpa/README.md">
<img src="./apps/cpa/logo.png" width="56" height="56" alt="CPA"><br>
<b>CPA / CLIProxyAPI</b>
</a><br>
AI CLI 统一代理服务<br>
<kbd>PostgreSQL</kbd><br>
<a href="https://github.com/router-for-me/CLIProxyAPI">项目来源</a>
</td>
<td width="33%" align="center">
<a href="./apps/octopus/README.md">
<img src="./apps/octopus/logo.png" width="56" height="56" alt="Octopus"><br>
<b>Octopus</b>
</a><br>
LLM API 聚合与负载均衡服务<br>
<kbd>PostgreSQL</kbd><br>
<a href="https://github.com/bestruirui/octopus">项目来源</a>
</td>
</tr>
</table>

<table>
<tr>
<td width="33%" align="center">
<a href="./apps/lsky/README.md">
<img src="./apps/lsky/logo.png" width="56" height="56" alt="Lsky Pro"><br>
<b>Lsky Pro</b>
</a><br>
自托管图床系统<br>
<kbd>PostgreSQL</kbd> <kbd>Redis 可选</kbd><br>
<a href="https://github.com/walrus8364/lsky-pro/pkgs/container/lsky-pro">lsky-pro 镜像</a>
</td>
<td width="33%" align="center">
<a href="./apps/metapi/README.md">
<img src="./apps/metapi/logo.png" width="56" height="56" alt="Metapi"><br>
<b>Metapi</b>
</a><br>
多个 AI 网关的统一聚合入口<br>
<kbd>本地数据目录</kbd><br>
<a href="https://github.com/cita-777/metapi">项目来源</a>
</td>
<td width="33%" align="center">
<a href="./apps/axonhub/README.md">
<img src="./apps/axonhub/logo.png" width="56" height="56" alt="AxonHub"><br>
<b>AxonHub</b>
</a><br>
一体化 AI 开发与管理平台<br>
<kbd>PostgreSQL</kbd><br>
<a href="https://github.com/looplj/axonhub">项目来源</a>
</td>
</tr>
</table>

<table>
<tr>
<td align="center">
<a href="./apps/lx-sync-server/README.md">
<img src="./apps/lx-sync-server/logo.png" width="56" height="56" alt="LX Sync Server"><br>
<b>LX Sync Server</b>
</a><br>
LX Music 数据同步服务端<br>
<kbd>本地数据目录</kbd><br>
<a href="https://github.com/XCQ0607/lxserver">项目来源</a>
</td>
</tr>
</table>

## 当前编排口径

| 应用 | 1Panel 版本目录 | 镜像 | 默认端口映射 | 持久化与配置 |
| --- | --- | --- | --- | --- |
| Anheyu | `1.8.20` | `anheyu/pro:1.8.20` | `8091:8091` | `./data`、`./themes`、`./static`、`./backup` |
| CPA / CLIProxyAPI | `7.2.50` | `eceasy/cli-proxy-api:v7.2.50` | `8317:8317` | `./config.yaml`、`./auths`、`./logs` |
| Octopus | `0.9.28` | `bestrui/octopus:v0.9.28` | `8080:8080` | `./data`，PostgreSQL DSN 由环境变量注入 |
| Lsky Pro | `2.1` | `ghcr.io/walrus8364/lsky-pro:latest` | `8000:80` | `./data:/var/www/html`，PostgreSQL/Redis/Admin/License 由环境变量注入 |
| Metapi | `1.3.0` | `1467078763/metapi:v1.3.0` | `4000:4000` | `./data:/app/data` |
| AxonHub | `1.0.0-beta4` | `looplj/axonhub:v1.0.0-beta4` | `18090:8090` | `./config.yml`、`./data`，内置 `/health` 健康检查 |
| LX Sync Server | `1.9.4` | `ghcr.io/xcq0607/lxserver:v1.9.4` | `9527:9527` | `./data`、`./logs`、`./cache`、`./music`，WebDAV 参数由环境变量注入 |

说明：

- 有 PostgreSQL 能力的应用优先使用 PostgreSQL：Anheyu、CPA、Octopus、Lsky、AxonHub。
- Lsky 使用 `ghcr.io/walrus8364/lsky-pro` 镜像；镜像公开 tag 只有 `latest`、`amd64`、`arm64`，所以 1Panel 版本目录写真实应用版本 `2.1`，compose 保留 `latest@sha256`。
- 所有镜像都带 digest pin，安装时仍可追溯到不可变镜像内容。
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

## 维护约定

- 只收录当前实际需要维护的应用，不追求大而全。
- 版本目录必须写真实应用版本号，不使用 `latest` 作为目录名。
- 敏感配置只放在 1Panel 表单变量或运行环境中，不写入仓库模板。
- 修改应用模板后运行：

```bash
python scripts/validate-appstore.py
python scripts/sync-readme-app-table.py --check
python scripts/check-updates.py --no-fail
```

## 反馈

如发现配置错误或需要调整应用，请在 [Issues](https://github.com/Elykia093/appstore/issues) 反馈。1Panel 本体问题请前往 [1Panel 主项目](https://github.com/1Panel-dev/1Panel/issues)。
