# 代码 Review Agent 总体设计

## 1. 背景

本项目用于构建一个面向 GitHub Pull Request 的代码审查专用 Agent 框架。

整体设计把两类职责分开：

- Agent 运行时：使用 OpenAI Agents SDK 负责 agent loop、tool calling、多 Agent 编排、结构化执行和 tracing。
- 代码审查领域能力：由本项目自己实现仓库检查、diff 处理、grep、blame、测试命令等工具。

这样可以避免从零实现 Agent runtime，同时保留代码审查场景所需的精细控制能力。

## 2. 设计目标

- 审查 Pull Request 中的代码变更，并输出简洁、可验证、有证据支撑的审查意见。
- 重点关注正确性、安全风险、数据丢失、并发问题、API 契约退化和用户可见行为变化。
- 避免输出纯风格类意见和缺少依据的猜测。
- 支持不同 Agent 角色使用不同模型。
- 模型选择必须通过 YAML 配置完成，避免在 Agent 代码中硬编码模型名称。
- 同时支持本地仓库审查，以及未来的 GitHub webhook 集成。

## 3. 非目标

- 不替代人工代码审查的最终批准。
- 不构建通用自主编码 Agent。
- 默认不运行任意 shell 命令。
- 第一版框架不直接向 GitHub 发布评论。
- 不从零实现一套自定义 Agent runtime。

## 4. 总体架构

```text
GitHub PR / 本地分支
        |
        v
Review Request
        |
        v
ReviewRunner
        |
        +-- RepositoryTools
        |     +-- get_diff
        |     +-- changed_files
        |     +-- read_file
        |     +-- grep
        |     +-- git_blame
        |     +-- run_tests，可选
        |
        +-- Reviewer Agent
        |     基于代码证据发现潜在问题
        |
        +-- Verifier Agent
        |     质疑和验证 Reviewer 的结论
        |
        +-- Summarizer Agent
              生成最终 Markdown 审查结果
        |
        v
ReviewReport
```

框架采用分阶段审查流程，而不是只依赖一个大型 Agent 一次性完成全部工作。这样可以让中间结果更容易审计，也能降低误报率。

## 5. 核心审查流程

1. 根据本地仓库路径、base ref 和 head ref 构造 review request。
2. 使用 repository tools 收集变更文件列表和 unified diff。
3. 将 diff 和文件列表发送给 Reviewer Agent。
4. Reviewer Agent 在必要时调用工具读取上下文、搜索引用或查看 blame。
5. 将 Reviewer 的输出和原始 diff 一起发送给 Verifier Agent。
6. Verifier Agent 对每条发现进行确认、驳回，或要求更多证据。
7. 将 Reviewer 和 Verifier 的输出发送给 Summarizer Agent。
8. Summarizer Agent 返回最终 Markdown 代码审查报告。

当前 CLI 入口：

```bash
github-reviewer review --repo /path/to/repo --base origin/main --head HEAD
```

## 6. Agent 角色设计

### 6.1 Reviewer Agent

职责：

- 阅读 diff。
- 使用工具读取变更代码周边上下文。
- 发现正确性和安全性问题。
- 解释影响，并引用具体代码证据。

期望输出：

- 审查摘要。
- 问题列表，每个问题包含 severity、file/line、evidence、impact 和 suggested fix。
- 可用于验证问题的测试或检查建议。

Reviewer Agent 不应该输出：

- 单纯风格偏好。
- 没有证据的猜测。
- 缺少可触发路径的问题。

### 6.2 Verifier Agent

职责：

- 逐条质疑 Reviewer 的发现。
- 确认引用的代码证据是否准确。
- 驳回薄弱、错误或过度推断的问题。
- 标记仍然缺少的证据。

期望输出：

- 已确认的问题。
- 被驳回的问题，以及简短原因。
- 仍需补充的证据。

Verifier Agent 可以使用不同于 Reviewer Agent 的模型。这样可以降低“同一个模型重复认可自己错误判断”的风险。

### 6.3 Summarizer Agent

职责：

- 生成最终 Pull Request 审查意见。
- 保留已确认的问题。
- 移除被驳回或置信度不足的问题。
- 保持输出简洁、明确、可执行。

期望输出：

- 可直接作为 PR comment 使用的 Markdown。
- 如果没有高置信度问题，要明确说明。
- 在有必要时补充残余风险或测试缺口。

## 7. 仓库工具层

Repository tools 是 Agent 访问代码仓库的受控接口。

当前工具：

- `get_diff(base_ref, head_ref, context_lines)`：返回 unified git diff。
- `changed_files(base_ref, head_ref)`：返回变更文件列表。
- `read_file(path, start, end)`：安全读取指定文件行范围，并附带行号。
- `grep(pattern, path_glob, max_matches)`：使用 ripgrep 搜索仓库文本。
- `git_blame(path, start, end)`：返回指定行范围的 git blame。
- `run_tests(command, timeout_seconds)`：在配置允许时运行 allowlist 中的测试命令。

设计约束：

- 文件路径必须位于仓库根目录内。
- diff 和文件读取结果受配置的字节数上限约束。
- 测试命令默认关闭。
- 测试命令必须显式加入 allowlist。
- 工具层应保持确定性，并便于审计。

## 8. 模型配置

模型选择通过 YAML 配置完成。

示例：

```yaml
agents:
  reviewer:
    model: reviewer
  verifier:
    model: verifier
  summarizer:
    model: summarizer

models:
  reviewer:
    provider: openai
    name: gpt-5.6-sol
    settings:
      temperature: 0.1
      reasoning_effort: high

  verifier:
    provider: openai
    name: gpt-5.6-luna
    settings:
      temperature: 0.0
      reasoning_effort: medium

  summarizer:
    provider: openai
    name: gpt-5.6-luna
    settings:
      temperature: 0.2
      reasoning_effort: none
```

支持的 provider 模式：

- `openai`：使用 OpenAI Agents SDK 默认 provider，并通过模型名称选择模型。
- `openai_compatible`：接入 OpenAI-compatible Chat Completions endpoint。
- `litellm`：通过 LiteLLM 接入其他模型厂商或内部模型网关。

这种设计允许团队为不同角色选择不同模型。例如：

- Reviewer 使用更强的代码理解模型。
- Verifier 使用另一个模型进行独立验证。
- Summarizer 使用成本更低、速度更快的模型生成最终文本。

## 9. 主要模块

```text
src/github_reviewer/
  config/
    loader.py        加载 YAML，并展开环境变量。
    schema.py        定义类型化应用配置。

  agents/
    model_factory.py 根据配置构造 SDK 模型对象。
    builder.py       创建 reviewer、verifier、summarizer agents。
    runner.py        执行分阶段 review 流程。

  tools/
    repo.py          仓库检查和命令执行工具。

  github/
    events.py        GitHub Pull Request 事件结构。

  review/
    service.py       ReviewRunner 运行时工厂。

  cli.py             本地命令行入口。
```

## 10. 数据模型

### RuntimeReviewRequest

表示一次审查运行请求。

字段：

- `repo`：本地仓库路径。
- `base`：base git ref。
- `head`：head git ref。

### ReviewReport

表示一次审查结果。

字段：

- `reviewer_output`：Reviewer Agent 的原始输出。
- `verifier_output`：Verifier Agent 的原始输出。
- `final_output`：最终 Markdown 审查结果。

保留中间输出有助于调试、评估和后续 review 质量分析。

## 11. 安全与控制

框架必须把仓库内容、diff、PR 描述和评论都视为不可信输入。

关键控制点：

- 工具只暴露有限、明确的能力。
- 文件读取限制在仓库目录内。
- 默认关闭 shell 命令执行。
- 启用 shell 执行时，只允许 allowlist 中的命令。
- 最终输出应避免泄露代码中可能出现的 secret。
- GitHub 评论发布应由独立集成层处理，并受权限模型控制。

未来 GitHub 评论发布能力应满足：

- 幂等；
- 绑定 commit SHA；
- 可配置关闭；
- 可以追踪已发布评论 ID。

## 12. 错误处理

常见失败场景：

- git ref 无效。
- 仓库路径不是 git checkout。
- 文件路径试图逃逸仓库根目录。
- diff 过大并被截断。
- 模型 provider 凭证缺失。
- provider 不支持某个模型参数。
- 工具命令超时。

框架处理原则：

- 配置错误应尽早失败。
- 工具错误在合适场景下应对 Agent 可见。
- CLI 应清晰暴露运行前置条件或配置错误。
- 如果只是可选上下文工具失败，优先保留可用的部分审查结果，而不是静默失败。

## 13. 可观测性

Agent 执行过程应使用 OpenAI Agents SDK tracing 进行观测。

建议保留的关键信号：

- 每个角色实际使用的模型。
- 排除 secret 后的 prompt/run 输入。
- 工具调用及工具输出。
- Verifier 驳回的问题。
- 最终问题数量和 severity 分布。
- 运行耗时。
- 可用时记录 token 使用量。

这些信号可用于调优 prompt、比较模型效果，并评估误报率。

## 14. 后续扩展方向

### 14.1 GitHub App 集成

增加 Pull Request webhook 处理能力：

```text
GitHub Webhook
      |
      v
Webhook Handler
      |
      v
Checkout / Fetch PR
      |
      v
ReviewRunner
      |
      v
GitHub Review Comment
```

### 14.2 审查结果持久化

保存每次审查运行，便于审计和评估。

建议保存：

- request metadata；
- commit SHA；
- model config version；
- intermediate outputs；
- final output；
- posted comment ID。

### 14.3 专项 Review Agent

后续可以增加可选的领域 Agent：

- Security Reviewer。
- Concurrency Reviewer。
- API Compatibility Reviewer。
- Test Coverage Reviewer。
- Database Migration Reviewer。

这些专项 Agent 的输出可以继续进入同一套 Verifier 和 Summarizer 阶段。

### 14.4 结构化输出

后续可以把自由格式 Markdown 问题升级为结构化 finding object。

示例：

```json
{
  "severity": "high",
  "file": "src/example.py",
  "line": 42,
  "title": "Missing authorization check",
  "evidence": "...",
  "impact": "...",
  "suggested_fix": "..."
}
```

结构化输出可以更好地支持 GitHub inline comment、质量统计和回归评估。

## 15. 初始里程碑

1. 支持本地 CLI 审查 `base...head`。
2. 支持按 Agent 角色配置模型。
3. 提供安全的仓库工具层。
4. 增加配置加载和路径安全基础测试。
5. 增加 GitHub App webhook 和 PR checkout。
6. 支持结构化 finding 和 inline comment。
7. 建立评估数据集，用于衡量误报和漏报。
