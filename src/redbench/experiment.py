"""Run one experiment end to end: config -> components -> runner -> run directory."""

from __future__ import annotations

import logging
import platform
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from redbench import __version__
from redbench.cache import open_cache
from redbench.config import RedBenchConfig, config_hash, dump_config
from redbench.errors import RedBenchError
from redbench.factory import build_components
from redbench.judges.base import Judge
from redbench.logging_setup import add_file_handler, remove_handler
from redbench.metrics import compute_metrics
from redbench.run_store import RunStore
from redbench.runner import Runner

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunSummary:
    """What the caller needs after a run."""

    run_dir: Path
    metrics: dict[str, Any]
    interrupted: bool


def _describe_judge(judge: Judge) -> dict[str, Any]:
    describe = getattr(judge, "describe", None)
    if describe is not None:
        info: dict[str, Any] = describe()
        return info
    return {"type": judge.name, "success_definition": judge.success_definition}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def run_experiment(config: RedBenchConfig) -> RunSummary:
    """Execute ``config`` and write config, manifest, results and metrics to a new run dir."""
    cfg_hash = config_hash(config)
    store = RunStore.create(config.run.output_dir, config.run.name, cfg_hash)
    log_handler = add_file_handler(store.path(RunStore.LOG_FILE))
    logger.info("run %s started (config hash %s)", store.run_id, cfg_hash)
    try:
        store.write_text(RunStore.CONFIG_FILE, dump_config(config))
        with open_cache(config.run.cache) as cache:
            components = build_components(config, cache)
            try:
                runner = Runner(
                    components.target,
                    components.sources,
                    components.judge,
                    secondary_judges=components.secondary_judges,
                    max_cases=config.run.max_cases,
                )
                cases = runner.load_cases()
                manifest: dict[str, Any] = {
                    "run_id": store.run_id,
                    "status": "running",
                    "started_at": _now(),
                    "config_hash": cfg_hash,
                    "seed": config.run.seed,
                    "redbench_version": __version__,
                    "python": sys.version.split()[0],
                    "platform": platform.platform(),
                    "cache": {"mode": config.run.cache.mode, "path": str(config.run.cache.path)},
                    "target": components.target.describe(),  # fails fast if the backend is down
                    "attack_sources": [source.describe() for source in components.sources],
                    # describe() on model-backed judges also fails fast if their model is missing.
                    "judge": _describe_judge(components.judge),
                    "secondary_judges": [_describe_judge(judge) for judge in components.secondary_judges],
                    "n_cases": len(cases),
                }
                store.write_json(RunStore.MANIFEST_FILE, manifest)
                with store.result_writer() as writer:
                    outcome = runner.run(cases, writer)
            finally:
                components.close()
        metrics = compute_metrics(
            outcome.results,
            success_definition=components.judge.success_definition,
            pricing=config.pricing,
            secondary_definitions={judge.name: judge.success_definition for judge in components.secondary_judges},
        )
        store.write_json(RunStore.METRICS_FILE, metrics)
        manifest.update(
            status="interrupted" if outcome.interrupted else "completed",
            finished_at=_now(),
            n_results=len(outcome.results),
        )
        store.write_json(RunStore.MANIFEST_FILE, manifest)
        logger.info("run %s %s: %d results in %s", store.run_id, manifest["status"], len(outcome.results), store.root)
        return RunSummary(run_dir=store.root, metrics=metrics, interrupted=outcome.interrupted)
    except RedBenchError as exc:
        # Record expected failures in run.log before the file handler is detached.
        logger.error("run %s failed: %s", store.run_id, exc)
        raise
    except Exception:
        logger.exception("run %s crashed", store.run_id)
        raise
    finally:
        remove_handler(log_handler)
