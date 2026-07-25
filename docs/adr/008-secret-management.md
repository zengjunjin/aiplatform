# ADR-008: 密钥管理（环境变量 + 弱值黑名单）

## 状态

已采纳

## 日期

2026-07-21

## 上下文

平台阶段一（P0 Critical 修复）引入了多项安全约束，但密钥管理一直依赖开发者"自觉"设置强值，缺乏自动校验。具体问题：

- **JWT_SECRET / POSTGRES_PASSWORD 默认弱值**：`config.py` 默认值 `"change-me-in-production"` / `"rag_password"` 容易被直接带入生产环境。
- **CI/本地环境使用占位符**：CI workflows 使用 `JWT_SECRET=dev-secret-change-me` 这类占位符，与生产密钥混淆。
- **`.env` 文件被提交到 release 目录**：早期 `release/RAG知识库平台/backend/.env` 包含 `DEBUG=true` 与 `JWT_SECRET=change-me-in-production`，release 目录已从仓库移除，但密钥泄露风险仍需在启动校验中防范。
- **`/metrics` 端点引入新 token**：Task 10 新增 `METRICS_TOKEN` 配置项，无校验容易复用弱值。
- **JWT 引入 iss/aud 校验**：Task 阶段二新增 `JWT_ISSUER=rag-platform` / `JWT_AUDIENCE=rag-client`，旧 token 全部失效（Breaking Change），需要明确文档化。

关键约束：

- 不能引入 Vault / AWS Secrets Manager / SOPS 等外部密钥管理服务（本地部署优先）。
- 必须在应用启动时（`config.py` `model_post_init`）强制校验，不依赖部署文档。
- **无论 DEBUG 模式与否，弱密钥一律 `raise ValueError` 阻止启动**（Task 31 移除了原 DEBUG 模式仅告警的分支，避免 JWT_SECRET 弱密钥在开发环境被误用导致生产泄漏）。
- 必须覆盖 `JWT_SECRET` / `POSTGRES_PASSWORD` 两类核心密钥；其他密钥（`METRICS_TOKEN`/`OLLAMA_API_KEY` 等）暂不强制。

## 决策

采用 **环境变量 + Pydantic `model_post_init` 弱值黑名单校验** 作为密钥管理方案。

### 1. 弱值黑名单

在 `backend/app/config.py` 的 `model_post_init` 中维护已知弱值集合：

```python
KNOWN_WEAK_JWT_SECRETS = {
    "change-me-in-production",
    "dev-secret-change-me",
    "your-secret-key",
    "secret",
    "",
}
```

启动时校验：

```python
def model_post_init(self, __context):
    # pytest 环境跳过校验，便于测试使用任意配置
    if "pytest" in sys.modules:
        return
    problems: list[str] = []
    if len(self.JWT_SECRET) < 32:
        problems.append("JWT_SECRET 长度不足（最少 32 字符）")
    if self.JWT_SECRET in KNOWN_WEAK_JWT_SECRETS:
        problems.append("JWT_SECRET 命中已知弱值黑名单。")
    if self.POSTGRES_PASSWORD in KNOWN_WEAK_PG_PASSWORDS:
        problems.append("POSTGRES_PASSWORD 命中已知弱值黑名单。")
    if problems:
        # Task 31: 无论 DEBUG 模式与否都 raise（移除 warning 分支）
        raise ValueError("配置校验失败：\n  - " + "\n  - ".join(problems))
```

### 2. 环境变量优先级

- `.env` 文件提供默认值（开发用）
- 环境变量覆盖 `.env`（CI/生产用）
- `model_post_init` 在 Pydantic 校验后强制运行，是最后兜底

### 3. 密钥分类

| 类别       | 配置项                | 校验严格度                                   |
|------------|----------------------|----------------------------------------------|
| 必须强随机 | `JWT_SECRET`         | 黑名单 + 最小长度 32 字符                    |
| 必须强随机 | `POSTGRES_PASSWORD`  | 黑名单 + 最小长度 8 字符                     |
| 可选       | `METRICS_TOKEN`      | 不强制（默认 `None` 时 `/internal/metrics` 403） |
| 可选       | `OLLAMA_API_KEY`     | 不强制（默认 `None`）                         |

### 4. release 目录策略（已废弃）

- 早期仓库中 `release/RAG知识库平台/backend/.env` 用于一键启动演示环境，包含 `DEBUG=true` 与 `JWT_SECRET=change-me-in-production`。
- **该策略已废弃**：release 目录已从仓库移除，且 `change-me-in-production` 已被加入 `_WEAK_JWT_SECRETS` 黑名单，启动校验会直接 `raise ValueError` 拦截。
- 如需本地演示，请使用 `backend/.env.example` 中的 `JWT_SECRET=please_replace_with_a_long_random_string_at_least_32_chars`（此值同样在黑名单中，需替换为真实强随机值后方可启动）。
- 生产部署必须自行提供 `.env`，并将 `DEBUG=false` 与强随机 `JWT_SECRET`/`POSTGRES_PASSWORD` 写入。

### 5. JWT iss/aud Breaking Change

Task 阶段二已引入：

- `JWT_ISSUER = "rag-platform"`
- `JWT_AUDIENCE = "rag-client"`
- `decode_token` 同时校验 iss 与 aud

**Breaking Change**：所有阶段一之前签发的 token 全部失效，用户需重新登录。

## 后果

### 正面影响

- **启动即校验**：弱密钥在应用启动阶段就被拦截，避免带入生产。
- **DEBUG 模式同样严格**：Task 31 起无论 DEBUG 与否都阻止弱密钥启动，避免开发环境误用弱密钥后被带入生产。
- **统一密钥分类**：明确了哪些密钥必须强随机、哪些可选，未来新增配置可对号入座。
- **JWT 安全性提升**：iss/aud 校验让 token 不能跨服务复用，降低 token 泄露后的横向攻击面。

### 负面影响

- **Breaking Change**：iss/aud 引入后所有旧 token 失效，部署时需要通知所有在线用户重新登录。
- **弱值黑名单维护成本**：每次发现新的弱值模式都要手动加入黑名单（无法穷举）。
- **无法防止"看似强但实际弱"的密钥**：如 `aaaaaaaaaa...`（32 个 a）能通过黑名单但不安全；未来可考虑引入熵值校验。

## 替代方案

| 方案                      | 优点                                 | 缺点                                            | 为何未选择 |
|---------------------------|--------------------------------------|-------------------------------------------------|------------|
| HashiCorp Vault           | 动态密钥、自动轮换、审计日志         | 需额外部署 Vault 集群，本地部署场景过重          | 与项目"本地优先"约束冲突 |
| SOPS + age/PGP            | 加密 .env 文件，git 安全             | 仍需密钥分发（age key / PGP 私钥），增加运维复杂度 | 引入新工具链，收益有限 |
| docker secrets            | 容器原生，与 docker-compose 集成     | 仅适用于 docker 部署，本地开发与 Tauri 场景不适用 | 不覆盖全部部署模式 |
| 仅 .env 文档约定          | 零代码变更                           | 依赖开发者自觉，弱密钥仍可能带入生产              | 不可靠，违反"启动即校验"目标 |

## 参考

- [Pydantic Settings 文档](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [OWASP Cryptographic Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html)
- [RFC 7519 JWT §4.1.1 iss / §4.1.3 aud](https://www.rfc-editor.org/rfc/rfc7519)
- ADR-007: 可观测性技术栈（OTel 同样通过环境变量 `OTEL_EXPORTER_OTLP_ENDPOINT` 控制）
