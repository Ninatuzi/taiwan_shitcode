"""BMS 测试用例生成平台 — 后端应用包。

从单机桌面工具升级为多人可用的网页后端服务：
- 去全局会话状态，按 case_id 隔离
- PostgreSQL + pgvector 持久化
- Redis 队列 + 并发闸
- 本地模型（OpenAI 兼容接口）
"""

__version__ = "0.1.0"
