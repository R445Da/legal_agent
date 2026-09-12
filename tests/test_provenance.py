"""The citation verifier and the provenance block."""

from app.rag import provenance as prov

EVIDENCE = [
    {"n": 1, "kind": "law", "id": "law-1", "cite": "مادهٔ ۳۰ قانون بیمه", "title": "جانشینی"},
    {"n": 2, "kind": "case", "id": "case-1", "cite": "۱۴۰۲۰۰۱", "title": "بازیافت", "case_number": "۱۴۰۲۰۰۱"},
]


def test_fully_cited_answer_is_ok():
    answer = ("بیمه‌گر پس از پرداخت خسارت قائم‌مقام بیمه‌گذار می‌شود [1]. "
              "در پروندهٔ مشابه دادگاه حکم به پرداخت داد [۲].")
    g = prov.verify_citations(answer, EVIDENCE)
    assert g["cited"] == [1, 2] and g["valid"] == [1, 2] and g["invalid"] == []
    assert g["coverage"] == 1.0 and g["status"] == "ok"
    assert [c["supported"] for c in g["claims"]] == [True, True]


def test_dangling_index_and_uncited_claim_are_partial():
    answer = ("بیمه‌گر پس از پرداخت خسارت قائم‌مقام بیمه‌گذار می‌شود [1]. "
              "این جمله هیچ استنادی به شواهد ندارد و باید علامت بخورد. "
              "و این یکی به شمارهٔ ناموجود اشاره می‌کند [7].")
    g = prov.verify_citations(answer, EVIDENCE)
    assert g["invalid"] == [7] and g["valid"] == [1]
    assert g["status"] == "partial"
    assert len(g["unsupported_claims"]) == 2
    assert 0 < g["coverage"] < 1


def test_no_citations_is_unsupported():
    g = prov.verify_citations("این پاسخ طولانی است اما به هیچ شاهدی اشاره نمی‌کند.", EVIDENCE)
    assert g["status"] == "unsupported" and g["coverage"] == 0.0 and g["cited"] == []


def test_no_evidence_is_unsupported_even_with_brackets():
    g = prov.verify_citations("ادعایی با استناد به چیزی که وجود ندارد [1].", [])
    assert g["status"] == "unsupported" and g["invalid"] == [1]


def test_headings_and_fragments_are_not_claims():
    answer = "جمع‌بندی:\nکوتاه.\nبیمه‌گر قائم‌مقام بیمه‌گذار در حدود پرداختی است [1]."
    g = prov.verify_citations(answer, EVIDENCE)
    assert len(g["claims"]) == 1 and g["status"] == "ok"


def test_persian_digits_and_spaces_inside_brackets():
    assert prov.cited_numbers("الف [ ۱ ] ب [2] ج [۱]") == [1, 2]


def test_evidence_from_refs_and_cases_number_in_order():
    refs = [{"id": "a", "cite": "مادهٔ ۱", "title": "t", "text": "x" * 500}, {"id": "b", "cite": "مادهٔ ۲"}]
    ev = prov.evidence_from_refs(refs)
    assert [e["n"] for e in ev] == [1, 2] and ev[0]["kind"] == "law" and len(ev[0]["text"]) == 400
    cases = [{"id": "c", "case_number": "۱", "title": "t", "outcome": "رد دعوا"}]
    assert prov.evidence_from_cases(cases)[0]["cite"] == "۱"
    contexts = [{"n": 1, "source": "entry/xyz", "title": "مدخل", "similarity": None},
                {"n": 2, "source": "doc.txt", "chunk_id": "ch", "document_id": "d", "similarity": 0.4}]
    ev = prov.evidence_from_contexts(contexts)
    assert ev[0]["kind"] == "entry" and ev[1]["kind"] == "chunk" and ev[1]["id"] == "ch"


def test_build_provenance_shape():
    block = prov.build_provenance(
        intent="law", provider="mock", model="mock/rules-v1", evidence=EVIDENCE,
        tool_trail=[{"seq": 1, "tool": "search_law", "summary": "s"}],
        usage={"calls": 1, "input_tokens": 10, "output_tokens": 5},
        answer="بیمه‌گر قائم‌مقام بیمه‌گذار می‌شود و این جمله بلند است [1].", latency_ms=12.6,
    )
    assert block["version"] == 1 and block["intent"] == "law"
    assert block["grounding"]["status"] == "ok" and "claims" not in block["grounding"]
    assert block["evidence"][0]["label"] == "ماده: مادهٔ ۳۰ قانون بیمه"
    assert block["tool_trail"][0]["tool"] == "search_law"
    assert block["usage"]["input_tokens"] == 10 and block["latency_ms"] == 13
    assert block["created_at"]
