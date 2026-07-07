# New API

基于 [QuantumNous/new-api](https://github.com/QuantumNous/new-api) 的大模型网关与 AI 资产管理系统。

本模板使用 `calciumion/new-api` 镜像，并通过 PostgreSQL 持久化数据。应用数据挂载到 `./data`，日志挂载到 `./logs`。

## 部署说明

- 服务端口：`3000`
- 数据库：PostgreSQL，连接信息由 1Panel 表单变量注入
- 数据目录：`./data`
- 日志目录：`./logs`
- 会话密钥：`SESSION_SECRET`

安装后请进入管理后台完成初始化，并及时修改默认管理员凭据。
