# GitHub App 与 PR 评论发布详细设计

## 1. 目标

将审查核心接入 GitHub Pull Request 生命周期：接收可信 webhook、准备特定提交的工作区、运行审查，并以幂等方式发布汇总评论和可定位的 inline comment。

本功能属于规划阶段；它必须复用现有 `ReviewRunner`，不在 webhook handler 中实现审查逻辑。

## 2. 事件范围与流程

初版仅处理 `pull_request` 的 `opened`、`synchronize`、`reopened` 事件。

```text
Webhook
  -> 验证签名与事件
  -> 去重并创建 ReviewJob
  -> checkout PR head SHA
  -> ReviewRunner.review
  -> 持久化结果
  -> 发布/更新 GitHub 评论
```

只对同一仓库、同一 PR、同一 `head.sha` 运行一次成功审查。重试使用同一幂等键，不得制造重复评论。

## 3. Webhook Handler

Handler 的职责仅包括：验签、解析、过滤、创建任务和快速返回 `2xx`。模型调用、仓库 checkout 与评论发布必须在后台 job 中运行，避免 webhook 超时。

`PullRequestEvent` 至少包含：仓库全名、安装 ID、PR 编号、base ref/SHA、head ref/SHA、事件 action、PR URL 与发送时间。

## 4. 仓库准备

- 使用 GitHub App installation token 克隆或复用受控缓存中的 bare repository。
- 按仓库和 commit SHA 创建隔离工作目录，checkout 到精确的 `head.sha`。
- base ref 使用 payload 中的 base SHA，禁止依赖会变化的分支名称。
- 不执行仓库中的安装脚本、hook 或任意构建命令；只有已配置的测试 allowlist 可以运行。
- 任务完成后清理临时工作目录；缓存仅保留 Git 对象，不保留工作树。

## 5. 评论发布

发布分为两类：

- 汇总评论：每个 commit SHA 一条，由隐藏标记 `<!-- github-reviewer:run_id -->` 标识。
- Inline comment：仅对 `confirmed` 且能定位到 PR diff 的 finding 发布，正文包含 finding ID 隐藏标记。

发布前查询已有标记。相同 finding ID 更新已有评论或跳过；已不再存在的 finding 不自动删除，初版在汇总评论中标记“本次已解决/不再复现”的状态。

## 6. 权限与失败策略

GitHub App 权限遵循最小化：Pull requests 读写、Contents 只读、Metadata 只读。默认仅评论，不批准、不请求修改、不推送代码。

评论发布失败不得丢弃审查结果。记录 `publish_status=failed` 和可重试原因，由任务队列重试。来自 fork 的 PR 按部署策略限制 token 权限和测试执行。

## 7. 测试与验收

- 验证 webhook 签名、事件过滤和重复投递去重。
- 用 GitHub API mock 验证 checkout SHA 与评论幂等。
- 验证无法定位的 finding 只进入汇总评论。
- 验证发布失败后保留持久化结果且可以重试。

