# 离线 Linux 安装指南

`scripts/dev_bootstrap.sh` 默认联网（`dnf` 装包 + `git` 拉 pgvector 源码）。
离线机请按本指南：先在一台**同发行版、同架构、可联网**的机器上把以下三类产物下好，
拷到离线机，再用脚本的离线模式启动。

> 脚本已做到：失败立即报错退出（不会再假装成功），自动探测 PG/Redis 二进制，
> 支持本地 pgvector 源码与跳过联网安装。

---

## 需要下载的三类产物

### 1) 系统软件包（RPM，含全部依赖）

在联网机（Amazon Linux 2023 同版本）上：

```bash
mkdir bms-rpms && cd bms-rpms
dnf download --resolve --alldeps \
  postgresql15-server postgresql15-contrib postgresql15-server-devel \
  redis6 gcc make
```

> `postgresql15-server-devel` 提供 `pg_config` 与 PGXS（编译 pgvector 必需），
> 安装时会替换系统的 `libpq-devel`（用 `--allowerasing`）。
>
> 非 Amazon Linux 的对应包名：
> - RHEL/Rocky：`postgresql16-server` `postgresql16-devel` `redis` `gcc` `make`
> - Ubuntu/Debian：`postgresql-16` `postgresql-server-dev-16` `redis-server` `build-essential`
>   （Debian/Ubuntu 有现成 `postgresql-16-pgvector`，可省去下面第 2 步源码编译）

### 2) pgvector 源码（0.8.0）

```bash
curl -L -o pgvector-0.8.0.tar.gz \
  https://github.com/pgvector/pgvector/archive/refs/tags/v0.8.0.tar.gz
```

### 3) Python 依赖（wheel）

务必用**相同 Python 版本（3.11）+ 相同架构**的机器下载：

```bash
mkdir bms-wheels
pip download -r requirements.txt -d bms-wheels
```

---

## 在离线机上安装

把 `bms-rpms/`、`pgvector-0.8.0.tar.gz`、`bms-wheels/` 拷到离线机，然后：

```bash
# 1) 系统包
cd bms-rpms && dnf install -y --allowerasing ./*.rpm && cd ..

# 2) 解压 pgvector 源码（脚本会自动编译）
tar xzf pgvector-0.8.0.tar.gz          # 得到 pgvector-0.8.0/

# 3) 离线模式启动基础设施
#    SKIP_INSTALL=1 跳过 dnf；PGVECTOR_SRC 指向解压目录
cd 原始碼
SKIP_INSTALL=1 PGVECTOR_SRC=/绝对路径/pgvector-0.8.0 bash scripts/dev_bootstrap.sh

# 4) Python 依赖
python -m venv .venv
.venv/bin/pip install --no-index --find-links=/绝对路径/bms-wheels -r requirements.txt

# 5) 建表 + 自测
.venv/bin/python -m backend.app.schema
.venv/bin/python -m pytest tests/ -v
```

脚本支持的环境变量：

| 变量 | 作用 |
|---|---|
| `SKIP_INSTALL=1` | 跳过 dnf 安装（系统包已手动装好时用） |
| `PGVECTOR_SRC=/path` | 指定本地 pgvector 源码目录（离线编译） |
| `PGDATA=/path` | PG 数据目录（默认 `/var/lib/pgsql/15/data`） |
| `PGPORT=5432` | PG 端口 |
| `PGVECTOR_VERSION=v0.8.0` | 联网拉取时的版本 |

---

## 常见问题

- **脚本报 `找不到 pg_config`**：没装 `*-server-devel`。
- **`pgvector 编译失败`**：缺 `gcc`/`make` 或 PG 开发头文件。
- **`找不到 redis-server / redis6-server`**：你的发行版 Redis 命令名不同，确认已安装。
- **PostgreSQL 用 16**：把上面的 15 换成 16 即可，pgvector 0.8.0 与 PG16 完全兼容。
