# BMS 测试用例生成平台 — 实现指令书（供 AI 编码代理逐步执行）

> 本文件是给 AI 编码代理（Kiro）的**自包含实现指令**。阅读者无需任何额外背景。请严格按本文件从上到下执行。

---

## 0. 给执行代理的工作方式（最重要，必须遵守）

1. **一次只做一个 Task**。按第 5 节「构建顺序」从 Task 0 开始，**逐个**实现，不要一口气把整个项目写完。
2. **每个 Task 完成后必须自测**：按该 Task 的「验收/自测方法」实际运行验证（写最小测试脚本或给出可复制的 curl/命令），**确认通过后再进入下一个 Task**。
3. **每个 Task 结束时输出三件事**：(a) 改了哪些文件；(b) 如何运行/测试；(c) 自测结果（通过/未通过及原因）。然后停下来等待确认或继续下一个。
4. **不确定就先声明假设**再做，不要静默猜测；涉及破坏性操作（删库删文件）要先说明。
5. **不要重写核心分析算法**：项目根目录已有现成 FastAPI 后端与分析逻辑（PDF 章节解析、文本清洗、CSV 参数解析与匹配、Prompt 组装）。**在其基础上改造**，保持这些逻辑不变。
6. 全程遵守第 3 节「全局约束」。

---

## 1. 项目背景（自包含）

把一个**现有的单机桌面工具**升级为**部署在一台内网服务器、多人浏览器可用的网页后端服务**。

业务：用户上传 BMS（电池管理系统）规格书 PDF 和参数表 CSV，勾选章节，由本地大模型生成结构化的 HTML 测试用例卡片（含前置条件、测试步骤、预期动作、Pass 判定，覆盖边界值）。

现状要改造的痛点：
- 后端是**单用户全局状态**（一个模块级字典存当前 PDF/章节/参数），多人并发会互相覆盖——必须去掉。
- 无持久化、历史只存浏览器本地——要落库、全局共享。
- 依赖云端模型——改为**本地模型（OpenAI 兼容接口）**。
- 桌面 exe 形态——改为**纯网页后端服务**。

**本指令书范围 = 后端 + 用例生成引擎 + 部署**。前端由他人负责，**不在本次实现范围**；但要提供稳定的 REST + SSE 接口供前端对接（见第 9 节）。

---

## 2. 技术栈与环境

- 语言/框架：**Python + FastAPI**（沿用现有后端），ASGI 运行用 uvicorn/gunicorn。
- 数据库：**PostgreSQL 16 + pgvector 扩展**（关系数据 + 少量向量同库）。
- 缓存/队列：**Redis**（任务队列 + 并发闸 + 进度通道）。
- 文件存储：**服务器本地磁盘目录**（库里只存路径）。
- 本地模型：**OpenAI 兼容 Chat Completions 接口**，流式；嵌入用本地 BGE-M3。
- 组合测试工具：**allpairspy**（Python 库，pip 装，MIT）；可选 **PICT**（二进制，subprocess）。
- 反向代理（部署期）：nginx。
- 所有外部依赖地址、模型名、并发数、清理周期、文件大小上限**全部走环境变量/配置文件**（见第 10 节）。

---

## 3. 全局约束（每个 Task 都要遵守）

1. **不做登录 / 不做账号权限**。所有接口开放，仅用 `case_id` 隔离数据。
2. **去掉一切全局会话状态**，改为每次作业一条 `case` 记录、按 `case_id` 隔离。
3. **文件按 `case_id` 分目录存本地**，库存相对路径；**默认保留 7 天后自动清理**（周期可配）。
4. **本地模型经 OpenAI 兼容接口调用**，端点/模型名/上下文/输出上限全部可配；当前先接 IT 的 Flash 模型评测，生产切回 DeepSeek 32B——**切换只改配置不改代码**。
5. **算力受限**：模型全研发中心共享、约 4 并发。平台用队列限并发：**同时运行 running=2，等待 queued=2，系统满 4 时第 5 个请求拒绝**（提示"排队已满，稍后再试"）。这三个数走配置。
6. **核心分析逻辑不重写**（章节解析、清洗、参数匹配、Prompt）。
7. **不实现**：数据看板、参数覆盖率报告、重新生成+版本对比（明确不做）。
8. 文件类型仅接受 PDF/CSV；单文件大小上限可配（默认 PDF≤50MB）。
9. 数据一致性：**先落盘成功，再写库**；失败回滚。状态以 PostgreSQL 为准。

---

## 4. 数据模型（建表用，字段为设计说明）

> 通用设计，不绑定任何特定 CSV 格式。`case_params` 只固定语义列，格式特有字段进 `raw` jsonb。

**cases**：id(UUID,PK)、pdf_filename、pdf_path、pdf_page_count、chapters(jsonb：title/page_start/page_end/level 列表)、csv_filename(可空)、csv_path(可空)、csv_param_count(可空)、csv_format(可空)、status(created/analyzing/done/failed)、created_at、expire_at(=created_at+7天)。索引：created_at、status、expire_at。

**case_params**：id(PK)、case_id(FK)、param_class(可空)、subclass(可空)、name、value、unit(可空)、min_value(可空)、max_value(可空)、raw(jsonb：原始整行，容纳 offset/formula/flags/raw_value 等格式特有列)。数值列以文本原样存。索引：case_id、(case_id,param_class,subclass)、name。

**generation_tasks**：id(UUID,PK=task_id)、case_id(FK)、selected_titles(jsonb)、status(queued/running/done/failed/canceled)、queue_position(可空)、total_chapters、current_chapter、error_msg(可空)、token_usage(可空)、started_at、finished_at、created_at。索引：case_id、status、created_at。

**generation_results**：id(UUID,PK)、task_id(FK)、case_id(FK)、html、tc_count(可空)、embedding(vector(1024),可空,用于语义检索)、created_at。索引：case_id、task_id；embedding 建 HNSW 索引。

**op_logs**：id(PK)、action、case_id(可空)、detail(jsonb,可空)、created_at。（排障/审计/队列统计用）

---

## 5. 构建顺序（逐个 Task：实现 → 自测 → 通过后继续）

> **里程碑对照（Task 按此归属阶段，避免把重活放错时间）**
> - **M0 准备与评测（即日–7/8，集训前）= Task 0~4**：只打地基——环境、建表、上传/解析/落库、文件存储与清理。**不含覆盖引擎**。
>   - ⚠️ **本周优先（非 Task，人工执行）**：当前 IT 的 Flash 模型**下周停用**，务必本周用真实文档（配几条手工 BVA+pairwise 样例）评测其生成质量并记录结论，之后生产切回 DeepSeek 32B。
> - **集训封闭期 7/9–8/9**：不开发。
> - **M1 核心闭环（8/10–8/24）= Task 5~8**：队列并发 + 模型接入（切回 32B）+ **覆盖最大化引擎（整块在此完成，不在 M0 提前做半截）**。
> - **M2 历史与检索（8/25–9/5）= Task 9~12**：历史接口、导出、语义检索、队列状态。
> - **M3 联调交付（9/8–9/15）= Task 13**：nginx 反代部署、前端联调、文档、验收。
>
> 注：覆盖引擎（Task 8）是核心重活，必须整块连续做，**严禁拆到集训长假前只做一半**。模型评测是一次性人工活动，不作为 Kiro 的编码 Task。

> 每个 Task 都按第 0 节方式执行。括号内是该 Task 的「自测方法」与「完成标准（DoD）」。

**Task 0 — 工程与依赖就位**
做：确认能读到现有后端代码；安装依赖（fastapi、uvicorn、psycopg/SQLAlchemy、redis、pgvector、allpairspy、openai 兼容客户端、pypdf 等）；准备 `.env` 配置加载（第 10 节键）。
自测：启动 FastAPI，`GET /api/health` 返回 200，且能分别连通 PostgreSQL 与 Redis（健康检查里体现）。
DoD：health 接口返回 DB/Redis 连通状态。

**Task 1 — 数据库建表 + pgvector**
做：启用 pgvector 扩展；按第 4 节建全部表与索引；提供建表脚本与"建用户/建库"命令记录（写进部署文档）。
自测：跑建表脚本后，能查询到 5 张表与索引；插入/读取一条样例 case。
DoD：表结构与第 4 节一致，样例读写通过。

**Task 2 — 去全局状态 + 上传 PDF + 章节解析**
做：去掉旧的模块级 `_state`；实现 `POST /api/cases/upload-pdf`：存文件到 `/data/cases/<case_id>/`，调用现有章节解析逻辑，写 `cases`，返回 case_id+章节列表+页数。
自测：用真实规格书 PDF 上传，返回 case_id 与章节树；磁盘有文件、库里有记录；并发上传两个文件，两条 case 互不影响。
DoD：上传→解析→落库落盘全通，多 case 隔离。

**Task 3 — 上传 CSV + 参数解析入库**
做：`POST /api/cases/{case_id}/upload-csv`：存文件，调用现有 CSV 解析逻辑，把参数写 `case_params`（固定语义列 + raw jsonb），返回条数与格式诊断。
自测：上传真实 TI Data Flash CSV，库里参数条数正确、min/max 正确入库、格式特有列进了 raw。
DoD：参数正确入库，换一份不同格式 CSV 不报错（多余列进 raw）。

**Task 4 — 文件存储隔离 + 7 天自动清理**
做：确认按 case_id 分目录；实现每日清理调度（扫 expire_at 过期 → 删目录 + 删相关记录，幂等，正在运行的任务跳过）；提供 `POST /api/admin/cleanup` 手动触发。
自测：构造一条 expire_at 已过期的 case，手动触发清理，文件与记录都被清掉；运行中的任务不被清。
DoD：过期清理正确且幂等，手动接口可用。

**Task 5 — Redis 队列 + 并发闸 + 任务状态机**
做：`POST /api/cases/{case_id}/generate` 建 `generation_tasks`(status=queued) 并入队，返回 task_id+排队位置；Worker 进程消费队列；并发闸 **running≤2**；等待 **queued≤2**；**满 4 拒绝**；状态机 queued→running→done/failed，可 cancel。状态 Redis+PG 双写、以 PG 为准。
自测：连发 6 个生成请求 → 前 2 跑、再 2 排队、第 5/6 被拒绝并返回明确提示；查 `GET /api/tasks/{id}` 状态正确；cancel 生效。
DoD：并发数严格为 2、队列为 2、满即拒绝，状态流转正确。

**Task 6 — 模型接入（OpenAI 兼容，流式，可配置）**
做：实现"生成调用层"，经 OpenAI 兼容接口流式调模型；端点/模型名/上下文/输出上限读配置；先接 Flash 模型，生产可改配置切 32B。Prompt 沿用现有结构。**分章节处理**：每章单独成请求，控制输入/输出预算，避免超上下文。
自测：用一章内容跑通流式生成，拿到 HTML；改配置切换到另一模型端点无需改码即可工作。
DoD：能流式生成、可配置切换、分章节不超长。

**Task 7 — SSE 进度推送**
做：Worker 把每个 chunk/进度写 Redis；`GET /api/tasks/{task_id}/stream` 订阅 Redis 转发 SSE，事件 `chunk/progress/log/done/error`；断线重连可补拉当前进度。
自测：浏览器/curl 连 SSE，能实时收到逐章进度与生成内容，done 后状态为 done；中途断开再连能续上。
DoD：SSE 实时、可续连，事件类型齐全。

**Task 8 — 用例覆盖最大化引擎（核心）**
做：在调用模型前插入确定性枚举层：
  - (1) **结构化抽取**：对每个所选章节，让模型抽取功能的状态/触发条件/动作逻辑/关联参数/优先级，输出受 schema 约束的结构化对象并校验。
  - (2) **取上下限（BVA）**：对每个参数读 min/max，生成边界点（下界±误差、下界、区间典型值、上界、上界±误差，误差可配）。**用 BVA，不用二分法。**
  - (3) **pairwise + 约束**：用 **allpairspy**（默认）对各参数边界点做成对覆盖，并用 filter 排除非法/互斥组合（优先级冲突、min>max 等）；关键功能可配置提到 n-wise 或全穷举；可选用 PICT。**禁止调用任何在线 API，组合工具一律本地离线调用。**
  - (4) **规范填写**：每个组合连同结构化逻辑送模型，生成一条标准 Testcase（功能/前置条件/条件/步骤/预期动作/Pass 判定）。
自测：给一个含多参数的章节，引擎产出：每参数边界点齐全、跨参数 pairwise 组合、非法组合被排除、每条输出为标准 Testcase。
DoD：数量与覆盖由程序保证，模型只做填写；约束生效；离线运行。

**Task 9 — 历史案例接口**
做：`GET /api/cases`（分页、倒序、关键词搜索）、`GET /api/cases/{id}`（详情：文档信息+结果）、`GET /api/cases/{id}/result`、`GET /api/cases/{id}/source-pdf`。全局共享，不绑定个人。
自测：造几条历史，列表分页/搜索正确，详情可取结果、可下载原 PDF。
DoD：历史全局可查、可取结果与原件。

**Task 10 — 多格式导出**
做：`GET /api/cases/{id}/export?format=html|xlsx|docx`，由结果 HTML 转换导出。
自测：三种格式都能导出且内容与页面一致、可正常打开。
DoD：导出可用。

**Task 11 — 语义检索（pgvector）**
做：生成结果（或章节摘要）用 BGE-M3 生成向量写入 embedding；`GET /api/search?q=` 做向量相似检索（与关键词检索并存）。
自测：用相近描述能召回语义相关的历史案例。
DoD：语义检索能召回相似项。

**Task 12 — 队列状态接口**
做：`GET /api/queue/status` 返回 running 数、queued 数、并发上限、各任务排位。
自测：制造排队场景，接口数字与实际一致。
DoD：队列状态准确。

**Task 13 — 部署（nginx 反代）+ 文档沉淀**
做：nginx 配置：`/` 托管前端静态、`/api/*` 反代 FastAPI、SSE 路径关闭缓冲、设置上传体积上限；**严禁裸暴露后端端口/公网 IP**。整理部署文档（PostgreSQL/pgvector/Redis 安装、建库建表命令、踩坑、配置项）。
自测：经 nginx 域名走通整条链路；SSE 不被缓冲。
DoD：浏览器经反代可完成全流程；部署文档可复用。

---

## 6. 文件存储与清理（细节）

- 目录：`/data/cases/<case_id>/source.pdf`、`params.csv`（如有）、`meta.json`（可选）。
- 写入顺序：建 case_id → 建目录 → 落盘 → 成功后写库；任一步失败回滚。
- 清理：每日扫 `expire_at < now`，删目录 + 删 cases/case_params/generation_tasks/generation_results 记录；幂等；running 任务跳过；记 op_logs。

---

## 7. 队列与并发（细节）

- running 上限、queued 容量、清理周期、文件大小上限均走配置（默认 running=2、queued=2）。
- 系统内任务数 = running + queued ≤ 4；超出对新请求返回明确"排队已满"。
- 状态机：queued →(并发闸放行) running →(成功) done；running →(异常/超时) failed；queued/running →(取消) canceled。
- 进度键设过期时间防堆积；可选结果缓存键 `hash(pdf内容+选中章节+模型版本)`。

---

## 8. 模型接入（细节）

- OpenAI 兼容 Chat Completions，streaming。
- 配置：`LLM_BASE_URL / LLM_MODEL / LLM_API_KEY / LLM_MAX_INPUT_TOKENS / LLM_MAX_OUTPUT_TOKENS / LLM_TIMEOUT`；嵌入：`EMBED_BASE_URL / EMBED_MODEL`。
- 分章节：每章单独请求，拼 Prompt 前估算 token，超预算再细分；输出上限按模型能力配，不足支持续写。
- 输出后处理：剥离 ```html 围栏与多余前后言，校验测试卡片结构完整，异常可重发该任务（不做版本留存）。
- 当前 Flash 模型仅作评测（下周失权限），生产改配置切 DeepSeek 32B。

---

## 9. 接口契约（供前端对接，前端不在本次实现内）

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | /api/cases/upload-pdf | 上传 PDF、解析章节、建案例 |
| POST | /api/cases/{case_id}/upload-csv | 上传 CSV、解析参数 |
| POST | /api/cases/{case_id}/generate | 提交生成任务（入队），返回 task_id+排位 |
| GET | /api/tasks/{task_id} | 查询任务状态/进度 |
| GET | /api/tasks/{task_id}/stream | SSE 订阅进度与结果流 |
| POST | /api/tasks/{task_id}/cancel | 取消任务 |
| GET | /api/cases | 历史列表（分页/倒序/搜索） |
| GET | /api/cases/{case_id} | 案例详情 |
| GET | /api/cases/{case_id}/result | 取生成 HTML |
| GET | /api/cases/{case_id}/source-pdf | 下载原 PDF |
| GET | /api/cases/{case_id}/export | 导出 html/xlsx/docx |
| GET | /api/search | 语义/关键词检索历史 |
| GET | /api/queue/status | 队列与算力占用状态 |
| POST | /api/admin/cleanup | 手动触发过期清理 |
| GET | /api/health | 健康检查（含 DB/Redis 连通） |

SSE 事件：`chunk`（生成片段）、`progress`（当前章/总章、排位）、`log`、`done`、`error`。

---

## 10. 配置项清单（环境变量）

- 数据库：`PG_DSN`（或分项 host/port/user/password/db）
- Redis：`REDIS_URL`
- 文件：`DATA_DIR`（默认 /data/cases）、`FILE_RETENTION_DAYS`（默认 7）、`MAX_UPLOAD_MB`（默认 50）
- 队列：`MAX_RUNNING`（默认 2）、`MAX_QUEUED`（默认 2）
- 模型：`LLM_BASE_URL / LLM_MODEL / LLM_API_KEY / LLM_MAX_INPUT_TOKENS / LLM_MAX_OUTPUT_TOKENS / LLM_TIMEOUT`
- 嵌入：`EMBED_BASE_URL / EMBED_MODEL`
- 引擎：`BVA_TOLERANCE_*`（边界误差）、`COMBINATION_STRENGTH`（默认 pairwise）

---

## 11. 完成总验收（整个项目）

1. 浏览器经 nginx 可完成 上传→勾选→排队→生成→查看→导出 全流程。
2. 多人并发零串扰；running=2/queued=2/满4拒绝 正确。
3. 所有结果落库，历史全局可查、可检索、可导出。
4. 生成全部由本地模型完成，分章节不超长；覆盖引擎保证数量与覆盖、约束生效、离线运行。
5. 过期数据按 7 天自动清理。
6. 无登录、无 exe；模型端点可配置切换。
7. 部署文档可复用。

> 再次强调：**逐个 Task 实现并自测通过后再继续**，每个 Task 结束报告"改了什么 / 怎么测 / 测试结果"。
