# 配置加载与模型选择详细设计

## 1. 目标

所有模型供应商、模型名称、模型参数和角色映射均由 YAML 配置决定。Agent 业务代码不得硬编码模型名称、endpoint 或密钥。

## 2. 配置结构

```yaml
review:
  base_ref: origin/main
  head_ref: HEAD
  max_diff_bytes: 200000
  max_file_bytes: 60000
  allow_test_commands: []

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
    name: ${REVIEWER_MODEL}
    settings:
      temperature: 0.1
      reasoning_effort: high
```

配置概念分三层：

| 层次 | 职责 | 示例 |
| --- | --- | --- |
| `review` | 单次审查的资源与执行限制 | diff 上限、允许的测试命令。 |
| `agents` | 角色到逻辑模型名的映射 | `reviewer -> reviewer`。 |
| `models` | 逻辑模型名到供应商连接信息的映射 | `reviewer -> openai/gpt-*`。 |

## 3. Schema

`config/schema.py` 定义以下类型：

- `ModelSettingsConfig`：`temperature`、`max_tokens`、`reasoning_effort` 等模型参数。
- `ModelConfig`：`provider`、`name`、`base_url`、`api_key_env`、`supports_structured_output`、`settings`。
- `AgentConfig`：单个角色引用的逻辑模型名，以及是否暴露仓库工具的 `use_repo_tools` 开关。
- `ReviewConfig`：工具输出上限、默认 refs、测试命令 allowlist、Provider 重试次数与退避参数。
- `AppConfig`：顶层聚合配置，并提供 `model_for_agent(role)` 查询方法。

`provider` 仅允许 `openai`、`openai_compatible` 和 `litellm`。配置中未知字段应默认拒绝，避免拼写错误被静默忽略。

`supports_structured_output` 默认为 `true`。对不支持 OpenAI `response_format` 的兼容模型设置为 `false`；运行时会要求模型返回 JSON，并在本地校验为同一份 schema。

## 4. 加载与环境变量展开

`load_config(path)` 的处理顺序：

1. 读取 YAML 为原始字典。
2. 递归展开字符串中的 `${VARIABLE}`，只允许读取当前进程环境变量。
3. 将结果传入 `AppConfig` 校验并返回类型化对象。

缺失的环境变量必须直接失败，并在报错中指出配置路径与变量名；不得打印变量值。`.env` 仅作为开发时由调用方加载的便利文件，生产环境应使用部署平台注入的环境变量。

## 5. Model Factory

`agents/model_factory.py` 根据 `ModelConfig.provider` 构造 SDK 所需的模型对象：

| Provider | 构造方式 | 适用场景 |
| --- | --- | --- |
| `openai` | 传递模型名称，使用 SDK 默认 provider | OpenAI API。 |
| `openai_compatible` | 创建指定 `base_url` 的 OpenAI Chat Completions 客户端 | 自建或兼容 OpenAI 协议的网关。 |
| `litellm` | 创建 `LitellmModel` | 其他厂商或统一模型网关。 |

`build_model_settings()` 只映射 SDK 已支持的设置。供应商不支持的参数由配置校验或运行时适配层明确报错，不能悄悄丢弃。

## 6. 密钥处理

- `api_key_env` 保存环境变量名称，绝不保存真实密钥。
- 未设置 `api_key_env` 时，`openai` 使用 SDK 默认的凭证查找机制。
- 自定义 provider 的 endpoint 必须为 HTTPS，开发环境例外需显式配置。
- 日志、异常和 tracing 属性不得出现 API Key 或 Authorization header。

## 7. 测试与验收

- 校验角色引用不存在的模型、未知 provider、非法 `reasoning_effort` 时失败。
- 验证环境变量可在嵌套字段内展开，缺失变量会失败且不泄露值。
- 用 mock 分别验证三种 provider 的模型构造和 settings 映射。
- 验证更换 YAML 中的模型名称后，无需修改 Python 代码即可生效。
