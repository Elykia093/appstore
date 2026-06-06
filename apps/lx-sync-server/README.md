# LX Sync Server

基于 [XCQ0607/lxserver](https://github.com/XCQ0607/lxserver) 的 LX Music 数据同步服务端增强版。

本模板使用 `ghcr.io/xcq0607/lxserver:latest` 镜像。

该项目主要使用本地目录持久化数据和日志；本模板按当前编排挂载 `./data:/server/data` 与 `./logs:/server/logs`。

安装时可配置前端管理密码、WebDAV 地址、WebDAV 用户名、WebDAV 密码，以及用户路径和根目录访问开关。官方 Docker 说明未提供 PostgreSQL 配置项。
