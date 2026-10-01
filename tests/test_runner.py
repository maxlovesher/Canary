import io

import pytest

from redbench.attacks.jailbreakbench import JailbreakBenchSource
from redbench.errors import DatasetError
from redbench.judges.refusal_patterns import RefusalPatternJudge
from redbench.records import AttackResult
from redbench.registry import BuildContext
from redbench.run_store import ResultWriter
from redbench.runner import Runner
from tests.helpers import JBB_SAMPLE, ScriptedTarget

CTX = BuildContext(seed=0)


def make_runner(max_cases=None, **target_params) -> tuple[Runner, ScriptedTarget]:
    target = ScriptedTarget(ScriptedTarget.Params(**target_params), CTX)
    source = JailbreakBenchSource(JailbreakBenchSource.Params(path=JBB_SAMPLE), CTX)
    judge = RefusalPatternJudge(RefusalPatternJudge.Params(), CTX)
    return Runner(target, [source], judge, max_cases=max_cases), target


def run_all(runner: Runner):
    buffer = io.StringIO()
    writer = ResultWriter(buffer)
    outcome = runner.run(runner.load_cases(), writer)
    lines = [AttackResult.model_validate_json(line) for line in buffer.getvalue().splitlines()]
    return outcome, lines


def test_runs_every_case_and_judges():
    runner, target = make_runner(replies={"jbb-2": "I'm sorry, I can't help with that."})
    outcome, lines = run_all(runner)
    assert target.calls == [f"jbb-{i}" for i in range(1, 7)]
    assert len(outcome.results) == 6 and lines == outcome.results
    by_id = {r.case.id: r for r in outcome.results}
    assert by_id["jbb-1"].verdict.success is True
    assert by_id["jbb-2"].verdict.success is False
    assert not outcome.interrupted


def test_target_error_is_recorded_unjudged_and_run_continues():
    runner, _ = make_runner(fail_ids=["jbb-3"])
    outcome, _ = run_all(runner)
    failed = next(r for r in outcome.results if r.case.id == "jbb-3")
    assert failed.response is None
    assert failed.verdict.success is None
    assert "scripted failure" in failed.error
    assert len(outcome.results) == 6


def test_max_cases_truncates():
    runner, target = make_runner(max_cases=2)
    outcome, _ = run_all(runner)
    assert target.calls == ["jbb-1", "jbb-2"]
    assert len(outcome.results) == 2


def test_interrupt_keeps_partial_results():
    runner, _ = make_runner(interrupt_ids=["jbb-4"])
    outcome, lines = run_all(runner)
    assert outcome.interrupted
    assert [r.case.id for r in lines] == ["jbb-1", "jbb-2", "jbb-3"]


def test_duplicate_ids_across_sources_rejected():
    target = ScriptedTarget(ScriptedTarget.Params(), CTX)
    source = JailbreakBenchSource(JailbreakBenchSource.Params(path=JBB_SAMPLE), CTX)
    judge = RefusalPatternJudge(RefusalPatternJudge.Params(), CTX)
    with pytest.raises(DatasetError, match="duplicate"):
        Runner(target, [source, source], judge).load_cases()
