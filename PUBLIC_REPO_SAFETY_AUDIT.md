# Public Repo Safety Audit

审计日期：2026-09-09。范围：本项目 `agent-runtime-platform/` 的源码、配置、测试、合成数据、README/文档、可公开证据，以及从固定 Base HEAD 之后新增提交中的项目文件 blob。机器结果见 [public-safety.json](docs/evidence/public-safety.json)，复现命令 `python -m evaluation.audit_public`。

## 检查结果

| 检查项 | 结论与处理 |
|---|---|
| API key | 环境中存在合法 DeepSeek key，真实调用成功；未写入源文件、请求JSON或trace；扫描实际环境凭证精确匹配为0 |
| token | 只保留 provider token usage 数量；常见密钥格式、Bearer/Authorization风险经代码审阅；测试占位值为合成字符串 |
| password / private key | 无真实口令或私钥文件；包含的password字段只用于redaction测试与规则，数据为合成值 |
| private path / hostname | JUnit中宿主路径前缀与hostname已删除；首次失败日志路径替换为 `<project>`；源码与公开证据不含个人绝对路径 |
| personal data | 任务、inventory、知识、事实、人名均为合成示例；request/session ID 为随机技术ID；无真实用户对话或客户记录 |
| corporate data | 不读取公司系统、客户库或业务文件；无公司数据 |
| old project artifacts | 基础树为空；所有新增文件仅位于本独立子目录；无旧代码、旧测试结果、旧评测数字或打包产物 |
| Docker | allowlist COPY；.env、runtime数据库、虚拟环境、Python缓存和egg-info不进入构建上下文；实际镜像无/app/.env |
| Git tracked files | .env.example为空凭证模板；忽略.env变体、数据库、缓存和虚拟环境；无merge/cherry-pick |
| 历史项目 blobs | 自动扫描 Base之后可达的项目blob，不仅扫描当前文件，防止删除当前文件后误认为历史安全 |
| Trace contents | 合成任务trace可公开；不保存reasoning_content/隐藏chain-of-thought或Authorization；包含实际模型选工具行为、usage和失败结果 |
| 外部操作 | 只调用用户已授权的DeepSeek、拉取公开Python/Docker依赖；未发送邮件/消息，未push或发布远端仓库 |

## 审计边界

本结论针对项目内容可公开，不声称任意未来输入都安全。运行时redaction是best effort；真实用户新增trace仍须单独审核。数据库和本地虚拟环境没有随Git或Docker发布。

**正常 Git 作者/提交者署名元数据保留，项目不属于匿名发布。** 机器审计不输出作者身份；没有为了匿名化重写用户指定的Base历史、提交身份或日期。若公开原分支，Git署名仍属于其正常发布元数据。文件证据中的宿主个人路径和hostname已处理，不能把这种处理描述成Git历史匿名化。

AI辅助开发已披露。所有测试和实验均保留真实日期；只做内容脱敏，不篡改Git日期或手工回写mtime；文件编辑自然更新修改时间。最终HEAD回执在提交后生成且gitignored，避免自身hash循环，里面仅有分支、commit、日期和Git状态。

PUBLIC_REPO_SAFE = YES
