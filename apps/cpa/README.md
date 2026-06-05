# CPA

基于 [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) 的 AI CLI 统一代理服务。

本应用模板使用 PostgreSQL 存储配置和认证数据，并按当前编排挂载：

- `./config.yaml:/CLIProxyAPI/config.yaml`
- `./auths:/root/.cli-proxy-api`
- `./logs:/CLIProxyAPI/logs`

默认只暴露管理入口端口 `8317`。安装后访问管理界面，并使用安装时填写的管理密码继续配置上游与认证。
