"""
The demo, as data: ordered stages, each a few prompts with the intent and
run mode they should be sent with, and what the answer must contain.

The chat shows the stages as chips when the conversation is empty and walks
a stage prompt by prompt; the gallery lists them; `scripts/demo_stages.py`
runs every stage end to end on the current model and checks `expect`, so
the demo script is also the acceptance test.
"""

from dataclasses import dataclass, field

FILING_TEXT = (
    "صورت‌جلسهٔ رسیدگی شعبهٔ ۳ دادگاه حقوقی تهران\n"
    "خواهان: شرکت سهامی بیمه ایران (با وکالت آقای رضا کریمی)\n"
    "خوانده: آقای علی مرادی\n"
    "موضوع: بازیافت خسارت پرداختی از رانندهٔ مقصر\n"
    "دادگاه با استناد به ماده ۳۰ قانون بیمه موضوع را به کارشناسی ارجاع داد."
)


@dataclass
class StagePrompt:
    text: str
    intent: str | None = None          # forced intent, None = router
    mode: str | None = None            # run mode for archive prompts
    expect: dict = field(default_factory=dict)  # {"intent": ..., "keys": [...], "status": ...}
    reply: bool = False                # a conversation reply, not a new message
    note: str = ""                     # what to point at during the demo


@dataclass
class Stage:
    id: str
    title: str
    blurb: str
    prompts: list[StagePrompt]
    show: list[str] = field(default_factory=list)   # sections worth opening afterwards


STAGES: list[Stage] = [
    Stage(
        "law_lookup", "پرسش از قانون با استناد و پرونده‌های مشابه",
        "یک پرسش حقوقی؛ پاسخ با استناد [n] به مواد، سپس پرونده‌های مشابه از گراف و تحلیل تطبیقی.",
        [StagePrompt("ماده ۳۰ قانون بیمه دربارهٔ جانشینی بیمه‌گر چه می‌گوید؟", intent="law",
                     expect={"intent": "law", "keys": ["refs", "similar_cases", "provenance"]},
                     note="پنل «شواهد و ردپای پاسخ» و ردیف‌های قابل‌کلیک پرونده‌های مشابه")],
        show=["laws"],
    ),
    Stage(
        "precedents", "سابقهٔ آرا در بایگانی",
        "پرسش دربارهٔ رویهٔ پرونده‌ها؛ پاسخ از جدول پرونده‌ها با نتیجهٔ هر کدام.",
        [StagePrompt("پرونده‌های بازیافت از رانندهٔ فاقد گواهینامه چطور تمام شده‌اند؟", intent="cases",
                     expect={"intent": "cases", "keys": ["cases", "lessons", "provenance"]},
                     note="«چه چیزی جواب داد / نداد»")],
        show=["cases"],
    ),
    Stage(
        "agent_research", "پژوهش عاملی با ابزارها",
        "مدل خودش با ابزارهای فقط‌خواندنی جستجو می‌کند؛ هر فراخوانی زنده نمایش داده می‌شود و پاسخ به شواهد شماره‌دار استناد می‌کند.",
        [StagePrompt("وکیل رضا کریمی در چه پرونده‌هایی بوده و نتیجه‌شان چه شد؟", intent="agent",
                     expect={"intent": "agent", "keys": ["tool_log", "provenance"]},
                     note="ردپای ابزارها، پوشش استناد، توکن‌ها")],
        show=["entities"],
    ),
    Stage(
        "conversational_filing", "ثبت گفتگویی پرونده",
        "یک متن بدون شمارهٔ پرونده؛ دستیار می‌گوید چه چیزی را برداشته و شماره را در گفتگو می‌پرسد.",
        [StagePrompt(FILING_TEXT, intent="archive", mode="conversation",
                     expect={"status": "awaiting_input"}, note="پرسش دستیار به‌جای جدول"),
         StagePrompt("شماره پرونده: ۱۴۰۲۰۰۱۲۳۴", reply=True, expect={"status": "awaiting_input"}),
         StagePrompt("تأیید", reply=True, expect={"status": "committed"}, note="مدخل، پرونده و گراف ساخته شد")],
        show=["cases", "entities"],
    ),
    Stage(
        "archive_analytics", "آمار و گراف",
        "شمارش‌ها بدون مدل، سپس پروفایل اشخاص و گراف پرونده.",
        [StagePrompt("چند پرونده شخص ثالث داریم؟", intent="analytics",
                     expect={"intent": "analytics", "keys": ["stats"]})],
        show=["analytics", "entities"],
    ),
    Stage(
        "ci_live", "خط لولهٔ CI زنده و وب‌هوک‌ها",
        "بازپخش یک اجرای واقعی CI در داشبورد و دریافت رویدادهای امضاشدهٔ آرشیو.",
        [],
        show=["dashboard", "webhooks"],
    ),
]
BY_ID = {s.id: s for s in STAGES}


async def run_stage(session, llm, stage: Stage, *, source: str = "demo") -> list[dict]:
    """Execute a stage's prompts and check `expect`. Returns one report per prompt."""
    from app.rag import conversation, workflow
    from app.rag.orchestrator import run_assistant

    reports = []
    run_id = None
    for prompt in stage.prompts:
        problems: list[str] = []
        if prompt.reply:
            if not run_id:
                problems.append("no run to reply to")
                view = {}
            else:
                view = await conversation.turn(session, run_id, llm, prompt.text)
            status = view.get("status")
            if prompt.expect.get("status") and status != prompt.expect["status"]:
                problems.append(f"status {status} != {prompt.expect['status']}")
            reports.append({"stage": stage.id, "prompt": prompt.text[:60], "status": status, "problems": problems})
            continue
        if prompt.intent == "archive" and prompt.mode:
            view = await workflow.start(session, raw_text=prompt.text, source=f"{source}/{stage.id}", llm=llm,
                                        mode=prompt.mode, forced_intent="archive")
            run_id = view["id"]
            status = view.get("status")
            if prompt.expect.get("status") and status != prompt.expect["status"]:
                problems.append(f"status {status} != {prompt.expect['status']}")
            reports.append({"stage": stage.id, "prompt": prompt.text[:60], "status": status, "problems": problems})
            continue
        res = await run_assistant(session, llm, prompt.text, force_intent=prompt.intent, source=source)
        if prompt.expect.get("intent") and res.get("intent") != prompt.expect["intent"]:
            problems.append(f"intent {res.get('intent')} != {prompt.expect['intent']}")
        for key in prompt.expect.get("keys", []):
            if not res.get(key):
                problems.append(f"missing {key}")
        reports.append({"stage": stage.id, "prompt": prompt.text[:60], "intent": res.get("intent"),
                        "grounding": ((res.get("provenance") or {}).get("grounding") or {}).get("status"),
                        "problems": problems})
    return reports
