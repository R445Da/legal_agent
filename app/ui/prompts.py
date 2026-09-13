"""
The sample prompts, as data — one list the assistant screen and the eval share.

These used to live in a throwaway script that only ever ran on a terminal. That
is the wrong home twice over: you could not click them, and the prompts the
tests exercised were free to drift away from the prompts the app advertised.
Keeping them here means the chips on the assistant's home screen and the
prompts the eval runs are literally the same strings, so a prompt that is shown
is a prompt that is checked.

Each entry says what it is *for* — which route it should reach and what a right
answer looks like — because a sample prompt whose behaviour nobody wrote down
is just a nice-looking string.

`follows` marks a prompt that only makes sense after the one before it: «از
همان‌ها چند تا مختومه شده؟» refines the set already on screen, so it is shown
attached to its parent rather than as something to click cold.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Prompt:
    text: str
    note: str                      # what it should do — shown as the chip's tooltip
    intent: str | None = None      # the route it should reach, when it is pinned
    follows: bool = False          # only meaningful after the previous prompt


@dataclass
class Group:
    id: str
    title: str
    blurb: str
    prompts: list[Prompt] = field(default_factory=list)


GROUPS: list[Group] = [
    Group(
        "archive", "پرسش از آرشیو",
        "شمارش و دسته‌بندی بر اساس برچسب‌های واقعی آرشیو — نه جستجوی متنی.",
        [
            Prompt("چند نوع پرونده در مورد تخلفات رانندگی داریم؟",
                   "برچسب‌های رانندگی را از واژگان واقعی جمع می‌کند و می‌شمارد؛ "
                   "«مستمری» نباید در این خوشه بیاید."),
            Prompt("از همان‌ها چند تا مختومه شده و چند تا هنوز جاری است؟",
                   "همان مجموعه را دوباره دسته‌بندی می‌کند — بدون فراخوانی مدل.",
                   follows=True),
            Prompt("در پرونده‌های بیمهٔ شخص ثالث، پرتکرارترین برچسب‌ها کدام‌اند؟",
                   "برچسب‌های متنی و رشتهٔ بیمه‌ای را در یک پرسش با هم می‌آورد."),
            Prompt("پرونده‌های تقلب و جعل بیمه‌ای در رشتهٔ آتش‌سوزی چند تاست؟",
                   "اشتراک دو واژگان — نه اجتماع آن‌ها؛ پاسخ باید کوچک باشد."),
        ],
    ),
    Group(
        "entities", "اشخاص و وکلا",
        "پاسخ از جدول طرفین پرونده‌ها، نه از جستجوی متن — پاسخ به شکل تیکت.",
        [
            Prompt("وکیل رضا کریمی در چه پرونده‌هایی بوده؟",
                   "باید تیکت شخص با همهٔ پرونده‌ها و نقش او در هرکدام باز شود."),
            Prompt("پرونده‌های شرکت سهامی بیمه ایران را نشان بده",
                   "همان مسیر برای یک سازمان."),
        ],
    ),
    Group(
        "law", "قوانین و مستندات",
        "پاسخ با استناد [n] به مواد قانونی، سپس پرونده‌های مرتبط.",
        [
            Prompt("ماده ۳۰ قانون بیمه دربارهٔ جانشینی چه می‌گوید؟",
                   "متن ماده با استناد، سپس پرونده‌هایی که به آن استناد کرده‌اند."),
            Prompt("پرونده‌های بازیافت از رانندهٔ فاقد گواهینامه چطور تمام شده‌اند؟",
                   "جستجو در پرونده‌ها و جمع‌بندی نتیجهٔ آن‌ها."),
        ],
    ),
    Group(
        "agent", "پژوهش عاملی",
        "مدل خودش با ابزارهای فقط‌خواندنی جستجو می‌کند و هر فراخوانی دیده می‌شود.",
        [
            Prompt("وکیل رضا کریمی در چه پرونده‌هایی بوده و نتیجه‌شان چه شد؟",
                   "ردپای ابزارها زنده نمایش داده می‌شود و پاسخ به شواهد استناد می‌کند.",
                   intent="agent"),
        ],
    ),
    Group(
        "filing", "ثبت گفتگویی پرونده",
        "متن را می‌خواند، آنچه را کم است یکی‌یکی می‌پرسد و در آرشیو ثبت می‌کند.",
        [
            Prompt(
                "این صورت‌جلسه را ثبت کن: شعبهٔ ۴ دادگاه حقوقی شیراز، خواهان بیمهٔ "
                "پاسارگاد با وکالت مریم احمدی، خوانده کامران زارعی، موضوع بازیافت "
                "خسارت با استناد به مادهٔ ۳۰ قانون بیمه.",
                "پرسش‌ها یکی‌یکی می‌آیند؛ هر پاسخ یک نوبت در گفتگوست.",
                intent="archive"),
        ],
    ),
]

BY_ID = {g.id: g for g in GROUPS}


def all_prompts() -> list[Prompt]:
    return [p for group in GROUPS for p in group.prompts]


def eval_prompts(group_id: str) -> list[Prompt]:
    """The prompts one group advertises — what the eval for it should run."""
    group = BY_ID.get(group_id)
    return list(group.prompts) if group else []
