# ADR-010: Alertmanager Webhook Receiver 自建实现

## 状态

已采纳

## 日期

2026-07-25

## 上下文

平台阶段五（可观测性）的告警链路需要将 Prometheus Alertmanager 触发的告警 webhook 转发到一个接收器，用于：

- 持久化告警记录到文件，便于事后审计与回溯
- 在容器日志中输出告警摘要，便于 `docker logs` 快速查看
- 作为 Alertmanager 的 webhook 接收端点，补全“告警生成 → 通知 → 留痕”链路

原方案使用第三方公开镜像 `ghcr.io/timberio/alertmanager-webhook-receiver`，存在以下问题：

- **镜像来源不可控**：第三方镜像更新节奏与安全补丁由外部维护者决定，无法自主把控
- **功能固化**：第三方实现的字段提取、日志格式、持久化路径无法按平台需求定制
- **供应链风险**：拉取 ghcr.io 公开镜像依赖外部仓库可用性，且无法保证镜像内容不变
- **审计需求未满足**：平台要求告警以 JSON Lines 格式落盘并保留原始 payload 以便审计，第三方镜像不支持该格式

关键约束：

- 接收器需在 docker-compose 中作为独立服务运行，与 Alertmanager 通过 webhook 对接
- 实现需轻量，不引入复杂依赖
- 告警日志需持久化到 docker volume，便于离线分析
- 需暴露健康检查端点供 docker healthcheck 使用

## 决策

选择 **自建 Python Flask + Gunicorn + 文件持久化** 方案，替代第三方镜像。

### 1. 应用框架：Flask

- 使用 Flask 作为轻量 HTTP 框架，仅需一个 `POST /webhook` 端点接收 Alertmanager payload，一个 `GET /healthz` 端点供健康检查。
- Flask 同步模型契合 webhook 接收场景（接收 → 写文件 → 返回 200），无需异步框架。
- 端口通过 `PORT` 环境变量配置（默认 5001）。

### 2. WSGI 服务器：Gunicorn

- 使用 Gunicorn 作为生产 WSGI 服务器，替代 Flask 内置 dev server。
- 提供多 worker 进程、优雅重启、生产级稳定性，避免 dev server 单线程瓶颈。

### 3. 持久化：JSON Lines 文件

- 每条告警以 JSON Lines 格式追加到 `/data/alerts.log`（docker volume 挂载点，路径可通过 `LOG_DIR` 环境变量覆盖）。
- 记录字段：`timestamp`、`status`（firing/resolved）、`alertname`、`severity`、`instance`、`summary`、`description`、`starts_at`、`ends_at`、`raw`（保留原始告警数据，便于审计）。
- 文件追加写入，无需数据库依赖，简单可靠。

### 4. 控制台摘要

- 同时将告警摘要打印到 stdout，格式：`[时间] [SEVERITY] [status] alertname - summary`，便于 `docker logs` 快速查看。
- 处理失败时通过 stderr 输出错误，不影响其他告警处理。

### 5. 健康检查

- 暴露 `GET /healthz` 返回 `{"status":"ok"}`，供 docker-compose healthcheck 使用。

### 6. 容错

- payload 校验：缺少 `alerts` 字段返回 400。
- 单条告警处理异常仅记录错误，不中断后续告警处理，整体接口仍返回 200 与接收数量。

## 后果

### 正面影响

- **完全可控**：字段提取、日志格式、持久化路径均按平台需求定制，无需妥协第三方实现。
- **审计友好**：JSON Lines 格式 + 原始 payload 保留，便于事后回溯与离线分析（`grep` / `jq` 即可查询）。
- **供应链安全**：自建镜像，构建过程透明，不依赖外部公开镜像仓库。
- **运维简单**：文件持久化无需数据库，docker volume 挂载即可；故障排查直接 `docker logs` 或查看 `alerts.log`。
- **与平台告警链路一体化**：Alertmanager → webhook-receiver → alerts.log，链路清晰，与 runbooks 告警描述对齐。

### 负面影响

- **需自行维护**：新增一个需要维护的组件（代码、Dockerfile、依赖更新），相比直接拉取第三方镜像多一份维护成本。
- **单点文件持久化**：`alerts.log` 单文件，未做轮转与压缩，长期运行可能增长过大（需配合 logrotate 或定期归档）。
- **无告警去重**：当前实现按 Alertmanager 推送原样落盘，不做去重，重复告警会重复记录。
- **Gunicorn + Flask 依赖体积**：镜像需包含 Python + Flask + Gunicorn，约 50-80MB。

## 替代方案

| 方案 | 优点 | 缺点 | 为何未选择 |
|------|------|------|------------|
| 第三方镜像 `ghcr.io/timberio/alertmanager-webhook-receiver` | 开箱即用，零开发成本 | 镜像来源不可控，功能固化，无法定制日志格式与审计字段，存在供应链风险 | 无法满足审计需求与自主可控要求 |
| Alertmanager 直接发邮件 / IM webhook | 无中间组件 | 无法持久化告警记录到本地文件，无法在 `docker logs` 查看摘要 | 缺少本地审计留痕能力 |
| 自建 Node.js / Go 接收器 | 性能好，二进制部署简单 | 引入新语言栈，与平台 Python 生态不一致 | 增加技术栈复杂度 |
| 写入数据库（PostgreSQL）持久化 | 支持复杂查询 | 引入数据库依赖，告警接收与 DB 强耦合，DB 故障会导致告警丢失 | 过度设计，文件持久化已满足审计需求 |
| 直接打印到 stdout（不写文件） | 实现最简单 | docker logs 轮转会丢失历史告警，无法长期审计 | 不满足持久化审计需求 |

## 参考

- 实现：
  - `deploy/alertmanager-webhook-receiver/app.py`：Flask 应用（webhook 接收 + 文件持久化 + 健康检查）
  - `deploy/docker-compose.yml`：`alertmanager-webhook-receiver` 服务定义
  - `deploy/alertmanager.yml`：Alertmanager webhook 接收器配置
- 相关 runbook：`docs/runbooks/` 下各告警处理流程，告警摘要格式与本接收器输出一致
