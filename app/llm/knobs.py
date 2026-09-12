"""
Which tuning knobs a given model actually accepts.

The problem this solves: `reasoning_effort` is valid on Groq's gpt-oss and
Qwen3 models and a 400 error on `llama-*`, `allam-*` and `groq/compound*`.
`max_tokens` is deprecated on Groq but correct everywhere else. Anthropic wants
`thinking={"type": "enabled", ...}` and nothing else understands that. Hardcoding
any of it into a call site means the call site has to know which backend it is
talking to — exactly what `base.py` exists to prevent.

So capability lives here as *data*. `knobs_for(provider, model)` returns the
list of controls that model supports; the UI renders one widget per entry and
passes the collected values straight through to `generate(**knobs)`. Switch the
model in the dropdown and the control panel changes with it, because it is
derived from the model id rather than written by hand.

Providers must ignore knobs they do not support (see `LLMProvider.generate`),
so a stale value left over from a previous selection can never break a call.
"""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class Knob:
    """One tunable parameter, described well enough for a UI to render it."""

    key: str  # keyword passed to generate(): "reasoning_effort", ...
    label: str  # human label for the widget
    kind: Literal["select", "slider", "toggle"]
    default: Any
    options: list[Any] = field(default_factory=list)  # select only
    min: float | None = None  # slider only
    max: float | None = None
    step: float | None = None
    help: str = ""


# Applies to every backend: the two parameters each provider translates into
# whatever its own API calls them.
def _universal(max_tokens_default: int = 1024) -> list[Knob]:
    return [
        Knob(
            key="temperature",
            label="دمای نمونه‌برداری",
            kind="slider",
            default=0.0,
            min=0.0,
            max=1.0,
            step=0.05,
            help="صفر یعنی قطعی و تکرارپذیر — پیش‌فرض درست برای پاسخ مستند.",
        ),
        Knob(
            key="max_tokens",
            label="سقف توکن خروجی",
            kind="slider",
            default=max_tokens_default,
            min=256,
            max=8192,
            step=256,
            help=(
                "سقف است نه هدف — بالا بردنش هزینه‌ای ندارد مگر آنکه مدل واقعاً "
                "بیشتر تولید کند. در مدل‌های استدلالی این بودجه شامل «فکر کردن» "
                "پنهان و خودِ پاسخ است، پس عدد کم ممکن است تماماً صرف فکر کردن "
                "شود و متن خالی برگردد."
            ),
        ),
    ]


_EFFORT = Knob(
    key="reasoning_effort",
    label="میزان استدلال",
    kind="select",
    default="low",
    options=["low", "medium", "high"],
    help=(
        "مدل چقدر پیش از پاسخ فکر کند. توکن‌های فکر کردن، توکن تولیدشدهٔ واقعی‌اند، "
        "پس این اصلی‌ترین کلید کنترل زمان در یک مدل استدلالی است."
    ),
)


def _is_groq_reasoner(model: str) -> tuple[bool, bool]:
    """(takes_reasoning_effort, needs_reasoning_format_parsed) for a Groq model.

    gpt-oss already splits reasoning into its own field, so passing
    `reasoning_format` to it is a 400. Other `<think>`-style reasoners need the
    parsed split or the chain-of-thought arrives inline in `content`.
    """
    lowered = model.lower()
    is_gpt_oss = lowered.startswith("openai/gpt-oss")
    takes_effort = is_gpt_oss or "qwen3" in lowered
    needs_parsed = not is_gpt_oss and ("qwen3" in lowered or "r1" in lowered)
    return takes_effort, needs_parsed


def knobs_for(provider: str, model: str) -> list[Knob]:
    """Every knob the given model accepts, ready to render."""
    model = model or ""
    common = _universal()

    if provider == "groq":
        takes_effort, _ = _is_groq_reasoner(model)
        return common + ([_EFFORT] if takes_effort else [])

    if provider == "openai":
        # An OpenAI-compatible gateway may be fronting anything. Offer the
        # effort dial only for ids that look like reasoners, so the control
        # panel stays honest for plain chat models behind the same endpoint.
        takes_effort, _ = _is_groq_reasoner(model)
        if takes_effort or model.startswith(("o1", "o3", "o4", "gpt-5")):
            return common + [_EFFORT]
        return common

    if provider == "anthropic":
        # Claude has no `reasoning_effort`; it has `output_config.effort`, and
        # the provider maps this knob onto it (turning on adaptive thinking at
        # the same time). Same control, same meaning, so reuse the widget.
        #
        # Sampling params were REMOVED on Opus 5 / Sonnet 5 / Opus 4.7-4.8 —
        # sending `temperature` there is a 400. The provider already drops it,
        # but a slider the model ignores is exactly the dishonest panel this
        # module exists to prevent, so hide it too.
        from .anthropic_provider import _takes_temperature

        knobs = common if _takes_temperature(model) else [
            k for k in common if k.key != "temperature"
        ]
        return knobs + [_EFFORT]

    # local (Ollama) exposes nothing beyond the universal pair.
    return common


def reasoning_capable(provider: str, model: str) -> bool:
    """Whether this model can return a separate `reasoning` field, i.e. whether
    a 'thinking' panel is worth creating for it."""
    if provider in ("groq", "openai"):
        takes_effort, needs_parsed = _is_groq_reasoner(model)
        return takes_effort or needs_parsed
    # Every current Claude model thinks, and the provider asks for a summary,
    # so a reasoning panel is always worth rendering.
    return provider == "anthropic"
