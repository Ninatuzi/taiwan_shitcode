# 开发与运行说明（M0：Task 0~4）

本阶段交付：工程与依赖就位、数据库建表（PostgreSQL + pgvector）、去全局状态的
PDF/CSV 上传解析入库、文件按 case_id 隔离与 7 天自动清理。

> 环境：Linux（Amazon Linux 2023 / 通用 Linux）。已去除 Windows/exe 形态。

## 1. 安装基础设施（PostgreSQL 15 + pgvector + Redis 6）

```bash
cd 原始碼
bash scripts/dev_bootstrap.sh
```

该脚本幂等：安装并启动 PostgreSQL（:5432）、构建安装 pgvector 0.8.0、启动
Redis（:6379），并创建数据库 `bms` / 角色 `bms` / 启用 `vector` 扩展。

> 生产环境用 PostgreSQL 16；开发沙箱仓库仅提供 15，pgvector 与全部 SQL 均兼容。

## 2. Python 依赖

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 3. 配置

```bash
cp .env.example .env
# 编辑 .env，至少填入本地模型的 LLM_API_KEY
```

关键配置（详见 `.env.example`）：

- 模型走 OpenAI 兼容接口：`LLM_BASE_URL=http://10.7.5.237:5001/v1`、`LLM_MODEL=DeepSeek-V4-Flash`
- 数据库 / Redis / 文件目录 / 并发数 / 清理周期 / 上传上限全部可配

## 4. 建表

```bash
.venv/bin/python -m backend.app.schema          # 建扩展 + 5 张表 + 索引 + HNSW
# .venv/bin/python -m backend.app.schema --drop  # 先删后建（仅开发）
```

## 5. 启动服务

```bash
.venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

## 6. 自测

```bash
.venv/bin/python -m pytest tests/ -v
```

## 已实现接口（M0）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/health | 健康检查，含 DB / Redis 连通状态 |
| POST | /api/cases/upload-pdf | 上传 PDF、解析章节、建 case（按 case_id 隔离） |
| POST | /api/cases/{case_id}/upload-csv | 上传 CSV、解析参数入库（语义列 + raw jsonb） |
| POST | /api/admin/cleanup | 手动触发过期清理（7 天） |

每日自动清理由 APScheduler 调度（周期由 `CLEANUP_INTERVAL_HOURS` 控制）。

## 说明

- 旧的 `backend/main.py`（单用户、Anthropic Claude）已被 `backend/app/` 新结构取代，
  保留其 Prompt 结构作为 Task 6/8 迁移参考。
- 核心解析逻辑（`backend/pdf_utils.py`、`backend/csv_utils.py`）保持不变，仅将
  Tesseract 路径改为跨平台（Linux 优先用 PATH，支持 `TESSERACT_CMD` 覆盖）。
