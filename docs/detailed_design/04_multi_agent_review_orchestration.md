# 多 Agent 审查编排详细设计

## 1. 目标

将发现问题、独立验证和面向开发者的表达拆分为三个阶段，降低单次模型输出造成的误报，并保留完整的审计链路。

## 2. 组件职责

| 组件 | 输入 | 输出 | 允许工具 |
| --- | --- | --- | --- |
| Reviewer | diff、文件列表、审查规则 | 候选 findings | 全部仓库只读工具；测试工具受配置控制。 |
| Verifier | 原始 diff、候选 findings | confirmed/rejected/needs_evidence | 同 Reviewer。 |
| Summarizer | 验证结果、候选 findings、运行元数据 | 最终 Markdown | 默认不调用工具。 |
| ReviewRunner | `RuntimeReviewRequest` | `ReviewReport` | 负责顺序调用与错误编排。 |

## 3. 运行时流程

```text
准备 diff 与文件列表
  -> Reviewer：生成候选问题
  -> Verifier：逐项确认、驳回或要求证据
  -> Summarizer：只依据已确认问题生成报告
  -> ReviewReport
```

1. `ReviewRunner` 先收集 diff 与变更文件；两者是后续阶段的共同事实输入。
2. 调用 Reviewer。其提示词要求只报告可由代码路径和仓库证据支持的问题，并附文件与行号。
3. 调用 Verifier。其提示词要求逐项重查证据与触发条件，不能仅认可 Reviewer 的措辞。
4. 调用 Summarizer。它只保留 `confirmed` finding；`needs_evidence` 只能进入“残余风险/测试缺口”，不得作为确定 bug。
5. 保存各阶段原始文本、结构化结果和模型运行元数据到 `ReviewReport`。

阶段间传递内容应采用有边界的摘要：diff 受配置截断，候选 finding 数量受上限控制。不得把完整工具调用历史无差别拼入后续 prompt。
每个角色的模型/工具循环受 `review.max_agent_turns` 限制，防止兼容模型在大型变更上无界探索。

## 4. Agent 指令要求

Reviewer 指令必须强调：正确性、安全、数据损失、并发、API 契约和用户可见行为；忽略纯格式问题；每项 finding 说明触发条件与影响。

Verifier 指令必须强调：寻找反例；验证行号、调用路径和现有保护条件；明确输出确认、驳回或证据不足的结论。

Summarizer 指令必须强调：简洁、可执行、无夸张；不重新发明问题；无确认问题时输出明确的“未发现高置信度问题”。

## 5. 故障降级

- Reviewer 失败：本次审查失败，不产生可能误导使用者的最终结论。
- Verifier 失败：默认不发布 Reviewer 原始 finding；CLI 可以通过显式 `--allow-unverified-output` 作为实验性开关输出，并标记“未验证”。
- Summarizer 失败：由确定性的本地渲染器依据已确认结构化 finding 生成 Markdown。
- 单个工具调用失败：将错误反馈给当前 Agent；若仍能完成任务，保留部分结果并在报告中标示上下文缺口。

## 6. 并发与可扩展性

第一阶段采用串行编排，确保 Verifier 基于完整 Reviewer 结论工作。后续增加专项 Agent 时，可并行执行多个发现阶段，再合并为统一候选 finding 集合交给 Verifier。

每次 `ReviewRunner` 运行必须创建独立的请求上下文、工具实例和 trace，不能共享可变的 Agent 会话状态。

## 7. 测试与验收

- 使用 mock 模型验证三阶段输入、调用顺序和输出归属。
- 验证 Summarizer 无法访问未确认 finding 作为确定结论。
- 验证 Verifier、Summarizer 失败时的降级与状态标记。
- 验证不同角色通过配置使用不同模型。
