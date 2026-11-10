# Research — ADK, agents-cli, DeepSeek, free options

Date: 2026-11-09

## Google ADK

- Repo: `google/adk-python` (~22k stars), PyPI `google-adk` **2.14.0**,
  Python >=3.11, Apache-2.0.
- ADK 2.0 Python GA May 2026. Core is a graph workflow runtime: agents, tools
  and functions are nodes; edges support routing, fan-out/fan-in, loops,
  retries, dynamic branching, nested workflows and human-in-the-loop.
- Task API: structured agent-to-agent delegation (single-turn/multi-turn,
  HITL, task agents as workflow nodes).
- Multi-agent hierarchies (`sub_agents`, `AgentTool`), MCP/OpenAPI tools,
  callbacks/plugins, sessions/state, memory, artifacts.
- A2A for agents running as separate services. ADK guidance: local sub-agents
  for in-process work; A2A only across service/team/language boundaries.
- Model-agnostic: Gemini native; Claude/OpenAI via LiteLLM. DeepSeek via
  LiteLLM/OpenAI-compatible needs a spike.
- Eval, Cloud Run / Agent Runtime deploy, Cloud Trace observability.

## agents-cli

- Repo: `google/agents-cli` (~6.3k stars), PyPI `google-agents-cli` **1.13.0**,
  Python >=3.11 + uv + Node.
- A CLI + coding-agent skills for the Google Cloud agent lifecycle:
  `scaffold`, `eval`, `deploy`, `publish`, `observe`.
- Scaffolds ~60-file ADK/LangChain/Claude-SDK projects with tests, eval
  datasets, Docker, Terraform and CI/CD.
- Local dev works without Google Cloud (AI Studio key), but deploy targets are
  Google Cloud only: Agent Runtime (Gemini platform), Cloud Run, GKE. Publish
  goes to the Gemini app.
- Not required for Zuri. We use ADK directly and skip Google hosting.

## DeepSeek API (current)

- Models: `deepseek-v4-pro` (V4-Pro-0813), `deepseek-flash`
  (V4.1-Flash-1017).
- 1M context, up to 384K output; JSON output; tool calls; vision on Flash.
- Pricing per 1M tokens (off-peak / peak):
  - Flash: input $0.15 / $0.30, output $0.60 / $1.20; cache hit $0.003/$0.006.
  - V4 Pro: input $0.66 / $1.32, output $1.98 / $3.96; cache hit $0.022/$0.044.
- OpenAI-compatible and Anthropic-compatible endpoints.
- Example: a 20K-input / 5K-output task on V4 Pro is ~2-3 cents off-peak.

## Free/cheap alternatives

- OpenRouter free models (large free variants; rate-limited; list changes).
- Groq, Cerebras, GitHub Models, Mistral: free tiers with tight limits.
- Local models: machine is i5-8350U / 16GB RAM / Intel UHD 620 (no GPU);
  only small slow models (4B–8B) are practical. Use as offline fallback only.
- Google AI Studio free tier exists but the user does not want Gemini as the
  main model.

## Decision

DeepSeek is the main provider. Free fallbacks are optional later. No Google
Cloud dependency.
