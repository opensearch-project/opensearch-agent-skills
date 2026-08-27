"""Self-contained HTML report renderer.

Renders the benchmark results as a single portable HTML file: per-mode
measurement tables, the recommended configs, flagged regressions, and real
inline-SVG Pareto scatter plots (quality vs latency, quality vs footprint). No
external JS/CSS/CDN — it opens anywhere, which matters for the
vendor-neutral/portability story.

Also provides a plain-text summary for the terminal/agent transcript.

The chart palette/marks follow the shared data-viz system (light-mode reference
instance): a validated colorblind-safe categorical palette (blue = recommended,
aqua = Pareto frontier), hairline recessive grid/axes, ≥8px markers with a 2px
surface ring, and text drawn in ink tokens (never the series color).
"""

from __future__ import annotations

import html
import json
import math
from typing import Callable

from model import Measurement, Metric, Mode


# --- data-viz palette (light mode; see dataviz references/palette.md) ---------
_SURFACE = "#fcfcfb"  # chart surface
_INK = "#0b0b0b"      # primary ink
_INK2 = "#52514e"     # secondary ink
_MUTED = "#898781"    # axis / tick labels
_GRID = "#e1e0d9"     # hairline gridline
_AXIS = "#c3c2b7"     # baseline / axis
_REC = "#2a78d6"      # categorical slot 1 (blue) — recommended config
_OTHER = "#a8a6a0"    # muted gray — other configs
_FRONT = "#1baf7a"    # categorical slot 2 (aqua) — Pareto frontier
_FLOOR = "#52514e"    # secondary ink — quality-floor threshold (dashed)


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


# --- inline-SVG scatter -------------------------------------------------------

def _nice_ticks(lo: float, hi: float, target: int = 5) -> list[float]:
    """Round tick positions covering [lo, hi] (1/2/5 × 10ⁿ steps).

    Degrades gracefully: a zero/negative span returns the single value so the
    caller can still render one tick instead of dividing by zero.
    """
    if not (hi > lo):
        return [lo]
    raw = (hi - lo) / max(target, 1)
    mag = 10 ** math.floor(math.log10(raw))
    norm = raw / mag
    step = (1 if norm < 1.5 else 2 if norm < 3 else 5 if norm < 7 else 10) * mag
    start = math.ceil(lo / step) * step
    ticks: list[float] = []
    t = start
    for _ in range(1000):  # guard against float drift
        if t > hi + step * 1e-9:
            break
        ticks.append(t)
        t += step
    return ticks or [lo, hi]


# One plotted point: (x, y, label, is_recommended, footprint_bytes, quality, p95_latency)
_Point = tuple[float, float, str, bool, "int | None", float, float]


def _scatter(
    pts: list[_Point],
    *,
    x_title: str,
    y_title: str,
    x_fmt: Callable[[float], str],
    y_fmt: Callable[[float], str],
    title: str,
    quality_floor: float | None = None,
) -> str:
    """A real quality(Y) vs cost(X) scatter with axes, ticks, a Pareto frontier
    and an optional quality-floor reference line, as self-contained inline SVG.

    Both axes read "up-left is better": Y = quality@k (higher is better), X = a
    cost axis (latency or footprint; lower is better), so the frontier is the
    non-dominated up-left boundary.
    """
    if not pts:
        return f"<p><em>No data to plot for {html.escape(title)}.</em></p>"

    W, H = 540, 356
    # narrow right margin (legend now lives along the bottom, not the right), and
    # a taller bottom margin to hold the x-title + a horizontal legend row.
    m_left, m_right, m_top, m_bot = 66, 24, 46, 80
    px0, px1 = m_left, W - m_right          # plot area x-extent
    py0, py1 = m_top, H - m_bot             # plot area y-extent (py1 = baseline)

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    xlo, xhi = min(xs), max(xs)
    ylo, yhi = min(ys), max(ys)
    if quality_floor is not None:
        ylo, yhi = min(ylo, quality_floor), max(yhi, quality_floor)
    # Pad domains; when every value is equal fall back to a unit span so the
    # scales never divide by zero (graceful degradation for flat data).
    xspan = (xhi - xlo) or (abs(xhi) or 1.0)
    yspan = (yhi - ylo) or (abs(yhi) or 1.0)
    xlo, xhi = xlo - xspan * 0.08, xhi + xspan * 0.08
    ylo, yhi = ylo - yspan * 0.12, yhi + yspan * 0.12
    xlo, ylo = max(xlo, 0.0), max(ylo, 0.0)  # cost & quality are never negative

    def sx(x: float) -> float:
        return px0 + (x - xlo) / (xhi - xlo) * (px1 - px0)

    def sy(y: float) -> float:  # higher quality plots higher on the chart
        return py1 - (y - ylo) / (yhi - ylo) * (py1 - py0)

    g: list[str] = []

    # chart title
    g.append(
        f'<text x="{px0}" y="22" font-size="13" font-weight="600" '
        f'fill="{_INK}">{html.escape(title)}</text>'
    )

    # gridlines (hairline, recessive)
    xticks, yticks = _nice_ticks(xlo, xhi), _nice_ticks(ylo, yhi)
    for tx in xticks:
        X = sx(tx)
        g.append(
            f'<line x1="{X:.1f}" y1="{py0:.1f}" x2="{X:.1f}" y2="{py1:.1f}" '
            f'stroke="{_GRID}" stroke-width="1"/>'
        )
    for ty in yticks:
        Y = sy(ty)
        g.append(
            f'<line x1="{px0:.1f}" y1="{Y:.1f}" x2="{px1:.1f}" y2="{Y:.1f}" '
            f'stroke="{_GRID}" stroke-width="1"/>'
        )

    # axes
    g.append(
        f'<line x1="{px0}" y1="{py1:.1f}" x2="{px1:.1f}" y2="{py1:.1f}" '
        f'stroke="{_AXIS}" stroke-width="1"/>'
    )
    g.append(
        f'<line x1="{px0}" y1="{py0:.1f}" x2="{px0}" y2="{py1:.1f}" '
        f'stroke="{_AXIS}" stroke-width="1"/>'
    )

    # tick marks + numeric labels
    for tx in xticks:
        X = sx(tx)
        g.append(
            f'<line x1="{X:.1f}" y1="{py1:.1f}" x2="{X:.1f}" y2="{py1 + 4:.1f}" stroke="{_AXIS}"/>'
        )
        g.append(
            f'<text x="{X:.1f}" y="{py1 + 18:.1f}" text-anchor="middle" '
            f'font-size="11" fill="{_MUTED}" style="font-variant-numeric:tabular-nums">'
            f'{html.escape(x_fmt(tx))}</text>'
        )
    for ty in yticks:
        Y = sy(ty)
        g.append(
            f'<line x1="{px0 - 4:.1f}" y1="{Y:.1f}" x2="{px0:.1f}" y2="{Y:.1f}" stroke="{_AXIS}"/>'
        )
        g.append(
            f'<text x="{px0 - 8:.1f}" y="{Y + 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="{_MUTED}" style="font-variant-numeric:tabular-nums">'
            f'{html.escape(y_fmt(ty))}</text>'
        )

    # axis titles (x-title sits just below the tick labels, above the legend row)
    cx, cy = (px0 + px1) / 2, (py0 + py1) / 2
    g.append(
        f'<text x="{cx:.1f}" y="{py1 + 34:.1f}" text-anchor="middle" font-size="12" '
        f'fill="{_INK2}">{html.escape(x_title)}</text>'
    )
    g.append(
        f'<text x="16" y="{cy:.1f}" text-anchor="middle" font-size="12" fill="{_INK2}" '
        f'transform="rotate(-90 16 {cy:.1f})">{html.escape(y_title)}</text>'
    )

    # quality-floor reference line (dashed threshold annotation)
    if quality_floor is not None and ylo <= quality_floor <= yhi:
        Y = sy(quality_floor)
        g.append(
            f'<line x1="{px0}" y1="{Y:.1f}" x2="{px1:.1f}" y2="{Y:.1f}" '
            f'stroke="{_FLOOR}" stroke-width="1.5" stroke-dasharray="5 4"/>'
        )
        g.append(
            f'<text x="{px1:.1f}" y="{Y - 5:.1f}" text-anchor="end" font-size="10" '
            f'fill="{_FLOOR}">quality floor {quality_floor:.2f}</text>'
        )

    # Pareto frontier: non-dominated points (no other point has ≤x and ≥y and is
    # strictly better on at least one axis), connected left→right.
    front = [
        p for i, p in enumerate(pts)
        if not any(
            q[0] <= p[0] and q[1] >= p[1] and (q[0] < p[0] or q[1] > p[1])
            for j, q in enumerate(pts) if j != i
        )
    ]
    front.sort(key=lambda p: (p[0], -p[1]))
    if len(front) >= 2:
        pathpts = " ".join(f"{sx(p[0]):.1f},{sy(p[1]):.1f}" for p in front)
        g.append(
            f'<polyline points="{pathpts}" fill="none" stroke="{_FRONT}" '
            f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        )

    # dots — other configs first, recommended on top
    rec: _Point | None = None
    for p in pts:
        x, y, label, is_rec, fp, qual, lat = p
        if is_rec:
            rec = p
            continue
        X, Y = sx(x), sy(y)
        hover = (
            f"{html.escape(label)} — {html.escape(y_title)}={qual:.3f}, "
            f"p95={lat:.1f} ms, {_fmt_bytes(fp)}"
        )
        g.append(
            f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="5" fill="{_OTHER}" '
            f'stroke="{_SURFACE}" stroke-width="2"><title>{hover}</title></circle>'
        )
    if rec is not None:
        x, y, label, _is_rec, fp, qual, lat = rec
        X, Y = sx(x), sy(y)
        hover = (
            f"{html.escape(label)} — {html.escape(y_title)}={qual:.3f}, "
            f"p95={lat:.1f} ms, {_fmt_bytes(fp)} (recommended)"
        )
        g.append(  # highlight ring
            f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="10.5" fill="none" '
            f'stroke="{_REC}" stroke-width="1.5" opacity="0.55"/>'
        )
        g.append(
            f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="6.5" fill="{_REC}" '
            f'stroke="{_SURFACE}" stroke-width="2"><title>{hover}</title></circle>'
        )
        # place the "recommended" label so its full width (~80px) stays inside
        # the plot: default to the right of the dot, flip left when the label end
        # would overrun px1. Nudge it below the dot if it would clip the top edge.
        label_w = 82
        lx, anchor = X + 13, "start"
        if X + 13 + label_w > px1:  # right side would overrun — flip to the left
            lx, anchor = X - 13, "end"
        ly_lbl = Y - 10 if Y - 10 > py0 + 12 else Y + 20
        g.append(
            f'<text x="{lx:.1f}" y="{ly_lbl:.1f}" text-anchor="{anchor}" '
            f'font-size="11" font-weight="600" fill="{_INK}">recommended</text>'
        )

    # legend: a horizontal row BELOW the x-axis title (frees the right margin, so
    # it can never collide with the in-plot "recommended" label). Each entry is a
    # swatch + text; we advance x by an estimated text width so entries don't
    # overlap. Identity is never color-alone: swatch + word label.
    ly = py1 + 54
    lx = px0
    def _legend_entry(draw_swatch: Callable[[float], None], label: str) -> None:
        nonlocal lx
        draw_swatch(lx)
        g.append(f'<text x="{lx + 12:.1f}" y="{ly + 4:.1f}" font-size="10" fill="{_INK2}">{label}</text>')
        lx += 12 + len(label) * 6.0 + 22  # swatch + text width estimate + gap

    _legend_entry(
        lambda x: g.append(
            f'<circle cx="{x + 4:.1f}" cy="{ly:.1f}" r="6" fill="{_REC}" stroke="{_SURFACE}" stroke-width="2"/>'
        ),
        "recommended",
    )
    _legend_entry(
        lambda x: g.append(f'<circle cx="{x + 4:.1f}" cy="{ly:.1f}" r="5" fill="{_OTHER}"/>'),
        "other config",
    )
    _legend_entry(
        lambda x: g.append(
            f'<line x1="{x:.1f}" y1="{ly:.1f}" x2="{x + 10:.1f}" y2="{ly:.1f}" stroke="{_FRONT}" stroke-width="2"/>'
        ),
        "Pareto frontier",
    )
    if quality_floor is not None:
        _legend_entry(
            lambda x: g.append(
                f'<line x1="{x:.1f}" y1="{ly:.1f}" x2="{x + 10:.1f}" y2="{ly:.1f}" stroke="{_FLOOR}" '
                f'stroke-width="1.5" stroke-dasharray="5 4"/>'
            ),
            "quality floor",
        )

    return (
        f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'style="max-width:100%;height:auto;background:{_SURFACE}" role="img" '
        f'aria-label="{html.escape(title)}: {html.escape(y_title)} versus {html.escape(x_title)}">'
        + "".join(g)
        + "</svg>"
    )


def _mode_charts(
    ms: list[Measurement],
    metric: Metric,
    k: int,
    recommended: set[str],
    quality_floor: float | None,
) -> str:
    """Build the quality-vs-latency and (when footprints exist)
    quality-vs-footprint scatters for one mode."""
    y_title = f"{metric.value}@{k}"
    lat_pts: list[_Point] = []
    fp_pts: list[_Point] = []
    for m in ms:
        q = m.quality.get(metric, k)
        if q is None:
            continue
        is_rec = m.config.label in recommended
        lat = m.latency_p95_ms
        fp = m.cost.primary_bytes()
        lat_pts.append((lat, q, m.config.label, is_rec, fp, q, lat))
        if fp is not None:
            fp_pts.append((fp / (1024 * 1024), q, m.config.label, is_rec, fp, q, lat))

    if not lat_pts:
        return "<p><em>No quality data to plot (shown in table only).</em></p>"

    charts = [
        _scatter(
            lat_pts,
            x_title="p95 latency (ms)",
            y_title=y_title,
            x_fmt=lambda v: f"{v:g}",
            y_fmt=lambda v: f"{v:.2f}",
            title="quality vs latency",
            quality_floor=quality_floor,
        )
    ]
    if fp_pts:
        charts.append(
            _scatter(
                fp_pts,
                x_title="footprint (MB)",
                y_title=y_title,
                x_fmt=lambda v: f"{v:g}",
                y_fmt=lambda v: f"{v:.2f}",
                title="quality vs footprint",
                quality_floor=quality_floor,
            )
        )
    return (
        '<div style="display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start">'
        + "".join(charts)
        + "</div>"
    )


def render_html(
    results: dict[Mode, list[Measurement]],
    recommendations: dict[Mode, list[Measurement]],
    metric: "Metric | dict[Mode, Metric]",
    k: int,
    meta: dict | None = None,
) -> str:
    """Render a single self-contained HTML file (string).

    `metric` may be a single Metric or a per-mode mapping so each mode is
    displayed on the metric it was ranked by. `meta` may carry `quality_floor`
    (drawn as the chart reference line) alongside the run metadata.
    """
    meta = meta or {}
    quality_floor = meta.get("quality_floor")
    parts: list[str] = []
    parts.append(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>ai-search-tuner report</title><style>"
        "body{font:14px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif;margin:2rem;color:#0f172a;max-width:920px}"
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
        parts.append(_mode_charts(ms, metric_m, k, rec_labels, quality_floor))
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
