"""Static Persian fixtures for the design gallery — nothing here touches the database."""

CASE = {
    "id": "c-1", "case_number": "1402009988", "title": "بازیافت خسارت پرداختی از رانندهٔ مقصر",
    "case_type": "بازیافت از راننده مقصر", "insurance_line": "شخص ثالث", "court": "دادگاه عمومی حقوقی تهران",
    "status": "closed", "status_fa": "مختومه", "outcome": "حکم به محکومیت راننده به استرداد ۲,۲۵۰,۰۰۰,۰۰۰ ریال",
    "score": 0.91, "why": ["استناد مشترک به قانون بیمه — مادهٔ ۳۰", "طرف مشترک: رضا کریمی (وکیل خواهان)", "همان رشتهٔ بیمه: شخص ثالث"],
    # `path` is a list of graph paths, each a list of nodes with relation nodes between them
    "path": [[{"type": "law", "id": "l1", "label": "قانون بیمه — مادهٔ ۳۰"},
              {"relation": "CITES", "relation_fa": "استناد به", "dir": "in"},
              {"type": "case", "id": "c-1", "label": "بازیافت خسارت پرداختی از رانندهٔ مقصر"}]],
}
CASE_2 = {**CASE, "id": "c-2", "case_number": "1401489592", "title": "دعوای بازیافت — رانندهٔ فاقد گواهینامه",
          "outcome": "رد دعوا به علت عدم احراز یکی از موارد مادهٔ ۱۶", "score": 0.62,
          "why": ["هم‌نوع: بازیافت از راننده مقصر", "واژه‌های مشترک با پرسش"], "path": []}

LESSONS = {"worked": [{"case_number": "1402009988", "point": "تقصیر، بازیافت"}],
           "failed": [{"case_number": "1401489592", "point": "فاقد گواهینامه"}], "pending": [], "unknown": [],
           "summary": "1 پذیرفته‌شده · 1 ردشده · 0 در جریان"}

PROVENANCE = {
    "version": 1, "intent": "law", "provider": "anthropic", "model": "claude-opus-5",
    "evidence": [{"n": 1, "kind": "law", "id": "l1", "cite": "مادهٔ ۳۰ قانون بیمه", "label": "ماده: مادهٔ ۳۰ قانون بیمه", "score": None},
                 {"n": 2, "kind": "case", "id": "c-1", "cite": "1402009988", "label": "پرونده: 1402009988", "score": 0.91}],
    "tool_trail": [{"seq": 1, "tool": "search_law", "summary": "search_law(query='ماده ۳۰') → 3 ماده", "ms": 12, "evidence_ns": [1]},
                   {"seq": 2, "tool": "similar_cases", "summary": "similar_cases(question='جانشینی') → 5 پرونده", "ms": 40, "evidence_ns": [2]}],
    "grounding": {"cited": [1, 2], "valid": [1, 2], "invalid": [], "coverage": 1.0, "status": "ok", "unsupported_claims": []},
    "usage": {"calls": 2, "input_tokens": 2310, "output_tokens": 410, "cache_read_tokens": 2048, "cache_write_tokens": 0, "latency_ms": 1830},
}

CONTEXTS = [{"n": 1, "title": "دادنامه — شعبهٔ ۳", "source": "mock/1402009988.txt", "document_id": "d1",
             "similarity": 0.83, "text": "دادگاه با استناد به مادهٔ ۳۰ قانون بیمه … حکم به محکومیت راننده صادر کرد."}]

STEPS = [{"name": "جستجوی قوانین", "detail": "۳ ماده از پایگاه قوانین", "ms": 12},
         {"name": "پرونده‌های مشابه از گراف", "detail": "۵ پرونده · ۱۱ مسیر در گراف", "ms": 40},
         {"name": "پاسخ با استناد به مواد", "detail": "مدل claude-opus-5", "ms": 1780}]

CI_RUNS = [{"run_id": "1", "run_number": 9, "workflow": "docker", "branch": "v3", "sha": "9a716091abcd",
            "html_url": "https://github.com/R445Da/legal_agent/actions", "status": "in_progress", "conclusion": None,
            "updated_at": None,
            "jobs": [{"name": "test", "status": "completed", "conclusion": "success", "stages": []},
                     {"name": "build", "status": "in_progress", "conclusion": None,
                      "stages": [{"name": "Build and push", "status": "in_progress", "conclusion": None}]}]},
           {"run_id": "2", "run_number": 8, "workflow": "docker", "branch": "v3", "sha": "3a7e3edc0000",
            "status": "completed", "conclusion": "failure", "updated_at": None,
            "jobs": [{"name": "test", "status": "completed", "conclusion": "failure", "stages": []}]}]

RUN_VIEW = {"steps": [
    {"seq": 1, "step_id": "classify", "status": "done", "detail": "ثبت مطلب جدید", "ms": 3},
    {"seq": 2, "step_id": "extract", "status": "done", "detail": "استخراج شد: عنوان، خلاصه، ۳ طرف", "ms": 1840},
    {"seq": 3, "step_id": "references", "status": "done", "detail": "۱ استناد — ۱ به پایگاه قوانین متصل شد", "ms": 9},
    {"seq": 4, "step_id": "timeline", "status": "done", "detail": "۲ رویداد روی خط زمان", "ms": 2},
    {"seq": 5, "step_id": "similar", "status": "done", "detail": "۴ مورد مشابه", "ms": 120},
    {"seq": 6, "step_id": "labels", "status": "awaiting_input", "detail": "در انتظار پاسخ شما در گفتگو", "ms": 5},
]}

CONVERSATION_MESSAGE = (
    "از متن شما این‌ها را برداشتم:\n• عنوان: صورت‌جلسهٔ رسیدگی شعبهٔ ۳\n• مرجع: دادگاه حقوقی تهران\n"
    "• طرفین: شرکت سهامی بیمه ایران، آقای علی مرادی\n• ۱ استناد قانونی\n\n"
    "این‌ها را پیدا نکردم: شمارهٔ پرونده.\nدر همین گفتگو پاسخ دهید — مثلاً «شمارهٔ پرونده: ۱۴۰۲۰۰۱۲۳۴»."
)
