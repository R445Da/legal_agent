"""
What a spoken phrase means before it is treated as a message.

Dictation has no buttons. Someone filing a case by voice cannot reach for
«گفتگوی جدید» in the corner of the screen, so a few phrases are reserved: say
them and they act on the session instead of being sent to the router as text.

The list is deliberately short. Every phrase here is a phrase that would be
useless as a message anyway — nobody dictates a court session that consists of
the words «گفتگوی جدید» — so reserving them costs nothing, while reserving
something like «تأیید» would steal a legitimate answer from the filing
dialogue. Confirmations belong to the dialogue and are handled there
(`app/rag/conversation.py`); this only covers commands about the session.

Matching is on the *whole* utterance, folded: a command is what the person
said, not a word buried inside a paragraph they dictated. That is the other
half of why «تأیید» is not here — as a substring it appears constantly.
"""

from __future__ import annotations

# command id -> the phrases that mean it
_COMMANDS: dict[str, tuple[str, ...]] = {
    "new_chat": (
        "گفتگوی جدید", "گفت‌وگوی جدید", "مکالمهٔ جدید", "مکالمه جدید",
        "چت جدید", "از اول", "از نو", "شروع دوباره", "دوباره شروع کن",
        "گفتگو را پاک کن", "تاریخچه را پاک کن", "new chat", "new conversation",
    ),
    "new_case": (
        "پروندهٔ جدید", "پرونده جدید", "ثبت پروندهٔ جدید", "ثبت پرونده جدید",
        "بایگانی جدید", "new case",
    ),
    "stop": (
        "توقف", "متوقف کن", "بس است", "کافیست", "کافی است", "رها کن",
        "stop", "cancel",
    ),
    "repeat": (
        "دوباره بگو", "تکرار کن", "نشنیدم", "چی گفتی", "repeat",
    ),
}

# Persian text arrives with a zero-width non-joiner in the middle of many
# words, and speech-to-text is not consistent about it — «گفت‌وگوی» and
# «گفتوگوی» are the same phrase to a listener, so they must be the same here.
_STRIP = str.maketrans({"\u200c": " ",   # ZWNJ: «گفت‌وگوی» == «گفت وگوی»
                        "\u0654": "",     # hamza above: «پروندهٔ» == «پرونده»
                        "،": " ", ".": " ", "؟": " ", "!": " ", "؛": " "})


def fold(text: str) -> str:
    """One spelling of an utterance, for comparison only."""
    return " ".join((text or "").translate(_STRIP).lower().split())


def command_of(text: str) -> str | None:
    """The command a whole utterance is, or None when it is just a message.

    >>> command_of("گفتگوی جدید")
    'new_chat'
    >>> command_of("برای پروندهٔ خیانت در امانت، بازپرس گفت مهلت تمدید شد")
    """
    said = fold(text)
    if not said or len(said) > 40:
        # Anything long is dictation, whatever words it happens to contain.
        return None
    for command, phrases in _COMMANDS.items():
        if any(said == fold(phrase) for phrase in phrases):
            return command
    return None


# What the assistant says back when it acts on one, so a voice-only user hears
# that the command landed rather than watching for a silent screen change.
ACK_FA = {
    "new_chat": "گفتگوی تازه‌ای شروع کردم.",
    "new_case": "بسیار خوب — متن پرونده را بگویید.",
    "stop": "متوقف شد.",
    "repeat": "دوباره می‌گویم.",
}
