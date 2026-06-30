# 生产部署文档(Task 13)

内网服务器部署 BMS 测试用例生成平台。前端由前端团队产出;本文聚焦后端 + nginx。

## 0. 组件
- PostgreSQL 16 + pgvector(数据 + 向量检索)
- Redis(任务队列 / 并发闸 / 进度通道)
- Python 3.11 + FastAPI(uvicorn/gunicorn)
- 本地大模型(OpenAI 兼容,vLLM):`DeepSeek_32B_f16`
- nginx(统一入口反向代理)

## 1. 安装依赖
- 在线:见 `docs/DEVELOPMENT.md`;一键脚本 `scripts/dev_bootstrap.sh`。
- 离线:见 `docs/OFFLINE_INSTALL.md`(逐包下载清单 + dpkg 安装)。

Python 依赖:`pip install -r requirements.txt`(导出 xlsx/docx 另需 `openpyxl python-docx`)。

## 2. 建库与建表
```bash
sudo -u postgres psql -c "CREATE ROLE bms LOGIN PASSWORD 'bms';"
sudo -u postgres psql -c "CREATE DATABASE bms OWNER bms;"
sudo -u postgres psql -d bms -c "CREATE EXTENSION vector;"
python -m backend.app.schema    # 建 5 张表 + 索引 + HNSW 向量索引
```

## 3. 配置
`cp .env.example .env` 并按内网填写(数据库、Redis、模型端点/密钥、并发数、清理周期、上传上限)。关键:
```
LLM_BASE_URL=http://10.0.6.89:8080/v1
LLM_MODEL=DeepSeek_32B_f16
EMBED_BASE_URL=...        # BGE-M3 嵌入服务(用于语义检索;没有则语义检索自动降级关键词)
MAX_RUNNING=2
MAX_QUEUED=2
MAX_UPLOAD_MB=50
```

## 4. 运行后端(仅监听本机,由 nginx 对外)
开发:
```bash
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 7008
```
生产(多 worker,推荐 gunicorn + uvicorn worker):
```bash
gunicorn backend.app.main:app -k uvicorn.workers.UvicornWorker \
  -b 127.0.0.1:7008 --workers 2 --timeout 700
```
> 说明:任务队列调度器随应用启动(lifespan)。多 worker 时队列状态以 Redis 为准;
> 如需严格单一调度,建议用 1 个 web worker + 队列,或后续抽独立 worker 进程。

systemd 示例 `/etc/systemd/system/bms.service`:
```ini
[Unit]
Description=BMS Backend
After=network.target postgresql.service redis-server.service

[Service]
WorkingDirectory=/opt/bms/原始碼
ExecStart=/opt/bms/原始碼/.venv/bin/gunicorn backend.app.main:app -k uvicorn.workers.UvicornWorker -b 127.0.0.1:7008 --workers 2 --timeout 700
Restart=always
User=bms
EnvironmentFile=/opt/bms/原始碼/.env

[Install]
WantedBy=multi-user.target
```

## 5. nginx 反向代理
用 `deploy/nginx.conf`:
- `/api/*` 反代后端;
- SSE 路径 `^/api/tasks/.+/stream$` **关闭缓冲**(`proxy_buffering off`),否则实时进度收不到;
- `client_max_body_size` 与上传上限对齐;
- **严禁把后端端口/公网 IP 裸暴露**,只让 nginx 对外。

```bash
cp deploy/nginx.conf /etc/nginx/conf.d/bms.conf
nginx -t && systemctl reload nginx
```

## 6. 语义检索索引
首次或批量导入后,灌入向量:
```bash
curl -X POST http://127.0.0.1:7008/api/admin/reindex
```

## 7. 验收自检
- `GET /api/health` → db/redis 连通、llm 配置正确;
- 浏览器经 nginx 完成 上传→勾选→(可排队/实时进度)生成→查看→导出→检索;
- `GET /api/queue/status` 数字与实际一致;并发满 4 时第 5 个请求被拒。
