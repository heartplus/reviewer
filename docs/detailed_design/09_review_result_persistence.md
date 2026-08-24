# 审查结果持久化详细设计

## 1. 目标

保存本地审查运行与 finding 生命周期，支撑审计、模型效果评估和故障排查。

本功能属于规划阶段。初版建议使用关系型数据库；对象存储可用于保存经过脱敏的较大原始文本。

## 2. 数据实体

| 实体 | 主键 | 核心字段 |
| --- | --- | --- |
| `review_runs` | `run_id` | repo、PR、base/head SHA、配置版本、状态、时间、最终报告。 |
| `review_stages` | `run_id + stage` | 实际模型、provider、耗时、token、状态、错误摘要。 |
| `findings` | `finding_id + run_id` | 文件、行号、severity、状态、证据、建议、Verifier 原因。 |

`review_runs` 的唯一约束建议为 `(repository, base_ref, head_ref, config_version)`；是否允许同一范围因配置版本不同重新审查由本地使用策略决定。

## 3. 写入时机

1. 审查开始时创建 `review_runs(status=running)`。
2. 每个 Agent 阶段完成后 upsert `review_stages`。
3. Verifier 完成后写入结构化 findings。
4. 最终渲染完成后更新 `review_runs(status=completed)`。

发生不可恢复错误时将 run 标为 `failed`，保留已完成阶段和安全错误摘要。不能用“失败”覆盖已有成功 run。

## 4. 数据保留与访问

- 运行元数据与 finding 可长期保留；原始 diff、prompt、工具输出默认不持久化。
- 若启用原始内容留存，必须先脱敏、加密、设置保留期限并限制查询权限。
- 删除仓库接入或客户要求清理时，按仓库维度删除或匿名化关联数据，并保留合规审计记录。

## 5. 一致性与重试

数据库操作使用事务；阶段、finding 和最终报告应能追溯到同一个 `run_id`。若未来增加远程发布功能，应将其设计为独立 outbox，不影响本地审查的完成语义。

## 6. 测试与验收

- 验证相同仓库、范围和配置版本的重复执行符合本地去重策略。
- 验证阶段失败不会丢失已写入的元数据。
- 验证仓库级数据删除、脱敏和访问控制策略。
