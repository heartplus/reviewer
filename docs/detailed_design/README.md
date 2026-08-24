# 代码 Review Agent 详细设计文档索引

本文档集合从 [总体设计](../overall_design.md) 拆分而来。每份文档定义一个可独立实现、测试和演进的功能边界。

执行命令与排查方式见[本地 Git 代码审查使用手册](../usage_guide.md)；当前目标的剩余工作见[本地 Git 审查目标缺口清单](../local_review_gap_analysis.md)。

## 文档与交付状态

| 文档 | 功能 | 阶段 | 主要依赖 |
| --- | --- | --- | --- |
| [01_local_cli_review.md](01_local_cli_review.md) | 本地命令行审查 | 当前 | 配置、编排、仓库工具 |
| [02_configuration_and_model_selection.md](02_configuration_and_model_selection.md) | 配置加载与按角色选型模型 | 当前 | OpenAI Agents SDK |
| [03_repository_tools.md](03_repository_tools.md) | 受控仓库工具层 | 当前 | Git、ripgrep |
| [04_multi_agent_review_orchestration.md](04_multi_agent_review_orchestration.md) | Reviewer、Verifier、Summarizer 编排 | 当前 | 配置、仓库工具 |
| [05_review_result_and_structured_findings.md](05_review_result_and_structured_findings.md) | 审查结果与结构化 Finding | 当前 + 演进 | 编排 |
| [06_security_and_error_handling.md](06_security_and_error_handling.md) | 安全边界与异常处理 | 当前 | 配置、仓库工具、CLI |
| [07_observability.md](07_observability.md) | 运行追踪与质量观测 | 当前 | 编排、结果模型 |
| [08_github_app_integration.md](08_github_app_integration.md) | GitHub App 与 PR 评论发布 | 不在当前目标内 | 无 |
| [09_review_result_persistence.md](09_review_result_persistence.md) | 审查记录持久化 | 可选扩展 | 结果模型、可观测性 |
| [10_specialized_review_agents.md](10_specialized_review_agents.md) | 专项审查 Agent 扩展 | 规划 | 多 Agent 编排、结构化 Finding |

“当前”表示本地审查工具应优先完成的能力；“可选扩展”表示不影响命令行审查；“不在当前目标内”表示保留文档作为未来参考，但不纳入验收。

## 推荐实现顺序

1. 配置与模型选择、仓库工具层。
2. 多 Agent 审查编排与本地 CLI。
3. 结果结构化、安全控制、可观测性。
4. 可选的本地持久化与专项 Agent。
