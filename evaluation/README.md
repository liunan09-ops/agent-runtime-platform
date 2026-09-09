# Evaluation protocol v1

固定数据集先于 held-out 执行提交：`64ce2d1`；SHA-256 见 `datasets/manifest-v1.json`。48 条任务为 32 development / 16 held-out。数据及答案合成且公开；此 held-out 是工程开发协议分组，不是盲测或外部基准。不在 src 中按 case ID、split 或 expected answer 分支。

## 运行

```bash
python -m evaluation.harness --split development
python -m evaluation.harness --split held-out
python -m evaluation.harness
python -m evaluation.harness --live
python -m evaluation.experiments
python -m evaluation.verify_docker
```

`--live` 只选 8 条标记 live_eligible 的 held-out 自然语言任务，丢弃 mock_script，统一通过 ReAct 请求真实服务。运行失败也写入报告，不筛选最好结果。普通 run 使用脚本 mock 或显式工具/工作流，不消耗模型 token。

## 指标定义

| 指标 | 分子 / 分母 | 限制 |
|---|---|---|
| task_success | 通过全部 expected dotted-path 断言的 case / 全 case | 负例要求正确 REJECTED/FAILED；不是所有 case 都要求 SUCCESS |
| tool_selection_accuracy | 工具名称调用多重集合交集 / max(实际、目标逻辑调用数) | 不要求独立并行步骤的完成顺序相同；按 logical selection，含被校验拒绝的选择 |
| tool_argument_accuracy | 工具名+args 的 canonical JSON 字符串多重集合交集 / 同上 | 保留数值 int/float 表示差异与 SQL 空格，严格而非语义等价 |
| workflow_completion | SUCCESS 的 Pipeline / 所有 Pipeline | 包含刻意失败的工作流，9/12 不是 3 个实现缺陷 |
| recovery_success | 错误处理 case 的全部任务断言通过 / 错误处理 case | 包含安全拒绝、正确终止，不全是“从失败变成功”；只用于工程契约 |
| context_fact_retention | 从受预算上下文取回的正确实体值 / 所需实体值 | 显式标注事实，受控提取器；不是 LLM 自然语言答题 |
| latency | perf_counter elapsed | run 包含调度及状态落库（最终一次保存不含在 state.latency_ms）；context 是 compaction CPU 时间 |
| llm_call_count | provider.complete attempts | mock 调用也是 mock provider 调用，不冒充网络调用 |
| tool_call_count | 实际 execute attempt | 未注册、权限或输入验证拒绝为 0；成功重试两次为 2 |
| token_usage | provider 返回 prompt/completion/total | mock 为 null；context estimate 单列 |
| cost_usd | 无价格配置 | null，不从 token 虚构费用 |

## 已知 bad cases

1. e01/e03/e05/e07：naive 丢失 owner、budget 两个早期事实；输出上下文仍在预算内，任务失败合理。
2. d10 live：SQL total=47 正确，但模型输出整个 observation，违反 final payload 格式；保持 task_success=false，不为 held-out 修补特殊规则。
3. r12 live：参数化 SQL 在 `item = ?` 的空格与目标 `item=?` 不同。任务通过、strict argument match 不通过。
4. p01/p09 deterministic：上游输出 float 与目标 int 的 JSON 表示不同，严格参数指标扣分，任务语义仍通过。
5. 重要实体总量超过预算，structured 同样丢失事实；见实验 B overflow probe。
6. Direct 单调用不能实现两个 HTTP 查询后聚合；Runtime SUCCESS 不代表该复合任务完成。

## 证据与复现

每条运行保存完整结构化 trace；报告写明 UTC 实际时间、Git 工作基础版本、Python 和系统类型。首次 live 在基于 `64ce2d1` 的工作区执行，harness 与 trace 随后纳入 `345493b`；期间的格式化和 Pipeline fallback 状态记录修正未修改 live prompt、数据集或评分。最终 deterministic / experiments 对实现 checkpoint 再执行一次。真实模型具有随机性与服务端版本变化，复跑不保证同样数字；不要用复跑结果覆盖首次记录后宣称提高。

本仓库不使用旧项目评测数字，也不把 8 条 live 结果称为大规模 benchmark。成本、tokenizer 准确率、自动摘要质量、真实网络并发收益、吞吐和在线用户规模均无证据。
