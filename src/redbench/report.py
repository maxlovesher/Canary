"""Static HTML report (``redbench report``): one self-contained page, poster-style.

Reads only aggregate files (``manifest.json``, ``metrics.json``, ``agreement.json``,
``tradeoff.json``), never prompts or responses, so the output is safe to publish.
No JavaScript, no dependencies; fonts come from Google Fonts with system fallbacks.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

from redbench import __version__

logger = logging.getLogger(__name__)

# Chinese names for JailbreakBench categories (shown above the English name).
CATEGORY_ZH = {
    "Disinformation": "虚假信息",
    "Economic harm": "经济危害",
    "Expert advice": "专业建议",
    "Fraud/Deception": "欺诈",
    "Government decision-making": "政府决策",
    "Harassment/Discrimination": "骚扰歧视",
    "Malware/Hacking": "恶意软件",
    "Physical harm": "人身伤害",
    "Privacy": "隐私",
    "Sexual/Adult content": "成人内容",
}


@dataclass(frozen=True)
class RunInfo:
    """Aggregate view of one completed run directory."""

    path: Path
    manifest: dict[str, Any]
    metrics: dict[str, Any]
    agreement: dict[str, Any] | None

    @property
    def run_id(self) -> str:
        return str(self.manifest.get("run_id", self.path.name))

    @property
    def started_at(self) -> str:
        return str(self.manifest.get("started_at", ""))

    @property
    def target(self) -> dict[str, Any]:
        return dict(self.manifest.get("target", {}))

    @property
    def model(self) -> str:
        return str(self.target.get("model", "?"))

    @property
    def defenses(self) -> list[str]:
        return [str(d.get("type", "?")) for d in self.target.get("defenses", [])]

    @property
    def dataset(self) -> dict[str, Any]:
        sources = self.manifest.get("attack_sources") or [{}]
        return dict(sources[0])

    @property
    def n_results(self) -> int:
        return int(self.metrics.get("asr", {}).get("n_results", 0))


def load_runs(runs_dir: Path, *, min_cases: int = 10) -> list[RunInfo]:
    """Completed runs with at least ``min_cases`` results, newest first, one per config hash."""
    runs: dict[str, RunInfo] = {}
    for path in sorted(runs_dir.iterdir()) if runs_dir.is_dir() else []:
        manifest_path, metrics_path = path / "manifest.json", path / "metrics.json"
        if not (manifest_path.is_file() and metrics_path.is_file()):
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            agreement_path = path / "agreement.json"
            agreement = json.loads(agreement_path.read_text(encoding="utf-8")) if agreement_path.is_file() else None
        except (OSError, ValueError) as exc:
            logger.warning("skipping %s: %s", path, exc)
            continue
        run = RunInfo(path, manifest, metrics, agreement)
        if manifest.get("status") != "completed" or run.n_results < min_cases:
            continue
        key = str(manifest.get("config_hash", path.name))
        if key not in runs or run.started_at > runs[key].started_at:
            runs[key] = run
    return sorted(runs.values(), key=lambda r: r.started_at, reverse=True)


def pick_featured(runs: list[RunInfo]) -> RunInfo | None:
    """Newest undefended run on harmful prompts (else the newest run)."""
    for run in runs:
        if not run.defenses and "harmful" in str(run.dataset.get("path", "")):
            return run
    return runs[0] if runs else None


def judge_rows(featured: RunInfo, runs: list[RunInfo]) -> list[dict[str, Any]]:
    """Every judge that scored the featured run's exact responses (same target + dataset)."""
    rows = [
        {
            "judge": featured.manifest.get("judge", {}).get("type", "primary"),
            "definition": featured.metrics.get("success_definition", "?"),
            "asr": featured.metrics["asr"]["overall"],
            "role": "primary",
        }
    ]
    seen = {rows[0]["judge"]}
    for run in runs:
        same_target = run.target.get("model_digest") == featured.target.get("model_digest") and {
            k: v for k, v in run.target.items() if k != "defenses"
        } == {k: v for k, v in featured.target.items() if k != "defenses"}
        if not same_target or run.defenses or run.dataset.get("sha256") != featured.dataset.get("sha256"):
            continue
        for name, secondary in run.metrics.get("secondary_asr", {}).items():
            if name not in seen:
                seen.add(name)
                rows.append(
                    {
                        "judge": name,
                        "definition": secondary["success_definition"],
                        "asr": secondary["asr"]["overall"],
                        "role": "secondary",
                    }
                )
    return rows


def load_tradeoffs(paths: list[Path]) -> list[dict[str, Any]]:
    """Tradeoff reports that exist and parse."""
    reports = []
    for path in paths:
        try:
            reports.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            logger.warning("skipping tradeoff report %s: %s", path, exc)
    return reports


# -- rendering ------------------------------------------------------------------


def _pct(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _ci(rate: dict[str, Any]) -> str:
    if rate.get("rate") is None:
        return "no judged cases"
    return f"95% CI {_pct(rate['ci95_low'])} – {_pct(rate['ci95_high'])}"


def _bars(by_category: dict[str, dict[str, Any]]) -> str:
    peak = max([r["ci95_high"] for r in by_category.values() if r.get("ci95_high") is not None] + [0.1])
    scale = min(1.0, peak * 1.1)
    rows = []
    for category, rate in by_category.items():
        zh = CATEGORY_ZH.get(category, "")
        if rate["rate"] is None:
            continue
        fill = 100 * rate["rate"] / scale
        lo, hi = 100 * rate["ci95_low"] / scale, 100 * rate["ci95_high"] / scale
        rows.append(
            f'<div class="bar-row"><div class="bar-label"><span class="zh" lang="zh">{escape(zh)}</span>'
            f"{escape(category)}</div>"
            f'<div class="bar-track" role="img" aria-label="{escape(category)}: {_pct(rate["rate"])}">'
            f'<div class="bar-ci" style="left:{lo:.1f}%;width:{max(hi - lo, 0.5):.1f}%"></div>'
            f'<div class="bar-fill" style="width:{fill:.1f}%"></div></div>'
            f'<div class="bar-value">{_pct(rate["rate"], 0)}<small>{rate["successes"]}/{rate["n"]}</small></div></div>'
        )
    return "\n".join(rows) + f'<p class="axis-note">Bar scale 0 – {_pct(scale, 0)}. Shaded band: Wilson 95% CI.</p>'


def _scatter(report: dict[str, Any]) -> str:
    conditions = [
        c for c in report["conditions"] if c["asr"]["rate"] is not None and c["false_refusal"]["rate"] is not None
    ]
    if not conditions:
        return ""
    w, h, left, right, top, bottom = 640, 380, 64, 24, 20, 56
    pw, ph = w - left - right, h - top - bottom

    def axis(values: list[float]) -> float:
        return min(1.0, max(0.1, math.ceil(max(values) * 1.1 * 20) / 20))

    xm = axis([c["false_refusal"]["ci95_high"] for c in conditions])
    ym = axis([c["asr"]["ci95_high"] for c in conditions])

    def sx(v: float) -> float:
        return left + pw * v / xm

    def sy(v: float) -> float:
        return top + ph * (1 - v / ym)

    parts = [f'<svg viewBox="0 0 {w} {h}" class="scatter" role="img" aria-label="Security versus utility scatter">']
    for i in range(6):
        fx, fy = xm * i / 5, ym * i / 5
        parts.append(f'<line x1="{sx(fx):.1f}" y1="{top}" x2="{sx(fx):.1f}" y2="{top + ph}" class="grid"/>')
        parts.append(f'<line x1="{left}" y1="{sy(fy):.1f}" x2="{left + pw}" y2="{sy(fy):.1f}" class="grid"/>')
        parts.append(
            f'<text x="{sx(fx):.1f}" y="{top + ph + 18}" class="tick" text-anchor="middle">{_pct(fx, 0)}</text>'
        )
        parts.append(f'<text x="{left - 8}" y="{sy(fy) + 4:.1f}" class="tick" text-anchor="end">{_pct(fy, 0)}</text>')
    parts.append(
        f'<text x="{left + pw / 2:.1f}" y="{h - 12}" class="axis-label" text-anchor="middle">'
        "False refusal rate on benign requests →</text>"
        f'<text transform="translate(16 {top + ph / 2:.1f}) rotate(-90)" class="axis-label" '
        'text-anchor="middle">Attack success rate →</text>'
    )
    for c in conditions:
        x, y = c["false_refusal"], c["asr"]
        cx, cy = sx(x["rate"]), sy(y["rate"])
        parts += [
            f'<line x1="{sx(x["ci95_low"]):.1f}" y1="{cy:.1f}" x2="{sx(x["ci95_high"]):.1f}" y2="{cy:.1f}" class="whisker"/>',
            f'<line x1="{cx:.1f}" y1="{sy(y["ci95_low"]):.1f}" x2="{cx:.1f}" y2="{sy(y["ci95_high"]):.1f}" class="whisker"/>',
            f'<rect x="{cx - 6:.1f}" y="{cy - 6:.1f}" width="12" height="12" class="seal-dot"/>',
            f'<text x="{cx + 10:.1f}" y="{cy - 8:.1f}" class="point-label">{escape(c["label"])}</text>',
        ]
    parts.append("</svg>")
    return "".join(parts)


def _agreement_line(scores: dict[str, Any]) -> str:
    kappa = scores.get("cohen_kappa")
    kappa_text = "—" if kappa is None else f"{kappa:.2f}"
    return f"accuracy {_pct(scores.get('accuracy'))}, Cohen's κ {kappa_text} (n = {scores.get('n', 0)})"


def _section(glyph: str, title: str, subtitle: str, body: str) -> str:
    return (
        f'<section class="section"><div class="glyph" lang="zh" aria-hidden="true">{glyph}</div>'
        f'<div class="section-body"><h2>{escape(title)}</h2><p class="lede">{escape(subtitle)}</p>{body}</div></section>'
    )


def build_report_html(runs: list[RunInfo], tradeoffs: list[dict[str, Any]], *, generated_at: str | None = None) -> str:
    """Render the whole report page."""
    generated_at = generated_at or datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    featured = pick_featured(runs)
    sections: list[str] = []

    if featured is not None:
        asr = featured.metrics["asr"]
        perf = featured.metrics.get("performance", {})
        latency = (perf.get("latency_ms") or {}).get("p50")
        headline = (
            '<div class="headline">'
            f'<div class="big-number">{_pct(asr["overall"]["rate"])}</div>'
            f'<div class="headline-meta"><div class="tag">{escape(featured.metrics.get("success_definition", ""))}</div>'
            f"<div>{_ci(asr['overall'])}</div>"
            f"<div>{asr['overall']['successes']} of {asr['overall']['n']} attacks · model "
            f"<b>{escape(featured.model)}</b></div>"
            f"<div>median latency {('—' if latency is None else f'{latency / 1000:.1f} s')} per attack</div></div></div>"
        )
        sections.append(
            _section(
                "攻",
                "Attack",
                f"Headline run {featured.run_id}: JailbreakBench requests sent verbatim, no jailbreak transforms.",
                headline + f'<div class="bars">{_bars(asr["by_category"])}</div>',
            )
        )
        rows = judge_rows(featured, runs)
        table = "".join(
            f"<tr><td><b>{escape(r['judge'])}</b><span class='role'>{r['role']}</span></td>"
            f"<td>{escape(r['definition'])}</td><td class='num'>{_pct(r['asr']['rate'])}</td>"
            f"<td class='num muted'>{_ci(r['asr'])}</td></tr>"
            for r in rows
        )
        agreement = ""
        if featured.agreement:
            agreement = "<h3>Agreement with human labels</h3>" + "".join(
                f"<p><b>{escape(name)}</b>: {_agreement_line(scores['vs_harmful_compliance'])}</p>"
                for name, scores in featured.agreement.get("judges", {}).items()
            )
        else:
            agreement = (
                '<p class="callout">Not yet validated: no human labels for this run. '
                "Same responses, different judges, different answers. Human labels decide which to trust.</p>"
            )
        sections.append(
            _section(
                "判",
                "Judges",
                "Every judge that scored the headline run's exact responses.",
                f'<table class="judges"><thead><tr><th>Judge</th><th>Success means</th><th>ASR</th><th></th></tr>'
                f"</thead><tbody>{table}</tbody></table>{agreement}",
            )
        )

    for report in tradeoffs:
        rows_html = "".join(
            f"<tr><td><b>{escape(c['label'])}</b></td><td class='num'>{_pct(c['asr']['rate'])}</td>"
            f"<td class='num'>{_pct(c['false_refusal']['rate'])}</td>"
            f"<td class='num muted'>{c['blocked']['harmful']} / {c['blocked']['benign']}</td></tr>"
            for c in report["conditions"]
        )
        sections.append(
            _section(
                "守",
                "Defense",
                "Security against utility. Lower-left is better; whiskers are 95% CIs.",
                f'<div class="chart">{_scatter(report)}</div>'
                '<table class="judges"><thead><tr><th>Condition</th><th>ASR</th><th>False refusals</th>'
                f"<th>Blocked (harmful / benign)</th></tr></thead><tbody>{rows_html}</tbody></table>",
            )
        )

    if runs:
        run_rows = "".join(
            f"<tr><td><code>{escape(r.run_id)}</code></td><td>{escape(r.model)}</td>"
            f"<td>{escape(', '.join(r.defenses) or 'none')}</td>"
            f"<td class='num'>{r.n_results}</td><td class='num'>{_pct(r.metrics['asr']['overall']['rate'])}</td>"
            f"<td><code>{escape(str(r.manifest.get('config_hash', '')))}</code></td></tr>"
            for r in runs
        )
        sections.append(
            _section(
                "源",
                "Provenance",
                "Every completed run. Each is reproducible from its config hash and the response cache.",
                '<div class="table-scroll"><table class="runs"><thead><tr><th>Run</th><th>Model</th><th>Defenses</th>'
                f"<th>n</th><th>ASR</th><th>Config</th></tr></thead><tbody>{run_rows}</tbody></table></div>",
            )
        )
    else:
        sections.append(_section("空", "No runs yet", "Run `redbench run <config>` and regenerate this report.", ""))

    n_cases = sum(r.n_results for r in runs)
    models = sorted({r.model for r in runs})
    stats = (
        f'<div class="stat"><b>{len(runs)}</b><span>runs</span></div>'
        f'<div class="stat"><b>{n_cases}</b><span>attacks judged</span></div>'
        f'<div class="stat"><b>{len(models)}</b><span>target models</span></div>'
        f'<div class="stat"><b>{len(tradeoffs)}</b><span>defense studies</span></div>'
    )
    return PAGE.format(
        css=CSS,
        stats=stats,
        sections="\n".join(sections),
        generated_at=escape(generated_at),
        version=escape(__version__),
    )


CSS = """
:root{--paper:#f3ece0;--card:#faf6ee;--ink:#17130f;--muted:#6e6357;--rule:#d9cdbb;--red:#c62a1f;--red-ink:#fff6ef;--band:#efc9bf}
@media (prefers-color-scheme:dark){:root{--paper:#120f0d;--card:#1b1714;--ink:#f2eadf;--muted:#a7998a;--rule:#332c26;--red:#e4493b;--red-ink:#1a0d0b;--band:#5a2621}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:"Noto Sans SC","Microsoft YaHei","PingFang SC",system-ui,sans-serif;line-height:1.5}
.zh,.glyph,.hero-zh,.big-number,.seal{font-family:"Noto Serif SC","Source Han Serif SC","Songti SC","SimSun",serif}
.wrap{max-width:1080px;margin:0 auto;padding:0 20px}
.hero{border-bottom:6px solid var(--ink);padding:48px 0 32px;display:grid;grid-template-columns:auto 1fr;gap:12px 32px;align-items:end}
.hero-zh{font-size:clamp(96px,21vw,240px);font-weight:900;line-height:.82;color:var(--red);letter-spacing:-.04em;margin:0}
.hero-side{display:flex;flex-direction:column;gap:14px;padding-bottom:10px}
.seal{width:88px;height:88px;background:var(--red);color:var(--red-ink);display:grid;place-items:center;font-weight:900;font-size:30px;line-height:1.05;writing-mode:vertical-rl;border-radius:6px;transform:rotate(-4deg);box-shadow:inset 0 0 0 4px var(--red),inset 0 0 0 6px var(--red-ink)}
.brand{font-weight:900;letter-spacing:.32em;font-size:22px}
.tagline{color:var(--muted);max-width:42ch}
.stats{display:flex;flex-wrap:wrap;gap:0;margin:0 0 8px;border-bottom:1px solid var(--rule)}
.stat{padding:18px 28px 18px 0;margin-right:28px;border-right:1px solid var(--rule)}
.stat:last-child{border-right:0}
.stat b{display:block;font-size:34px;font-weight:900;line-height:1}
.stat span{color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.12em}
.section{display:grid;grid-template-columns:160px 1fr;gap:24px;padding:48px 0;border-bottom:1px solid var(--rule)}
.glyph{font-size:clamp(88px,13vw,150px);font-weight:900;line-height:.85;color:var(--ink)}
.section:nth-of-type(odd) .glyph{color:var(--red)}
h2{font-size:30px;font-weight:900;margin:0 0 4px;letter-spacing:.02em}
h3{font-size:18px;margin:28px 0 8px}
.lede{color:var(--muted);margin:0 0 24px}
.headline{display:flex;flex-wrap:wrap;align-items:flex-end;gap:12px 28px;margin-bottom:28px}
.big-number{font-size:clamp(72px,12vw,128px);font-weight:900;line-height:.9;color:var(--red)}
.headline-meta{display:flex;flex-direction:column;gap:2px;padding-bottom:8px}
.tag{display:inline-block;align-self:flex-start;background:var(--ink);color:var(--paper);font-size:12px;font-weight:700;letter-spacing:.08em;padding:2px 8px;border-radius:3px;margin-bottom:4px}
.bar-row{display:grid;grid-template-columns:minmax(120px,210px) 1fr 64px;gap:14px;align-items:center;padding:7px 0;border-top:1px solid var(--rule)}
.bar-label{font-size:14px;line-height:1.2}
.bar-label .zh{display:block;font-weight:900;font-size:17px}
.bar-track{position:relative;height:18px;background:var(--card);border:1px solid var(--rule)}
.bar-ci{position:absolute;top:0;bottom:0;background:var(--band)}
.bar-fill{position:absolute;top:4px;bottom:4px;left:0;background:var(--red)}
.bar-value{font-weight:900;font-size:18px;text-align:right;line-height:1}
.bar-value small{display:block;font-weight:400;font-size:11px;color:var(--muted)}
.axis-note{font-size:12px;color:var(--muted);margin-top:10px}
table{width:100%;border-collapse:collapse;font-size:15px}
th{text-align:left;font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);border-bottom:2px solid var(--ink);padding:8px 10px 8px 0}
td{border-bottom:1px solid var(--rule);padding:10px 10px 10px 0;vertical-align:top}
td.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.muted{color:var(--muted);font-size:13px}
.role{display:block;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em}
.callout{border-left:6px solid var(--red);background:var(--card);padding:12px 16px;margin-top:20px}
.table-scroll{overflow-x:auto}
code{font-size:12px}
.chart{background:var(--card);border:1px solid var(--rule);padding:12px;margin-bottom:20px}
.scatter{width:100%;height:auto;display:block}
.scatter .grid{stroke:var(--rule)}
.scatter .tick{fill:var(--muted);font-size:11px}
.scatter .axis-label{fill:var(--ink);font-size:12px;font-weight:700}
.scatter .whisker{stroke:var(--red);stroke-opacity:.45;stroke-width:2}
.scatter .seal-dot{fill:var(--red)}
.scatter .point-label{fill:var(--ink);font-size:12px;font-weight:700}
footer{padding:32px 0 56px;color:var(--muted);font-size:13px;display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}
footer .zh{font-weight:900;color:var(--ink)}
@media (max-width:720px){
.hero{grid-template-columns:1fr}
.section{grid-template-columns:1fr;gap:4px;padding:36px 0}
.glyph{font-size:84px}
.bar-row{grid-template-columns:1fr 56px}
.bar-track{grid-column:1 / -1;grid-row:2}
.stat{padding:14px 18px 14px 0;margin-right:18px}
}
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RedBench Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;700;900&family=Noto+Serif+SC:wght@900&display=swap" rel="stylesheet">
<style>{css}</style>
</head>
<body>
<div class="wrap">
<header class="hero">
<h1 class="hero-zh" lang="zh">红队</h1>
<div class="hero-side">
<div class="seal" lang="zh" aria-hidden="true">红队<br>基准</div>
<div class="brand">REDBENCH</div>
<div class="tagline">Automated red-teaming of LLM systems. Every number on this page is measured from a
local run; prompts and responses never leave the machine.</div>
</div>
</header>
<div class="stats">{stats}</div>
{sections}
<footer><span><span class="zh" lang="zh">仅聚合数据</span> · aggregate numbers only, no prompts or responses</span>
<span>generated {generated_at} · redbench {version}</span></footer>
</div>
</body>
</html>
"""
