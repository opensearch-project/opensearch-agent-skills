"""Self-contained HTML report renderer.

Renders the benchmark results as a single portable HTML file: per-mode
measurement tables, the recommended configs, flagged regressions, and a
lightweight inline-SVG Pareto scatter (quality vs footprint). No external JS/CSS
— it opens anywhere, which matters for the vendor-neutral/portability story.

Also provides a plain-text summary for the terminal/agent transcript.
"""

from __future__ import annotations

import html
import json
from dataclasses import asdict
from typing import Iterable

from model import Measurement, Metric, Mode


def _fmt_bytes(n: int | None) -> str:
    if n is None:
        return "n/a"
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            return f"{f:.1f} {u}"
        f /= 1024
    return f"{n} B"


def _quality_str(m: Measurement, metric: Metric, k: int) -> str:
    v = m.quality.get(metric, k)
    return f"{v:.3f}" if v is not None else "—"


def _metric_for(metric: "Metric | dict[Mode, Metric]", mode: Mode) -> Metric:
    """Accept either a single metric or a per-mode mapping (default RECALL)."""
    if isinstance(metric, dict):
        return metric.get(mode, Metric.RECALL)
    return metric


def text_summary(
    results: dict[Mode, list[Measurement]],
    recommendations: dict[Mode, list[Measurement]],
    metric: "Metric | dict[Mode, Metric]",
    k: int,
) -> str:
    """A compact, terminal-friendly summary for the agent transcript.

    `metric` may be a single Metric (used for all modes) or a per-mode mapping
    so each mode is displayed on the metric it was actually ranked by.
    """
    lines: list[str] = []
    lines.append("=" * 66)
    lines.append("ai-search-tuner — results")
    lines.append("=" * 66)
    for mode, ms in results.items():
        if not ms:
            continue
        metric_m = _metric_for(metric, mode)
        ref = ms[0].quality.reference or "?"
        mlabel = metric_m.value  # recall / ndcg / map
        lines.append(f"\n[{mode.value}]  (quality reference: {ref})")
        lines.append(
            f"  {'config':<32}{mlabel+'@'+str(k):>10}{'p95 ms':>10}{'footprint':>12}  flags"
        )
        for m in ms:
            flags = ",".join(m.flags) if m.flags else ""
            lines.append(
                f"  {m.config.label:<32}"
                f"{_quality_str(m, metric_m, k):>10}"
                f"{m.latency_p95_ms:>10.1f}"
                f"{_fmt_bytes(m.cost.primary_bytes()):>12}  {flags}"
            )
        recs = recommendations.get(mode, [])
        if recs:
            best = recs[0]
            note = ""
            if "silent-quality-drop" in best.flags:
                note = "  [best within your constraints; quality below the unconstrained best]"
            lines.append(
                f"  → recommended: {best.config.label} "
                f"({mlabel}@{k}={_quality_str(best, metric_m, k)}, "
                f"p95={best.latency_p95_ms:.1f}ms, "
                f"footprint={_fmt_bytes(best.cost.primary_bytes())}){note}"
            )
    lines.append("")
    return "\n".join(lines)


def _svg_scatter(ms: list[Measurement], metric: Metric, k: int, recommended: set[str]) -> str:
    """A minimal quality(x) vs footprint(y) scatter as inline SVG.

    Points with no footprint are omitted from the scatter (shown only in table).
    """
    pts = []
    for m in ms:
        q = m.quality.get(metric, k)
        fp = m.cost.primary_bytes()
        if q is None or fp is None:
            continue
        pts.append((q, fp, m.config.label))
    if not pts:
        return "<p><em>No footprint data to plot (shown in table only).</em></p>"

    W, H, pad = 460, 300, 48
    qs = [p[0] for p in pts]
    fps = [p[1] for p in pts]
    qmin, qmax = min(qs), max(qs)
    fmin, fmax = min(fps), max(fps)
    qrange = (qmax - qmin) or 1.0
    frange = (fmax - fmin) or 1.0

    def sx(q):
        return pad + (q - qmin) / qrange * (W - 2 * pad)

    def sy(f):  # invert: lower footprint = higher on chart (better)
        return H - pad - (f - fmin) / frange * (H - 2 * pad)

    dots = []
    for q, f, label in pts:
        color = "#2563eb" if label in recommended else "#94a3b8"
        r = 6 if label in recommended else 4
        dots.append(
            f'<circle cx="{sx(q):.1f}" cy="{sy(f):.1f}" r="{r}" fill="{color}">'
            f'<title>{html.escape(label)}: qual@{k}={q:.3f}, {_fmt_bytes(f)}</title></circle>'
        )
    axis = (
        f'<line x1="{pad}" y1="{H-pad}" x2="{W-pad}" y2="{H-pad}" stroke="#cbd5e1"/>'
        f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{H-pad}" stroke="#cbd5e1"/>'
        f'<text x="{W/2}" y="{H-12}" text-anchor="middle" font-size="12" fill="#475569">quality@{k} →</text>'
        f'<text x="14" y="{H/2}" text-anchor="middle" font-size="12" fill="#475569" '
        f'transform="rotate(-90 14 {H/2})">← smaller footprint (better)</text>'
    )
    return f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}">{axis}{"".join(dots)}</svg>'


def render_html(
    results: dict[Mode, list[Measurement]],
    recommendations: dict[Mode, list[Measurement]],
    metric: "Metric | dict[Mode, Metric]",
    k: int,
    meta: dict | None = None,
) -> str:
    """Render a single self-contained HTML file (string).

    `metric` may be a single Metric or a per-mode mapping so each mode is
    displayed on the metric it was ranked by.
    """
    meta = meta or {}
    parts: list[str] = []
    parts.append(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>ai-search-tuner report</title><style>"
        "body{font:14px/1.5 system-ui,sans-serif;margin:2rem;color:#0f172a;max-width:920px}"
        "h1{font-size:1.4rem}h2{font-size:1.1rem;margin-top:2rem;border-bottom:1px solid #e2e8f0;padding-bottom:.3rem}"
        "table{border-collapse:collapse;width:100%;margin:.6rem 0}"
        "th,td{text-align:left;padding:.35rem .6rem;border-bottom:1px solid #f1f5f9;font-variant-numeric:tabular-nums}"
        "th{color:#475569;font-weight:600}"
        ".rec{background:#eff6ff}.flag{color:#b91c1c;font-weight:600}"
        ".ref{color:#64748b;font-size:.85rem}"
        ".pill{background:#dbeafe;color:#1e40af;padding:.1rem .5rem;border-radius:.5rem;font-size:.8rem}"
        "</style></head><body>"
    )
    parts.append("<h1>ai-search-tuner — retrieval quality/cost report</h1>")
    if meta:
        parts.append(
            "<p class='ref'>"
            + " · ".join(f"{html.escape(str(kk))}: {html.escape(str(vv))}" for kk, vv in meta.items())
            + "</p>"
        )

    for mode, ms in results.items():
        if not ms:
            continue
        recs = recommendations.get(mode, [])
        rec_labels = {m.config.label for m in recs}
        metric_m = _metric_for(metric, mode)
        mlabel = metric_m.value
        ref = ms[0].quality.reference or "?"
        parts.append(f"<h2>{html.escape(mode.value)}</h2>")
        parts.append(f"<p class='ref'>quality reference: <span class='pill'>{html.escape(ref)}</span>")
        if not mode.is_approximate:
            parts.append(
                " — <em>exact Lucene scoring; graded on relevance/overlap, not recall-vs-exact</em>"
            )
        parts.append("</p>")
        parts.append(_svg_scatter(ms, metric_m, k, rec_labels))
        parts.append(
            f"<table><tr><th>config</th><th>{html.escape(mlabel)}@{k}</th><th>p50 ms</th>"
            "<th>p95 ms</th><th>footprint</th><th>flags</th></tr>"
        )
        for m in ms:
            cls = " class='rec'" if m.config.label in rec_labels else ""
            flags = (
                f"<span class='flag'>{html.escape(', '.join(m.flags))}</span>" if m.flags else ""
            )
            parts.append(
                f"<tr{cls}><td>{html.escape(m.config.label)}</td>"
                f"<td>{_quality_str(m, metric_m, k)}</td>"
                f"<td>{m.latency_p50_ms:.1f}</td>"
                f"<td>{m.latency_p95_ms:.1f}</td>"
                f"<td>{_fmt_bytes(m.cost.primary_bytes())}</td>"
                f"<td>{flags}</td></tr>"
            )
        parts.append("</table>")
        if recs:
            b = recs[0]
            note = ""
            if "silent-quality-drop" in b.flags:
                note = (
                    " <span class='ref'>— best within your constraints; quality is "
                    "below the unconstrained best (loosen the latency/footprint "
                    "budget to recover it)</span>"
                )
            parts.append(
                f"<p>→ <b>recommended:</b> <code>{html.escape(b.config.label)}</code> "
                f"({html.escape(mlabel)}@{k}={_quality_str(b, metric_m, k)}, p95={b.latency_p95_ms:.1f}ms, "
                f"footprint={_fmt_bytes(b.cost.primary_bytes())}){note}</p>"
            )
            parts.append("<details><summary>recommended config JSON</summary><pre>")
            parts.append(html.escape(json.dumps(b.config.as_dict(), indent=2, default=str)))
            parts.append("</pre></details>")

    parts.append("</body></html>")
    return "".join(parts)
