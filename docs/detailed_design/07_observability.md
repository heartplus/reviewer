# 运行追踪与质量观测详细设计

## 1. 目标

使每一次审查都可回答四个问题：使用了什么模型、看到了哪些有限上下文、调用了哪些工具、最终为何保留或驳回某个问题。

## 2. Trace 结构

每次 `ReviewRunner.review()` 创建一个根 trace，包含以下 span：

```text
review.run
  -> repository.prepare
  -> reviewer.run
       -> tool.*
  -> verifier.run
       -> tool.*
  -> summarizer.run
  -> report.render
```

根 trace 属性：`run_id`、仓库标识（脱敏）、base/head commit SHA、配置版本、触发来源、是否截断。角色 span 属性：角色名、逻辑模型名、实际 provider/model、耗时、调用状态、token 使用量（供应商提供时）。

## 3. 指标

需要记录并可聚合的指标：

- 审查运行数、成功率、失败类型、重试次数和端到端耗时。
- 各角色的模型、耗时、输入/输出 token 和估算成本。
- 工具调用数、失败率、超时率、截断率。
- 每次审查的候选、确认、驳回和证据不足 finding 数。
- severity 分布、每千行变更的 finding 数。
- 当有人工标注时的确认率、误报率和漏报率。

## 4. 日志与脱敏

日志使用结构化 JSON。必填字段包括 `timestamp`、`level`、`run_id`、`stage`、`event` 和 `error_code`（错误时）。

默认不记录完整 diff、文件内容、原始 prompt 或原始模型输出。需要诊断时，必须显式开启受访问控制的采样，并先经过 secret 脱敏。

## 5. 告警建议

- provider 认证失败或连续限流。
- 审查失败率持续高于阈值。
- 模型成本或平均 token 使用异常增长。
- 某个模型版本的 Verifier 驳回率显著变化。
- 工具路径越界或命令拒绝事件突然增多。

## 6. 测试与验收

- 使用 in-memory exporter 验证完整 trace 树、阶段属性和运行 ID 关联。
- 验证日志中不存在 API Key 和模拟 secret。
- 验证工具超时、provider 重试和降级路径都产生可检索事件。
