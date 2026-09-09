# Architecture Decision Record — ADR-001

日期：2026-09-09。状态：Accepted。项目：Agent Runtime & Tool Workflow Platform。
所有工程内容位于仓库的 `agent-runtime-platform/` 子目录，独立于冻结的旧项目。

## 边界

Runtime 负责请求验证、状态转换、工具契约、调度、预算、恢复、上下文、持久化与回放；业务 Agent 应提供工具、指令和工作流。这里的合成算术、库存 SQL、知识文件仅用于测试 Runtime，不构建行业 RAG 应用。模型是可替换的决策提供者，不能绕过 Registry 调用能力。

## 决策

| 部件 | 选择与约束 | 取舍 |
|---|---|---|
| Tool Registry | Pydantic 输入/输出 schema；async callable；timeout、bounded retry、risk、permission、idempotency；统一结构化错误 | 不执行任意 Python、Shell 或写数据库 SQL；只对可重试错误及幂等工具重试 |
| Direct | 显式工具名与参数，一次逻辑调用 | 不宣称自然语言工具选择能力 |
| ReAct | JSON action/observation loop；限制步数、单次 LLM 超时和总运行时间；最终输出经 schema 校验 | 不读取、记录或返回隐藏 chain-of-thought；mock 是脚本提供者，不是智能模型 |
| Pipeline/DAG | 显式依赖和 JSON 引用、拓扑层并行、条件分支、fallback、可选失败步骤 | 层间 barrier 简单可解释，但比动态 ready queue 调度更保守 |
| 状态 | PENDING → RUNNING；工具阶段 WAITING_TOOL；失败处理 RECOVERING；终态 SUCCESS/FAILED/REJECTED；取消为 FAILED + CANCELLED | run 状态描述调度器；每个工具 attempt 单独 trace，避免并行任务竞争修改总状态 |
| Context | 最近消息窗口、硬性估算 token/message 预算；naive baseline 与结构化 compact；显式实体/约束和历史摘要；大工具结果摘要 | token 是 UTF-8 字节/4 的预算估计，不冒充模型 tokenizer；结构化事实来自调用者标注，不宣称自动抽取所有事实 |
| Async | asyncio TaskGroup、timeout、Semaphore；SQLAlchemy AsyncEngine + aiosqlite | cancellation 传播并清理子任务；协作式超时不能安全终止任意阻塞扩展代码，因此 demo 仅使用受控计算 |
| 持久化 | SQLite + SQLAlchemy；run JSON 快照 + 有序事件表，事务写入；本地磁盘 volume | 不支持多节点队列、分布式锁；崩溃时遗留非终态在单 worker 启动恢复为 FAILED/INTERRUPTED |
| Trace | 请求、mode、step、动作、参数、结果摘要和用于回放的完整受限结果、时延、错误、retry、转换、终态；统一 secret redaction | demo 数据可公开；本地 trace 可含用户输入，默认不入 Git；不记录 HTTP Authorization 或原始模型响应 |
| Replay | 读取已保存事件与结果，生成新的持久化 run，标记 replay_of；不调用模型/工具 | 是确定性结果回放，不证明原模型会再次做出相同决策；不自动重放外部副作用 |
| API | FastAPI /runs、/tools、/traces、/replay、/health；POST /runs 等待完成，后台取消由断开/协程取消语义决定；额外 DELETE /runs/{id} 支持进程内取消 | 无鉴权的本地演示服务，Docker 端口绑定 localhost；非持久化作业队列 |
| Provider | httpx OpenAI-compatible Chat Completions；DeepSeek 默认；JSON action contract；mock scripted provider；可配置 timeout 和 fallback | provider 错误文本不回显响应体；usage 只采用服务器实际返回值，cost 未配置价格时为 null |
| Evaluation | 版本化固定 48 条，development/held-out 分离；semantic assertions；真实模型仅用于 held-out 自然语言 ReAct 子集 | deterministic 测试衡量工程行为，不证明模型泛化；不针对 held-out 编写运行时分支 |

## 恢复语义

输入错误/权限不足拒绝；工具 timeout/可重试异常可在工具政策内重试；次数耗尽保留根因；ReAct 可接收结构化错误继续下一步；模型 malformed JSON 有单独修复预算；模型不可用可以执行请求中显式提供的 Direct fallback；DAG 默认必需步骤失败则最终 FAILED，独立结果仍可观察，依赖失败的后续步骤跳过，可选失败不阻塞无依赖步骤。总 timeout、取消、最大步数均进入明确终态。SUCCESS 可以包含已恢复错误，但不得掩盖必需步骤失败。

## 明确不采用

不采用 Multi-Agent、MCP 聚合、Kubernetes、Kafka、微服务、复杂前端、LoRA/SFT、自训练 LLM、CUDA、RL Agent、第二个业务 RAG。它们不能帮助验证本项目的单进程 runtime 边界，且会扩大依赖和无法证实的履历表述。不引入 LangChain/LangGraph：此项目需要直接展示状态机、异步执行、契约与回放机制；这是教学范围选择，不是通用性能判断。不使用向量数据库：知识 demo 是固定本地 JSON 查找。不用 PostgreSQL/Redis/Celery：SQLite 足以承载单 worker 演示和重启证据。

## 验证与证据纪律

先提交数据集再运行 held-out；模型结果和 mock 结果独立文件；实验保存每次原始测量、版本、UTC 实际时间和环境。依赖版本通过锁文件和真实安装验证。Docker 必须 build/run/health/offline agent/workflow/restart；有合法 key 再做 live request。测试、评测与实验均从本项目独立产生，不继承旧数字。不篡改 Git 日期或文件时间。最终报告自身无法包含自身 commit hash，Final HEAD 以最终 Git 命令及最终答复为准，并在报告中解释对应内容 checkpoint。

## 参考

- [Python asyncio TaskGroup / timeout / cancellation](https://docs.python.org/3.11/library/asyncio-task.html)：结构化并发与取消清理依据。
- [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)：每个数据库操作使用独立 AsyncSession。
- [DeepSeek API](https://api-docs.deepseek.com/)：兼容 Chat Completions 的请求格式，实际兼容性由集成验证确认。
