# Groq's `max_completion_tokens` — why a request succeeds and returns nothing

You hit this repeatedly. It is the single most confusing failure in the Groq
integration, because **the request succeeds**. HTTP 200, no exception, valid
JSON envelope — and `content` is the empty string.

---

## The one sentence

On a reasoning model, the token budget pays for the model's **hidden thinking
first** and the visible answer second. Set it too low and thinking spends all of
it, so there is nothing left to write the answer with.

---

## Three things stacked on top of each other

### 1. Groq renamed the parameter

`max_tokens` is deprecated on Groq. The parameter that caps output is
**`max_completion_tokens`**. Send `max_tokens` and it is ignored — you get the
model's own default, not your limit.

This is why `GroqProvider` overrides `_request()` instead of inheriting
`OpenAIProvider`'s body: one renamed key.

```python
# app/llm/groq_provider.py
body = {
    "model": self.model,
    "max_completion_tokens": max_tokens,   # not max_tokens — see docstring
    ...
}
```

### 2. The budget covers reasoning *and* the answer

This is the part that surprises people. `openai/gpt-oss-20b` is a **reasoning
model**: before answering it generates internal thinking tokens you never see
but *do* pay for, and they come out of the same budget.

```
max_completion_tokens = 20
├── hidden reasoning ......... 20 tokens   ← consumed the entire budget
└── visible answer ...........  0 tokens   ← nothing left
```

The response is `finish_reason: "length"` with `content: ""`. Nothing raised.
Measured on this machine — twelve consecutive calls at `max_tokens=20`, all
twelve empty:

```
 1. FAIL  RuntimeError: openai/gpt-oss-20b: truncated at max_completion_tokens
          (20 tokens) before emitting any answer — the reasoning budget consumed
          the whole allowance.
 ...
 → 0 ok / 12 failed
```

The same prompt at `max_tokens=400, reasoning_effort="low"`: **12 ok / 0 failed**,
~0.5s each. Only the budget changed.

### 3. With `json_mode` it doesn't even reach the length check

Groq validates the completion against the JSON grammar **server-side**. When
reasoning ate the budget there is no JSON to validate, so instead of returning
`finish_reason="length"` it raises:

```
openai.BadRequestError: 400 — code: json_validate_failed, failed_generation: ""
```

That is a **400**, a different class from the truncation case, so the length
check downstream never runs. This is why the provider catches it explicitly:

```python
except openai.BadRequestError as e:
    if json_mode and e.code == "json_validate_failed":
        raise RuntimeError(
            f"{self.model}: Groq's JSON-mode validator rejected the output "
            f"(max_completion_tokens={max_tokens}) — the reasoning budget "
            "likely consumed the whole allowance before any JSON was produced. "
            "Raise max tokens, or lower reasoning effort."
        ) from e
```

Without that branch you see `BadRequestError: json_validate_failed` and go
looking for a bug in your schema. There is no bug in your schema.

---

## How to recognise it

| what you see | what it is |
|---|---|
| Empty answer bubble, no error | budget spent on reasoning |
| `finish_reason: "length"`, `content: ""` | same, seen in the raw response |
| `400 json_validate_failed`, `failed_generation: ""` | same, but in JSON mode |
| Persian warning about «سقف توکن خروجی» in the chat | the app caught it for you |

All four are one problem. None of them is a bad prompt, a bad key, or a bad schema.

---

## What to do

**Raise the ceiling before lowering the effort.** Output tokens are cheap; a
truncated run costs the whole call.

| situation | setting |
|---|---|
| Extraction from a full document | `max_tokens=3000` (what `extract_entry` uses) |
| Routing / classification | `max_tokens=120` is fine — **but** pin `reasoning_effort="low"` |
| Chat reply | `max_tokens=1200`, effort `low` |
| Anything returning empty | double `max_tokens` first, then drop effort |

In the UI these are the two sidebar knobs: **«سقف توکن خروجی»** (the budget) and
**«میزان استدلال»** (how much of it thinking is allowed to take).

---

## The general rule, beyond Groq

Every reasoning model bills thinking against the output cap:

| provider | parameter | thinking control |
|---|---|---|
| Groq (gpt-oss, qwen3) | `max_completion_tokens` | `reasoning_effort: low\|medium\|high` |
| Anthropic (Opus 5, Sonnet 5) | `max_tokens` | `output_config.effort` + adaptive thinking |
| Ollama (local) | `num_predict` | n/a — these models don't hide reasoning |

`app/llm/knobs.py` exists precisely so the UI only offers `reasoning_effort` to
models that accept it — it is a **400 error** on `llama-*`, `allam-*` and
`groq/compound*`, which is what "knobs are data, not conditionals" means.

Anthropic has the same trap with a different face: `AnthropicProvider.generate()`
raises when `stop_reason == "max_tokens"` with no text, saying the same thing in
Persian-facing terms.

---

## What you said you wanted to change

Add notes here when you get to it. Candidates worth considering:

- **Per-call budgets are hardcoded** across `orchestrator.py`
  (`max_tokens=3000` for extract, `120` for routing, `1200` for chat). They
  ignore the sidebar's «سقف توکن خروجی». Deliberate — a user-set 256 would break
  extraction — but it means the knob does less than it appears to.
- **No adaptive retry.** A truncated call could re-run once at double the budget
  instead of surfacing an error. Cheap to add in `GroqProvider.generate`.
- **`reasoning_effort` default is `"low"`** everywhere in the pipeline. Fine for
  extraction; possibly wrong for a hard legal question.
