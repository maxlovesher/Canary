"""Static HTML report: run discovery, judge grouping, rendering, CLI."""

import json
from html.parser import HTMLParser

from redbench.cli import EXIT_OK, main
from redbench.report import build_report_html, judge_rows, load_runs, pick_featured
from redbench.tradeoff import build_report, summarize_condition
from tests.test_tradeoff import results


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)

    def handle_data(self, data):
        self.text.append(data)


def parse(page: str) -> _Collector:
    collector = _Collector()
    collector.feed(page)
    return collector


def make_runs(config_dict, write_config, tmp_path, *extra_args):
    assert main(["run", str(write_config(config_dict)), *extra_args]) == EXIT_OK


def test_load_runs_filters_small_and_incomplete(config_dict, write_config, tmp_path):
    make_runs(config_dict, write_config, tmp_path)
    make_runs(config_dict, write_config, tmp_path, "--set", "run.max_cases=2", "--set", "run.name=smoke")
    runs_dir = tmp_path / "runs"
    (runs_dir / "broken").mkdir()
    (runs_dir / "broken" / "manifest.json").write_text("{not json", encoding="utf-8")
    (runs_dir / "broken" / "metrics.json").write_text("{}", encoding="utf-8")
    assert [r.n_results for r in load_runs(runs_dir, min_cases=5)] == [6]
    assert len(load_runs(runs_dir, min_cases=1)) == 2


def test_judges_grouped_across_runs_of_the_same_responses(config_dict, write_config, tmp_path):
    make_runs(config_dict, write_config, tmp_path)
    runs = load_runs(tmp_path / "runs", min_cases=1)
    featured = pick_featured(runs) or runs[0]
    rows = judge_rows(featured, runs)
    assert rows[0]["role"] == "primary" and rows[0]["judge"] == "refusal_patterns"


def test_page_renders_sections_and_escapes(config_dict, write_config, tmp_path):
    make_runs(config_dict, write_config, tmp_path)
    runs = load_runs(tmp_path / "runs", min_cases=1)
    tradeoff = build_report(
        [summarize_condition("<filter>", results([True, False]), results([True, True], prefix="b"))], judge=None
    )
    page = build_report_html(runs, [tradeoff], generated_at="2026-10-03 00:00 UTC")
    parsed = parse(page)
    text = " ".join(parsed.text)
    for heading in ("Attack", "Judges", "Defense", "Provenance"):
        assert heading in text
    assert "红队" in text and "仅聚合数据" in text
    assert "&lt;filter&gt;" in page and "<filter>" not in page
    assert "svg" in parsed.tags and "script" not in parsed.tags  # static, no JS
    assert "placeholder" not in page.lower()  # never includes prompts or responses


def test_empty_runs_dir_renders_placeholder_section(tmp_path):
    page = build_report_html(load_runs(tmp_path / "nothing"), [])
    assert "No runs yet" in page


def test_cli_report(config_dict, write_config, tmp_path):
    make_runs(config_dict, write_config, tmp_path)
    tradeoff_path = tmp_path / "t.json"
    tradeoff_path.write_text(
        json.dumps(build_report([summarize_condition("none", results([True]), results([True]))], judge=None)),
        encoding="utf-8",
    )
    out = tmp_path / "site" / "index.html"
    args = ["report", "--runs-dir", str(tmp_path / "runs"), "--tradeoff", str(tradeoff_path)]
    assert main([*args, "--min-cases", "1", "--out", str(out)]) == EXIT_OK
    page = out.read_text(encoding="utf-8")
    assert "Security against utility" in page and "test-run" in page
