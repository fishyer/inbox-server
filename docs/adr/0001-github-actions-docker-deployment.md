---
status: accepted
---

# 使用 GitHub Actions 发布并部署 Docker Compose 服务

默认分支更新后，由 git-manager 生成的 GitHub Actions workflow 创建确定性 Release，并通过 `testing` Environment 的专用 SSH 身份部署到 `/apps/inbox-server/releases/`。运行配置固定保存在 `/apps/inbox-server/shared/`，发布目录通过 `current` 软链接切换，Docker Compose 项目名固定为 `inbox-server`，确保 Postgres 与 Redis 命名卷不随 Release 变化。该方案优先于把敏感配置打入仓库或为每个 Release 创建新 Compose 项目，因为它同时保持凭据隔离、发布可追溯性和持久化数据连续性。
