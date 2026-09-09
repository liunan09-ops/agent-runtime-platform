# Verification Record

开发/运行真实日期：2026-09-09；所有时间来自系统或 Git 默认时间，没有日期覆盖。所有数据为本项目合成数据。

## 测试

- 本机 Python 3.14.6：45 passed、1 live skipped；另 `RUN_LIVE_TESTS=1 pytest -m live`：1 passed，45 deselected。
- Docker Python 3.11.16：同套 45 passed、1 live skipped。为了运行测试，仅在临时测试容器内安装 requirements-dev.lock、只读挂载 tests/evaluation/config；应用源码使用镜像安装包。临时测试容器用 root 装依赖，不改变应用运行 UID 10001 的验证。
- 语句覆盖：857/891 = 96.18%；34 条未覆盖语句，未声称分支覆盖。
- Ruff check 与 format 验证通过。
- 证据：[pytest.log](evidence/pytest.log)、[pytest-live.log](evidence/pytest-live.log)、[pytest-docker-py311.log](evidence/pytest-docker-py311.log)、[coverage.json](evidence/coverage.json)。
- JUnit XML 的 hostname 和 absolute project prefix 已移除；测试数量、状态、时延、日期没有修改。

覆盖关注：Registry 生命周期与 schema、五工具安全边界、输出违约、幂等重试、Direct/ReAct/DAG/condition、并发重叠与上限、取消清理、总timeout/LLMtimeout、坏JSON修复、模型不可用fallback、部分失败、context预算/事实overflow、状态转换、持久化重启、异常中断终态、trace序号、结果回放零调用、API和并发run隔离。

## Evaluation

48 条 v1 数据集先固定并提交，然后运行。deterministic 最终复核基于实现 checkpoint `345493b`；首次 live 结果原样保留，见 evaluation/README.md 的版本说明。所有结果、包括失败项，都保存可核对 trace。没有针对 held-out 加入 prompt 或运行时规则。

A/B/C 实验最终复核得到串行 253.79ms、并行 91.65ms，中位比2.77×。所有原始 repetitions 在 experiments.json，不能把 repeated runs 当独立任务扩大样本量。

## Docker

[机器证据](evidence/docker-verification.json)包括实际 image ID、Docker server版本、Python版本、运行/重启健康、offline ReAct/DAG输出、trace数量、replay零调用、restart前后RunState相等、非root UID、.env不存在和live request返回值/usage。

验证脚本使用唯一临时容器/volume，并在 finally 中只删除自己创建的资源；不改动已有容器、数据库或服务。网络端口绑定 localhost，避免把无鉴权演示接口公开暴露。

## 实际修复记录

1. 首轮 SQL 测试失败：初始化数据的事务未先提交，authorizer 也阻止连接上下文退出时的事务操作。改为初始化后commit、受控只读执行、closing确保连接关闭。读查询与写拒绝测试通过。
2. Pipeline fallback成功后的总状态遗漏RECOVERING。按波次检测是否发生错误，再统一推进恢复状态，新增测试覆盖，避免并行协程竞争修改状态。
3. 首次容器restart验证失败：Docker为随机映射端口重分配，验证脚本请求旧端口；服务正常重启。脚本重新查询端口，之后验证成功。保留[首次失败证据](evidence/docker-first-attempt.json)，并将尚未到达的live步骤明确标记NOT_REACHED。
4. Pytest通过可执行入口运行时，项目级evaluation包不在搜索路径；在pytest配置中明确pythonpath，验证了本机和3.11容器两种入口。

没有为提高 held-out 成绩修改通用 prompt 或解析已知答案。live d10 的 final JSON 错误、r12严格SQL参数差异和naive丢事实都保留在结果中。

## 证据边界

测试/模型/容器/实验分别报告。最终落库前记录的 state.latency_ms 不包括最后一次 final save，因此不宣称完整HTTP端到端耗时。Provider返回tokens可信度高于本地估算；无价格配置时cost为null。正常Git作者署名保留，发布范围不是匿名历史；源文件和证据移除了宿主个人路径和hostname。
