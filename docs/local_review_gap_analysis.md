# 本地 Git 审查目标缺口清单

## 1. 当前验收目标

工具只需要对用户指定的本地 Git 仓库执行两种审查：

- `review`：审查一个 `base...head` 范围的总体变更。
- `history`：按时间顺序审查 `base..head` 中每个提交的单独变更。

不要求 GitHub App、Webhook、远程仓库 checkout、PR 评论、任务队列或服务端数据库。

## 2. 已满足的能力

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| 配置化模型选择 | 已满足 | YAML 可分别指定 Reviewer、Verifier、Summarizer 的 provider、模型和参数。 |
| OpenAI-compatible 模型 | 已满足 | 默认配置可使用 DeepSeek Pro 和 Flash。 |
| 单个范围审查 | 已满足 | `review --repo --base --head` 输出确定性的 Markdown 报告。 |
| 指定提交审查 | 已满足 | 传一个 `--commit <SHA>` 时比较其父提交；重复传两个 `--commit` 时比较指定的 base/head。 |
| 逐提交历史审查 | 已满足 | `history --repo --base --head --limit` 不修改目标工作区。 |
| 全量历史审查 | 已满足 | `history --all` 包含根提交，并以空 Git tree 作为其比较基线。 |
| 三阶段验证 | 已满足 | Reviewer 发现、Verifier 裁定、Summarizer 组织结果；最终仅输出 confirmed finding。 |
| 基础仓库隔离 | 已满足 | 路径逃逸、`.git` 访问、无效 ref 和二进制文件均受限。 |
| 空 diff 节省模型调用 | 已满足 | 无变更时直接返回结果。 |

## 3. 已补齐的必要项

### 3.1 命令行端到端测试

已加入 Typer 端到端测试，覆盖 `review`、`history`、配置错误、模型失败、标准输出与
`--show-intermediate` 的脱敏行为。

### 3.2 测试工具的返回契约

`run_tests` 现在返回退出码、独立截断后的 stdout/stderr、`timed_out` 与截断标记，并只
向子进程传入最小环境变量。测试覆盖非零退出、超时、输出截断和父进程 secret 隔离。

### 3.3 输出前的统一脱敏

模型输入、仓库工具输出、结构化日志、终端中间结果、最终 Markdown 与可选 SQLite 保存
均使用同一套递归脱敏规则，覆盖常见 token、Bearer header、私钥和带认证信息的 URL。

### 3.4 Provider 的有限重试

临时 Provider 错误会按配置进行有限次数的指数退避加抖动，并将重试次数写入运行元数据
和结构化事件；认证、无效模型和工具循环上限等错误不会重试。

### 3.5 工具审计与变更状态

`changed_files` 现在保留新增、删除、修改和重命名状态。每次仓库工具调用都会产生脱敏的
结构化事件，包含工具名、参数摘要、耗时、成功状态、截断状态和错误码；工具错误同步写入
本次运行的 `tool_failures` 元数据。

最终报告的结论和 finding 数量只由 Verifier 裁定后的结构化 finding 生成，不再直接采用
Summarizer 的自由文本摘要。

## 4. 后续优化项

- 为 `history` 增加可选的 Markdown 输出目录，便于长期保存每个提交的报告；当前可通过 shell 重定向保存。

## 5. 不纳入当前验收

- GitHub Webhook、GitHub App installation token、PR 评论发布和评论幂等。
- 远程仓库 clone、服务端任务队列和多用户权限控制。
- GitHub 评论相关的 outbox 与 published comments 数据模型。
