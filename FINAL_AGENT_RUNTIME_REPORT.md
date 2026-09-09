# Final Agent Runtime Report

本项目已完成限定范围的实现、测试、评测、真实容器验证和求职证据整理。实际开发与验证日期：**2026-09-09（2026.09）**。

## Git / 范围

- Branch：`agent-runtime-platform`
- Base HEAD：`5a7f8f21d26807aeb02f21731adc0062f9c41fa1`
- 实现与最终离线实验 checkpoint：`345493bd83cafeeb340601b170bed7547b3746dc`
- Final HEAD：见本地机器回执 [`docs/evidence/final-head.json`](docs/evidence/final-head.json) 的 `final_head`，以及最终交付消息中的完整 hash。
- 回执在最终提交后由 `python -m evaluation.finalize_receipt` 只读 Git 生成；该单个文件 gitignored，解决文档包含自身 commit hash 的循环。克隆后可重新生成。其余代码、报告、原始结果与审计证据全部提交。
- 所有新增路径仅在仓库的 `agent-runtime-platform/`；无 merge、cherry-pick、旧项目目录改动或旧数字复用。未设置 Git 日期覆盖变量，未篡改文件时间戳。

## 最终状态

| 项目 | 状态 / 证据 |
|---|---|
| Runtime | 完成；Pydantic RunState、预算和终态；src/agent_runtime/runtime.py |
| Tool Registry | 完成；5 tools、schema、timeout/retry、risk/permission、async invoke |
| Direct | 完成；显式单工具调用、结构化拒绝、fallback |
| ReAct | 完成；有限 loop、单次和总 timeout、JSON 修复、action/observation trace，无隐藏推理 |
| Pipeline | 完成；顺序/并行、依赖引用、条件分支、optional、fallback、partial failure |
| Context | 完成；recent window、message/估算 token budget、naive/structured、事实及大结果摘要 |
| Async | 完成；asyncio TaskGroup/Semaphore、timeout、cancellation，测试验证清理与并发上限 |
| Recovery | 完成；timeout、异常、坏 JSON、无效参数、工具/模型不可用、retry exhausted、部分失败 |
| Trace | 完成；SQLite + SQLAlchemy，状态和事件事务存储；restart persistence 实测 |
| Replay | 完成；saved-results-v1，当前工具/LLM 调用为 0；不执行 live replay |
| FastAPI | 完成；6 个必需端点和进程内取消端点；全部请求/响应模型化 |
| Docker | **PASS**；build/run/health/offline ReAct/DAG/replay/restart/live；UID 10001 |
| Live DeepSeek | **7/8 held-out 任务通过**；deepseek-chat 服务返回 deepseek-v4-flash；30,436 provider tokens；单独 live 测试和容器请求也通过 |
| Tests | **45 passed + 1 默认 skipped**；另单独 **1 live passed**；Python 3.11 Docker 同套 **45 passed + 1 skipped** |
| Coverage | **857/891 = 96.18% statements**；不冒充 branch coverage |
| Evaluation | 版本 v1.0.0，48 条，32 development / 16 held-out；deterministic **44/48**，运行合约子集 **40/40** |
| Sequential vs Parallel | 3×80ms mock I/O、7 组；中位数 **253.79 → 91.65ms（2.77×）** |
| Context experiment | 5/10/20/40 turns；naive 2/4 facts，structured 4/4；20 次/设置；不是真实模型摘要评测 |
| Execution mode experiment | 12 tasks，3 repetitions；Direct 18/18、ReAct 36/36、Pipeline 36/36；三模式公平对比仅 single 子集 |
| Public repo safety | **PUBLIC_REPO_SAFE = YES**；范围为项目文件与新提交项目 blob，正常Git署名保留；见 PUBLIC_REPO_SAFETY_AUDIT.md |
| Resume-safe keywords | Agent Runtime, Tool Registry, bounded ReAct, Pipeline/DAG, asyncio, Context Management, Error Recovery, Trace/Replay, FastAPI, SQLAlchemy, SQLite, Docker, Evaluation |
| Resume-safe numbers | 5 tools；3 modes；48 synthetic tasks；7/8 live；45 offline tests；96.18% statement coverage；3×80ms 场景 2.77× |
| P0 gaps | **无阻止如实投递的缺口**；只在已验证范围内表述 |
| P1 interview gaps | 解释 mock/live 区别、SUCCESS≠任务正确、取消与幂等重试、SQLite 和 context/replay 边界；见 Gap Audit |
| Freeze decision | **冻结，停止增加项目功能** |

## 不能夸大之处

真实 held-out d10 格式错误保留为 FAIL，r12 SQL 空格差异导致 strict args 扣分。naive context 的 4 条失败保留；DAG 的 3 条预期失败不能当业务完成。Mock provider 脚本不证明智能推理，合成 sleep 比值不能当线上性能。没有鉴权、跨节点、生产负载、自动事实抽取、真实大规模评测证据。AI 辅助开发已披露。

## 可复核材料

- [Architecture Decision Record](ARCHITECTURE_DECISION_RECORD.md)
- [README](README.md) / [实验](docs/EXPERIMENTS.md) / [验证](docs/VERIFICATION.md)
- [固定数据集与口径](evaluation/README.md)
- [deterministic 原始结果](evaluation/results/deterministic-all.json) / [live 原始结果](evaluation/results/live-deepseek-held-out.json)
- [Docker 证据](docs/evidence/docker-verification.json) / [测试](docs/evidence/pytest.log) / [3.11 容器测试](docs/evidence/pytest-docker-py311.log)
- [公开仓库安全](PUBLIC_REPO_SAFETY_AUDIT.md) / [简历证据](RESUME_AGENT_RUNTIME_EVIDENCE.md) / [Gap Audit](AGENT_RUNTIME_GAP_AUDIT.md)

PROJECT_FROZEN_FOR_2027_CAMPUS_RECRUITING

NO_ADDITIONAL_PROJECT_FEATURES_REQUIRED
