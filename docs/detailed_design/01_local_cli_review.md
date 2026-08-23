# 本地命令行审查详细设计

## 1. 目标

提供一个无需 GitHub 服务端依赖的本地入口，对指定仓库的 `base...head` 变更执行完整代码审查，并将最终 Markdown 报告输出到标准输出。

该入口用于开发调试、CI 验证和后续 GitHub 集成前的本地能力验证。

## 2. 命令接口

```bash
github-reviewer review \
  --repo /path/to/repository \
  --base origin/main \
  --head HEAD \
  --config config/default.yaml \
  --show-intermediate
```

| 参数 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--repo` | 是 | 无 | 目标 Git 工作区的绝对或相对路径。 |
| `--base` | 否 | 配置中的 `review.base_ref` | 对比基准 ref。 |
| `--head` | 否 | 配置中的 `review.head_ref` | 被审查的目标 ref。 |
| `--config` | 否 | `config/default.yaml` | YAML 配置文件路径。 |
| `--show-intermediate` | 否 | `false` | 在最终报告前输出 Reviewer 和 Verifier 原始结果。 |

命令退出码：`0` 表示审查完成；`2` 表示命令参数或配置错误；`3` 表示仓库准备失败；`4` 表示模型运行失败；`5` 表示内部未预期错误。

## 3. 执行流程

```text
CLI 参数
  -> 加载并校验配置
  -> 解析 repo/base/head
  -> 创建 ReviewRunner
  -> 执行三阶段审查
  -> 输出最终 Markdown
  -> 映射退出码
```

1. `cli.py` 解析参数，不在 CLI 中读取模型环境变量。
2. 使用 `load_config()` 读取 YAML，并在配置校验前展开环境变量。
3. 用参数覆盖 `review.base_ref` 和 `review.head_ref` 的默认值，构造 `RuntimeReviewRequest`。
4. 调用 `create_review_runner(config, repo)` 创建本次运行隔离的工具集与 Agent。
5. 调用 `ReviewRunner.review(request)`，将 `ReviewReport.final_output` 输出到标准输出。
6. `--show-intermediate` 为真时，以固定分隔标题输出两个中间结果；不得输出 API Key、完整环境变量或未脱敏 tracing 数据。

## 4. 输入校验

运行模型前必须检查：

- `repo` 存在、为目录，且其工作区属于 Git 仓库。
- `base` 与 `head` 都可由 Git 解析为 commit。
- 配置文件存在且通过 schema 校验。
- 每个启用 Agent 的 `model` 都指向已定义模型。

若 diff 为空，应返回一份成功的报告，内容明确说明“未发现待审查的代码变更”，且不调用模型以节省成本。

## 5. 输出约定

默认只输出可贴入 PR 的 Markdown。输出至少包含：

- 审查结论：发现问题或无高置信度问题。
- 已确认 finding 列表，按 severity 从高到低排序。
- 每项 finding 的文件、行号、问题说明、影响和建议修复方向。
- 需要人工关注的残余风险或测试缺口。

标准输出承载正常结果；标准错误承载诊断信息。不得把调试日志混入最终 Markdown。

## 6. 测试与验收

- 对一个包含已知缺陷的 fixture 仓库运行，验证请求参数、输出和退出码。
- 对空 diff 验证不会创建模型调用。
- 对不存在的仓库、无效 ref、无效 YAML 和缺失模型映射分别验证可读错误信息。
- 对 `--show-intermediate` 验证中间输出仅在显式开启时出现。

