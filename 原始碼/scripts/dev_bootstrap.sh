#!/usr/bin/env bash
# Dev infra bootstrap for the BMS platform (Linux / Amazon Linux 2023 sandbox).
# Installs & starts PostgreSQL 15 + pgvector + Redis 6, idempotently.
# NOTE: System packages are ephemeral in the sandbox; re-run this each session.
set -uo pipefail

PGDATA="${PGDATA:-/var/lib/pgsql/15/data}"
PGBIN=/usr/bin
log() { echo "[bootstrap] $*"; }

# ---- 1. Install packages ----
if ! command -v initdb >/dev/null 2>&1; then
  log "Installing postgresql15 + redis6 + build tools ..."
  dnf install -y postgresql15-server postgresql15-contrib redis6 gcc make git >/tmp/dnf_core.log 2>&1
  dnf install -y --allowerasing postgresql15-server-devel >/tmp/dnf_devel.log 2>&1
else
  log "postgresql already installed"
fi

# ---- 2. Build & install pgvector ----
if ! ls /usr/share/pgsql/extension/vector.control >/dev/null 2>&1; then
  log "Building pgvector v0.8.0 ..."
  cd /tmp
  rm -rf pgvector
  git clone --depth 1 --branch v0.8.0 https://github.com/pgvector/pgvector.git >/tmp/pgv_clone.log 2>&1
  cd pgvector
  make PG_CONFIG=/usr/bin/pg_config >/tmp/pgv_make.log 2>&1
  make PG_CONFIG=/usr/bin/pg_config install >/tmp/pgv_install.log 2>&1
  log "pgvector installed"
else
  log "pgvector already installed"
fi

# ---- 3. postgres OS user ----
id postgres >/dev/null 2>&1 || useradd -r -m -d /var/lib/pgsql postgres
mkdir -p /var/lib/pgsql/15
chown -R postgres:postgres /var/lib/pgsql

# ---- 4. initdb ----
if [ ! -f "$PGDATA/PG_VERSION" ]; then
  log "Initializing PGDATA at $PGDATA ..."
  su postgres -c "$PGBIN/initdb -D $PGDATA -U postgres --auth=trust --encoding=UTF8" >/tmp/initdb.log 2>&1
fi

# ---- 5. start postgres ----
if ! su postgres -c "$PGBIN/pg_ctl -D $PGDATA status" >/dev/null 2>&1; then
  log "Starting PostgreSQL on :5432 ..."
  su postgres -c "$PGBIN/pg_ctl -D $PGDATA -l /tmp/pg.log -o '-p 5432' -w start" >/tmp/pgstart.log 2>&1
fi

# ---- 6. create app DB + role + extension ----
su postgres -c "$PGBIN/psql -p 5432 -tc \"SELECT 1 FROM pg_roles WHERE rolname='bms'\"" 2>/dev/null | grep -q 1 \
  || su postgres -c "$PGBIN/psql -p 5432 -c \"CREATE ROLE bms LOGIN PASSWORD 'bms';\"" >/dev/null 2>&1
su postgres -c "$PGBIN/psql -p 5432 -tc \"SELECT 1 FROM pg_database WHERE datname='bms'\"" 2>/dev/null | grep -q 1 \
  || su postgres -c "$PGBIN/psql -p 5432 -c \"CREATE DATABASE bms OWNER bms;\"" >/dev/null 2>&1
su postgres -c "$PGBIN/psql -p 5432 -d bms -c \"CREATE EXTENSION IF NOT EXISTS vector;\"" >/dev/null 2>&1

# ---- 7. start redis ----
if ! redis6-cli ping >/dev/null 2>&1; then
  log "Starting Redis on :6379 ..."
  redis6-server --daemonize yes --port 6379 >/tmp/redis_start.log 2>&1
fi

# ---- 8. report ----
log "PostgreSQL: $(su postgres -c "$PGBIN/pg_ctl -D $PGDATA status" >/dev/null 2>&1 && echo UP || echo DOWN)"
log "Redis: $(redis6-cli ping 2>/dev/null || echo DOWN)"
log "pgvector in bms db: $(su postgres -c "$PGBIN/psql -p 5432 -d bms -tc \"SELECT extversion FROM pg_extension WHERE extname='vector'\"" 2>/dev/null | tr -d ' ')"
log "done"
