"""Security-vs-utility comparison across defense conditions (``redbench tradeoff``).

Each condition pairs two runs made with the same target + defenses:

- a **harmful** run: ASR (lower = more secure), from the primary judge or a
  chosen secondary judge;
- a **benign** run: utility = share of benign requests answered (judged by the
  primary refusal judge, so a non-refusal counts as "useful"); the false refusal
  rate is its complement.

Outputs aggregate numbers only (no prompts or responses), so reports are safe to commit.
"""

from __future__ import annotations

import html
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from redbench.metrics.asr import RateSummary, attack_success_rate, primary_verdict, secondary_verdict
from redbench.metrics.stats import percentile
from redbench.records import AttackResult

PALETTE = ("#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#4b5563")


@dataclass(frozen=True)
class Condition:
    """One defense configuration: its label and the harmful + benign run directories."""

    label: str
    harmful_dir: Path
    benign_dir: Path


def summarize_condition(
    label: str,
    harmful: Sequence[AttackResult],
    benign: Sequence[AttackResult],
    *,
    judge: str | None = None,
) -> dict[str, Any]:
    """ASR, utility, false refusal rate, blocks and latency for one condition."""
    verdict_of = primary_verdict if judge is None else secondary_verdict(judge)
    asr = attack_success_rate(harmful, verdict_of)["overall"]
    utility = attack_success_rate(benign, primary_verdict)["overall"]
    false_refusal = (
        RateSummary.from_counts(utility["n"] - utility["successes"], utility["n"]).to_dict()
        if utility["n"]
        else RateSummary.from_counts(0, 0).to_dict()
    )
    return {
        "label": label,
        "asr": asr,
        "utility": utility,
        "false_refusal": false_refusal,
        "blocked": {
            "harmful": sum(1 for r in harmful if r.response is not None and r.response.blocked_by),
            "benign": sum(1 for r in benign if r.response is not None and r.response.blocked_by),
        },
        "latency_ms_p50": {
            "harmful": _p50(harmful),
            "benign": _p50(benign),
        },
    }


def _p50(results: Sequence[AttackResult]) -> float | None:
    latencies = [r.response.latency_ms for r in results if r.response is not None]
    return percentile(latencies, 50) if latencies else None


def build_report(conditions: Sequence[dict[str, Any]], *, judge: str | None) -> dict[str, Any]:
    """Wrap condition summaries with the definitions needed to read them."""
    return {
        "provenance": "measured",
        "asr_judge": judge or "primary",
        "utility_definition": "non-refusal rate on benign requests (primary judge)",
        "conditions": list(conditions),
    }


def format_table(report: dict[str, Any]) -> str:
    """Terminal table: one row per condition."""
    lines = [
        f"Security vs utility ({report['provenance']}; ASR judge: {report['asr_judge']})",
        f"{'condition':<24} {'ASR':>7} {'95% CI':>17} {'false refusal':>14} {'95% CI':>17} {'blocked h/b':>12}",
    ]
    for c in report["conditions"]:
        lines.append(
            f"{c['label'][:24]:<24} {_pct(c['asr']['rate']):>7} {_ci(c['asr']):>17} "
            f"{_pct(c['false_refusal']['rate']):>14} {_ci(c['false_refusal']):>17} "
            f"{c['blocked']['harmful']:>5}/{c['blocked']['benign']:<6}"
        )
    return "\n".join(lines)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _ci(rate: dict[str, Any]) -> str:
    if rate["rate"] is None:
        return "n/a"
    return f"[{rate['ci95_low']:.1%}, {rate['ci95_high']:.1%}]"


def render_svg(report: dict[str, Any]) -> str:
    """Scatter of ASR (y) vs false refusal rate (x) with 95% CI whiskers. Lower-left is better."""
    width, height = 720, 460
    left, right, top, bottom = 70, 200, 50, 60
    plot_w, plot_h = width - left - right, height - top - bottom
    conditions = [
        c for c in report["conditions"] if c["asr"]["rate"] is not None and c["false_refusal"]["rate"] is not None
    ]
    x_max = _axis_max([c["false_refusal"]["ci95_high"] for c in conditions])
    y_max = _axis_max([c["asr"]["ci95_high"] for c in conditions])

    def sx(v: float) -> float:
        return left + plot_w * v / x_max

    def sy(v: float) -> float:
        return top + plot_h * (1 - v / y_max)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="system-ui, sans-serif" font-size="12">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="{left}" y="24" font-size="15" font-weight="600" fill="#111827">Security vs utility</text>',
        f'<text x="{left}" y="40" fill="#6b7280">Lower-left is better. Whiskers: Wilson 95% CI. '
        f"ASR judge: {html.escape(report['asr_judge'])}</text>",
    ]
    for i in range(6):  # gridlines + tick labels
        fx, fy = x_max * i / 5, y_max * i / 5
        out.append(f'<line x1="{sx(fx):.1f}" y1="{top}" x2="{sx(fx):.1f}" y2="{top + plot_h}" stroke="#e5e7eb"/>')
        out.append(f'<line x1="{left}" y1="{sy(fy):.1f}" x2="{left + plot_w}" y2="{sy(fy):.1f}" stroke="#e5e7eb"/>')
        out.append(
            f'<text x="{sx(fx):.1f}" y="{top + plot_h + 16}" text-anchor="middle" fill="#6b7280">{fx:.0%}</text>'
        )
        out.append(f'<text x="{left - 8}" y="{sy(fy) + 4:.1f}" text-anchor="end" fill="#6b7280">{fy:.0%}</text>')
    out += [
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#9ca3af"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#9ca3af"/>',
        f'<text x="{left + plot_w / 2:.1f}" y="{height - 18}" text-anchor="middle" fill="#374151">'
        "False refusal rate on benign requests (utility cost)</text>",
        f'<text transform="translate(20 {top + plot_h / 2:.1f}) rotate(-90)" text-anchor="middle" fill="#374151">'
        "Attack success rate (ASR)</text>",
    ]
    for index, c in enumerate(conditions):
        color = PALETTE[index % len(PALETTE)]
        x, y = c["false_refusal"], c["asr"]
        cx, cy = sx(x["rate"]), sy(y["rate"])
        out += [
            f'<line x1="{sx(x["ci95_low"]):.1f}" y1="{cy:.1f}" x2="{sx(x["ci95_high"]):.1f}" y2="{cy:.1f}" '
            f'stroke="{color}" stroke-opacity="0.5"/>',
            f'<line x1="{cx:.1f}" y1="{sy(y["ci95_low"]):.1f}" x2="{cx:.1f}" y2="{sy(y["ci95_high"]):.1f}" '
            f'stroke="{color}" stroke-opacity="0.5"/>',
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" fill="{color}"/>',
            f'<circle cx="{left + plot_w + 24}" cy="{top + 10 + 20 * index}" r="5" fill="{color}"/>',
            f'<text x="{left + plot_w + 36}" y="{top + 14 + 20 * index}" fill="#111827">'
            f"{html.escape(c['label'])}</text>",
        ]
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _axis_max(values: Sequence[float]) -> float:
    """Round the largest value up to a tidy axis limit (at least 10%)."""
    peak = max(values, default=0.0)
    return min(1.0, max(0.1, math.ceil(peak * 1.1 * 20) / 20))
