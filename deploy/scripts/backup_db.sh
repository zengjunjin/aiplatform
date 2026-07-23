#!/usr/bin/env bash
#
# RAG 知识库平台 — PostgreSQL 数据库备份脚本
#
# 用法:
#   ./backup_db.sh [--dry-run]
#
# 环境变量（从 .env 或部署环境读取 PG 凭据）:
#   POSTGRES_HOST       PostgreSQL 主机地址        (默认: localhost)
#   POSTGRES_PORT       PostgreSQL 端口            (默认: 5432)
#   POSTGRES_USER       数据库用户名               (必填)
#   POSTGRES_PASSWORD   数据库密码                 (必填)
#   POSTGRES_DB         数据库名称                  (必填)
#   BACKUP_DIR          备份输出目录               (默认: ./backups)
#
# 保留策略 (7/30/365):
#   - 每日备份 (daily):   保留 7 天
#   - 每周备份 (weekly):  保留 30 天（每周日生成）
#   - 每月备份 (monthly): 保留 365 天（每月 1 号生成）
#
set -euo pipefail

# ─── 参数解析 ─────────────────────────────────────────────
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run)
      DRY_RUN=1
      ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *)
      echo "错误: 未知参数 '$arg'（可用: --dry-run）" >&2
      exit 1
      ;;
  esac
done

# ─── 配置 ─────────────────────────────────────────────────
PG_HOST="${POSTGRES_HOST:-localhost}"
PG_PORT="${POSTGRES_PORT:-5432}"
PG_USER="${POSTGRES_USER:?错误: POSTGRES_USER 未设置}"
PG_PASSWORD="${POSTGRES_PASSWORD:?错误: POSTGRES_PASSWORD 未设置}"
PG_DB="${POSTGRES_DB:?错误: POSTGRES_DB 未设置}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"

# 保留策略（天）
RETENTION_DAILY=7
RETENTION_WEEKLY=30
RETENTION_MONTHLY=365

# ─── 辅助函数 ─────────────────────────────────────────────
log()   { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
dry()   { [ "$DRY_RUN" -eq 1 ]; }
run()   { if dry; then log "[dry-run] 将执行: $*"; else "$@"; fi; }
today() { date '+%Y%m%d'; }
dow()   { date '+%u'; }   # 1=Mon..7=Sun
dom()   { date '+%d'; }

# 根据日期确定备份类型: 每月 1 号=monthly, 每周日=weekly, 其余=daily
backup_type() {
  if [ "$(dom)" = "01" ]; then
    echo "monthly"
  elif [ "$(dow)" = "7" ]; then
    echo "weekly"
  else
    echo "daily"
  fi
}

# ─── 主流程 ───────────────────────────────────────────────
TYPE="$(backup_type)"
TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
FILENAME="backup_${TYPE}_${PG_DB}_${TIMESTAMP}.dump"
FILEPATH="${BACKUP_DIR}/${FILENAME}"

log "开始 PostgreSQL 数据库备份"
log "  类型:   ${TYPE}"
log "  数据库: ${PG_DB}@${PG_HOST}:${PG_PORT}"
log "  用户:   ${PG_USER}"
log "  输出:   ${FILEPATH}"
if dry; then
  log "  模式:   dry-run（不会实际执行备份或清理）"
fi

# 确保备份目录存在
if dry; then
  log "[dry-run] 将创建目录: ${BACKUP_DIR}"
else
  mkdir -p "${BACKUP_DIR}"
fi

# 执行 pg_dump（custom 格式，支持并行恢复与选择性恢复）
export PGPASSWORD="${PG_PASSWORD}"
log "执行 pg_dump ..."
run pg_dump \
  -h "${PG_HOST}" \
  -p "${PG_PORT}" \
  -U "${PG_USER}" \
  -d "${PG_DB}" \
  -F c \
  --no-owner \
  --no-privileges \
  -f "${FILEPATH}"

if ! dry; then
  if [ -f "${FILEPATH}" ]; then
    SIZE=$(du -h "${FILEPATH}" | cut -f1)
    log "备份完成: ${FILEPATH} (${SIZE})"
  else
    log "错误: 备份文件未生成" >&2
    exit 1
  fi
fi

# ─── 保留策略清理 ─────────────────────────────────────────
# 按备份类型分别清理，确保 daily/weekly/monthly 各自独立保留
cleanup() {
  local pattern="$1"
  local days="$2"
  local label="$3"
  log "清理 ${label} 备份（保留 ${days} 天）: 模式=${pattern}"
  if [ ! -d "${BACKUP_DIR}" ]; then
    log "  备份目录不存在，跳过清理"
    return 0
  fi
  if dry; then
    # dry-run 模式下仅列出将被删除的文件
    find "${BACKUP_DIR}" -name "${pattern}" -type f -mtime +${days} -print 2>/dev/null | while read -r f; do
      log "[dry-run] 将删除: ${f}"
    done
  else
    find "${BACKUP_DIR}" -name "${pattern}" -type f -mtime +${days} -delete 2>/dev/null || true
  fi
}

cleanup "backup_daily_*"   "${RETENTION_DAILY}"   "每日"
cleanup "backup_weekly_*"  "${RETENTION_WEEKLY}"  "每周"
cleanup "backup_monthly_*" "${RETENTION_MONTHLY}" "每月"

unset PGPASSWORD
log "数据库备份流程完成"
