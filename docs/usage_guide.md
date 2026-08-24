# 本地 Git 代码审查使用手册

## 1. 用途

`github-reviewer` 只审查本机已有的 Git 仓库，不会修改仓库、切换分支或创建提交。

- `review`：将一个 ref 范围作为整体审查。
- `history`：逐个审查一个 Git 历史范围中的提交。

报告默认输出到终端，内容为 Markdown。

## 2. 安装

在项目根目录执行：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

工具需要 Git。启用仓库搜索时还需要 `rg`（ripgrep）。

## 3. 配置模型

复制环境变量模板并填入模型服务的 API Key：

```bash
cp .env.example .env
```

`.env` 已被 Git 忽略。不要将 API Key 写入 `config/default.yaml`、报告或终端命令历史。

默认配置使用 DeepSeek：

- Reviewer：`deepseek-v4-pro`
- Verifier：`deepseek-v4-pro`
- Summarizer：`deepseek-v4-flash`

模型、endpoint、API Key 环境变量名和角色映射都在
[`config/default.yaml`](../config/default.yaml) 中配置。DeepSeek 的默认 endpoint 为
`https://api.deepseek.com`。

可通过环境变量临时指定密钥：

```bash
export DEEPSEEK_API_KEY='your-api-key'
```

## 4. 审查一个范围

下面的命令审查 `origin/main` 到当前 `HEAD` 的全部变更：

```bash
github-reviewer review \
  --repo /absolute/path/to/repository \
  --base origin/main \
  --head HEAD
```

常用参数：

| 参数 | 含义 |
| --- | --- |
| `--repo` | 被审查的本地 Git 仓库路径，必填。 |
| `--base` | 比较起点；省略时使用配置中的 `review.base_ref`。 |
| `--head` | 比较终点；省略时使用配置中的 `review.head_ref`。 |
| `--config` | YAML 配置路径；默认是 `config/default.yaml`。 |
| `--show-intermediate` | 额外显示 Reviewer 与 Verifier 的结构化中间结果。 |
| `--verbose` | 将运行诊断输出到标准错误。 |

例如，审查两个明确提交之间的总体差异：

```bash
github-reviewer review \
  --repo /absolute/path/to/repository \
  --base a1b2c3d \
  --head e4f5a6b
```

## 5. 逐提交审查 Git 历史

下面的命令按时间顺序审查 `origin/main..HEAD` 中的每个提交：

```bash
github-reviewer history \
  --repo /absolute/path/to/repository \
  --base origin/main \
  --head HEAD \
  --limit 20
```

`base` 本身不包含在范围内，语义等价于：

```bash
git rev-list --reverse origin/main..HEAD
```

每个提交都以“该提交的父提交 -> 该提交”的差异进行审查。即使当前工作区有未提交修改，
历史审查读取的仍是提交对象中的版本，不会触碰工作区文件。

先确认范围内有哪些提交：

```bash
git -C /absolute/path/to/repository log --oneline origin/main..HEAD
```

审查仓库的全部可达提交（包括根提交）时，使用 `--all`：

```bash
github-reviewer history \
  --repo /absolute/path/to/repository \
  --head HEAD \
  --all \
  --limit 200
```

根提交会与一个空 Git tree 比较，因此也会得到独立报告。`--all` 会忽略 `--base`。

## 6. 保存报告

报告写到标准输出，诊断日志写到标准错误。保存报告时只重定向标准输出：

```bash
github-reviewer history \
  --repo /absolute/path/to/repository \
  --base origin/main \
  --head HEAD \
  --limit 20 \
  > review-history.md
```

范围审查同理：

```bash
github-reviewer review --repo /absolute/path/to/repository --base origin/main --head HEAD > review.md
```

## 7. 配置中的关键限制

`config/default.yaml` 的 `review` 区域控制输入规模与工具行为：

- `max_diff_bytes`：最大 diff 大小；超出时会截断。
- `max_file_bytes`：单次文件读取和搜索结果上限。
- `max_agent_turns`：每个 Agent 最多的模型/工具循环次数。
- `provider_retry_max_attempts`：模型临时失败时的最大尝试次数，默认 `3`。
- `provider_retry_base_delay_seconds` 与 `provider_retry_max_delay_seconds`：重试退避时间范围。
- `allow_test_commands`：默认 `false`；只有显式开启后才允许 Agent 运行测试。
- `test_command_allowlist`：可执行测试命令的精确白名单。

启用测试命令时，工具返回退出码、独立的标准输出与标准错误、超时和截断状态。测试进程只继承最小运行环境，不会继承模型 API Key 等调用端 secret。

默认 DeepSeek 配置将 `agents.reviewer.use_repo_tools` 与
`agents.verifier.use_repo_tools` 设为 `false`，即只基于传入的 diff 审查。这是为了避免
兼容模型在工具循环中反复调用。若所用模型的工具调用稳定，可改为 `true` 以读取更多上下文。

## 8. 退出码与排查

| 退出码 | 含义 | 常见处理方式 |
| --- | --- | --- |
| `0` | 审查完成。 | 查看 Markdown 报告。 |
| `2` | 配置或参数错误。 | 检查 YAML、环境变量、模型名和命令参数。 |
| `3` | 仓库或 Git ref 错误。 | 确认路径是 Git 仓库，并用 `git rev-parse <ref>` 验证 ref。 |
| `4` | 模型调用失败。 | 检查 API Key、网络、endpoint、模型名与供应商状态。 |
| `5` | 未预期错误。 | 使用 `--verbose` 重试，并保留标准错误内容排查。 |

常见问题：

- `origin/main` 不存在：将 `--base` 改为仓库实际分支或明确 commit SHA。
- 输出提示没有变更：确认 base 与 head 不同，并用 `git diff base...head` 检查。
- 模型凭证缺失：确认 `.env` 位于项目根目录，或已在当前终端导出对应变量。
- 报告缺少上下文：适当提高 `max_diff_bytes`，或对支持工具调用的模型开启 `use_repo_tools`。

## 9. 执行前检查

```bash
git -C /absolute/path/to/repository status --short
git -C /absolute/path/to/repository rev-parse origin/main
git -C /absolute/path/to/repository rev-parse HEAD
github-reviewer --help
github-reviewer history --help
```
