# Lsky Pro

兰空图床 Lsky Pro 的 1Panel 应用模板。

本模板使用 `ghcr.io/walrus8364/lsky-pro:latest` 镜像，容器内端口为 `80`，并将 `./data` 挂载到 `/var/www/html`。

安装时需要填写站点地址、授权密钥、管理员账号、管理员邮箱和管理员密码。PostgreSQL 连接信息由 1Panel 表单变量注入，Redis 可按需选择。
