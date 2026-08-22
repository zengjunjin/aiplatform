# Docker 容器化专项评审报告

**评审人**：架构师 高见远（Gao）
**日期**：2026-07-29
**范围**：backend/Dockerfile、frontend/Dockerfile、docker-compose.yml（根）、deploy/docker-compose.yml、deploy/nginx.conf、两个 Makefile、两个 .dockerignore、deploy/alertmanager-webhook-receiver/Dockerfile；关联文件（frontend/nginx.conf、deploy/promtail.yml、deploy/prometheus.yml、deploy/docker-compose.dev.yml、deploy/docker-compose.prod.yml、backend/pyproject.toml、backend/app/config.py、README.md）
**方法**：纯静态配置评审（daemon 未启动），所有结论均标注文件:行号

---

## 一、总体评价

**容器化成熟度：7/10。**

这套 18 服务的编排展现出明显超出秋招平均水平的工程素养：多阶段构建的层缓存设计、非 root 运行、强制密钥（`:?` 语法）、健康检查分层（liveness/readiness 分离、backend 刻意不等 ollama 的降级设计）、完善的 dev/prod override 体系。但三处硬伤拉低"可重现交付"得分：**dev/prod 边界没守住**（源码 bind mount 与 GPU reservations 混进默认 compose 文件）、**torch 构建先下 5GB CUDA 再卸载**的带宽浪费、**文档漂移**（README 声称 TLS、指向已失效的 deploy/Makefile）。修复 TOP 5 后可到 8.5/10。

---

## 二、问题清单

### P0 — 会导致启动失败 / 运行错误

#### P0-1 Ollama GPU reservations 使无 N 卡机器 `compose up` 报错【疑点3，属实】

- **位置**：deploy/docker-compose.yml:85-91
- **问题**：`deploy.resources.reservations.devices`（driver: nvidia, count: all）在 compose v2 中**会被实际执行**（与 `deploy.resources.limits` 不同，后者被忽略）。在无 NVIDIA GPU、或未安装 nvidia-container-toolkit 的机器（含所有 Mac、多数面试官笔记本）上，ollama 容器创建失败，报 `could not select device driver "nvidia" with capabilities: [[gpu]]`，`up` 以非零码退出并打印红色错误。
- **影响**：其余服务因 backend/celery 不 depends_on ollama（compose:137-143 仅等 postgres/redis/qdrant）照常启动，应用层有降级——栈"大体可用但开局报错"，演示第一印象受损。作者本机有 N 卡 + WSL2 CUDA 穿透，完全无感。
- **建议**：将 GPU 块迁移到 `deploy/docker-compose.gpu.yml` override，默认 compose 为 CPU-only；README 注明有 N 卡时用 `-f deploy/docker-compose.yml -f deploy/docker-compose.gpu.yml up -d`。

#### P0-2 fresh clone 缺 deploy/.env 时 compose 直接拒绝启动（README 未提示）

- **位置**：deploy/docker-compose.yml:10（`POSTGRES_PASSWORD:?...`）、:284（`GRAFANA_ADMIN_PASSWORD:?...`）、:115-116 与 :173-174（`env_file: .env`）；README.md:111-129
- **问题**：两个强制变量无兜底，且 backend/celery 声明 `env_file: .env`（相对 deploy/ 解析，即 deploy/.env）。fresh clone 后未执行 `cp deploy/.env.example deploy/.env` 并填密码时，`docker compose up` 在变量插值阶段即报错退出。README 的"方式一: Docker Compose"quickstart（README:118 `docker-compose up -d`）**通篇未提 .env 这一步**。
- **影响**：面试官按 README 操作必翻车，且报错信息对不熟悉 compose `:?` 语法的人不直观。作者本机 deploy/.env 已存在（仓库中有此文件但应被 gitignore），所以从未踩到。
- **建议**：README quickstart 第一步加 `cp deploy/.env.example deploy/.env` 并说明必填项；`.env.example` 中 POSTGRES_PASSWORD/GRAFANA_ADMIN_PASSWORD 可给"仅本地演示用"的示例值并注释警告。

### P1 — 明显反模式 / 效率问题

#### P1-1 backend/celery 把宿主机源码 bind mount 到 /app/app，镜像代码被运行时遮蔽【疑点1，属实，反模式成立】

- **位置**：deploy/docker-compose.yml:144-149（backend：storage + alembic + app）、:204-207（celery：storage + app）
- **问题**：`../backend/app:/app/app` 使 backend/Dockerfile:45 `COPY . .` 及 runtime 阶段 :70 `COPY --from=builder` 拷贝的代码在运行时被完全覆盖。镜像不再是自包含交付物——"构建产物"与"运行内容"脱钩，`docker run` 镜像与 `compose up` 行为不一致。注释（:147-148）表明动机是"改代码不用重建镜像"，这是开发期诉求，但写进了**默认** compose 文件。更说明问题的是：deploy/docker-compose.dev.yml:19-30 **重复声明了同样的挂载**——作者本意是放 dev override，主文件忘删，dev.yml 沦为纯重复。
- **影响**：(a) "容器化交付"叙事被面试官一问即穿（"你的镜像里跑的到底是哪份代码？"）；(b) 镜像里那份代码成为死重，且与 host 代码漂移时产生"改了代码没生效/生效了但不知道为什么"类困惑；(c) backend 还挂载 `../backend/alembic:/app/alembic`（:146），与启动命令 `alembic upgrade head`（:153-155）耦合——host 迁移文件被误删/未更新时容器启动即失败；(d) Windows host 的 CRLF、`__pycache__` 会被带进 Linux 容器（Python 兼容 CRLF，风险低但脏）。
- **建议**：默认 compose 删除 `:146` 与 `:149`、`:207` 三条源码/迁移挂载（storage 数据挂载可保留），dev 挂载由 deploy/docker-compose.dev.yml 独占接管（已有现成声明）。交付形态 = 镜像自包含；开发形态 = `-f docker-compose.yml -f docker-compose.dev.yml`。

#### P1-2 torch 先装 CUDA 版（~5GB）再卸载换装 CPU 版，构建带宽巨大浪费【疑点2，属实】

- **位置**：backend/pyproject.toml:42（torch 仅由 `sentence-transformers = "^3.0.0"` 传递引入，**无 torch 显式依赖、无 pytorch source**）；backend/Dockerfile:30（poetry install 拉 CUDA torch）→ :37-41（uninstall 20 个包）→ :42（装 CPU torch==2.12.1）
- **问题**：poetry 从 PyPI 默认源解析出 CUDA 版 torch 及全套 nvidia-* 依赖（约 4-5GB 下载），安装后立刻卸载。每次无缓存构建都浪费 ~5GB 带宽与数分钟构建时间。
- **附带脆弱点**：:37-41 的卸载清单硬编码了 `nvidia-cudnn-cu13`、`nvidia-nccl-cu13` 等 **cu13 后缀包名**，且 `2>/dev/null;` 吞掉所有错误——poetry.lock 未来解析到不同 CUDA 代际（cu12/cu126 等）时卸载静默失败，CUDA 库残留镜像内而无人察觉；pip 安装的 torch==2.12.1 与 poetry.lock 中 sentence-transformers 解析时的 torch 版本可能不一致（当前约束 torch>=1.11 尚兼容）。
- **建议**：在 pyproject.toml 声明专用源并显式 pin：
  ```toml
  [[tool.poetry.source]]
  name = "pytorch-cpu"
  url = "https://download.pytorch.org/whl/cpu"
  priority = "explicit"

  [tool.poetry.dependencies]
  torch = { version = "2.12.1+cpu", source = "pytorch-cpu" }
  ```
  然后删除 Dockerfile:35-42 整个卸载/重装块。本机 GPU 开发需求可用 poetry group 或单独的 requirements  Overlay 解决。

#### P1-3 双 Makefile 漂移，deploy/Makefile 已实际失效且拉错模型【疑点5，属实且更严重】

- **位置**：根 Makefile（新版，`docker compose -f deploy/docker-compose.yml`，正确）vs deploy/Makefile（旧版残留）
- **问题**：
  1. deploy/Makefile 所有 target 均为 `cd deploy && docker-compose ...`（:18,21,24,27,30,33,36-38,44,47）：(a) `docker-compose` 是 v1 语法，Docker Desktop 靠 compose-switch 兼容、裸 Linux 直接 command not found；(b) 该文件**自身位于 deploy/ 内**，在 deploy/ 里执行 make 时 `cd deploy` 目标不存在，全部 target 失败——它是"只能在仓库根目录用 `make -f deploy/Makefile` 调用"的怪胎。
  2. init-models 漂移：根 Makefile:40-43 拉 qwen2.5:7b + **bge-m3** + bge-reranker-base，与应用配置一致（backend/app/config.py:95 `EMBEDDING_MODEL = "bge-m3"` ✓）；deploy/Makefile:35-38 拉 qwen2.5:7b + **nomic-embed-text** + bge-reranker-base——模型错了，fresh 环境若按旧版初始化，embedding 调用会失败或触发隐式拉取阻塞。
  3. README:94 仍写"项目在 deploy/ 目录提供了 Makefile"、README:109 称"Makefile 会自动 cd deploy && docker-compose"、README:118 quickstart 用 v1 语法 `docker-compose up -d`——文档全面指向旧版。
- **建议**：删除 deploy/Makefile；README 改为指向根 Makefile 并统一 `docker compose`（v2，空格）语法。

#### P1-4 Prometheus bearer_token 硬编码，fresh 部署后 backend 指标抓取 401

- **位置**：deploy/prometheus.yml:15（`bearer_token: 'acceptance-test-metrics-token-2026-xyz-abc-123'` 字面值）vs deploy/.env.example:147（`METRICS_TOKEN=` 默认为空）
- **问题**：prometheus.yml 注释（:12-14）自述"token 必须与 .env 中 METRICS_TOKEN 一致"，但 .env.example 留空并引导用户自填——fresh 部署或重置 .env 后，Prometheus 抓取 backend `/internal/metrics` 稳定 401。prod override 已有正确解法（docker-compose.prod.yml:82-86 用 entrypoint + envsubst 注入），但默认流程用不上。
- **影响**：演示时 Grafana 主 dashboard（rag-platform-overview.json）backend 面板全空，"完整可观测性"叙事塌一半。作者本机 .env 恰好与硬编码值一致，所以无感。
- **建议**：默认 compose 也采用 prod 的 envsubst 模式（把 :82-86 的 entrypoint/volumes 写法并入主文件），或在 .env.example 中把 METRICS_TOKEN 示例值设为与 prometheus.yml 一致并加粗注释"两者必须同步修改"。

#### P1-5 10 个服务缺 logging 轮转，长开机写爆 vhdx

- **位置**：已配 json-file 10m×3 轮转的仅 8 个服务：postgres(:23-27)、redis(:43-47)、qdrant(:68-72)、ollama(:103-107)、backend(:162-166)、celery_worker(:217-221)、jaeger(:372-376)、nginx(:454-458)。**未配置**的：prometheus(:225-241)、redis-exporter(:244-252)、node-exporter(:255-269)、grafana(:272-293)、loki(:296-312)、promtail(:315-326)、flower(:329-343)、alertmanager(:378-392)、alertmanager-webhook-receiver(:395-416)、nginx-exporter(:461-471)。
- **影响**：这些服务容器日志无界增长，直接写入 G:\DockerData 的 ext4.vhdx（只增不缩，见 P2-6）；配合 promtail 采集场景长时间开机，磁盘膨胀可观。
- **建议**：compose 文件顶部加 anchor（`x-logging: &default-logging`）统一挂载，一处改全栈生效。

### P2 — 改进建议

#### P2-1 版本 pinning 不一致，且比预想的更广【疑点4，属实，需修正表述】

- **位置**：浮动最新标签：prom/prometheus:**latest**（:226）、grafana/grafana:**latest**（:273）、nginx:**alpine**（:437）。只 pin major/minor（patch 浮动）：postgres:16-alpine(:5)、redis:7-alpine(:30)、mher/flower:2.0(:330)、jaegertracing/all-in-one:1.60(:349)、python:3.12-slim（backend/Dockerfile:4,54；webhook Dockerfile:1）、node:20-alpine（frontend/Dockerfile:2）、nginx:1.27-alpine（frontend/Dockerfile:13）。完整 pin 的仅 8 个：qdrant:v1.18.3、ollama:0.3.14、redis_exporter:v1.59.0、node-exporter:v1.8.2、loki:2.9.0、promtail:2.9.0、alertmanager:v0.27.0、nginx-exporter:1.1.0。
- **影响**："其余 12 个镜像都 pin 了版本"的说法不成立。最大实际风险是 grafana:latest 跨大版本升级导致 provisioning/dashboard JSON 不兼容（演示前一天 `docker compose pull` 即可能翻车）。
- **建议**：至少把三个浮动标签 pin 到当前验证过的 minor 版本（如 grafana/grafana:11.x、prom/prometheus:v2.x、nginx:1.27-alpine）；追求严格可重现可用 digest。

#### P2-2 nginx HSTS 配在纯 HTTP 上，README 却声称 TLS【疑点7，属实，文档漂移】

- **位置**：deploy/nginx.conf:74（`Strict-Transport-Security` 在 `listen 80`(:48) 的 server 块，全文件无 443/ssl_certificate）；README.md:43（架构图 "Nginx<br/>反向代理 + TLS + CSP"）
- **问题**：浏览器对 HTTP 响应的 HSTS 头直接忽略——该配置无害但无效；README 声称的 TLS 在实现中不存在。
- **建议**：秋招项目不必真上 TLS，删除 HSTS 头并把 README 架构图改为 "反向代理 + 安全响应头（CSP 等）"。面试被问"你的 TLS 证书在哪"时是明确扣分点。

#### P2-3 node-exporter 监控的是 WSL2 VM 而非 Windows 宿主机；promtail 路径反而正确【疑点6，属实，需分层判断】

- **位置**：node-exporter 挂载 /proc /sys /（compose:259-262）；promtail 挂载 /var/lib/docker/containers(:319) + docker.sock(:320)，promtail.yml:17 用 docker_sd
- **判断**：两个路径在 Docker Desktop WSL2 下都解析到 **VM 内部**。promtail 的目标是"采集容器日志"——容器日志本就写在 VM 的 /var/lib/docker/containers 下，**配置有效且语义正确**。node-exporter 拿到的是 VM 的 CPU/内存/vhdx 磁盘，**不是 Windows 宿主机**——功能有效但 Grafana 上"宿主机"面板名不副实。
- **建议**：README 可观测性章节注明此边界（演示时 vhdx 磁盘水位反而可当话题）；dashboard 标题改为 "Docker VM (WSL2)"。

#### P2-4 健康检查矩阵不完整 + backend start_period 偏紧【疑点9，属实】

- **位置**：无 healthcheck 的服务：prometheus、grafana、redis-exporter、node-exporter、promtail、flower、alertmanager、nginx-exporter（loki:304-309、jaeger:363-368 有）。backend start_period 40s（:161）vs 启动命令先跑 `alembic upgrade head`（:153-155）。nginx healthcheck 用 `nginx -t`（:447）只测配置不测服务。frontend/nginx 对 backend 的 depends_on 是 service_started（:424-425, :443-445）。
- **影响**：18 服务并发冷启动时 CPU 争抢 + WSL2 IO，alembic 首迁超过 40s 的概率不为零；backend 被标 unhealthy 后 compose 不重启（restart 策略不响应 health），nginx 照启，/api 全部 502——"页面能开、接口全挂"。
- **建议**：backend start_period 提到 90s（或 command 前加 `until curl...` 等待）；observability 服务补 healthcheck（prod 文件 :97-101,:116-120,:150-154,:181-185,:198-202,:227-231,:282-286 已有现成写法可抄）；nginx healthcheck 改 `wget -qO- http://127.0.0.1:8080/stub_status`。

#### P2-5 alertmanager-webhook-receiver 与全仓硬化标准不一致

- **位置**：deploy/alertmanager-webhook-receiver/Dockerfile——无 USER 指令（root 运行，对比 backend/Dockerfile:83、frontend/Dockerfile:25）；:12 `VOLUME ["/data"]` 与 compose:405 bind mount 重复；requirements.txt:3 把 pytest==8.3.2 打进生产镜像。
- **建议**：加非 root 用户；删 VOLUME 行；pytest 移出 requirements.txt。

#### P2-6 G:\DockerData vhdx 只增不缩 + 本项目约 23GB 数据，需运维预案【疑点10，属实】

- **问题**：Docker Desktop WSL2 的 ext4.vhdx 删除容器/镜像后**不自动回缩**；本项目 8 个 named volume（compose:473-483）+ ollama 三个模型（qwen2.5:7b ~4.7GB、bge-m3 ~1.2GB、bge-reranker ~0.5GB）+ 18 个服务镜像（backend 约 1.5GB），累计 ~23GB。
- **建议**（写入 README 运维章节）：
  1. 演示季定期 `docker system prune`（注意 `-a --volumes` 会删数据卷，ollama 模型卷别误删）；
  2. vhdx 压缩：`wsl --shutdown` 后用 `diskpart` → `select vdisk file="G:\DockerData\...\ext4.vhdx"` → `compact vdisk`（或 Hyper-V 的 Optimize-VHD）；
  3. prometheus 已配 retention 7d/2GB（:236-237）是对的；补全 P1-5 的日志轮转是减缓膨胀的直接手段。

#### P2-7 其他杂项

- **端口冲突**：5432/6379/6333/80/3000/9090 全 publish 宿主机，面试官机器若装了本地 Postgres/Redis 即冲突。已全部参数化（`${POSTGRES_PORT:-5432}` 等，compose:12,32,52-53）是对的，README 应提示冲突时改 .env。
- **deploy/ 目录混杂**：test_*.json、tauri_cdp_*.mjs、backend_logs*.txt、celery_build.log 等十余个测试产物与核心编排文件同居一目录；compose:405 挂载的 ./logs/alertmanager 不存在时会被 Docker 以 root 创建。建议清理。
- **Makefile 依赖 bash**：根 Makefile backup(:51-54) 用 `set -a && . ./deploy/.env`，Windows 需 Git Bash；README 应同时给出纯 docker compose 命令路径。
- **frontend 内层 nginx 的 CSP 是死配置**：frontend/nginx.conf:17,31 的 add_header 会被外层 deploy/nginx.conf:55-59 `proxy_hide_header` 丢弃，真正生效的是外层 :69。不影响行为，但易造成"改内层 CSP 不生效"的困惑，建议注释说明。

---

## 三、疑点 8 专项裁决：双 nginx 是冗余还是合理分层？

**裁决：合理分层，不是冗余。** frontend/Dockerfile:13-15 用 nginx:1.27-alpine 服务 SPA，frontend/nginx.conf:23-25 处理 `try_files` SPA fallback、:27-29 给静态资源 1 年 immutable 缓存——职责是"静态资源优化"；外层 deploy/nginx.conf 做路由分发（/api :76-89、/ws :91-103 含 WebSocket upgrade、/docs 等）、统一安全头且用 `proxy_hide_header`（:55-59）主动消除与上游的重复、暴露 stub_status（:36-44 带网段白名单）供 exporter 抓取——职责是"边缘网关"。作者对双层的重复问题有清醒认知并做了处理。代价是多一跳代理和一个容器，对 18 服务栈可接受。**唯一可议项**：内层 CSP 为死配置（见 P2-7）。

---

## 四、容器化亮点（秋招视角）

1. **教科书级多阶段构建**：backend/Dockerfile:19 先 COPY pyproject.toml/poetry.lock 再装依赖、:45 最后 COPY 源码——层缓存最大化；poetry 版本锁定（:14 poetry==1.8.3）；apt `--no-install-recommends` + 清 lists（:11,:64）；builder 清 poetry/pip cache（:32-33）；runtime 清 .venv 的 `__pycache__/share/man`（:73-77）。面试可直接讲。
2. **非 root 运行细节到位**：backend:65 显式 uid 1000 + :83 USER；frontend:21-25 连 nginx pid 的 /run 目录权限都处理了——说明真踩过坑。
3. **密钥管理有骨气**：POSTGRES_PASSWORD/GRAFANA_ADMIN_PASSWORD 用 `:?` 强制、拒绝默认弱密码（compose:9-10 注释写明理由）。
4. **健康检查架构理念正确**：/healthz（进程存活）与 /readyz（依赖探测）分离且注释清晰（nginx.conf:105-116）；backend 刻意不 depends_on ollama——应用层降级优先于编排层强耦合，这是有架构品味的决定。
5. **依赖编排规范**：全栈 depends_on + `condition: service_healthy`（:137-143,:197-203,:336-340）。
6. **对基础镜像的认知深度**：qdrant 镜像无 curl/wget，改用 `bash /dev/tcp` 做健康检查（compose:59-61 注释说明原因）。
7. **.dockerignore 两份都精细**：backend 排除 tests/storage/.env/scripts（含逐条注释理由），frontend 连 src-tauri、vitest/eslint 配置都排了。
8. **全栈资源限制**：18 个服务每个都有 mem_limit + cpus，演示机不会 OOM 连环炸。
9. **prod override 体系完整**：docker-compose.prod.yml 有 cap_drop ALL、no-new-privileges、envsubst 注入 token、redis requirepass、qdrant apikey——证明作者知道 dev/prod 差异（问题只是默认文件没守住边界）。
10. **根 compose 用 include**（docker-compose.yml:4-5）做一行入口，符合 compose 规范相对路径解析。
11. **日志/追踪/指标三件套齐备**：OTel OTLP 到 Jaeger（:133-134）、LOG_JSON 结构化（:136）、promtail→loki→grafana 链路、alertmanager→webhook 落盘——可观测性叙事完整。

---

## 五、秋招演示场景风险评估（面试官现场 `docker compose up` 可能踩的坑，按概率排序）

| # | 风险 | 概率 | 触发条件 | 后果 | 预案 |
|---|------|------|----------|------|------|
| 1 | ollama GPU reservations 报错 | **高** | 面试官机器无 N 卡 / 无 nvidia-container-toolkit（Mac 必中） | ollama 创建失败，up 红字退出 | 默认 compose 改 CPU-only（P0-1） |
| 2 | 未建 deploy/.env 直接起不来 | **高**（若让对方自己跑） | README quickstart 未提此步 | `POSTGRES_PASSWORD must be set` 报错 | README 补步骤（P0-2） |
| 3 | METRICS_TOKEN 不一致 → Grafana 主 dashboard 空白 | **中高** | 换机/重置 .env 后自填 token | 可观测性演示翻车 | envsubst 注入（P1-4） |
| 4 | 首次构建拉 ~5GB CUDA torch 再卸载 | **中** | 现场无镜像缓存重新 build | 构建 20-40 分钟，现场网络翻车 | pytorch-cpu source（P1-2）+ 演示前预构建并 `docker save` 备份 |
| 5 | ollama 模型未预拉取 | **中** | fresh 环境未跑 init-models；或误用 deploy/Makefile 拉到错误的 nomic-embed-text | 现场问答超时/报错 | 预拉取 + 删旧 Makefile（P1-3） |
| 6 | 端口冲突（5432/6379/80/3000） | **中** | 对方机器装有本地 Postgres/Redis 等 | 对应服务起不来 | .env 改端口（已参数化，README 需提示） |
| 7 | grafana:latest 拉到新大版本 | **低中** | 演示前 `docker compose pull` | dashboard provisioning 不兼容 | pin 版本（P2-1） |
| 8 | backend alembic 冷启动超 40s → unhealthy + /api 502 | **低** | 低配置机器 18 服务并发冷启 | 页面能开接口全挂 | start_period 90s（P2-4） |
| 9 | 问答翻车点：TLS 在哪 / HSTS 为何无效 / node-exporter 监控的是哪台机器 / "镜像里的代码和挂载的代码哪份生效" | **低**（取决于面试官深度） | 追问环节 | 印象分损失 | 按 P2-2/P2-3 修文档，P1-1 修架构 |

**演示日建议**：永远在自己机器上演示 + 提前 `docker compose up -d` 预热 + ollama 模型预拉 + 准备 `docker save` 的镜像 tarball 离线兜底。

---

## 六、TOP 5 优先改进项

1. **【P0-1】ollama GPU 块移入 `deploy/docker-compose.gpu.yml`**，默认 compose 保证任意机器（含 Mac/无 N 卡笔记本）可起。
2. **【P1-1 + P0-2】默认 compose 删除 backend/celery 的源码与 alembic bind mount**（dev.yml 已有现成声明可接管），README quickstart 补 `cp deploy/.env.example deploy/.env` 步骤——镜像回归自包含交付，fresh clone 按文档可起。
3. **【P1-2】pyproject.toml 加 pytorch-cpu source 并显式 pin torch（+cpu）**，删除 backend/Dockerfile:35-42 的卸载/重装块——构建省 5GB，消除 cu13 硬编码清单的静默失效风险。
4. **【P1-3 + P2-1】删除 deploy/Makefile 并修正 README 指向**；pin prom/prometheus、grafana/grafana、nginx 三个浮动标签——消除运维入口歧义与 pull 翻车风险。
5. **【P1-4 + P1-5】prometheus.yml 的 bearer_token 改 envsubst 启动注入**（抄 prod 文件现成模式）；用 compose anchor 给全部服务统一补 logging 轮转与 healthcheck——可观测性演示不再依赖"token 恰好一致"的运气，vhdx 膨胀受控。

---

*报告完。评审基于静态配置精读，未执行任何 docker 命令，未修改任何被评审文件。*
