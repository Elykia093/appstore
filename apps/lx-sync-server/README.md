# LX Sync Server

基于 [XCQ0607/lxserver](https://github.com/XCQ0607/lxserver) 的 LX Music 数据同步服务端增强版。

本模板使用 `ghcr.io/xcq0607/lxserver:v1.9.4` 镜像。

该项目主要使用本地目录持久化数据、日志、缓存和音乐文件；本模板挂载 `./data:/server/data`、`./logs:/server/logs`、`./cache:/server/cache` 与 `./music:/server/music`，并显式注入对应路径环境变量。

安装时可配置前端管理密码、WebDAV 地址、WebDAV 用户名、WebDAV 密码，以及用户路径和根目录访问开关。官方 Docker 说明未提供 PostgreSQL 配置项。
