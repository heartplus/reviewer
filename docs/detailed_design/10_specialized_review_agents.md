# 专项审查 Agent 扩展详细设计

## 1. 目标

在通用 Reviewer 之外增加按领域启用的审查 Agent，以提高高风险领域的检查深度，同时保持统一验证、去重和输出方式。

候选专项角色：`security`、`concurrency`、`api_compatibility`、`test_coverage`、`database_migration`。

## 2. 配置模型

```yaml
agents:
  reviewer:
    model: reviewer

specialists:
  security:
    enabled: true
    model: security_reviewer
    paths: ["src/auth/**", "src/api/**"]
    severities: [critical, high, medium]

models:
  security_reviewer:
    provider: openai
    name: gpt-5.6-sol
    settings:
      temperature: 0.0
      reasoning_effort: high
```

每个专项 Agent 可指定模型、适用路径、最大上下文和 severity 范围。未匹配变更路径时不运行，以控制成本。

## 3. 编排方式

```text
通用 Reviewer ----+
Security Reviewer -+-> Finding Normalizer -> Verifier -> Summarizer
Concurrency -------+
```

通用 Reviewer 与已启用的专项 Agent 可并行执行。每个 Agent 输出同一 `ReviewFinding` schema，并标记 `source_agent`。Normalizer 按文件、行号、标题语义和证据重叠度合并重复候选项，再交由 Verifier 作最终裁定。

## 4. 领域边界

| Agent | 重点 | 不应承担的职责 |
| --- | --- | --- |
| Security | 认证授权、注入、秘密处理、越权、加密使用 | 通用风格和业务取舍。 |
| Concurrency | 竞态、锁、幂等、资源生命周期、异步取消 | 单线程业务逻辑。 |
| API Compatibility | 请求/响应、默认值、版本兼容、错误码 | 内部实现细节。 |
| Test Coverage | 变更关键路径缺失的回归测试 | 用测试数量替代质量判断。 |
| Database Migration | 数据回填、锁表、回滚、兼容读写 | 常规 SQL 格式。 |

专项提示词必须仍遵守通用证据标准：给出受影响路径、触发条件和可验证影响；不允许因为“领域名称”而放宽证据要求。

## 5. 资源控制

- 设置全局并发上限及每角色超时。
- 设置单次运行的总 token 和最大专项 Agent 数。
- 任一专项 Agent 失败不阻断通用审查；报告记录其未执行状态。
- 对昂贵角色支持按标签、路径和 PR 大小采样启用。

## 6. 测试与验收

- 验证路径过滤正确跳过不相关专项 Agent。
- 验证多个 Agent 的并行结果被合并、去重并统一验证。
- 验证专项 Agent 失败不会影响通用 findings。
- 使用带标注的领域案例集比较专项启用前后的确认率与误报率。
