# 受控仓库工具层详细设计

## 1. 目标

为 Agent 提供最小必要的仓库读取能力，同时避免任意文件读取、任意命令执行和不可控的大上下文输入。

`RepositoryTools` 是唯一允许直接访问 Git 工作区的领域适配层；Agent 与 CLI 均不得自行拼接 Git 或 shell 命令。

## 2. 初始化与共同约束

初始化参数包括仓库根目录与 `ReviewConfig`。初始化时解析根目录真实路径并验证 Git 工作区。

所有路径操作必须遵循：

- 将用户输入路径解析为仓库根目录下的真实路径。
- 拒绝绝对路径、`..` 逃逸、符号链接逃逸和 `.git` 元数据目录访问。
- 文本以 UTF-8 解码；二进制或无法解码的内容返回可解释错误。
- 所有输出受字节数和条目数限制；截断结果带明确标记。
- 每次工具调用记录工具名、参数摘要、耗时、成功状态和截断状态。

## 3. 工具接口

| 工具 | 入参 | 返回内容 | 限制 |
| --- | --- | --- | --- |
| `get_diff` | `base_ref`、`head_ref`、`context_lines` | unified diff | context 限制在 0-20；总字节数受配置控制。 |
| `changed_files` | `base_ref`、`head_ref` | 文件状态、路径；重命名时包含旧路径 | 限制最大文件数。 |
| `read_file` | `path`、`start`、`end` | 带行号的文本行 | 行范围必须合法；受单文件上限控制。 |
| `grep` | `pattern`、`path_glob`、`max_matches` | 匹配位置与摘录 | 固定为文本搜索；限制匹配数和单条长度。 |
| `git_blame` | `path`、`start`、`end` | 行级提交摘要 | 只允许仓库内普通文件和有限行范围。 |
| `run_tests` | `command`、`timeout_seconds` | `exit_code`、独立的 `stdout`/`stderr`、`timed_out` 与截断标记 | 默认禁用，命令必须精确命中 allowlist。 |

## 4. Git 命令设计

Git 命令使用参数数组执行，禁止通过 shell 解释字符串。`get_diff` 应使用等价于下列语义的调用：

```text
git diff --no-ext-diff --unified=<context> <base>...<head> --
```

在执行前分别验证两个 ref，避免将恶意参数解释为选项。变更文件使用 `--name-status -z`，按 NUL 分隔解析，以正确处理包含空格的文件名。

## 5. 测试命令策略

测试命令是高风险能力，按以下规则控制：

1. `allow_test_commands` 为空时，`run_tests` 返回“功能未启用”。
2. 调用值必须与 allowlist 条目完全相等，不接受前缀或子串匹配。
3. 命令在仓库根目录执行，继承最小化环境变量，不注入 secret。
4. 超时时终止子进程，并返回 `timed_out=true`、`exit_code=null`。
5. stdout/stderr 独立截断，保留退出码和截断标志；子进程仅继承运行所需的最小环境变量，不能继承 API Key 等调用端 secret。

## 6. 错误返回

工具错误以结构化文本或后续定义的 `ToolResult` 返回，至少包含稳定的错误码：`INVALID_REF`、`PATH_OUTSIDE_REPO`、`FILE_NOT_FOUND`、`BINARY_FILE`、`COMMAND_DISABLED`、`COMMAND_NOT_ALLOWED`、`COMMAND_TIMEOUT`。

可恢复错误应对 Agent 可见，使其能调整搜索策略；初始化失败、仓库损坏等不可恢复错误由上层终止本次审查。

## 7. 测试与验收

- 验证普通 diff、重命名文件、含空格路径和空 diff。
- 验证 `../`、绝对路径、符号链接逃逸和 `.git` 读取均被拒绝。
- 验证 diff、文件读取、grep 和测试输出的截断标记。
- 验证测试命令关闭、未列入 allowlist、超时和非零退出码。
