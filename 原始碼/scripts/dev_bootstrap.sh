#!/usr/bin/env bash
# Dev infra bootstrap for the BMS platform.
# 安装/启动 PostgreSQL + pgvector + Redis，并建库建扩展。
#
# 特点：
#   - 失败即停、绝不假装成功（每一步都有错误检查）。
#   - 自动探测 PG / Redis 二进制名与路径（兼容系统安装 / conda / 自编译）。
#   - 离线友好：可跳过联网安装、pgvector 可吃本地源码、Redis 可指定本地二进制。
#
# 可用环境变量覆盖：
#   PGDATA          PG 数据目录（默认 /var/lib/pgsql/15/data）
#   PGPORT          PG 端口（默认 5432）
#   PG_OS_USER      用哪个系统用户跑 PG（默认 postgres）。
#                   PostgreSQL 不能以 root 运行；conda 场景常设为某个普通用户，
#                   设为当前用户名即直接运行、不 su。
#   PGVECTOR_SRC    pgvector 源码目录（离线：解压好的源码路径）
#   REDIS_SERVER    redis-server 二进制路径（自编译/conda 时指定）
#   REDIS_CLI       redis-cli 二进制路径
#   SKIP_INSTALL=1  跳过包管理器安装（离线机已手动装好系统包时用）
#   PGVECTOR_VERSION 联网拉取时的版本（默认 v0.8.0）
set -uo pipefail

PGDATA="${PGDATA:-/var/lib/pgsql/15/data}"
PGPORT="${PGPORT:-5432}"
PG_OS_USER="${PG_OS_USER:-postgres}"
PGVECTOR_SRC="${PGVECTOR_SRC:-}"
REDIS_SERVER="${REDIS_SERVER:-}"
REDIS_CLI="${REDIS_CLI:-}"
SKIP_INSTALL="${SKIP_INSTALL:-0}"
PGVECTOR_VERSION="${PGVECTOR_VERSION:-v0.8.0}"

log()  { echo "[bootstrap] $*"; }
die()  { echo "[bootstrap][ERROR] $*" >&2; exit 1; }

# 某些环境（容器/沙箱）/tmp 非 1777，导致 postgres 无法建 socket 锁文件
chmod 1777 /tmp 2>/dev/null || true

# 以 PG_OS_USER 身份执行命令；若该用户即当前用户则直接运行（不 su）。
as_pg() {
  if [ -n "$PG_OS_USER" ] && [ "$PG_OS_USER" != "$(id -un)" ]; then
    su "$PG_OS_USER" -c "$1"
  else
    bash -c "$1"
  fi
}

# 探测二进制（PATH + 常见 PG 安装目录，含 conda）
find_bin() {
  local n="$1" p d
  p="$(command -v "$n" 2>/dev/null)" && { echo "$p"; return 0; }
  for d in /usr/pgsql-*/bin /usr/lib/postgresql/*/bin /usr/local/pgsql/bin \
           "$HOME"/anaconda3/envs/*/bin "$HOME"/miniconda3/envs/*/bin \
           /opt/conda/envs/*/bin; do
    [ -x "$d/$n" ] && { echo "$d/$n"; return 0; }
  done
  return 1
}

# ───────────────────────── 1. 安装系统包 ─────────────────────────
if [ "$SKIP_INSTALL" != "1" ] && ! find_bin initdb >/dev/null 2>&1; then
  if command -v dnf >/dev/null 2>&1; then
    log "用 dnf 安装 postgresql15 + redis6 + 编译工具 ..."
    dnf install -y postgresql15-server postgresql15-contrib redis6 gcc make git \
      || die "dnf 安装核心包失败（离线机请用 SKIP_INSTALL=1 并先手动装好）"
    dnf install -y --allowerasing postgresql15-server-devel \
      || die "dnf 安装 postgresql15-server-devel 失败"
  elif command -v apt-get >/dev/null 2>&1; then
    log "用 apt 安装 postgresql + redis + 编译工具 ..."
    apt-get update || die "apt-get update 失败"
    apt-get install -y postgresql postgresql-server-dev-all redis-server gcc make git \
      || die "apt 安装失败（离线机请用 SKIP_INSTALL=1 并先手动装好）"
  else
    die "未找到 dnf/apt 且 initdb 不存在。离线机请先手动安装 PG/Redis/gcc，再用 SKIP_INSTALL=1 重跑。"
  fi
else
  log "跳过系统包安装（SKIP_INSTALL=$SKIP_INSTALL）"
fi

# ── 定位关键二进制 ──
INITDB="$(find_bin initdb)"       || die "找不到 initdb（conda 环境请先 conda activate）"
PG_CTL="$(find_bin pg_ctl)"       || die "找不到 pg_ctl"
PSQL="$(find_bin psql)"           || die "找不到 psql"
PG_CONFIG="$(find_bin pg_config)" || die "找不到 pg_config（编译 pgvector 需要）"

# Redis：优先用显式指定，否则在 PATH 中探测常见命令名
if [ -z "$REDIS_SERVER" ]; then
  for s in redis-server redis6-server valkey-server; do command -v "$s" >/dev/null 2>&1 && { REDIS_SERVER="$s"; break; }; done
fi
if [ -z "$REDIS_CLI" ]; then
  for c in redis-cli redis6-cli valkey-cli; do command -v "$c" >/dev/null 2>&1 && { REDIS_CLI="$c"; break; }; done
fi
[ -n "$REDIS_SERVER" ] || die "找不到 redis-server。离线可自编译后用 REDIS_SERVER=/path/redis-server 指定"
[ -n "$REDIS_CLI" ]    || die "找不到 redis-cli。可用 REDIS_CLI=/path/redis-cli 指定"
log "PG: $INITDB | pg_config: $PG_CONFIG"
log "Redis: $REDIS_SERVER / $REDIS_CLI | PG_OS_USER=$PG_OS_USER"

# ───────────────────────── 2. 编译安装 pgvector ─────────────────────────
EXT_DIR="$("$PG_CONFIG" --sharedir)/extension"
if ! ls "$EXT_DIR/vector.control" >/dev/null 2>&1; then
  SRC="$PGVECTOR_SRC"
  if [ -z "$SRC" ]; then
    for cand in ./pgvector ./pgvector-* /tmp/pgvector; do [ -d "$cand" ] && { SRC="$cand"; break; }; done
  fi
  if [ -z "$SRC" ]; then
    command -v git >/dev/null 2>&1 || die "需要 pgvector 源码：离线请设 PGVECTOR_SRC=/解压路径"
    log "联网拉取 pgvector $PGVECTOR_VERSION ..."
    rm -rf /tmp/pgvector
    git clone --depth 1 --branch "$PGVECTOR_VERSION" https://github.com/pgvector/pgvector.git /tmp/pgvector \
      || die "git clone pgvector 失败（离线？请用 PGVECTOR_SRC 提供本地源码）"
    SRC=/tmp/pgvector
  fi
  log "从源码编译 pgvector: $SRC（针对 $PG_CONFIG）"
  ( cd "$SRC" && make clean >/dev/null 2>&1; make PG_CONFIG="$PG_CONFIG" ) || die "pgvector 编译失败"
  ( cd "$SRC" && make PG_CONFIG="$PG_CONFIG" install ) || die "pgvector 安装失败"
  ls "$EXT_DIR/vector.control" >/dev/null 2>&1 || die "pgvector 安装后仍找不到 vector.control"
  log "pgvector 已安装到 $EXT_DIR"
else
  log "pgvector 已存在，跳过编译"
fi

# ───────────────────────── 3. postgres 系统用户 ─────────────────────────
if [ -n "$PG_OS_USER" ] && [ "$PG_OS_USER" != "$(id -un)" ]; then
  id "$PG_OS_USER" >/dev/null 2>&1 || useradd -r -m -d /var/lib/pgsql "$PG_OS_USER" || die "创建用户 $PG_OS_USER 失败"
fi
if [ "$(id -un)" = "root" ] && [ "$PG_OS_USER" = "root" ]; then
  die "PostgreSQL 不能以 root 运行。请设 PG_OS_USER=某普通用户（如 postgres）后重跑。"
fi
mkdir -p "$(dirname "$PGDATA")"
[ "$PG_OS_USER" != "$(id -un)" ] && chown -R "$PG_OS_USER" "$(dirname "$PGDATA")" 2>/dev/null || true

# ───────────────────────── 4. initdb ─────────────────────────
if [ ! -f "$PGDATA/PG_VERSION" ]; then
  log "初始化 PGDATA: $PGDATA"
  as_pg "$INITDB -D '$PGDATA' -U postgres --auth=trust --encoding=UTF8" || die "initdb 失败"
fi

# ───────────────────────── 5. 启动 PostgreSQL ─────────────────────────
PGLOG="${PGLOG:-$PGDATA/startup.log}"
# 统一用 TCP 连接，避免 socket 目录不一致；限定 socket 目录到 PGDATA，规避 /tmp 权限问题
PSQLC="$PSQL -h 127.0.0.1 -p $PGPORT"
PG_START_OPTS="-p $PGPORT -c listen_addresses=127.0.0.1 -c unix_socket_directories=$PGDATA"
pg_reachable() { as_pg "$PSQLC -d postgres -tc 'SELECT 1'" >/dev/null 2>&1; }
if ! pg_reachable; then
  [ -f "$PGDATA/postmaster.pid" ] && as_pg "rm -f '$PGDATA/postmaster.pid'" 2>/dev/null || true
  log "启动 PostgreSQL :$PGPORT"
  as_pg "$PG_CTL -D '$PGDATA' -l '$PGLOG' -o \"$PG_START_OPTS\" -w start" \
    || { echo "--- $PGLOG ---"; as_pg "cat '$PGLOG'" 2>/dev/null; echo "--- log/ ---"; as_pg "tail -15 '$PGDATA'/log/*.log 2>/dev/null"; die "PostgreSQL 启动失败"; }
else
  log "PostgreSQL 已在运行（可连通），跳过启动"
fi
pg_reachable || die "PostgreSQL 未就绪（无法连接 :$PGPORT）"

# ───────────────────────── 6. 建库 + 角色 + 扩展 ─────────────────────────
as_pg "$PSQLC -tc \"SELECT 1 FROM pg_roles WHERE rolname='bms'\"" 2>/dev/null | grep -q 1 \
  || as_pg "$PSQLC -c \"CREATE ROLE bms LOGIN PASSWORD 'bms';\"" >/dev/null 2>&1 \
  || die "创建角色 bms 失败"
as_pg "$PSQLC -tc \"SELECT 1 FROM pg_database WHERE datname='bms'\"" 2>/dev/null | grep -q 1 \
  || as_pg "$PSQLC -c \"CREATE DATABASE bms OWNER bms;\"" >/dev/null 2>&1 \
  || die "创建数据库 bms 失败"
as_pg "$PSQLC -d bms -c \"CREATE EXTENSION IF NOT EXISTS vector;\"" >/dev/null 2>&1 \
  || die "启用 vector 扩展失败"

# ───────────────────────── 7. 启动 Redis ─────────────────────────
if ! "$REDIS_CLI" -p 6379 ping >/dev/null 2>&1; then
  log "启动 Redis :6379"
  "$REDIS_SERVER" --daemonize yes --port 6379 >/tmp/redis_start.log 2>&1 || die "Redis 启动命令失败"
  sleep 1
fi
"$REDIS_CLI" -p 6379 ping >/dev/null 2>&1 || die "Redis 未响应 ping"

# ───────────────────────── 8. 校验并报告（任何 DOWN 即非零退出）─────────────────────────
PG_OK=$(pg_reachable && echo UP || echo DOWN)
REDIS_OK=$("$REDIS_CLI" -p 6379 ping 2>/dev/null || echo DOWN)
VEC=$(as_pg "$PSQLC -d bms -tc \"SELECT extversion FROM pg_extension WHERE extname='vector'\"" 2>/dev/null | tr -d ' ')
log "PostgreSQL: $PG_OK"
log "Redis: $REDIS_OK"
log "pgvector in bms db: ${VEC:-<none>}"
[ "$PG_OK" = "UP" ] && [ "$REDIS_OK" = "PONG" ] && [ -n "$VEC" ] || die "基础设施未全部就绪，请看上面的错误。"
log "全部就绪 ✅"
