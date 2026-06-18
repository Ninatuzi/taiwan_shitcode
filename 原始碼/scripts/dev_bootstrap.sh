#!/usr/bin/env bash
# Dev infra bootstrap for the BMS platform.
# 安装/启动 PostgreSQL + pgvector + Redis，并建库建扩展。
#
# 特点：
#   - 失败即停、绝不假装成功（每一步都有错误检查）。
#   - 自动探测 PG / Redis 二进制名与路径（兼容不同发行版）。
#   - 离线友好：可跳过联网安装、pgvector 可吃本地源码。
#
# 可用环境变量覆盖：
#   PGDATA         PG 数据目录（默认 /var/lib/pgsql/15/data）
#   PGPORT         PG 端口（默认 5432）
#   PGVECTOR_SRC   pgvector 源码目录（离线：解压好的源码路径）
#   SKIP_INSTALL=1 跳过 dnf 安装（离线机已手动装好系统包时用）
#   PGVECTOR_VERSION  联网拉取时的版本（默认 v0.8.0）
set -uo pipefail

PGDATA="${PGDATA:-/var/lib/pgsql/15/data}"
PGPORT="${PGPORT:-5432}"
PGVECTOR_SRC="${PGVECTOR_SRC:-}"
SKIP_INSTALL="${SKIP_INSTALL:-0}"
PGVECTOR_VERSION="${PGVECTOR_VERSION:-v0.8.0}"

log()  { echo "[bootstrap] $*"; }
die()  { echo "[bootstrap][ERROR] $*" >&2; exit 1; }

# ── 探测二进制（PATH + 常见 PG 安装目录）──
find_bin() {
  local n="$1" p d
  p="$(command -v "$n" 2>/dev/null)" && { echo "$p"; return 0; }
  for d in /usr/pgsql-*/bin /usr/lib/postgresql/*/bin /usr/local/pgsql/bin; do
    [ -x "$d/$n" ] && { echo "$d/$n"; return 0; }
  done
  return 1
}

# ───────────────────────── 1. 安装系统包 ─────────────────────────
if [ "$SKIP_INSTALL" != "1" ] && ! find_bin initdb >/dev/null 2>&1; then
  if command -v dnf >/dev/null 2>&1; then
    log "用 dnf 安装 postgresql15 + redis6 + 编译工具 ..."
    dnf install -y postgresql15-server postgresql15-contrib redis6 gcc make git \
      || die "dnf 安装核心包失败（离线机请改用 SKIP_INSTALL=1 并先手动装好）"
    dnf install -y --allowerasing postgresql15-server-devel \
      || die "dnf 安装 postgresql15-server-devel 失败"
  else
    die "未找到 dnf 且 initdb 不存在。离线机请先手动安装 PG/Redis/gcc，然后用 SKIP_INSTALL=1 重跑。"
  fi
else
  log "跳过系统包安装（SKIP_INSTALL=$SKIP_INSTALL）"
fi

# ── 定位关键二进制 ──
INITDB="$(find_bin initdb)"   || die "找不到 initdb"
PG_CTL="$(find_bin pg_ctl)"   || die "找不到 pg_ctl"
PSQL="$(find_bin psql)"       || die "找不到 psql"
PG_CONFIG="$(find_bin pg_config)" || die "找不到 pg_config（pgvector 编译需要 *-server-devel）"

REDIS_SERVER=""; REDIS_CLI=""
for s in redis-server redis6-server valkey-server; do command -v "$s" >/dev/null 2>&1 && { REDIS_SERVER="$s"; break; }; done
for c in redis-cli redis6-cli valkey-cli;    do command -v "$c" >/dev/null 2>&1 && { REDIS_CLI="$c"; break; }; done
[ -n "$REDIS_SERVER" ] || die "找不到 redis-server / redis6-server"
[ -n "$REDIS_CLI" ]    || die "找不到 redis-cli / redis6-cli"
log "PG: $INITDB | Redis: $REDIS_SERVER / $REDIS_CLI"

# ───────────────────────── 2. 编译安装 pgvector ─────────────────────────
EXT_DIR="$("$PG_CONFIG" --sharedir)/extension"
if ! ls "$EXT_DIR/vector.control" >/dev/null 2>&1; then
  SRC="$PGVECTOR_SRC"
  if [ -z "$SRC" ]; then
    for cand in ./pgvector ./pgvector-* /tmp/pgvector; do [ -d "$cand" ] && { SRC="$cand"; break; }; done
  fi
  if [ -z "$SRC" ]; then
    command -v git >/dev/null 2>&1 || die "需要 pgvector 源码：离线请设 PGVECTOR_SRC=/解压路径，或把源码放到 ./pgvector"
    log "联网拉取 pgvector $PGVECTOR_VERSION ..."
    rm -rf /tmp/pgvector
    git clone --depth 1 --branch "$PGVECTOR_VERSION" https://github.com/pgvector/pgvector.git /tmp/pgvector \
      || die "git clone pgvector 失败（离线？请改用 PGVECTOR_SRC 提供本地源码）"
    SRC=/tmp/pgvector
  fi
  log "从源码编译 pgvector: $SRC"
  ( cd "$SRC" && make clean >/dev/null 2>&1; make PG_CONFIG="$PG_CONFIG" ) || die "pgvector 编译失败"
  ( cd "$SRC" && make PG_CONFIG="$PG_CONFIG" install ) || die "pgvector 安装失败"
  ls "$EXT_DIR/vector.control" >/dev/null 2>&1 || die "pgvector 安装后仍找不到 vector.control"
  log "pgvector 已安装到 $EXT_DIR"
else
  log "pgvector 已存在，跳过编译"
fi

# ───────────────────────── 3. postgres 系统用户 ─────────────────────────
id postgres >/dev/null 2>&1 || useradd -r -m -d /var/lib/pgsql postgres || die "创建 postgres 用户失败"
mkdir -p "$(dirname "$PGDATA")"
chown -R postgres:postgres "$(dirname "$PGDATA")" 2>/dev/null || true

# ───────────────────────── 4. initdb ─────────────────────────
if [ ! -f "$PGDATA/PG_VERSION" ]; then
  log "初始化 PGDATA: $PGDATA"
  su postgres -c "$INITDB -D '$PGDATA' -U postgres --auth=trust --encoding=UTF8" \
    || die "initdb 失败"
fi

# ───────────────────────── 5. 启动 PostgreSQL ─────────────────────────
if ! su postgres -c "$PG_CTL -D '$PGDATA' status" >/dev/null 2>&1; then
  log "启动 PostgreSQL :$PGPORT"
  su postgres -c "$PG_CTL -D '$PGDATA' -l /tmp/pg.log -o '-p $PGPORT' -w start" \
    || { echo '--- /tmp/pg.log ---'; cat /tmp/pg.log 2>/dev/null; die "PostgreSQL 启动失败"; }
fi
su postgres -c "$PG_CTL -D '$PGDATA' status" >/dev/null 2>&1 || die "PostgreSQL 未在运行"

# ───────────────────────── 6. 建库 + 角色 + 扩展 ─────────────────────────
su postgres -c "$PSQL -p $PGPORT -tc \"SELECT 1 FROM pg_roles WHERE rolname='bms'\"" 2>/dev/null | grep -q 1 \
  || su postgres -c "$PSQL -p $PGPORT -c \"CREATE ROLE bms LOGIN PASSWORD 'bms';\"" >/dev/null 2>&1 \
  || die "创建角色 bms 失败"
su postgres -c "$PSQL -p $PGPORT -tc \"SELECT 1 FROM pg_database WHERE datname='bms'\"" 2>/dev/null | grep -q 1 \
  || su postgres -c "$PSQL -p $PGPORT -c \"CREATE DATABASE bms OWNER bms;\"" >/dev/null 2>&1 \
  || die "创建数据库 bms 失败"
su postgres -c "$PSQL -p $PGPORT -d bms -c \"CREATE EXTENSION IF NOT EXISTS vector;\"" >/dev/null 2>&1 \
  || die "启用 vector 扩展失败"

# ───────────────────────── 7. 启动 Redis ─────────────────────────
if ! "$REDIS_CLI" -p 6379 ping >/dev/null 2>&1; then
  log "启动 Redis :6379"
  "$REDIS_SERVER" --daemonize yes --port 6379 >/tmp/redis_start.log 2>&1 || die "Redis 启动命令失败"
  sleep 1
fi
"$REDIS_CLI" -p 6379 ping >/dev/null 2>&1 || die "Redis 未响应 ping"

# ───────────────────────── 8. 校验并报告（任何 DOWN 即非零退出）─────────────────────────
PG_OK=$(su postgres -c "$PG_CTL -D '$PGDATA' status" >/dev/null 2>&1 && echo UP || echo DOWN)
REDIS_OK=$("$REDIS_CLI" -p 6379 ping 2>/dev/null || echo DOWN)
VEC=$(su postgres -c "$PSQL -p $PGPORT -d bms -tc \"SELECT extversion FROM pg_extension WHERE extname='vector'\"" 2>/dev/null | tr -d ' ')
log "PostgreSQL: $PG_OK"
log "Redis: $REDIS_OK"
log "pgvector in bms db: ${VEC:-<none>}"
[ "$PG_OK" = "UP" ] && [ "$REDIS_OK" = "PONG" ] && [ -n "$VEC" ] || die "基础设施未全部就绪，请看上面的错误。"
log "全部就绪 ✅"
