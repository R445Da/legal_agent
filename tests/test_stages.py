"""Every demo stage runs end to end on the offline model and meets its expectations."""

import pytest

from app.demo.stages import STAGES, run_stage

pytestmark = pytest.mark.db


async def test_all_stages_pass_on_mock(db_session):
    from app.llm.mock_provider import MockProvider

    llm = MockProvider()
    problems = []
    for stage in STAGES:
        if not stage.prompts:
            continue
        for report in await run_stage(db_session, llm, stage, source="test"):
            problems += [f"{stage.id}: {p}" for p in report["problems"]]
    assert not problems, problems
