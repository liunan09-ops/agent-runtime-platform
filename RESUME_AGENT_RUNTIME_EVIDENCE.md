# Resume Agent Runtime Evidence

## 项目身份与时间

- 推荐中文名：**可配置 Agent Runtime 与 Tool Workflow 平台**。
- 推荐英文名：**Agent Runtime & Tool Workflow Platform**。
- 项目真实日期：**2026.09**；本次实际开发、测试、模型请求与 Docker 证据日期为 2026-09-09。
- 简历上位系列可以使用用户规划的“智能决策与大模型应用系列实践｜2025.09 - 至今”，但本子项目仍须明确 2026.09，不能把系列起始日期当本项目起始日期。
- 技术栈：Python 3.11+、FastAPI、Pydantic v2、asyncio、SQLAlchemy Async、aiosqlite/SQLite、httpx、Pytest、OpenAI-compatible / DeepSeek、Docker。
- 本项目采用 AI 辅助开发。面试中必须能独立解释实现、重现证据并分析失败，不声称全部手写。

## 可安全写的数字

| 数字 | 完整口径 | 证据 |
|---|---|---|
| 5 个工具 | calculator、sql_query、http_mock、knowledge_lookup、data_analysis；合成只读示例 | [demo_tools.py](src/agent_runtime/demo_tools.py)、[Registry tests](tests/test_registry.py) |
| 3 种执行模式 | Direct / bounded ReAct / Pipeline DAG | [runtime.py](src/agent_runtime/runtime.py)、[runtime tests](tests/test_runtime.py) |
| 48 条固定任务 | development 32、held-out 16；独立合成 v1 数据集 | [manifest](evaluation/datasets/manifest-v1.json) |
| 44/48 | deterministic 任务断言通过，含预期失败；4 项 naive context 任务失败 | [deterministic-all.json](evaluation/results/deterministic-all.json) |
| 40/40 | 排除 8 项上下文对照后的 Runtime 合约任务通过；不代表模型准确率 | 同上 |
| 7/8 = 87.5% | 首次真实 DeepSeek held-out 自然语言任务通过；8 条小样本、单服务 | [live report](evaluation/results/live-deepseek-held-out.json) |
| 10/10 与 9/10 | live 工具选择 / strict name+args JSON 匹配；后者被 SQL 空格差异扣一项 | 同上；不能写成 100% 业务准确率 |
| 45 + 1 | 45 个离线测试通过，默认跳过 1 个 live 测试；另显式运行 live 测试通过 | [pytest.log](docs/evidence/pytest.log)、[pytest-live.log](docs/evidence/pytest-live.log) |
| 96.18% | Runtime **语句**覆盖，857/891；不是分支覆盖或无 bug 保证 | [coverage.json](docs/evidence/coverage.json) |
| 2.77× | 3 个各 80ms 的合成 I/O 工具，7 组成对实验，串行/并行中位数 253.79/91.65ms | [实验](docs/EXPERIMENTS.md)、[原始 repetitions](evaluation/results/experiments.json) |
| 5/10/20/40 turns | 每 turn 两条消息；400 估算 token 预算；4 个显式标注事实 | [context experiment](docs/EXPERIMENTS.md) |
| 2/4 → 4/4 facts | naive 与 structured 的固定场景事实保留；不是自动摘要提升百分比 | 同上 |
| 30,436 tokens | 首次 8 条真实 held-out 的 provider-reported total；成本未配置，不推算费用 | [live report](evaluation/results/live-deepseek-held-out.json) |

简历通常选 2–3 个有解释空间的数字即可，不把所有指标堆成“成绩单”。Docker/测试在两种 Python 版本重跑不是双倍测试数量；同一任务多次重复也不是更多独立任务。

## Agent / AI 应用版 bullets（3 条）

1. 设计可配置 Agent Runtime，以统一 Tool Registry 接入 5 类异步工具，支持 Direct、有限步 ReAct 和 Pipeline/DAG；通过输入/输出契约、超时预算、幂等重试与结构化错误管理工具执行。（C1–C4）
2. 实现 recent window 与结构化 Context Compaction，在固定 5/10/20/40 turns、400 估算 token 预算实验中，将 4 个显式事实的保留从 naive 的 2/4 提升至 4/4；保留预算溢出 bad case，并记录压缩时延与上下文空间取舍。（C5）
3. 构建 48 条版本化合成任务和 SQLite Trace/Replay；离线任务断言通过 44/48，另对 8 条 held-out 执行真实 DeepSeek 评测、通过 7/8，保留 SQL final JSON 格式错误案例并区分模型结果与 mock fixture。（C6–C8）

## AI Backend / Runtime 版 bullets（3 条）

1. 基于 FastAPI、Pydantic、SQLAlchemy/SQLite 实现可序列化运行状态、工具 schema、执行 API 和结构化事件持久化，提供终态查询与零工具/模型调用的确定性结果回放，验证容器重启后状态一致。（C1、C6、C9）
2. 使用 asyncio TaskGroup/Semaphore 实现有界并发、取消传播与分层 timeout；在 3×80ms 合成 I/O、7 组成对实验中，将串行中位时延 253.79ms 降至 91.65ms，约 2.77×，并覆盖重试耗尽、DAG 部分失败和 fallback。（C3、C4、C10）
3. 建立 45 个离线 Pytest 测试并验证 1 个 live 集成测试，Runtime 语句覆盖率 96.18%；完成 Docker build/run、health、离线 ReAct、条件工作流、trace/replay、restart 与真实 DeepSeek request 验证。（C7、C9、C11）

## 60 秒介绍

这个项目是一个可配置 Agent Runtime，重点是工具执行基础设施。业务方提供工具和工作流，Runtime 统一做参数校验、状态管理、异步调度、超时重试、上下文预算和 trace。我实现了 Direct、有限步 ReAct 和显式 DAG 三种模式，用 SQLite 保存运行记录，并可直接回放历史结果。验证分成工程行为和模型行为：48 条合成任务的离线断言通过 44 条，失败来自 naive 上下文丢事实；另有 8 条真实 DeepSeek held-out，通过 7 条，一条虽然查对总数，但 final JSON 包错了层。项目也完成了容器重启和并行对照。我会明确区分 mock、真实模型和合成延迟，避免把 Runtime 成功状态当作答案正确。

## 3 分钟介绍

我做这个项目，是为了把业务 Agent 背后可复用的执行能力单独实现出来。业务 Agent 需要回答具体领域的问题，而 Runtime 应当负责工具契约、预算、生命周期和可观察性。本项目在 2026 年 9 月独立开发，使用 AI 辅助，没有复用旧业务项目的测试或性能数字。

首先是 Tool Registry。每个工具有 Pydantic 输入与输出模型、timeout、retry policy、权限、风险和幂等性。调用都经过 Registry，不让模型绕过参数验证。五个示例工具覆盖安全算术、只读 SQL、mock HTTP、本地知识和数据分析。只有声明幂等的工具才会对可重试错误做有限重试，未知异常不会被无限重试掩盖。

然后是三种执行模式。Direct 用于调用者已经知道工具和参数的请求；ReAct 每步接收 JSON action，再把结构化 observation 加回上下文，限制步数、单次模型 timeout 和总 deadline；DAG 用显式依赖和引用连接工具，独立步骤并行，支持条件、可选步骤和 fallback。并行 attempt 记录各自事件，统一由调度器更新 run 状态，避免全局状态被多个协程同时改乱。取消会传递给 TaskGroup 子任务并完成清理。

上下文部分有 recent window、硬预算和两种策略。structured 保留明确标注的实体约束，压缩工具大结果并形成历史片段摘要。这里不声称自动抽取事实或精确 tokenizer；在固定 5 到 40 turns 的任务中，它保留了 4/4 个事实，naive 为 2/4，但 structured 更占空间和 CPU，事实本身超预算也会丢失。

所有运行状态和事件通过 SQLAlchemy 写入 SQLite。Replay 读取保存结果生成新的记录，工具和模型调用数为零。这有利于调试，但不是重跑模型，也不重放外部副作用。FastAPI 暴露这些能力，Docker 已验证离线 Agent、DAG、重启持久化和真实模型请求。

最后我把证据分开：45 个离线测试通过，语句覆盖率 96.18%；48 条合成任务离线断言通过 44 条；另有 8 条真实 DeepSeek held-out 通过 7 条。真实失败是 SQL 查询结果对了，但模型返回整条 observation 而非目标 payload，所以 Runtime 是 SUCCESS，任务仍失败。并行实验的 2.77 倍也只来自三个各 80ms 的 mock I/O，不代表线上收益。这个项目的价值是把执行机制、失败边界和证据做清楚，而不是宣称复杂平台能力。

## Claim → Code / Test / Evaluation

| Claim ID | 可说的 claim | 代码 | 测试 / 实测证据 |
|---|---|---|---|
| C1 | 统一 Tool abstraction + schema 校验 | [registry.py](src/agent_runtime/registry.py)、[models.py](src/agent_runtime/models.py) | [test_registry.py](tests/test_registry.py) |
| C2 | 五类受限 demo tools | [demo_tools.py](src/agent_runtime/demo_tools.py)、[data](src/agent_runtime/data/knowledge.json) | 输出/拒绝边界测试；d01–d12 traces |
| C3 | 三种执行模式、DAG/条件/引用 | [runtime.py](src/agent_runtime/runtime.py) | [test_runtime.py](tests/test_runtime.py)、p01–p12、[实验 C](docs/EXPERIMENTS.md) |
| C4 | 有界 timeout/retry/fallback/清晰终态 | [registry.py](src/agent_runtime/registry.py)、[runtime.py](src/agent_runtime/runtime.py) | timeout/cancel/partial failure/LLM 修复测试；r02–r08、p05–p12、e10–e12 |
| C5 | 明确预算的有损 Context Management | [context.py](src/agent_runtime/context.py) | [test_context.py](tests/test_context.py)、e01–e08、实验 B |
| C6 | SQLite trace 与保存结果回放 | [persistence.py](src/agent_runtime/persistence.py)、Runtime.replay | [test_persistence_api_provider.py](tests/test_persistence_api_provider.py)、e09/e10、Docker restart |
| C7 | Mock / compatible provider 可替换 | [providers.py](src/agent_runtime/providers.py) | wire contract 测试、单独 live 测试、live traces 的 llm_call metadata |
| C8 | 独立版本化评测与真实模型结果分开 | [harness.py](evaluation/harness.py)、[manifest](evaluation/datasets/manifest-v1.json) | [deterministic](evaluation/results/deterministic-all.json)、[live](evaluation/results/live-deepseek-held-out.json) |
| C9 | FastAPI + Docker 可运行与重启持久化 | [api.py](src/agent_runtime/api.py)、[Dockerfile](Dockerfile) | API tests、[docker-verification.json](docs/evidence/docker-verification.json) |
| C10 | 并发确实重叠、受限且更快于固定串行等待 | Runtime._pipeline / TaskGroup / Semaphore | overlap/semaphore 测试、实验 A 原始 14 次运行及 timeout probe |
| C11 | 独立测试与覆盖实测 | [tests](tests)、[pyproject.toml](pyproject.toml) | pytest.log、pytest-live.log、pytest-docker-py311.log、coverage.json |
| C12 | 无 key 离线可运行；输出公开审计 | MockProvider、环境变量读取、.dockerignore | offline-demo.log、[安全审计](PUBLIC_REPO_SAFETY_AUDIT.md) |

## 面试追问（36 题，含回答要点）

| # | 追问 | 回答要点 / 证据 |
|---:|---|---|
| 1 | Runtime 与业务 Agent 的边界是什么？ | Runtime 管执行机制；业务提供工具、指令与工作流。ADR/C1–C4。 |
| 2 | 为什么不用现成框架？ | 为展示并掌握契约、状态、调度实现；不声称比框架普遍更快。ADR。 |
| 3 | Tool Registry 相比字典函数有什么价值？ | schema、policy、错误、权限和事件集中，调用入口一致。C1。 |
| 4 | 怎么校验工具返回值？ | 输出模型 model_validate，违约返回 OUTPUT_CONTRACT。Registry test。 |
| 5 | Calculator 为什么不用 eval？ | AST 白名单、深度/大小/有限数值限制，禁止任意调用和幂。C2。 |
| 6 | SQL 工具如何限制写操作和昂贵查询？ | 合成库、query_only、authorizer、VM progress budget、行数上限。C2。 |
| 7 | HTTP 工具是真实网络吗？ | 使用真实 httpx 调用栈但 MockTransport；不访问互联网。C2。 |
| 8 | Direct、ReAct、Pipeline 怎么选？ | 已知单工具、动态下一动作、固定依赖分别适用；比较任务族。C3/实验 C。 |
| 9 | ReAct 保存了模型思维链吗？ | 没有；只存 action、observation、state，忽略 reasoning_content。Provider test。 |
| 10 | ReAct 怎么避免无限循环？ | max_steps、LLM timeout、run timeout 和 bounded repair retries。C4。 |
| 11 | 模型 malformed JSON 怎么处理？ | Pydantic Action 校验，有限修复反馈，不回显原始响应。r02/r07。 |
| 12 | LLM 不可用如何 fallback？ | 只有调用者显式声明 fallback 才执行，保留原始结构化错误。r08。 |
| 13 | 工具选择错误怎么恢复？ | 错误 observation 返回下一轮，模型可改正；最终未解决错误则 FAILED。r03/r04。 |
| 14 | 为什么有 SUCCESS 却任务失败？ | SUCCESS 是协议终态，语义需外部断言；live d10 是例子。C8。 |
| 15 | 状态机如何处理并行工具？ | attempt 各自 trace，总体状态由调度器在波次边界更新。C3/C4。 |
| 16 | DAG 如何检测环和未知依赖？ | Pydantic after validator 拓扑剥离；无 ready 节点即拒绝。test_invalid_dag_rejected。 |
| 17 | Pipeline 参数如何使用前一步结果？ | JSON $ref + 显式 depends_on，运行时逐路径解析，不 eval。p01/p09。 |
| 18 | 一个并行步骤失败是否取消其他步骤？ | 已知工具失败转 ToolResult，独立 sibling 可以完成；总取消/超时则取消整个 TaskGroup。C4。 |
| 19 | optional、SKIPPED、BLOCKED 有何差别？ | optional 失败可不使 run 失败；条件 false 为 SKIPPED；失败依赖使下游 BLOCKED。p04–p06/p11。 |
| 20 | 重试怎么保证不会重复副作用？ | 幂等性声明决定是否允许重试；demo 全部受限只读，未实现跨服务幂等键。C1/C4。 |
| 21 | timeout 与 cancellation 的区别？ | timeout 借助取消实现 deadline；外部 cancel 保留 CANCELLED，清理后重新传播。测试分别验证。 |
| 22 | asyncio 能加速 CPU 运算吗？ | 不能自动加速 CPU；实验只是 I/O 等待重叠，SQL 用线程且另设预算。C10。 |
| 23 | Semaphore 限制的是什么？ | 每 run 的并行工具数，不是跨进程或全服务请求限流。overlap test。 |
| 24 | 2.77× 是怎么测的？ | 三个80ms等待、七组成对交替运行；看所有原始延迟和中位比。实验 A。 |
| 25 | 为什么没到理论3×？ | 调度、持久化和客户端固定开销；未 profiler 不能具体分摊成因。实验 A。 |
| 26 | 上下文 token 预算精确吗？ | UTF-8/4 估算，仅 context JSON，system/tool schema 额外计；live usage 由服务返回。C5/C7。 |
| 27 | Structured compaction 能保留所有信息吗？ | 有损；事实显式标注，超预算仍会丢失，bad case 已记录。实验 B。 |
| 28 | 如何避免上下文摘要编造事实？ | 无生成式摘要，事实按显式 key 更新；不声称自动抽取正确。C5。 |
| 29 | SQLite 为什么够用，哪里不够？ | 单 worker 本地演示，事务/WAL易复现；无跨节点调度和高并发证明。C6。 |
| 30 | SQLAlchemy AsyncSession 能被多个 task 共享吗？ | 本项目不共享，每个事务独立 session，Store lock 串行写。C6。 |
| 31 | 重启后运行怎么恢复？ | 终态可查询；遗留非终态标 FAILED/INTERRUPTED，不续跑作业。restart test。 |
| 32 | Replay 与重新执行有什么区别？ | 零 live 调用的保存结果回放；验证可观察性而非新模型/新工具逻辑。C6。 |
| 33 | held-out 是否泄漏？ | 数据先固定、Runtime无case ID规则；fixture公开，不是第三方盲测。C8。 |
| 34 | 为什么参数准确率低于任务准确率？ | 字面 JSON 度量惩罚 int/float 与 SQL 空格差异；保留细分指标。C8。 |
| 35 | Docker 验证中遇到什么真实问题？ | 随机宿主端口重启后变化，脚本需重新查询端口；服务正常。docker-first-attempt 证据。 |
| 36 | 你亲自负责什么，AI参与什么？ | 目标、约束与质量判断需由本人承担；代码/测试/文档有AI辅助，必须现场能解释并修改。README disclaimer。 |

## Unsupported claims

以下内容没有证据，不写入简历：

- 生产用户、业务营收、企业部署、可用性 SLA、线上吞吐或大规模稳定性。
- 多 Agent 协作、MCP 聚合、Kubernetes/Kafka/微服务、训练/微调、CUDA/RL。
- “自主完成任意任务”“模型百分之百准确”“失败自动全部恢复成功”。
- “真实网络延迟降低 64%”“CPU 性能提升 2.77 倍”“自动摘要准确率 100%”。
- 完整安全沙箱、强鉴权/租户隔离、分布式事务、外部工具 exactly-once。
- 完整模型决策重演、live replay、自动跨请求会话记忆、持久化后台任务队列。
- 精确 tokenizer、费用节省比例、真实 RAG 检索收益、旧项目测试或评测数字。
- 2025.09 已完成本子项目；全部手写；大规模外部盲测。

## Limitations 与投递边界

这个项目支持如实投递 Agent/AI 应用、AI Backend/Runtime 校招岗位；胜任证明来自机制与证据可解释，不来自覆盖所有热门技术。模型样本小、数据合成、无上线/鉴权/规模验证，均应主动说清楚。保持代码冻结，把时间用在复现、白板设计、debug 演示和基础知识准备上。
