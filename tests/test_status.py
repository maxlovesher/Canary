import json
import os

from canary.cli import EXIT_OK, main
from canary.status import format_status, scan_runs


def make_run(root, name, status, n_cases, done, age_s, now):
    run = root / name
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({"status": status, "n_cases": n_cases}), encoding="utf-8")
    (run / "results.jsonl").write_text("".join("{}\n" for _ in range(done)), encoding="utf-8")
    for f in run.iterdir():
        os.utime(f, (now - age_s, now - age_s))


def test_scan_detects_progress_and_stale_runs(tmp_path):
    now = 1_000_000.0
    make_run(tmp_path, "20261001T000000Z_done_aaa", "completed", 6, 6, 9000, now)
    make_run(tmp_path, "20261002T000000Z_live_bbb", "running", 100, 37, 30, now)
    make_run(tmp_path, "20261003T000000Z_dead_ccc", "running", 100, 20, 86400 * 10, now)
    (tmp_path / "_logs").mkdir()  # helper folders are ignored
    statuses = {s.run_id.split("_")[1]: s for s in scan_runs(tmp_path, now=now)}
    assert set(statuses) == {"done", "live", "dead"}
    assert statuses["live"].status == "running" and (statuses["live"].done, statuses["live"].total) == (37, 100)
    assert statuses["dead"].status == "stale"
    assert statuses["done"].status == "completed"
    table = format_status(list(statuses.values()))
    assert "37/100" in table and "stale" in table and "10d" in table


def test_format_limit_keeps_active_runs(tmp_path):
    now = 1_000_000.0
    for i in range(5):
        make_run(tmp_path, f"2026100{i}T000000Z_old{i}_x", "completed", 1, 1, 9000, now)
    make_run(tmp_path, "20261009T000000Z_live_y", "running", 10, 2, 5, now)
    table = format_status(scan_runs(tmp_path, now=now), limit=2)
    assert "live" in table and "old4" in table and "old0" not in table
    assert "4 older runs hidden" in table


def test_cli_status(config_dict, write_config, tmp_path, capsys):
    assert main(["run", str(write_config(config_dict))]) == EXIT_OK
    capsys.readouterr()
    assert main(["status", "--runs-dir", str(tmp_path / "runs")]) == EXIT_OK
    out = capsys.readouterr().out
    assert "completed" in out and "6/6" in out
