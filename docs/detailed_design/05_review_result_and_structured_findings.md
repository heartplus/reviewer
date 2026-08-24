# 审查结果与结构化 Finding 详细设计

## 1. 目标

定义稳定的运行输入、内部 finding 和最终报告模型，使本地 CLI、可选持久化和评估使用同一份语义数据，而不是解析自由格式 Markdown。

## 2. 数据模型

```text
RuntimeReviewRequest
  repo: Path
  base: str
  head: str
  source: local
  pull_request_number: int | null
  commit_sha: str | null

ReviewFinding
  id: str
  severity: critical | high | medium | low
  status: candidate | confirmed | rejected | needs_evidence
  file: str
  line_start: int
  line_end: int | null
  title: str
  evidence: str
  trigger: str
  impact: str
  suggested_fix: str | null
  verifier_reason: str | null

ReviewReport
  request: RuntimeReviewRequest
  reviewer_output: str
  verifier_output: str
  findings: list[ReviewFinding]
  final_output: str
  metadata: ReviewRunMetadata
```

`ReviewRunMetadata` 至少包括运行 ID、开始结束时间、实际模型、diff 是否截断、工具失败摘要及各阶段状态。

## 3. Finding 生成与验证规则

Reviewer 生成的每项 finding 首先为 `candidate`。Verifier 对每项设置以下一种状态：

- `confirmed`：代码位置、触发条件和影响均有充分证据。
- `rejected`：结论错误、代码未受影响或已有保护机制；必须填写原因。
- `needs_evidence`：存在合理风险，但当前仓库证据不足；必须说明缺少什么。

只有 `confirmed` finding 可以出现在最终“问题”列表。严重级别含义：

| Severity | 含义 |
| --- | --- |
| `critical` | 可导致广泛数据泄露、数据丢失或服务不可用，应阻断合并。 |
| `high` | 具有明确触发路径的严重正确性或安全问题，应在合并前修复。 |
| `medium` | 重要边界条件、兼容性或可恢复性问题，通常应修复。 |
| `low` | 影响有限但有可验证价值的问题，不用于纯风格建议。 |

## 4. 标识与定位

`id` 由稳定字段生成，例如 `SHA-256(file + line_start + title)` 的短前缀。相同提交的重复运行应生成相同 ID，支持本地结果去重和统计。

`file` 必须是仓库根目录相对路径。行号必须落在 `head` 版本中；若无法可靠定位，应作为残余风险或测试缺口表达，不能伪装成可定位 finding。

## 5. Markdown 渲染

最终 Markdown 由 `ReviewReport.findings` 确定性渲染；模型摘要不直接进入最终结论，避免其措辞与结构化裁定矛盾。排序规则为 severity、文件路径、行号。

每项 confirmed finding 使用固定模板：

```markdown
### [high] `src/auth.py:42` Missing authorization check

**影响：** 未授权用户可读取其他租户的数据。

**证据：** 请求路径在读取记录前未验证 tenant_id。

**建议：** 在查询条件中加入当前主体的 tenant_id，并补充跨租户访问测试。
```

没有 confirmed finding 时，报告需包含结论和测试缺口，不可伪造正面保证。

## 6. 演进兼容性

第一阶段可同时保留 Agent 原始文本和解析后的 finding。每个数据模型携带 `schema_version`；新增字段应提供默认值，删除或改变字段语义须新增版本与迁移器。

## 7. 测试与验收

- 验证状态迁移、severity 枚举、无效行号和仓库外路径。
- 验证相同 finding 的 ID 稳定，变化文件或行号后 ID 改变。
- 验证渲染器不输出 rejected/needs_evidence finding。
- 验证无 finding、截断 diff 和定位失败的 Markdown 输出。
