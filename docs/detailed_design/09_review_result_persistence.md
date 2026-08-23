# 审查结果持久化详细设计

## 1. 目标

保存审查运行与 finding 生命周期，支撑审计、GitHub 评论幂等、模型效果评估和故障重试。

本功能属于规划阶段。初版建议使用关系型数据库；对象存储可用于保存经过脱敏的较大原始文本。

## 2. 数据实体

| 实体 | 主键 | 核心字段 |
| --- | --- | --- |
| `review_runs` | `run_id` | repo、PR、base/head SHA、配置版本、状态、时间、最终报告。 |
| `review_stages` | `run_id + stage` | 实际模型、provider、耗时、token、状态、错误摘要。 |
| `findings` | `finding_id + run_id` | 文件、行号、severity、状态、证据、建议、Verifier 原因。 |
| `published_comments` | `comment_id` | GitHub comment ID、run ID、finding ID、commit SHA、发布状态。 |
| `review_jobs` | `job_id` | 幂等键、任务状态、重试次数、下次执行时间。 |

`review_runs` 的唯一约束为 `(repository, pull_request_number, head_sha, config_version)`；是否允许同一提交因配置版本不同重新审查由部署策略决定。

## 3. 写入时机

1. 任务接受后创建 `review_jobs`，记录幂等键。
2. 审查开始时创建 `review_runs(status=running)`。
3. 每个 Agent 阶段完成后 upsert `review_stages`。
4. Verifier 完成后写入结构化 findings。
5. 最终渲染完成后更新 `review_runs(status=completed)`。
6. 评论发布后写入或更新 `published_comments`。

发生不可恢复错误时将 run 标为 `failed`，保留已完成阶段和安全错误摘要。不能用“失败”覆盖已有成功 run。

## 4. 数据保留与访问

- 运行元数据与 finding 可长期保留；原始 diff、prompt、工具输出默认不持久化。
- 若启用原始内容留存，必须先脱敏、加密、设置保留期限并限制查询权限。
- 删除仓库接入或客户要求清理时，按仓库维度删除或匿名化关联数据，并保留合规审计记录。

## 5. 一致性与重试

评论发布采用 outbox 模式：在同一事务中写入待发布记录，异步 worker 调用 GitHub API。这样即使进程在审查完成后崩溃，也能恢复发布。

重试必须依据稳定幂等键与 GitHub 隐藏标记去重。数据库操作使用事务；finding 和对应的评论记录应能追溯到同一个 `run_id`。

## 6. 测试与验收

- 验证相同 PR/head/config 重复投递只产生一个活跃 run。
- 验证阶段失败不会丢失已写入的元数据。
- 验证 outbox 在进程重启后能恢复发布。
- 验证仓库级数据删除、脱敏和访问控制策略。

