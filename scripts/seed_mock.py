"""
Rebuild the archive from a generated insurance-law dataset.

    .venv/bin/python -m scripts.seed_mock --reset --n 120

What it writes, in order:
  1. the legal-context base from data/laws/laws.json  (LegalReference rows)
  2. N mock cases: for each, a Persian court document (Document + Chunks,
     embedded), a structured Entry, and — through `casebase.sync_entry` —
     the LegalCase row, Person / Organization rows, CaseParty, CaseReference
     and the graph edges.

Deterministic for a given --seed, so the demo looks the same on every machine.
Every case carries exact article citations so the graph has something to show.
Real cases are added later through the same `commit_entry` path (the
assistant's «ثبت مطلب جدید» flow), never by editing this file.
"""

import argparse
import asyncio
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402  (loads .env first)
from app.rag.orchestrator import CASE_TYPES  # noqa: E402

LAWS = pathlib.Path("data/laws/laws.json")
COLLECTION = "mock-insurance"

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #
FIRST_M = ["رضا", "محمد", "علی", "حسین", "امیر", "مهدی", "سعید", "حمید", "مجید", "کاظم", "بهرام", "فرهاد", "ناصر", "یوسف", "احمد"]
FIRST_F = ["سارا", "مریم", "زهرا", "فاطمه", "نرگس", "لیلا", "مینا", "شیرین", "الهام", "نازنین", "پریسا", "هدیه"]
LAST = ["کریمی", "احمدی", "موسوی", "رحیمی", "حسینی", "رضایی", "محمدی", "جعفری", "صادقی", "نوروزی", "کاظمی", "شریفی",
        "عباسی", "قاسمی", "یزدانی", "فخارزاده", "زارع", "امینی", "بهرامی", "توکلی", "سلطانی", "میرزایی", "نظری", "هاشمی"]
LAWYERS = ["رضا کریمی", "سارا موسوی", "محمد نوروزی", "مریم شریفی", "علی یزدانی", "نرگس توکلی", "حسین سلطانی",
           "لیلا امینی", "امیر هاشمی", "زهرا نظری", "مهدی بهرامی", "شیرین قاسمی"]
JUDGES = ["قاضی محمود صالحی", "قاضی فرزانه رستمی", "قاضی احمد پورمحمدی", "قاضی مهناز کیانی", "قاضی جواد اسدی", "قاضی سیما وکیلی"]
INSURERS = ["شرکت سهامی بیمه ایران"] * 5 + ["شرکت بیمه آسیا", "شرکت بیمه البرز", "شرکت بیمه دانا", "شرکت بیمه پاسارگاد", "شرکت بیمه پارسیان", "شرکت بیمه معلم"]
COMPANIES = ["شرکت پتروشیمی خلیج فارس", "شرکت ساختمانی پارس‌سازه", "شرکت حمل‌ونقل بین‌المللی آریا", "شرکت تولیدی لوازم خانگی ایران‌پویا",
             "شرکت بازرگانی مهرگان", "کارخانه نساجی یزدباف", "شرکت فولاد کاوه", "بانک ملت", "بانک صادرات ایران",
             "شرکت داروسازی سبحان", "شرکت کشتیرانی جنوب", "هلدینگ ساختمانی آبادگران", "شرکت خدمات مهندسی توان‌گستر",
             "شرکت پخش مواد غذایی برکت", "کارخانه سیمان تهران"]
HOSPITALS = ["بیمارستان امام خمینی تهران", "بیمارستان نمازی شیراز", "بیمارستان قائم مشهد", "کلینیک تخصصی پارسیان"]
DOCTORS = ["دکتر بهمن آذری", "دکتر نسرین فرجی", "دکتر کامران مهدوی", "دکتر الهه رحمانی"]
CITIES = ["تهران", "شیراز", "مشهد", "اصفهان", "تبریز", "کرج", "اهواز", "قم", "رشت", "یزد"]
CIVIL_COURTS = ["دادگاه عمومی حقوقی {city} — شعبه {b}", "شورای حل اختلاف {city} — حوزه {b}"]
CRIM_COURTS = ["دادگاه کیفری دو {city} — شعبه {b}", "دادسرای عمومی و انقلاب {city} — شعبه {b} بازپرسی"]
ADMIN_COURTS = ["دیوان عدالت اداری — شعبه {b}", "هیئت حل اختلاف اداره کار {city}", "هیئت تشخیص اداره کار {city}"]
ARB = ["هیئت داوری موضوع بیمه‌نامه — {city}", "داوری اتاق بازرگانی {city}"]
CARS = ["پژو ۲۰۶", "پراید ۱۳۱", "سمند LX", "دنا پلاس", "تیبا ۲", "ال۹۰", "پژو پارس", "هایما S7", "کوییک", "شاهین"]
CARGO = ["محمولهٔ لوازم الکترونیکی", "محمولهٔ مواد اولیهٔ پتروشیمی", "محمولهٔ پارچه", "محمولهٔ قطعات خودرو", "محمولهٔ دارو", "محمولهٔ کاشی و سرامیک"]
ADDRS = ["خیابان ولیعصر", "بلوار چمران", "شهرک صنعتی", "خیابان امام", "بزرگراه آزادگان", "جادهٔ قدیم"]

CT = {i: t for i, t in enumerate(CASE_TYPES)}   # index -> Persian case type


def _name(rng, female=None):
    if female is None:
        female = rng.random() < 0.4
    return f"{rng.choice(FIRST_F if female else FIRST_M)} {rng.choice(LAST)}"


def _fa(n) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _date(rng, year=None, month=None):
    y = year or rng.choice([1400, 1401, 1402, 1403, 1404])
    m = month or rng.randint(1, 12)
    d = rng.randint(1, 29)
    return f"{y}/{m:02d}/{d:02d}"


def _next(date, months=0, days=0):
    y, m, d = (int(x) for x in date.split("/"))
    m += months
    d += days
    while d > 29:
        d -= 29
        m += 1
    while m > 12:
        m -= 12
        y += 1
    return f"{y}/{m:02d}/{d:02d}"


def _money(rng, lo, hi, step=10_000_000):
    return rng.randrange(lo, hi, step)


def _rials(v):
    return f"{_fa(f'{v:,}')} ریال"


# --------------------------------------------------------------------------- #
# Templates — one per case type. Each returns a dict with the document text and
# the structured draft (`commit_entry` shape).
# --------------------------------------------------------------------------- #
def t_claim(rng, ctx):
    """۱ مطالبه خسارت بیمه‌گذار علیه بیمه‌گر"""
    line = rng.choice(["آتش‌سوزی", "بدنه خودرو", "باربری", "درمان تکمیلی", "مهندسی (CAR/EAR)"])
    insured = rng.choice(COMPANIES) if line in ("آتش‌سوزی", "باربری", "مهندسی (CAR/EAR)") else _name(rng)
    amount = _money(rng, 500_000_000, 12_000_000_000)
    reason = {
        "آتش‌سوزی": "آتش‌سوزی انبار کالا و تلف موجودی",
        "بدنه خودرو": f"واژگونی خودروی {rng.choice(CARS)}",
        "باربری": f"آسیب‌دیدگی {rng.choice(CARGO)} حین حمل",
        "درمان تکمیلی": "رد هزینهٔ عمل جراحی به استناد بیماری از پیش موجود",
        "مهندسی (CAR/EAR)": "ریزش گود و خسارت به سازهٔ در حال احداث",
    }[line]
    refs = [{"law": "قانون بیمه", "article": "1", "context": "تعهد بیمه‌گر به جبران خسارت پس از وقوع حادثه", "used_by": "plaintiff"},
            {"law": "قانون بیمه", "article": "19", "context": "مبنای محاسبهٔ خسارت: تفاوت قیمت قبل و بعد از حادثه", "used_by": "court"}]
    if line == "آتش‌سوزی":
        refs.append({"law": "قانون بیمه", "article": "21", "context": "شمول خسارت اطفاء در خسارت حریق", "used_by": "court"})
        refs.append({"law": "آیین‌نامه شماره ۲۱ شورای عالی بیمه — شرایط عمومی بیمه‌نامه آتش‌سوزی", "article": "23", "context": "اعلام خسارت ظرف پنج روز", "used_by": "defendant"})
    if line == "درمان تکمیلی":
        refs.append({"law": "آیین‌نامه شماره ۶۴ شورای عالی بیمه — شرایط عمومی بیمه‌های درمان", "article": "5", "context": "استناد بیمه‌گر به دورهٔ انتظار و بیماری از پیش موجود", "used_by": "defendant"})
    if line == "باربری":
        refs.append({"law": "قانون بیمه", "article": "22", "context": "قیمت کالا در مقصد ملاک محاسبه", "used_by": "court"})
    outcome = rng.choice([
        f"حکم به محکومیت بیمه‌گر به پرداخت {_rials(amount)} به انضمام خسارت تأخیر تأدیه",
        f"حکم به پرداخت {_rials(int(amount * 0.6))} با اعمال کسورات کارشناسی؛ مازاد خواسته رد شد",
        "رد دعوا به دلیل عدم اعلام خسارت در مهلت مقرر",
        "ارجاع به کارشناس رسمی برای تعیین میزان خسارت؛ جلسهٔ بعدی تعیین شد",
    ])
    return dict(line=line, group="حقوقی", court=rng.choice(CIVIL_COURTS), amount=amount,
                plaintiff=insured, defendant=ctx["insurer"], refs=refs, outcome=outcome,
                subject=f"مطالبهٔ خسارت بیمه‌نامهٔ {line} — {reason}",
                body=f"خواهان به استناد بیمه‌نامهٔ {line} شمارهٔ {_fa(rng.randint(100000, 999999))} صادرهٔ {ctx['insurer']}، "
                     f"مطالبهٔ خسارت ناشی از {reason} به مبلغ {_rials(amount)} را دارد. "
                     f"خوانده با استناد به گزارش ارزیاب خسارت و شرایط عمومی بیمه‌نامه، میزان خسارت را مورد اختلاف قرار داد.",
                tags=["مطالبه خسارت", line, "بیمه‌گذار علیه بیمه‌گر"])


def t_defence(rng, ctx):
    """۲ دفاع بیمه‌گر: بطلان / تعلیق / قاعده نسبی"""
    line = rng.choice(["آتش‌سوزی", "عمر و سرمایه‌گذاری", "بدنه خودرو", "درمان تکمیلی"])
    defence = rng.choice(["کتمان عمدی", "کتمان غیرعمدی", "کم‌بیمه‌گی", "تشدید خطر"])
    amount = _money(rng, 300_000_000, 6_000_000_000)
    refs = {
        "کتمان عمدی": [{"law": "قانون بیمه", "article": "12", "context": "بطلان عقد به علت اظهار خلاف واقع عمدی در پرسشنامه", "used_by": "defendant"}],
        "کتمان غیرعمدی": [{"law": "قانون بیمه", "article": "13", "context": "اعمال قاعدهٔ نسبی حق بیمه به جای بطلان", "used_by": "court"}],
        "کم‌بیمه‌گی": [{"law": "قانون بیمه", "article": "10", "context": "خسارت به نسبت سرمایهٔ بیمه‌شده به قیمت واقعی", "used_by": "court"}],
        "تشدید خطر": [{"law": "قانون بیمه", "article": "16", "context": "عدم اعلام تغییر کاربری/تشدید خطر ظرف ده روز", "used_by": "defendant"}],
    }[defence]
    if line == "عمر و سرمایه‌گذاری":
        refs.append({"law": "قانون بیمه", "article": "24", "context": "پرداخت سرمایهٔ فوت به ذی‌نفع تعیین‌شده", "used_by": "plaintiff"})
    outcome = {
        "کتمان عمدی": rng.choice(["پذیرش دفاع بیمه‌گر و صدور حکم بطلان بیمه‌نامه؛ حق بیمه مسترد نمی‌شود", "رد دفاع بیمه‌گر به علت عدم اثبات عمد؛ حکم به پرداخت خسارت"]),
        "کتمان غیرعمدی": f"حکم به پرداخت خسارت با اعمال قاعدهٔ نسبی حق بیمه — {_rials(int(amount * 0.55))}",
        "کم‌بیمه‌گی": f"حکم به پرداخت خسارت به نسبت سرمایه — {_rials(int(amount * 0.7))}",
        "تشدید خطر": rng.choice(["پذیرش دفاع؛ رد دعوای خواهان", "رد دفاع به علت اطلاع نمایندهٔ بیمه‌گر از تغییر وضعیت"]),
    }[defence]
    plaintiff = rng.choice(COMPANIES) if line == "آتش‌سوزی" else _name(rng)
    return dict(line=line, group="حقوقی", court=rng.choice(CIVIL_COURTS), amount=amount,
                plaintiff=plaintiff, defendant=ctx["insurer"], refs=refs, outcome=outcome,
                subject=f"دفاع بیمه‌گر مبنی بر {defence} در بیمه‌نامهٔ {line}",
                body=f"در جریان رسیدگی به مطالبهٔ خسارت بیمه‌نامهٔ {line}، {ctx['insurer']} به عنوان خوانده دفاع {defence} را مطرح کرد "
                     f"و مدعی شد بیمه‌گذار در زمان انعقاد عقد، اطلاعات مؤثر بر ارزیابی خطر را به درستی اظهار نکرده است. "
                     f"دادگاه پرسشنامهٔ بیمه، گزارش بازدید اولیه و اظهارات طرفین را بررسی کرد.",
                tags=["دفاع بیمه‌گر", defence, line])


def t_subrogation(rng, ctx):
    """۳ جانشینی / بازیافت"""
    line = rng.choice(["بدنه خودرو", "باربری", "آتش‌سوزی", "مهندسی (CAR/EAR)"])
    amount = _money(rng, 400_000_000, 9_000_000_000)
    culprit = rng.choice(COMPANIES) if line in ("باربری", "آتش‌سوزی", "مهندسی (CAR/EAR)") else _name(rng)
    refs = [{"law": "قانون بیمه", "article": "30", "context": "قائم‌مقامی بیمه‌گر پس از پرداخت خسارت به بیمه‌گذار", "used_by": "plaintiff"},
            {"law": "قانون مسئولیت مدنی", "article": "1", "context": "مسئولیت مسبب حادثه به علت تقصیر", "used_by": "court"}]
    if line == "باربری":
        refs.append({"law": "قانون تجارت", "article": "388", "context": "مسئولیت متصدی حمل در خسارت به کالا", "used_by": "plaintiff"})
        refs.append({"law": "رأی وحدت رویه شماره ۲۹ هیأت عمومی دیوان عالی کشور", "article": "", "context": "بار اثبات بر عهدهٔ متصدی حمل", "used_by": "court"})
    outcome = rng.choice([
        f"حکم به محکومیت خوانده به پرداخت {_rials(amount)} در حق بیمه‌گر به عنوان قائم‌مقام بیمه‌گذار",
        f"حکم به پرداخت {_rials(int(amount * 0.5))} به نسبت درجهٔ تقصیر (۵۰٪)",
        "رد دعوا به علت عدم اثبات پرداخت خسارت به بیمه‌گذار پیش از طرح دعوا",
        "قرار رد دعوا به علت شمول مرور زمان دو سالهٔ مادهٔ ۳۶ قانون بیمه — قابل تجدیدنظر",
    ])
    if "مرور زمان" in outcome:
        refs.append({"law": "قانون بیمه", "article": "36", "context": "مبدأ مرور زمان از تاریخ حادثه", "used_by": "defendant"})
    return dict(line=line, group="حقوقی", court=rng.choice(CIVIL_COURTS), amount=amount,
                plaintiff=ctx["insurer"], defendant=culprit, refs=refs, outcome=outcome,
                subject=f"دعوای جانشینی بیمه‌گر علیه مسبب حادثه — رشتهٔ {line}",
                body=f"{ctx['insurer']} پس از پرداخت خسارت بیمه‌نامهٔ {line} به بیمه‌گذار خود و اخذ رسید و انتقال حقوق، "
                     f"به قائم‌مقامی از بیمه‌گذار علیه {culprit} به عنوان مسبب حادثه طرح دعوا کرد. "
                     f"خوانده منکر تقصیر شد و به زمان طرح دعوا ایراد گرفت.",
                tags=["جانشینی", "بازیافت", "ماده ۳۰", line])


def t_third_party(rng, ctx):
    """۴ شخص ثالث — خسارت بدنی/مالی"""
    kind = rng.choice(["بدنی", "بدنی", "مالی"])
    victim = _name(rng)
    driver = _name(rng, female=False)
    car = rng.choice(CARS)
    amount = _money(rng, 2_000_000_000, 15_000_000_000) if kind == "بدنی" else _money(rng, 100_000_000, 1_500_000_000)
    refs = [{"law": "قانون بیمه اجباری خسارات وارد شده به شخص ثالث در اثر حوادث ناشی از وسایل نقلیه", "article": "15", "context": "پرداخت بدون شرط به زیان‌دیده؛ مراجعهٔ مستقیم", "used_by": "plaintiff"},
            {"law": "قانون بیمه اجباری خسارات وارد شده به شخص ثالث در اثر حوادث ناشی از وسایل نقلیه", "article": "31", "context": "مهلت ۱۵ روزهٔ رسیدگی بیمه‌گر", "used_by": "court"}]
    if kind == "بدنی":
        refs += [{"law": "قانون مجازات اسلامی", "article": "448", "context": "تعیین دیه به عنوان خسارت بدنی", "used_by": "court"},
                 {"law": "رأی وحدت رویه شماره ۷۳۴ هیأت عمومی دیوان عالی کشور", "article": "", "context": "محاسبهٔ دیه به نرخ یوم‌الاداء", "used_by": "court"},
                 {"law": "قانون بیمه اجباری خسارات وارد شده به شخص ثالث در اثر حوادث ناشی از وسایل نقلیه", "article": "34", "context": "پرداخت ۵۰٪ دیهٔ تقریبی پیش از رأی قطعی", "used_by": "plaintiff"}]
        court = rng.choice(CRIM_COURTS)
        group = "کیفری"
        outcome = rng.choice([
            f"محکومیت راننده به پرداخت دیه به میزان {_fa(rng.choice([12, 18, 25, 33, 40]))} درصد دیهٔ کامل؛ بیمه‌گر مخاطب اجرای حکم",
            "محکومیت راننده به پرداخت دیهٔ کامل به اولیای دم؛ پرداخت در حدود تعهد بیمه‌نامه توسط بیمه‌گر",
            "صدور حکم دیه؛ اختلاف در مازاد بر تعهد بیمه‌نامه به صندوق تأمین خسارت‌های بدنی ارجاع شد",
        ])
    else:
        court = rng.choice(CIVIL_COURTS)
        group = "حقوقی"
        outcome = rng.choice([
            f"حکم به پرداخت {_rials(amount)} خسارت مالی توسط بیمه‌گر مطابق نظر کارشناس",
            f"حکم به پرداخت {_rials(int(amount * 0.8))} با کسر افت قیمت به علت عدم اثبات",
        ])
    return dict(line="شخص ثالث", group=group, court=court, amount=amount,
                plaintiff=victim, defendant=ctx["insurer"], extra=[(driver, "mottaham" if kind == "بدنی" else "khande")],
                refs=refs, outcome=outcome,
                subject=f"مطالبهٔ خسارت {kind} شخص ثالث — تصادف {car}",
                body=f"در تاریخ {ctx['incident']} خودروی {car} به رانندگی {driver} در {rng.choice(ADDRS)} {ctx['city']} با {victim} برخورد کرد. "
                     f"کروکی افسر کاردان فنی، راننده را مقصر شناخت. زیان‌دیده با ارائهٔ {'نظریهٔ پزشکی قانونی' if kind == 'بدنی' else 'فاکتور تعمیرگاه و نظر کارشناس'} "
                     f"به بیمه‌گر مراجعه کرد و به علت {rng.choice(['تأخیر در پرداخت', 'کسر خسارت', 'اختلاف در درصد دیه'])} طرح دعوا نمود.",
                tags=["شخص ثالث", f"خسارت {kind}", "تصادف"])


def t_recourse_driver(rng, ctx):
    """۵ بازیافت از راننده مقصر"""
    driver = _name(rng, female=False)
    reason = rng.choice(["فقدان گواهینامه", "رانندگی در حالت مستی", "فرار از صحنهٔ حادثه", "گواهینامهٔ غیرمتناسب با وسیلهٔ نقلیه"])
    amount = _money(rng, 1_500_000_000, 12_000_000_000)
    refs = [{"law": "قانون بیمه اجباری خسارات وارد شده به شخص ثالث در اثر حوادث ناشی از وسایل نقلیه", "article": "16", "context": f"رجوع بیمه‌گر به مسبب حادثه به علت {reason}", "used_by": "plaintiff"},
            {"law": "قانون بیمه", "article": "30", "context": "قائم‌مقامی بیمه‌گر پس از پرداخت", "used_by": "plaintiff"}]
    if "گواهینامه" in reason:
        refs.append({"law": "رأی وحدت رویه شماره ۸۰۶ هیأت عمومی دیوان عالی کشور", "article": "", "context": "عدم پوشش خسارت بدنی رانندهٔ فاقد گواهینامه", "used_by": "court"})
    outcome = rng.choice([
        f"حکم به محکومیت راننده به استرداد {_rials(amount)} پرداختی به زیان‌دیدگان در حق بیمه‌گر",
        f"حکم به پرداخت {_rials(int(amount * 0.6))} به نسبت درجهٔ تقصیر",
        "رد دعوا به علت عدم احراز یکی از موارد مادهٔ ۱۶ (گواهینامه معتبر بوده است)",
    ])
    return dict(line=rng.choice(["شخص ثالث", "حوادث راننده"]), group="حقوقی", court=rng.choice(CIVIL_COURTS), amount=amount,
                plaintiff=ctx["insurer"], defendant=driver, refs=refs, outcome=outcome,
                subject=f"بازیافت خسارت پرداختی از رانندهٔ مقصر — {reason}",
                body=f"{ctx['insurer']} پس از پرداخت دیه و خسارت به زیان‌دیدگان تصادف مورخ {ctx['incident']}، با استناد به {reason} "
                     f"رانندهٔ مسبب حادثه {driver} را به استرداد وجوه پرداختی محکوم می‌خواهد. گزارش پلیس راه و سوابق گواهینامه ضمیمه است.",
                tags=["بازیافت", "راننده مقصر", reason])


def t_fund(rng, ctx):
    """۶ صندوق تأمین خسارت‌های بدنی"""
    victim = _name(rng)
    reason = rng.choice(["فقدان بیمه‌نامه", "ناشناس ماندن وسیلهٔ نقلیهٔ مسبب", "انقضای بیمه‌نامه", "مازاد بر تعهد بیمه‌نامه"])
    amount = _money(rng, 2_000_000_000, 14_000_000_000)
    refs = [{"law": "قانون بیمه اجباری خسارات وارد شده به شخص ثالث در اثر حوادث ناشی از وسایل نقلیه", "article": "21", "context": f"شمول صندوق به علت {reason}", "used_by": "plaintiff"},
            {"law": "قانون بیمه اجباری خسارات وارد شده به شخص ثالث در اثر حوادث ناشی از وسایل نقلیه", "article": "25", "context": "پرداخت بدون شرط توسط صندوق و رجوع بعدی", "used_by": "court"}]
    if reason == "مازاد بر تعهد بیمه‌نامه":
        refs.append({"law": "قانون بیمه اجباری خسارات وارد شده به شخص ثالث در اثر حوادث ناشی از وسایل نقلیه", "article": "29", "context": "اختلاف صندوق و بیمه‌گر در هیئت سه‌نفره", "used_by": "defendant"})
        defendant = "صندوق تأمین خسارت‌های بدنی"
        extra = [(ctx["insurer"], "khande")]
    else:
        defendant = "صندوق تأمین خسارت‌های بدنی"
        extra = []
    outcome = rng.choice([
        f"الزام صندوق به پرداخت دیه به میزان {_rials(amount)} در حق زیان‌دیده",
        "رأی هیئت مادهٔ ۲۹: مسئولیت مازاد با صندوق؛ اعتراض بیمه‌گر ظرف ۲۰ روز",
        "پرداخت توسط صندوق و صدور اجرائیهٔ ثبتی علیه مسبب حادثه (مادهٔ ۲۶)",
    ])
    if "اجرائیه" in outcome:
        refs.append({"law": "قانون بیمه اجباری خسارات وارد شده به شخص ثالث در اثر حوادث ناشی از وسایل نقلیه", "article": "26", "context": "اسناد صندوق در حکم سند لازم‌الاجرا", "used_by": "court"})
    return dict(line="شخص ثالث", group="حقوقی", court=rng.choice(CIVIL_COURTS), amount=amount,
                plaintiff=victim, defendant=defendant, extra=extra, refs=refs, outcome=outcome,
                subject=f"مطالبهٔ خسارت بدنی از صندوق تأمین خسارت‌های بدنی — {reason}",
                body=f"زیان‌دیده {victim} در تصادف مورخ {ctx['incident']} دچار صدمهٔ بدنی شد. به علت {reason}، "
                     f"مطالبهٔ دیه از صندوق تأمین خسارت‌های بدنی طرح شد. گزارش پلیس، نظریهٔ پزشکی قانونی و گواهی عدم شناسایی/فقدان بیمه‌نامه ضمیمه است.",
                tags=["صندوق تأمین خسارت‌های بدنی", reason, "دیه"])


def t_employer(rng, ctx):
    """۷ حوادث ناشی از کار / مسئولیت کارفرما"""
    worker = _name(rng, female=False)
    employer = rng.choice(COMPANIES)
    injury = rng.choice(["سقوط از داربست", "برخورد با ماشین‌آلات", "برق‌گرفتگی", "ریزش خاک در گودبرداری"])
    amount = _money(rng, 1_000_000_000, 10_000_000_000)
    refs = [{"law": "قانون کار", "article": "95", "context": "مسئولیت کارفرما در اجرای مقررات حفاظت فنی", "used_by": "court"},
            {"law": "قانون مسئولیت مدنی", "article": "12", "context": "مسئولیت کارفرما در قبال خسارت وارده حین کار", "used_by": "plaintiff"},
            {"law": "قانون مجازات اسلامی", "article": "448", "context": "دیهٔ صدمهٔ بدنی", "used_by": "court"}]
    stage = rng.choice(["کیفری", "حقوقی"])
    if stage == "کیفری":
        court, group = rng.choice(CRIM_COURTS), "کیفری"
        plaintiff, defendant = worker, employer
        extra = [(ctx["insurer"], "bimegar")]
        outcome = rng.choice([
            f"محکومیت کارفرما به پرداخت {_fa(rng.choice([20, 35, 50, 100]))}٪ دیه به علت بی‌احتیاطی؛ پرداخت در حدود بیمه‌نامهٔ مسئولیت توسط بیمه‌گر",
            "تقسیم مسئولیت: ۷۰٪ کارفرما و ۳۰٪ کارگر بر اساس نظر بازرس کار",
        ])
    else:
        court, group = rng.choice(CIVIL_COURTS), "حقوقی"
        plaintiff, defendant = employer, ctx["insurer"]
        extra = [(worker, "zianide")]
        outcome = rng.choice([
            f"الزام بیمه‌گر به پرداخت {_rials(amount)} بابت دیهٔ محکوم‌به در حدود بیمه‌نامهٔ مسئولیت کارفرما",
            "رد دعوا به علت عدم صدور رأی قطعی مرجع قضایی پیش از مطالبه از بیمه‌گر",
        ])
    return dict(line="مسئولیت مدنی کارفرما", group=group, court=court, amount=amount,
                plaintiff=plaintiff, defendant=defendant, extra=extra, refs=refs, outcome=outcome,
                subject=f"حادثهٔ ناشی از کار — {injury} — مسئولیت کارفرما و بیمه‌گر",
                body=f"کارگر {worker} در تاریخ {ctx['incident']} در کارگاه {employer} بر اثر {injury} دچار صدمهٔ بدنی شد. "
                     f"گزارش بازرس اداره کار عدم رعایت مقررات حفاظت فنی را تأیید کرد. کارفرما دارای بیمه‌نامهٔ مسئولیت مدنی کارفرما نزد {ctx['insurer']} است.",
                tags=["حادثه ناشی از کار", "مسئولیت کارفرما", injury])


def t_social(rng, ctx):
    """۸ رجوع تأمین اجتماعی (م. ۶۶)"""
    employer = rng.choice(COMPANIES)
    amount = _money(rng, 800_000_000, 8_000_000_000)
    refs = [{"law": "قانون تأمین اجتماعی", "article": "66", "context": "رجوع سازمان به کارفرمای مقصر برای مستمری و هزینه‌ها", "used_by": "plaintiff"},
            {"law": "قانون تأمین اجتماعی", "article": "50", "context": "وصول از طریق اجرائیات سازمان", "used_by": "plaintiff"},
            {"law": "قانون کار", "article": "95", "context": "احراز تقصیر کارفرما در حفاظت فنی", "used_by": "court"}]
    stage = rng.choice(["رجوع سازمان", "مطالبه از بیمه‌گر"])
    if stage == "رجوع سازمان":
        plaintiff, defendant, extra = "سازمان تأمین اجتماعی", employer, [(ctx["insurer"], "bimegar")]
        outcome = rng.choice([
            f"الزام کارفرما به پرداخت {_rials(amount)} بابت مستمری‌های پرداختی سازمان",
            "پذیرش پرداخت یکجای معادل ده سال مستمری و بری‌الذمه شدن کارفرما (تبصرهٔ م. ۶۶)",
        ])
    else:
        plaintiff, defendant, extra = employer, ctx["insurer"], [("سازمان تأمین اجتماعی", "other")]
        outcome = rng.choice([
            "الزام بیمه‌گر به پرداخت تعهدات م. ۶۶ در حدود الحاقیهٔ بیمه‌نامهٔ مسئولیت",
            "رد دعوا به علت عدم خرید پوشش اضافی مادهٔ ۶۶ در بیمه‌نامه",
        ])
    return dict(line="مسئولیت مدنی کارفرما", group="حقوقی", court=rng.choice(CIVIL_COURTS), amount=amount,
                plaintiff=plaintiff, defendant=defendant, extra=extra, refs=refs, outcome=outcome,
                subject=f"مطالبات مادهٔ ۶۶ قانون تأمین اجتماعی — {stage}",
                body=f"به دنبال حادثهٔ ناشی از کار در {employer} و برقراری مستمری از کارافتادگی برای کارگر حادثه‌دیده، "
                     f"سازمان تأمین اجتماعی با استناد به مادهٔ ۶۶، هزینه‌ها و مستمری‌های پرداختی را از کارفرما مطالبه کرد. "
                     f"کارفرما مدعی شمول پوشش «تعهدات مادهٔ ۶۶» در بیمه‌نامهٔ مسئولیت خود نزد {ctx['insurer']} است.",
                tags=["ماده ۶۶", "تأمین اجتماعی", "مستمری"])


def t_fraud(rng, ctx):
    """۹ تقلب / جعل / کلاهبرداری بیمه‌ای"""
    accused = _name(rng, female=False)
    scheme = rng.choice(["صحنه‌سازی تصادف", "بیمه‌نامه با تاریخ مؤخر پس از حادثه", "جابه‌جایی رانندهٔ فاقد گواهینامه", "بیش‌اظهاری فاکتور تعمیرات", "فروش بیمه‌نامهٔ جعلی توسط نماینده"])
    amount = _money(rng, 300_000_000, 5_000_000_000)
    refs = [{"law": "قانون تشدید مجازات مرتکبین ارتشاء، اختلاس و کلاهبرداری", "article": "1", "context": "تحصیل وجه از بیمه‌گر از طریق حیله و تقلب", "used_by": "plaintiff"}]
    if "جعل" in scheme or "تاریخ" in scheme or "جعلی" in scheme:
        refs.append({"law": "قانون مجازات اسلامی", "article": "523", "context": "تقدیم تاریخ سند / ساختن بیمه‌نامه", "used_by": "court"})
    if "نماینده" in scheme:
        refs.append({"law": "آیین‌نامه شماره ۱۰۶ شورای عالی بیمه — تنظیم امور نمایندگی بیمه", "article": "17", "context": "مسئولیت شرکت بیمه در قبال بیمه‌گذاران و رجوع به نماینده", "used_by": "court"})
    refs.append({"law": "قانون بیمه", "article": "12", "context": "بطلان بیمه‌نامه به علت سوءنیت", "used_by": "plaintiff"})
    outcome = rng.choice([
        f"محکومیت متهم به {_fa(rng.choice([1, 2, 3]))} سال حبس، رد مال به میزان {_rials(amount)} و جزای نقدی معادل",
        "قرار منع تعقیب به علت فقد ادلهٔ کافی؛ اعتراض شاکی در دادگاه کیفری دو",
        "محکومیت به رد مال؛ حبس تعلیقی به مدت دو سال",
    ])
    return dict(line=rng.choice(["شخص ثالث", "بدنه خودرو", "درمان تکمیلی", "آتش‌سوزی"]), group="کیفری", court=rng.choice(CRIM_COURTS), amount=amount,
                plaintiff=ctx["insurer"], defendant=accused, plaintiff_role="shaki", defendant_role="mottaham", refs=refs, outcome=outcome,
                subject=f"شکایت کلاهبرداری بیمه‌ای — {scheme}",
                body=f"{ctx['insurer']} با استعلام سامانهٔ سنهاب و گزارش واحد کشف تقلب، {scheme} توسط {accused} را احراز و شکایت کیفری مطرح کرد. "
                     f"کارشناس تشخیص اصالت اسناد و تصاویر دوربین‌های مسیر در پرونده است. مبلغ مورد ادعا {_rials(amount)}.",
                tags=["تقلب بیمه‌ای", "کلاهبرداری", scheme])


def t_agent(rng, ctx):
    """۱۰ دعاوی نمایندگان و کارگزاران"""
    agent = rng.choice([f"نمایندگی بیمه {rng.choice(LAST)} — کد {_fa(rng.randint(10000, 99999))}", f"کارگزاری رسمی بیمه {rng.choice(['پارس', 'مهر', 'آتیه', 'سپهر'])}"])
    issue = rng.choice(["عدم واریز حق بیمه‌های وصولی", "فسخ قرارداد نمایندگی و مطالبهٔ خسارت", "صدور بیمه‌نامه خارج از حدود اختیار", "تسویهٔ کارمزد پورتفوی"])
    amount = _money(rng, 200_000_000, 4_000_000_000)
    refs = [{"law": "آیین‌نامه شماره ۱۰۶ شورای عالی بیمه — تنظیم امور نمایندگی بیمه", "article": "23", "context": "فسخ قرارداد نمایندگی به علت تخلف", "used_by": "plaintiff"},
            {"law": "آیین‌نامه شماره ۱۰۶ شورای عالی بیمه — تنظیم امور نمایندگی بیمه", "article": "17", "context": "مسئولیت شرکت در قبال بیمه‌گذاران و حق رجوع", "used_by": "court"},
            {"law": "قانون تأسیس بیمه مرکزی ایران و بیمه‌گری", "article": "17", "context": "صلاحیت شورای عالی بیمه در مقررات نمایندگی", "used_by": "court"}]
    if "کارگزاری" in agent:
        refs.append({"law": "آیین‌نامه شماره ۹۲ شورای عالی بیمه — کارگزاری (دلالی) رسمی بیمه مستقیم", "article": "3", "context": "تکالیف کارگزار", "used_by": "court"})
    if issue == "عدم واریز حق بیمه‌های وصولی":
        plaintiff, defendant = ctx["insurer"], agent
        outcome = f"الزام نماینده به پرداخت {_rials(amount)} حق بیمه‌های وصولی و ضبط تضمین"
    else:
        plaintiff, defendant = agent, ctx["insurer"]
        outcome = rng.choice(["رد دعوای نماینده؛ فسخ قرارداد صحیح تشخیص داده شد", f"الزام شرکت به پرداخت {_rials(amount)} کارمزد معوق"])
    court = rng.choice(CIVIL_COURTS + ["دیوان عدالت اداری — شعبه {b}"])
    return dict(line=rng.choice(["شخص ثالث", "بدنه خودرو", "عمر و سرمایه‌گذاری"]), group="حقوقی" if "دیوان" not in court else "اداری", court=court, amount=amount,
                plaintiff=plaintiff, defendant=defendant, extra=[("بیمه مرکزی جمهوری اسلامی ایران", "other")], refs=refs, outcome=outcome,
                subject=f"اختلاف نمایندگی/کارگزاری — {issue}",
                body=f"بین {ctx['insurer']} و {agent} در خصوص {issue} اختلاف حاصل شد. قرارداد نمایندگی، صورت‌حساب پورتفوی و مکاتبات با بیمه مرکزی ضمیمهٔ پرونده است.",
                tags=["نمایندگی", "کارگزاری", issue])


def t_employment(rng, ctx):
    """۱۱ دعاوی استخدامی کارکنان"""
    employee = _name(rng)
    issue = rng.choice(["اخراج و مطالبهٔ بازگشت به کار", "مطالبهٔ مزایای پایان خدمت", "تبدیل وضعیت استخدامی", "مطالبهٔ اضافه‌کاری و سنوات"])
    amount = _money(rng, 100_000_000, 2_000_000_000)
    admin = rng.random() < 0.5
    refs = [{"law": "قانون کار", "article": "157", "context": "صلاحیت هیئت‌های تشخیص و حل اختلاف", "used_by": "court"},
            {"law": "قانون کار", "article": "159", "context": "اعتراض به رأی هیئت تشخیص ظرف ۱۵ روز", "used_by": "plaintiff"}]
    if admin:
        refs.append({"law": "قانون تشکیلات و آیین دادرسی دیوان عدالت اداری", "article": "10", "context": "اعتراض به رأی هیئت حل اختلاف در دیوان", "used_by": "plaintiff"})
        court = "دیوان عدالت اداری — شعبه {b}"
        outcome = rng.choice(["نقض رأی هیئت حل اختلاف و اعادهٔ پرونده", "تأیید رأی هیئت حل اختلاف؛ رد شکایت"])
    else:
        court = rng.choice(ADMIN_COURTS[1:])
        outcome = rng.choice([f"الزام شرکت به پرداخت {_rials(amount)} مطالبات کارگری", "رأی به بازگشت به کار و پرداخت حقوق ایام تعلیق", "رد شکایت به علت قرارداد مدت معین"])
    return dict(line="", group="اداری", court=court, amount=amount,
                plaintiff=employee, defendant=ctx["insurer"], refs=refs, outcome=outcome,
                subject=f"دعوای استخدامی — {issue}",
                body=f"{employee} از کارکنان {rng.choice(['شعبه', 'ستاد', 'واحد خسارت'])} {ctx['insurer']} در {ctx['city']}، در خصوص {issue} شکایت کرد. "
                     f"حکم کارگزینی، قرارداد کار و لیست بیمهٔ تأمین اجتماعی ضمیمه است.",
                tags=["استخدامی", "کارگری", issue])


def t_regulator(rng, ctx):
    """۱۲ اعتراض به بیمه مرکزی / شورای عالی بیمه"""
    issue = rng.choice(["اعتراض به جریمهٔ نظارتی موضوع مادهٔ ۵۷", "درخواست ابطال مصوبهٔ شورای عالی بیمه", "اعتراض به تعلیق پروانهٔ رشته", "اعتراض به الزامات توانگری مالی"])
    refs = [{"law": "قانون تشکیلات و آیین دادرسی دیوان عدالت اداری", "article": "10" if "ابطال" not in issue else "12", "context": "صلاحیت دیوان در رسیدگی به تصمیم/مصوبه", "used_by": "court"},
            {"law": "قانون تأسیس بیمه مرکزی ایران و بیمه‌گری", "article": "1", "context": "اختیار نظارتی بیمه مرکزی", "used_by": "defendant"}]
    if "۵۷" in issue:
        refs.append({"law": "قانون بیمه اجباری خسارات وارد شده به شخص ثالث در اثر حوادث ناشی از وسایل نقلیه", "article": "57", "context": "رسیدگی به قصور شرکت بیمه در پرداخت خسارت", "used_by": "defendant"})
    if "ابطال" in issue:
        refs.append({"law": "قانون تأسیس بیمه مرکزی ایران و بیمه‌گری", "article": "17", "context": "حدود اختیار شورای عالی بیمه", "used_by": "plaintiff"})
    outcome = rng.choice(["رد شکایت؛ تصمیم بیمه مرکزی در حدود اختیارات قانونی تشخیص داده شد", "نقض تصمیم بیمه مرکزی به علت عدم رعایت تشریفات", "ابطال بند مورد اعتراض مصوبه توسط هیئت عمومی دیوان"])
    return dict(line=rng.choice(["شخص ثالث", "درمان تکمیلی", "اتکایی"]), group="اداری", court="دیوان عدالت اداری — شعبه {b}" if "ابطال" not in issue else "هیئت عمومی دیوان عدالت اداری",
                amount=None, plaintiff=ctx["insurer"], defendant="بیمه مرکزی جمهوری اسلامی ایران", refs=refs, outcome=outcome,
                subject=issue,
                body=f"{ctx['insurer']} نسبت به {issue} در دیوان عدالت اداری شکایت کرد. مصوبه/ابلاغیهٔ مورد اعتراض، مکاتبات نظارتی و گزارش بازرسی بیمه مرکزی ضمیمه است.",
                tags=["بیمه مرکزی", "دیوان عدالت اداری", issue])


def t_arbitration(rng, ctx):
    """۱۳ داوری قراردادی"""
    line = rng.choice(["مهندسی (CAR/EAR)", "آتش‌سوزی", "باربری", "اتکایی", "نفت و انرژی"])
    insured = rng.choice(COMPANIES)
    amount = _money(rng, 3_000_000_000, 60_000_000_000, step=100_000_000)
    refs = [{"law": "قانون آیین دادرسی دادگاه‌های عمومی و انقلاب در امور مدنی", "article": "454", "context": "ارجاع اختلاف به داوری طبق شرط بیمه‌نامه", "used_by": "court"},
            {"law": "قانون بیمه", "article": "19", "context": "مبنای محاسبهٔ خسارت", "used_by": "plaintiff"}]
    stage = rng.choice(["رأی داوری", "ابطال رأی داور"])
    if stage == "ابطال رأی داور":
        refs += [{"law": "قانون آیین دادرسی دادگاه‌های عمومی و انقلاب در امور مدنی", "article": "489", "context": "ادعای صدور رأی خارج از حدود اختیار داور", "used_by": "plaintiff"},
                 {"law": "قانون آیین دادرسی دادگاه‌های عمومی و انقلاب در امور مدنی", "article": "490", "context": "مهلت ۲۰ روزهٔ درخواست ابطال", "used_by": "court"}]
        court = rng.choice(CIVIL_COURTS[:1])
        outcome = rng.choice(["رد درخواست ابطال؛ رأی داور تأیید شد", "ابطال رأی داور به علت صدور خارج از مدت داوری"])
        plaintiff, defendant = ctx["insurer"], insured
    else:
        court = rng.choice(ARB)
        outcome = rng.choice([f"رأی داوری به پرداخت {_rials(int(amount * 0.75))} توسط بیمه‌گر", f"رأی داوری به پرداخت {_rials(amount)} به انضمام هزینهٔ کارشناسی"])
        plaintiff, defendant = insured, ctx["insurer"]
    return dict(line=line, group="داوری", court=court, amount=amount,
                plaintiff=plaintiff, defendant=defendant, refs=refs, outcome=outcome,
                subject=f"داوری اختلاف بیمه‌نامهٔ {line} — {stage}",
                body=f"اختلاف {insured} و {ctx['insurer']} در خصوص خسارت بیمه‌نامهٔ {line} به مبلغ {_rials(amount)} به موجب شرط داوری بیمه‌نامه به هیئت داوری ارجاع شد. "
                     f"هر طرف یک داور و سرداور با توافق تعیین شد. مرحلهٔ فعلی: {stage}.",
                tags=["داوری", line, stage])


def t_line_specific(rng, ctx):
    """۱۴ دعاوی رشته‌محور"""
    line = rng.choice(["درمان تکمیلی", "عمر و سرمایه‌گذاری", "باربری", "حوادث انفرادی", "مسئولیت حرفه‌ای پزشکان", "آتش‌سوزی"])
    amount = _money(rng, 200_000_000, 8_000_000_000)
    plaintiff = _name(rng)
    defendant = ctx["insurer"]
    extra = []
    if line == "درمان تکمیلی":
        issue = "رد هزینهٔ بستری به استناد بیماری از پیش موجود"
        refs = [{"law": "آیین‌نامه شماره ۶۴ شورای عالی بیمه — شرایط عمومی بیمه‌های درمان", "article": "5", "context": "دورهٔ انتظار و استثنائات", "used_by": "defendant"},
                {"law": "آیین‌نامه شماره ۶۴ شورای عالی بیمه — شرایط عمومی بیمه‌های درمان", "article": "11", "context": "مهلت ۱۵ روزهٔ اعلام دلایل رد", "used_by": "plaintiff"},
                {"law": "قانون بیمه", "article": "13", "context": "کتمان غیرعمدی", "used_by": "court"}]
        extra = [(rng.choice(HOSPITALS), "other")]
    elif line == "عمر و سرمایه‌گذاری":
        issue = "اختلاف ذی‌نفع و ورثه در سرمایهٔ فوت"
        refs = [{"law": "قانون بیمه", "article": "24", "context": "پرداخت به ذی‌نفع تعیین‌شده در بیمه‌نامه", "used_by": "court"},
                {"law": "قانون بیمه", "article": "23", "context": "رضایت بیمه‌شده", "used_by": "defendant"}]
        extra = [(_name(rng), "khande")]
    elif line == "باربری":
        issue = "کسری محموله در مقصد و بازیافت از متصدی حمل"
        plaintiff = rng.choice(COMPANIES)
        refs = [{"law": "قانون بیمه", "article": "22", "context": "قیمت کالا در مقصد", "used_by": "court"},
                {"law": "قانون تجارت", "article": "386", "context": "مسئولیت متصدی حمل در تلف کالا", "used_by": "plaintiff"},
                {"law": "قانون بیمه", "article": "30", "context": "جانشینی بیمه‌گر پس از پرداخت", "used_by": "defendant"}]
        extra = [(rng.choice(["شرکت حمل‌ونقل بین‌المللی آریا", "شرکت کشتیرانی جنوب"]), "khande")]
    elif line == "حوادث انفرادی":
        issue = "اختلاف در درصد نقص عضو"
        refs = [{"law": "آیین‌نامه شماره ۸۴ شورای عالی بیمه — شرایط عمومی بیمه‌نامه حوادث اشخاص", "article": "9", "context": "تعیین درصد نقص عضو با نظر پزشکی قانونی", "used_by": "court"},
                {"law": "آیین‌نامه شماره ۸۴ شورای عالی بیمه — شرایط عمومی بیمه‌نامه حوادث اشخاص", "article": "2", "context": "تعریف حادثه", "used_by": "defendant"}]
    elif line == "مسئولیت حرفه‌ای پزشکان":
        issue = "قصور پزشکی و مطالبه از بیمه‌گر مسئولیت"
        doctor = rng.choice(DOCTORS)
        refs = [{"law": "قانون مسئولیت مدنی", "article": "1", "context": "تقصیر حرفه‌ای", "used_by": "plaintiff"},
                {"law": "قانون مجازات اسلامی", "article": "448", "context": "دیهٔ نقص عضو", "used_by": "court"},
                {"law": "قانون بیمه", "article": "4", "context": "بیمهٔ مسئولیت حقوقی به عنوان موضوع بیمه", "used_by": "court"}]
        extra = [(doctor, "khande"), (rng.choice(HOSPITALS), "other")]
    else:
        issue = "کم‌بیمه‌گی و اعمال قاعدهٔ نسبی در خسارت حریق"
        plaintiff = rng.choice(COMPANIES)
        refs = [{"law": "قانون بیمه", "article": "10", "context": "قاعدهٔ نسبی سرمایه", "used_by": "court"},
                {"law": "قانون بیمه", "article": "21", "context": "شمول خسارت حریق", "used_by": "plaintiff"},
                {"law": "آیین‌نامه شماره ۲۱ شورای عالی بیمه — شرایط عمومی بیمه‌نامه آتش‌سوزی", "article": "1", "context": "خطرات اصلی", "used_by": "court"}]
    outcome = rng.choice([f"حکم به پرداخت {_rials(amount)}", f"حکم به پرداخت {_rials(int(amount * 0.65))} پس از کسورات", "رد دعوا", "ارجاع به کارشناسی و تعیین جلسهٔ بعدی"])
    return dict(line=line, group="حقوقی", court=rng.choice(CIVIL_COURTS), amount=amount,
                plaintiff=plaintiff, defendant=defendant, extra=extra, refs=refs, outcome=outcome,
                subject=f"{line} — {issue}",
                body=f"دعوای {plaintiff} علیه {ctx['insurer']} در خصوص {issue}. بیمه‌نامه، اعلام خسارت، مدارک درمانی/کارشناسی و مکاتبات رد خسارت ضمیمه است.",
                tags=[line, issue])


TEMPLATES = [t_claim, t_defence, t_subrogation, t_third_party, t_recourse_driver, t_fund, t_employer,
             t_social, t_fraud, t_agent, t_employment, t_regulator, t_arbitration, t_line_specific]


def build_case(rng, index: int) -> tuple[str, dict, str]:
    """-> (source, draft, raw_text)"""
    type_index = index % len(TEMPLATES)
    city = rng.choice(CITIES)
    insurer = rng.choice(INSURERS)
    filed = _date(rng)
    ctx = {"city": city, "insurer": insurer, "incident": _next(filed, months=-rng.randint(1, 6) if int(filed[5:7]) > 6 else 0, days=-rng.randint(3, 20))}
    spec = TEMPLATES[type_index](rng, ctx)
    case_type = CT[type_index]
    branch = rng.randint(1, 45)
    court = spec["court"].format(city=city, b=_fa(branch))
    number = f"{filed[:4]}{_fa(rng.randint(10, 99))}{_fa(rng.randint(1000, 9999))}"
    number = number.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    judge = rng.choice(JUDGES)
    lawyer_p = rng.choice(LAWYERS) if rng.random() < 0.85 else None
    lawyer_d = rng.choice([l for l in LAWYERS if l != lawyer_p]) if rng.random() < 0.7 else None
    status = rng.choices(["closed", "open", "appeal"], weights=[55, 30, 15])[0]
    decided = _next(filed, months=rng.randint(2, 9)) if status != "open" else None
    stage = {"closed": "قطعی", "open": "بدوی", "appeal": "تجدیدنظر"}[status]

    p_role = spec.get("plaintiff_role", "khahan")
    d_role = spec.get("defendant_role", "khande")
    parties = [{"name": spec["plaintiff"], "role": p_role}, {"name": spec["defendant"], "role": d_role}]
    for name, role in spec.get("extra", []):
        parties.append({"name": name, "role": role})
    representation = []
    if lawyer_p:
        parties.append({"name": lawyer_p, "role": "vakil_khahan"})
        representation.append({"lawyer": lawyer_p, "client": spec["plaintiff"]})
    if lawyer_d:
        parties.append({"name": lawyer_d, "role": "vakil_khande"})
        representation.append({"lawyer": lawyer_d, "client": spec["defendant"]})
    parties.append({"name": judge, "role": "ghazi"})

    events = [{"date": ctx["incident"], "description": "وقوع حادثه / منشأ اختلاف"},
              {"date": filed, "description": "ثبت دادخواست / شکایت"},
              {"date": _next(filed, months=1, days=rng.randint(0, 20)), "description": "جلسهٔ اول رسیدگی؛ استماع اظهارات طرفین"}]
    if rng.random() < 0.6:
        events.append({"date": _next(filed, months=2, days=rng.randint(0, 20)), "description": "ارجاع به کارشناس رسمی / وصول نظریهٔ کارشناسی"})
    if decided:
        events.append({"date": decided, "description": f"صدور رأی: {spec['outcome']}"})
        if status == "appeal":
            events.append({"date": _next(decided, days=rng.randint(5, 20)), "description": "ثبت اعتراض تجدیدنظرخواهی"})

    doc_kind = "دادنامه" if decided else "صورت‌جلسه"
    refs_text = "؛ ".join(
        (f"مادهٔ {r['article']} " if r["article"] else "") + r["law"] + (f" ({r['context']})" if r.get("context") else "")
        for r in spec["refs"]
    )
    people = [spec["plaintiff"], spec["defendant"], judge] + [l for l in (lawyer_p, lawyer_d) if l] + [n for n, _ in spec.get("extra", [])]
    orgs = [x for x in people if any(h in x for h in ("شرکت", "بیمه", "بانک", "سازمان", "صندوق", "کارخانه", "هلدینگ", "بیمارستان", "کلینیک", "نمایندگی", "کارگزاری"))]
    people = [x for x in people if x not in orgs]

    raw = (
        f"{doc_kind} — {court}\n"
        f"کلاسه پرونده: {_fa(number)} — تاریخ: {_fa(decided or events[-1]['date'])}\n"
        f"{'شاکی' if p_role == 'shaki' else 'خواهان'}: {spec['plaintiff']}" + (f" (با وکالت {lawyer_p})" if lawyer_p else "") + "\n"
        f"{'متهم' if d_role == 'mottaham' else 'خوانده'}: {spec['defendant']}" + (f" (با وکالت {lawyer_d})" if lawyer_d else "") + "\n"
        + "".join(f"{casebase_role_fa(role)}: {name}\n" for name, role in spec.get("extra", []))
        + f"قاضی: {judge}\n"
        f"نوع دعوا: {case_type}" + (f" — رشتهٔ بیمه: {spec['line']}" if spec["line"] else "") + "\n"
        f"موضوع: {spec['subject']}\n\n"
        f"گردش کار:\n{spec['body']}\n\n"
        f"مستندات قانونی:\n{refs_text}\n\n"
        + (f"رأی دادگاه:\n{spec['outcome']}\n" if decided else f"تصمیم دادگاه:\nپرونده در جریان رسیدگی است. {spec['outcome']}\n")
        + (f"\nخواستهٔ مالی: {_rials(spec['amount'])}\n" if spec.get("amount") else "")
    )
    draft = {
        "kind": "session",
        "title": f"{spec['subject']} — پروندهٔ {_fa(number)}",
        "summary": spec["body"] + " " + ("نتیجه: " + spec["outcome"] if decided else "در جریان رسیدگی."),
        "parties": parties,
        "representation": representation,
        "events": events,
        "entities": {
            "people": people, "orgs": orgs, "case_number": number, "court": court,
            "topic": spec["subject"], "case_type": case_type, "insurance_line": spec["line"],
            "claim_amount": str(spec["amount"] or ""), "outcome": spec["outcome"] if decided else "",
            "status": status, "filed_date": filed, "decided_date": decided or "", "stage": stage,
            "group": spec["group"], "branch": str(branch),
        },
        "legal_refs": spec["refs"],
        "tags": list(dict.fromkeys([case_type.split(" —")[0].split(":")[0].strip()] + spec["tags"] + ([spec["line"]] if spec["line"] else []))),
    }
    source = f"mock/{number}.txt"
    return source, draft, raw


def casebase_role_fa(role: str) -> str:
    from app.rag.casebase import ROLE_FA
    return ROLE_FA.get(role, role)


# --------------------------------------------------------------------------- #
async def _reset(session):
    from sqlalchemy import delete, select

    from app.db.models import (
        CaseParty, CaseReference, Chunk, Document, Entry, GraphEdge, Label, LegalCase,
        LegalReference, Organization, Person, Run, RunStep,
    )

    for model in (RunStep, Run, GraphEdge, CaseReference, CaseParty, Label, Entry, LegalCase,
                  Person, Organization, LegalReference):
        await session.execute(delete(model))
    doc_ids = (await session.execute(
        select(Document.id).where(Document.doc_metadata["collection"].astext == COLLECTION)
    )).scalars().all()
    if doc_ids:
        await session.execute(delete(Chunk).where(Chunk.document_id.in_(doc_ids)))
        await session.execute(delete(Document).where(Document.id.in_(doc_ids)))
    await session.commit()


async def _seed_laws(session) -> int:
    from app.rag.lawbase import upsert_ref

    data = json.loads(LAWS.read_text(encoding="utf-8"))
    n = 0
    for law in data["laws"]:
        for art in law["articles"]:
            await upsert_ref(
                session, law_title=law["law_title"], law_year=law.get("law_year") or None,
                article_no=art.get("no") or None, text=art["text"], kind=law.get("kind", "law"),
                title=art.get("title"), keywords=art.get("keywords") or [],
            )
            n += 1
    await session.commit()
    return n


async def main(args) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.engine import create_schema, resolve_database_url
    from app.rag.lawbase import resolve_refs
    from app.rag.orchestrator import commit_entry

    engine = create_async_engine(resolve_database_url())
    await create_schema(engine)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    rng = random.Random(args.seed)

    async with sessions() as session:
        if args.reset:
            await _reset(session)
            print("[seed] reset done")
        n_laws = await _seed_laws(session)
        print(f"[seed] legal context: {n_laws} articles")

        unresolved = 0
        for i in range(args.n):
            source, draft, raw = build_case(rng, i)
            draft["legal_refs"] = await resolve_refs(session, draft["legal_refs"], create_stubs=True)
            unresolved += sum(1 for r in draft["legal_refs"] if not r["resolved"])
            draft["_collection"] = COLLECTION
            entry = await commit_entry(session, draft, raw, source=source, related=None)
            if (i + 1) % 20 == 0:
                print(f"[seed] {i + 1}/{args.n} cases … last: {entry.title[:60]}")
        print(f"[seed] done — {args.n} cases, unresolved citations: {unresolved}")

        from app.rag.casebase import archive_stats
        stats = await archive_stats(session)
        print(f"[seed] cases={stats['cases']} persons={stats['persons']} orgs={stats['orgs']} "
              f"laws={stats['laws']} citations={stats['citations']}")
    await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--reset", action="store_true", help="drop entries/cases/graph/laws (+ mock documents) first")
    asyncio.run(main(ap.parse_args()))
