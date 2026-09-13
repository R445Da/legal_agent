"""Voice input: which utterances are commands, and how the Gemini Live
transcription backend is configured. No audio and no network here — the round
trip is exercised by hand with `scripts/live.sh --mic`."""

import pytest

from app.rag import voice


def test_reserved_phrases_are_commands():
    assert voice.command_of("گفتگوی جدید") == "new_chat"
    assert voice.command_of("گفت‌وگوی جدید") == "new_chat"      # with the ZWNJ
    assert voice.command_of("از نو") == "new_chat"
    assert voice.command_of("پروندهٔ جدید") == "new_case"
    assert voice.command_of("پرونده جدید") == "new_case"        # without the ezafe
    assert voice.command_of("توقف") == "stop"
    assert voice.command_of("دوباره بگو") == "repeat"


def test_punctuation_and_case_do_not_matter():
    assert voice.command_of("گفتگوی جدید.") == "new_chat"
    assert voice.command_of("  توقف  ") == "stop"
    assert voice.command_of("New Chat") == "new_chat"


def test_dictation_is_never_a_command():
    """The whole point of the length guard: a dictated session mentions all
    sorts of words, and none of them may hijack the turn."""
    dictated = (
        "برای پروندهٔ جدید خیانت در امانت، بازپرس گفت مهلت لایحه تا ۱۴۰۳/۰۷/۰۵ "
        "تمدید شد و پرونده به شعبهٔ سوم ارجاع گردید"
    )
    assert voice.command_of(dictated) is None
    assert voice.command_of("توقف رسیدگی به این پرونده اعلام شد") is None
    assert voice.command_of("") is None


def test_confirmations_belong_to_the_dialogue_not_here():
    """«تأیید» answers the filing question on screen; reserving it as a session
    command would steal that answer."""
    assert voice.command_of("تأیید") is None
    assert voice.command_of("ثبت کن") is None


def test_every_command_has_something_to_say_back():
    for command in ("new_chat", "new_case", "stop", "repeat"):
        assert voice.ACK_FA.get(command)


# --------------------------------------------------------------------------- #
def test_legal_vocabulary_is_loaded_and_persian():
    from app.rag import gemini_stt

    terms = gemini_stt.vocabulary()
    assert len(terms) > 40
    assert "کلاسه" in terms and "بازیافت خسارت" in terms
    assert not any(t.startswith("#") for t in terms)


def test_budget_scales_with_the_audio():
    from app.rag import gemini_stt

    one_second = b"\0" * (gemini_stt.RATE * 2)
    assert gemini_stt.budget_for(one_second) == pytest.approx(26.0)
    assert gemini_stt.budget_for(one_second * 10) == pytest.approx(35.0)


def test_backend_choice_prefers_gemini_then_groq_then_local(monkeypatch):
    from app.rag import transcribe

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    assert transcribe.default_choice().startswith("gemini:")

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert transcribe.default_choice().startswith("groq:")

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert transcribe.default_choice().startswith("local:")
