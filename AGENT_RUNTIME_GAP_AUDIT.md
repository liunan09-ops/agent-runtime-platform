# Agent Runtime Gap Audit

日期：2026-09-09。结论：当前限定范围已足以作为 2027 校招的第二项目，前提是按已验证口径描述、能独立解释和演示。

## P0：不补就不能投

**当前无未解决 P0。** 必需的 Runtime、Registry、三模式、状态、上下文、异步、失败处理、trace/replay、API、Docker、固定评测、真实模型小样本和求职证据均已完成。

已通过的门槛：

| 门槛 | 证据 |
|---|---|
| 与冻结旧项目独立 | Git diff 仅新增 agent-runtime-platform/；Base tree 空；安全审计 |
| 无 key 可运行 | 45 离线测试、三个本地示例、离线容器 ReAct/DAG |
| 关键失败可验证 | timeout/cancel/retry exhausted/坏JSON/无效参数/模型不可用/部分失败测试 |
| 实验真实且有 bad case | A/B/C 原始 repetitions；naive 丢事实、超预算丢实体、Direct 复合任务失败 |
| mock 和 live 分开 | 44/48 deterministic 与 7/8 首次真实 DeepSeek held-out 分开报告 |
| Docker 真正运行 | build/run/health/offline agent/workflow/restart/live，非rootUID |
| 不把运行 SUCCESS 当模型正确 | live d10 SUCCESS但task assertion FAIL 保留 |
| 文档/履历不夸大 | 真实日期2026.09、合成数据和AI辅助披露、claim→evidence映射 |

真实模型 7/8 的格式失败不是必须补成 8/8 才能投递的缺口；为 held-out 添加特殊规则反而破坏证据价值。naive 失败是对照结果，不应隐藏。

## P1：面试准备

1. 能从一次 API 请求走读到 RunState、Registry、attempt、SQLite transaction 和 trace；现场跑一次 replay 并解释计数为0。
2. 能手写有界 ReAct loop 和 asyncio timeout/TaskGroup 示例，解释 CancelledError 的传播与资源清理。
3. 解释幂等重试的适用条件，为什么未知异常不默认重试，外部副作用工具需要额外设计。
4. 解释 DAG 引用、拓扑层 barrier、SKIPPED/BLOCKED/optional 和并发状态记录。
5. 解释 structured compaction 显式事实标注、token estimator、预算覆盖范围和信息损失。
6. 复盘 live d10：SQL结果47正确但最终JSON层级错误；Runtime只验证Action结构，不知道业务语义。
7. 解释参数 exact-match 的局限，不能用它替代语义正确性，也不能只报对自己有利的指标。
8. 会复现 2.77× 的合成实验，说明测量样本、误差、适配范围，不把sleep等待比值当线上性能。
9. 解释 SQLite 单 worker 边界、服务重启行为、为什么 replay 不是再次运行模型或工具。
10. 熟悉 FastAPI、Pydantic、SQLAlchemy session、httpx client、Docker volume、Git 工作树基础。
11. 对 AI 辅助开发坦诚，能在不依赖助手的情况下修一个错误或新增一个受限工具示例。
12. 熟悉本项目不是后台任务系统：POST等待返回，活跃取消目前依赖已知ID的进程内管理。

这些是准备和讲解差距，不需要继续扩大项目功能。

## P2：未来增强（仅列边界，不实施）

若将来有明确真实使用需求，可评估：真实 tokenizer、带独立质量集的事实抽取、按完成事件动态调度 DAG、持久化作业队列/恢复、服务级并发限制、认证及 trace 数据治理、更多独立 live 任务与 provider 合约适配。它们都不是本轮校招冻结的前置条件。

不启动 Multi-Agent、MCP 聚合、Kubernetes、Kafka、微服务、复杂前端、LoRA/SFT、自训练模型、CUDA、RL 或第二个业务 RAG。它们超出本项目约束，也不能修复当前最需要准备的解释能力。

PROJECT_FROZEN_FOR_2027_CAMPUS_RECRUITING

NO_ADDITIONAL_PROJECT_FEATURES_REQUIRED
