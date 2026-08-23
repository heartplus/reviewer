# GitHub Reviewer

An agentic code review framework for GitHub pull requests.

The project follows the design from the reference conversation:

- use OpenAI Agents SDK for the agent loop, tool calling, multi-agent orchestration, structured runs, and tracing;
- keep code-review-specific repo tools in this project: diff, file reading, grep, blame, and test commands;
- allow each agent role to use a different model/provider through configuration.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

If you want to use `provider: litellm`, install the optional adapter too:

```bash
pip install -e ".[litellm]"
```

Edit `config/default.yaml` to choose models:

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
  verifier:
    provider: openai
    name: gpt-5.6-luna
  summarizer:
    provider: openai
    name: gpt-5.6-luna
```

Run against a local checkout:

```bash
github-reviewer review --repo /path/to/repo --base origin/main --head HEAD
```

Review every committed change in a range without changing the target working tree:

```bash
github-reviewer history --repo /path/to/repo --base origin/main --head HEAD
```

## Model Configuration

Model selection is intentionally config-driven. Supported provider modes:

- `openai`: pass a model name to the default OpenAI Agents SDK provider.
- `openai_compatible`: use a custom OpenAI-compatible chat completions endpoint.
- `litellm`: route through LiteLLM for Anthropic, Gemini, Mistral, local models, or an internal gateway.

Example:

```yaml
models:
  reviewer:
    provider: litellm
    name: anthropic/claude-sonnet-4
    api_key_env: ANTHROPIC_API_KEY

  verifier:
    provider: openai
    name: gpt-5.6-sol

  summarizer:
    provider: openai_compatible
    name: internal-summary-model
    base_url: https://llm-gateway.example.com/v1
    api_key_env: INTERNAL_LLM_API_KEY
```

DeepSeek uses the same `openai_compatible` mode. The checked-in default configuration
uses `deepseek-v4-pro` for Reviewer and Verifier, and `deepseek-v4-flash` for Summarizer;
provide its key as `DEEPSEEK_API_KEY` in a git-ignored `.env` file or in the deployment
environment:

```yaml
models:
  deepseek_pro:
    provider: openai_compatible
    name: deepseek-v4-pro
    base_url: https://api.deepseek.com
    api_key_env: DEEPSEEK_API_KEY
    supports_structured_output: false
    settings:
      extra_body:
        thinking:
          type: disabled

  deepseek_flash:
    provider: openai_compatible
    name: deepseek-v4-flash
    base_url: https://api.deepseek.com
    api_key_env: DEEPSEEK_API_KEY
    supports_structured_output: false
```

## Current Shape

```text
GitHub PR / local branch
        |
        v
ReviewRunner
        |
        +-- Reviewer Agent   -> finds likely correctness issues
        +-- Verifier Agent   -> challenges evidence and false positives
        +-- Summarizer Agent -> produces final Markdown review
        |
        v
ReviewReport
```

Repo tools are exposed to reviewer and verifier:

- `get_diff`
- `changed_files`
- `read_file`
- `grep`
- `git_blame`
- `run_tests` when enabled in config

## Result Safety

Reviewer and optional specialist agents return structured candidate findings. A separate
Verifier confirms, rejects, or marks each candidate as needing evidence. The final
Markdown renderer publishes only confirmed findings, so free-form model output cannot
accidentally turn an unverified concern into a reported bug.

The repository tools are read-only by default, bounded by configured output limits, and
resolve historical file context directly from Git objects. This lets `history` review
commits without checking them out or modifying a dirty worktree.

`review.max_agent_turns` limits each Agent's model/tool loop. The default is `6`; raise it
only when a model needs more repository exploration for larger changes.
Set `agents.<role>.use_repo_tools: false` for models that should review the supplied diff
without tool exploration; the default configuration uses this mode for DeepSeek Pro.

## Optional Integrations

Set `persistence.enabled: true` to retain runs, stages, findings, and a comment outbox
in SQLite. GitHub integration is provided as a webhook/workflow adapter: it verifies
`pull_request` deliveries, checks out the exact base/head SHAs in a temporary workspace,
then can publish idempotent summary and inline comments when `github.enabled` is set.

Detailed component contracts are in [docs/detailed_design](docs/detailed_design/README.md).
