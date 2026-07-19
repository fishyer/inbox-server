---
status: accepted
---

# React 运维控制台与 Nginx 同源交付

当前管理能力分散在 API、Docker 日志和 Git 仓库，且系统已由 FastAPI、worker、Redis 与 PostgreSQL 组成。决定使用 React + TypeScript + Vite 构建组件化运维控制台，并由 Nginx 在唯一宿主机端口提供静态资源、反向代理受 `X-API-Key` 保护的 FastAPI；相比 FastAPI 直出静态页面，Nginx 明确隔离静态交付与 API 生命周期，同时继续保持单一 origin 和认证边界。具体需求与实施范围见 [`add-operations-console`](../../openspec/changes/add-operations-console/proposal.md)。
