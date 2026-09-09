"""Render measured experiment and final status tables from committed machine-readable results."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    experiment = json.loads((ROOT / "evaluation/results/experiments.json").read_text())
    docker = json.loads((ROOT / "docs/evidence/docker-verification.json").read_text())
    a, b, c = experiment["A"], experiment["B"], experiment["C"]
    text = f"""# Three Controlled Experiments

实际测量时间：{experiment["recorded_at"]}。实现基础：`{experiment["git_head"]}`。
环境：Python {experiment["python"]} / {experiment["system"]} / {experiment["machine"]}；单进程、本地 SQLite。
原始数据：[experiments.json](../evaluation/results/experiments.json)，不继承旧项目数字。

## A. Sequential vs Async Parallel Tool Execution

3 个独立 HTTP mock 工具分别真实 `await asyncio.sleep(80ms)`；每组串行/并行成对测量，共 7 组，交替先后顺序。

| 模式 | n | 中位数 ms | 平均 ms | 最小 ms | 最大 ms |
|---|---:|---:|---:|---:|---:|
| Sequential | 7 | {a["sequential_ms"]["median"]:.2f} | {a["sequential_ms"]["mean"]:.2f} | {a["sequential_ms"]["min"]:.2f} | {a["sequential_ms"]["max"]:.2f} |
| Async parallel | 7 | {a["parallel_ms"]["median"]:.2f} | {a["parallel_ms"]["mean"]:.2f} | {a["parallel_ms"]["min"]:.2f} | {a["parallel_ms"]["max"]:.2f} |

中位数比值 **{a["median_speedup"]:.2f}×**。每次均校验相同输出和 3 次工具调用。运行时指标包括主要状态持久化开销，但不包括最后一次 final 快照的数据库提交。

Timeout probe：一个 250ms 延迟工具受 120ms 单次 deadline 限制，最多重试 2 次；独立 10ms 工具仍成功。总体状态 {a["timeout_probe"]["status"]}，总时延 {a["timeout_probe"]["latency_ms"]:.2f}ms；根因为 TOOL_TIMEOUT，外层错误 RETRY_EXHAUSTED。见 JSON 的 timeout_probe。

取舍：并行增加并发占用，仅对独立 I/O 等待有效；没有 CPU 加速、互联网性能或吞吐证据。波次调度会等待整层完成，不能消除慢步骤或必需步骤失败。

## B. Naive Truncation vs Structured Compaction

每 turn 为 user+assistant 两条消息。固定 5/10/20/40 turns，4 个显式标注事实，400 估算 token 预算，每项测 20 次。

| Turns | 策略 | context bytes | 估算 tokens | retained facts | task success | 中位 CPU ms |
|---:|---|---:|---:|---:|---:|---:|
"""
    for r in b["rows"]:
        text += f"| {r['turns']} | {r['strategy']} | {r['context_bytes']} | {r['estimated_context_tokens']} | {r['facts_retained']}/{r['facts_total']} | {r['task_success_rate']:.0%} | {r['latency_ms']['median']:.4f} |\n"
    text += f"""
任务成功是受控 key/value 提取器能从保留下来的上下文取回全部 4 个事实，不是 LLM 准确率。真实 provider token/cost 均为 null，表中估算量为 ceil(UTF-8 bytes/4)。

Structured 保留更多早期事实，也占用更多上下文和 CPU；naive 更短、更便宜，近期事实仍能保留。Bad case：事实自身超预算时，structured 保留 {b["bad_case"]["facts_kept"]} 条、丢弃 {b["bad_case"]["facts_dropped"]} 条，仍遵守 {b["bad_case"]["estimated_tokens"]} 的估算预算。

## C. Direct / ReAct / Pipeline

12 个定义明确的任务：6 单工具、3 依赖聚合、3 条件分支，各重复 3 次。ReAct 使用确定性动作脚本，不消耗模型网络时延或 token。Direct 只纳入其适配的 6 单工具任务。

| 模式 / 任务族 | 成功 / runs | 中位 ms | 平均 tool attempts | 平均 provider calls |
|---|---:|---:|---:|---:|
"""
    for name, group in c["groups"].items():
        if name.endswith("/all"):
            continue
        text += f"| {name} | {group['successes']}/{group['runs']} | {group['latency_ms']['median']:.2f} | {group['mean_tool_calls']:.2f} | {group['mean_llm_calls']:.2f} |\n"
    text += """
公平的三模式比较是 single 子集：相同的 6 个任务、各 3 次。不同任务族不能混在一起宣称某模式更准。Direct 不支持依赖和条件调度，因此为 N/A，未把已知工具结果硬编码进 Direct 参数以制造对等。

Bad case：用 Direct 的单次 alpha 查询处理“查询 alpha、beta 并求和”，Runtime SUCCESS、返回 value=10，但复合任务失败。ReAct 提供动态动作接口并增加 provider 轮次；Pipeline 适合固定依赖，省去 LLM 调用，但配置与波次调度也有开销。真实模型延迟须另看 live held-out，不能把这里的 mock 毫秒数当作真实 Agent 延迟。

## 测量限制

样本量小；实验受进程调度、数据库缓存和本地负载影响；记录原始所有 repetitions，无显著性检验。没有使用 profiler 证明微秒差异的成因；不承诺新机器、真实网络或真实任务上同样的比值。后续若复测，须保留运行时间和环境，不挑最好的一次。
"""
    (ROOT / "docs/EXPERIMENTS.md").write_text(text)
    final = f"""# Final Agent Runtime Report

本项目已完成限定范围的实现、测试、评测、真实容器验证和求职证据整理。实际开发与验证日期：**2026-09-09（2026.09）**。

## Git / 范围

- Branch：`agent-runtime-platform`
- Base HEAD：`5a7f8f21d26807aeb02f21731adc0062f9c41fa1`
- 实现与最终离线实验 checkpoint：`{experiment["git_head"]}`
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
| Docker | **{docker["result"]}**；build/run/health/offline ReAct/DAG/replay/restart/live；UID 10001 |
| Live DeepSeek | **7/8 held-out 任务通过**；deepseek-chat 服务返回 deepseek-v4-flash；30,436 provider tokens；单独 live 测试和容器请求也通过 |
| Tests | **45 passed + 1 默认 skipped**；另单独 **1 live passed**；Python 3.11 Docker 同套 **45 passed + 1 skipped** |
| Coverage | **857/891 = 96.18% statements**；不冒充 branch coverage |
| Evaluation | 版本 v1.0.0，48 条，32 development / 16 held-out；deterministic **44/48**，运行合约子集 **40/40** |
| Sequential vs Parallel | 3×80ms mock I/O、7 组；中位数 **{a["sequential_ms"]["median"]:.2f} → {a["parallel_ms"]["median"]:.2f}ms（{a["median_speedup"]:.2f}×）** |
| Context experiment | 5/10/20/40 turns；naive 2/4 facts，structured 4/4；20 次/设置；不是真实模型摘要评测 |
| Execution mode experiment | 12 tasks，3 repetitions；Direct 18/18、ReAct 36/36、Pipeline 36/36；三模式公平对比仅 single 子集 |
| Public repo safety | **PUBLIC_REPO_SAFE = YES**；范围为项目文件与新提交项目 blob，正常Git署名保留；见 PUBLIC_REPO_SAFETY_AUDIT.md |
| Resume-safe keywords | Agent Runtime, Tool Registry, bounded ReAct, Pipeline/DAG, asyncio, Context Management, Error Recovery, Trace/Replay, FastAPI, SQLAlchemy, SQLite, Docker, Evaluation |
| Resume-safe numbers | 5 tools；3 modes；48 synthetic tasks；7/8 live；45 offline tests；96.18% statement coverage；3×80ms 场景 {a["median_speedup"]:.2f}× |
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
"""
    (ROOT / "FINAL_AGENT_RUNTIME_REPORT.md").write_text(final)
    print("Wrote measured experiments and final report")


if __name__ == "__main__":
    main()
