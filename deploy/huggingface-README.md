---
title: Legal RAG
emoji: ⚖️
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# Legal RAG — آرشیو حقوقی

Persian legal archive with hybrid retrieval and a human-approved entry pipeline.

Configure in **Settings → Variables and secrets**:

| name | kind | value |
|---|---|---|
| `DATABASE_URL` | secret | `postgresql://…` from Supabase |
| `ANTHROPIC_API_KEY` | secret | `sk-ant-…` |
| `LLM_PROVIDER` | variable | `anthropic` |
| `LLM_MODEL` | variable | `claude-opus-5` |
| `ROUTER_MODEL` | variable | `anthropic::claude-haiku-4-5` |
| `PORT` | variable | `7860` |

Groq will **not** work here — its edge blocks datacenter IP ranges, and every
Space runs on one.
