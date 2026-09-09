# Three Controlled Experiments

实际测量时间：2026-09-09T10:58:06.744325+00:00。实现基础：`345493bd83cafeeb340601b170bed7547b3746dc`。
环境：Python 3.14.6 / Darwin / arm64；单进程、本地 SQLite。
原始数据：[experiments.json](../evaluation/results/experiments.json)，不继承旧项目数字。

## A. Sequential vs Async Parallel Tool Execution

3 个独立 HTTP mock 工具分别真实 `await asyncio.sleep(80ms)`；每组串行/并行成对测量，共 7 组，交替先后顺序。

| 模式 | n | 中位数 ms | 平均 ms | 最小 ms | 最大 ms |
|---|---:|---:|---:|---:|---:|
| Sequential | 7 | 253.79 | 254.66 | 252.08 | 261.95 |
| Async parallel | 7 | 91.65 | 91.74 | 90.69 | 93.38 |

中位数比值 **2.77×**。每次均校验相同输出和 3 次工具调用。运行时指标包括主要状态持久化开销，但不包括最后一次 final 快照的数据库提交。

Timeout probe：一个 250ms 延迟工具受 120ms 单次 deadline 限制，最多重试 2 次；独立 10ms 工具仍成功。总体状态 FAILED，总时延 266.32ms；根因为 TOOL_TIMEOUT，外层错误 RETRY_EXHAUSTED。见 JSON 的 timeout_probe。

取舍：并行增加并发占用，仅对独立 I/O 等待有效；没有 CPU 加速、互联网性能或吞吐证据。波次调度会等待整层完成，不能消除慢步骤或必需步骤失败。

## B. Naive Truncation vs Structured Compaction

每 turn 为 user+assistant 两条消息。固定 5/10/20/40 turns，4 个显式标注事实，400 估算 token 预算，每项测 20 次。

| Turns | 策略 | context bytes | 估算 tokens | retained facts | task success | 中位 CPU ms |
|---:|---|---:|---:|---:|---:|---:|
| 5 | naive | 640 | 160 | 2/4 | 0% | 0.0227 |
| 5 | structured | 1267 | 317 | 4/4 | 100% | 0.0331 |
| 10 | naive | 640 | 160 | 2/4 | 0% | 0.0234 |
| 10 | structured | 1569 | 393 | 4/4 | 100% | 0.0784 |
| 20 | naive | 642 | 161 | 2/4 | 0% | 0.0227 |
| 20 | structured | 1571 | 393 | 4/4 | 100% | 0.0865 |
| 40 | naive | 642 | 161 | 2/4 | 0% | 0.0230 |
| 40 | structured | 1571 | 393 | 4/4 | 100% | 0.0880 |

任务成功是受控 key/value 提取器能从保留下来的上下文取回全部 4 个事实，不是 LLM 准确率。真实 provider token/cost 均为 null，表中估算量为 ceil(UTF-8 bytes/4)。

Structured 保留更多早期事实，也占用更多上下文和 CPU；naive 更短、更便宜，近期事实仍能保留。Bad case：事实自身超预算时，structured 保留 1 条、丢弃 19 条，仍遵守 99 的估算预算。

## C. Direct / ReAct / Pipeline

12 个定义明确的任务：6 单工具、3 依赖聚合、3 条件分支，各重复 3 次。ReAct 使用确定性动作脚本，不消耗模型网络时延或 token。Direct 只纳入其适配的 6 单工具任务。

| 模式 / 任务族 | 成功 / runs | 中位 ms | 平均 tool attempts | 平均 provider calls |
|---|---:|---:|---:|---:|
| direct/single | 18/18 | 6.31 | 1.00 | 0.00 |
| react/single | 18/18 | 7.99 | 1.00 | 2.00 |
| react/dependent | 9/9 | 16.49 | 3.00 | 4.00 |
| react/conditional | 9/9 | 11.64 | 2.00 | 3.00 |
| pipeline/single | 18/18 | 6.47 | 1.00 | 0.00 |
| pipeline/dependent | 9/9 | 11.16 | 3.00 | 0.00 |
| pipeline/conditional | 9/9 | 9.55 | 2.00 | 0.00 |

公平的三模式比较是 single 子集：相同的 6 个任务、各 3 次。不同任务族不能混在一起宣称某模式更准。Direct 不支持依赖和条件调度，因此为 N/A，未把已知工具结果硬编码进 Direct 参数以制造对等。

Bad case：用 Direct 的单次 alpha 查询处理“查询 alpha、beta 并求和”，Runtime SUCCESS、返回 value=10，但复合任务失败。ReAct 提供动态动作接口并增加 provider 轮次；Pipeline 适合固定依赖，省去 LLM 调用，但配置与波次调度也有开销。真实模型延迟须另看 live held-out，不能把这里的 mock 毫秒数当作真实 Agent 延迟。

## 测量限制

样本量小；实验受进程调度、数据库缓存和本地负载影响；记录原始所有 repetitions，无显著性检验。没有使用 profiler 证明微秒差异的成因；不承诺新机器、真实网络或真实任务上同样的比值。后续若复测，须保留运行时间和环境，不挑最好的一次。
