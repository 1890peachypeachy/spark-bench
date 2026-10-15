#!/usr/bin/env python3
"""Side-by-side comparison chart + table for two (or more) qbench result sets.

    python3 bench/chart.py results/qbench-dsv41-zig-20261015.json [results/qbench-nemotron-....json] \
        --png results/qbench-compare.png --md results/qbench-compare.md

Renders an SVG (hand-written, no plotting library) and converts it with rsvg-convert or ImageMagick.
Percentages only; no prices anywhere. A missing series is simply not drawn, so the DeepSeek-only chart
today becomes the two-model chart the moment a second result file exists.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

QUALITY = [("mmlu", "Knowledge (MMLU-200)"), ("math", "Math (GSM8K-30)"), ("coding", "Coding (5 hidden tests)"),
           ("if", "Instruction following"), ("json", "JSON schema"), ("tools", "Tool use + chains"),
           ("longctx", "Long context (passkey)")]
SPEED = [("c1_code", "code, 1 stream"), ("c1_prose", "prose, 1 stream"), ("c4_agg", "4 streams, aggregate")]
COLORS = ["#2a78d6", "#d65a2a", "#3f9c56", "#8a5cd6", "#b58a00"]


def series(path: Path) -> dict:
    d = json.loads(path.read_text())
    a = d["areas"]
    q = {}
    for key, _ in QUALITY:
        area = a.get(key) or {}
        if area.get("error") or area.get("accuracy") is None:
            q[key] = None
        else:
            q[key] = round(100 * area["accuracy"], 1)
    s = {}
    sp = a.get("speed") or {}
    try:
        s["c1_code"] = sp["c1"]["code"]["decode_tok_s"]
        s["c1_prose"] = sp["c1"]["prose"]["decode_tok_s"]
        s["c4_agg"] = sp["c4"]["aggregate_tok_s"]
        s["ttft_code"] = sp["c1"]["code"]["ttft_s"]
    except KeyError:
        s = {}
    summ = a.get("summary") or {}
    return {"tag": d.get("tag") or path.stem, "model": d.get("model"), "quality": q, "speed": s,
            "summary": {"facts_kept": (summ.get("facts_kept_rate") or 0) * 100 if summ.get("facts_kept_rate") is not None else None,
                        "stale": (summ.get("stale_rate") or 0) * 100 if summ.get("stale_rate") is not None else None,
                        "invented": (summ.get("invented_rate") or 0) * 100 if summ.get("invented_rate") is not None else None},
            "raw": d}


def svg(sets: list[dict], title: str) -> str:
    pad_l, pad_r, pad_t = 250, 60, 76
    row_h, bar_h, gap = 30, 26, 3
    n_rows = len(QUALITY) + 3 + len(SPEED) + 1  # quality + summary row + spacer + speed + spacer
    width = 1120
    height = pad_t + n_rows * (row_h + gap) + 96
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}" font-family="Inter, DejaVu Sans, Helvetica, Arial, sans-serif">',
             f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
             f'<text x="24" y="34" font-size="22" font-weight="600" fill="#111">{title}</text>',
             f'<text x="24" y="58" font-size="13" fill="#666">Quality = % correct (higher is better). '
             f'Speed = decode tok/s on fixed prompts (thinking off). Same frozen inputs for every model.</text>']
    # legend
    for i, s in enumerate(sets):
        x = 24 + i * 220
        parts.append(f'<rect x="{x}" y="{pad_t - 20}" width="12" height="12" fill="{COLORS[i % len(COLORS)]}"/>')
        parts.append(f'<text x="{x + 18}" y="{pad_t - 9}" font-size="13" fill="#333">'
                     f'{s["tag"]} ({s.get("model") or "?"})</text>')
    y = pad_t
    plot_l = pad_l
    plot_r = width - pad_r
    scale = (plot_r - plot_l) / 100.0

    def row(label: str, values: list[float | None], y: int, unit: str = "%", maxv: float = 100.0) -> None:
        parts.append(f'<text x="{pad_l - 12}" y="{y + 19}" font-size="13" text-anchor="end" fill="#222">{label}</text>')
        wmax = (plot_r - plot_l) * (maxv / 100.0 if maxv > 0 else 1)
        parts.append(f'<rect x="{plot_l}" y="{y + 3}" width="{wmax:.1f}" height="{bar_h}" fill="#f2f4f7"/>')
        for i, v in enumerate(values):
            if v is None:
                continue
            off = i * (bar_h // max(1, len(values)))
            h = bar_h / max(1, len(values)) - 1
            frac = min(1.0, v / maxv) if maxv > 0 else 0
            w = (plot_r - plot_l) * frac
            parts.append(f'<rect x="{plot_l}" y="{y + 3 + off:.1f}" width="{w:.1f}" height="{h:.1f}" '
                         f'fill="{COLORS[i % len(COLORS)]}" rx="2"/>')
            txt = f"{v:.0f}{unit}" if unit == "%" else f"{v:.0f}{unit}"
            parts.append(f'<text x="{min(plot_l + w + 6, plot_r + 2):.1f}" y="{y + 3 + off + h - 2:.1f}" '
                         f'font-size="11" fill="#333">{txt}</text>')
        # gridline at 100%
        parts.append(f'<line x1="{plot_r}" y1="{y + 3}" x2="{plot_r}" y2="{y + 3 + bar_h}" stroke="#d0d5dd"/>')

    for key, label in QUALITY:
        row(label, [s["quality"].get(key) for s in sets], y)
        y += row_h + gap
    row("Summary: facts kept", [s["summary"]["facts_kept"] for s in sets], y)
    y += row_h + gap
    row("Summary: stale returned ↓", [s["summary"]["stale"] for s in sets], y)
    y += row_h + gap
    row("Summary: invented numbers ↓", [s["summary"]["invented"] for s in sets], y)
    y += row_h + gap + 14
    parts.append(f'<text x="24" y="{y - 6}" font-size="13" font-weight="600" fill="#444">Speed — decode tok/s</text>')
    smax = max([s["speed"].get(k, 0) or 0 for s in sets for k, _ in SPEED] + [1]) * 1.15
    for key, label in SPEED:
        row(label, [s["speed"].get(key) for s in sets], y, unit="", maxv=smax)
        y += row_h + gap
    parts.append(f'<text x="24" y="{height - 22}" font-size="11" fill="#888">'
                 f'Generated by bench/chart.py from qbench result JSON. Percentages only; no pricing.</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def markdown(sets: list[dict]) -> str:
    lines = ["# qbench comparison", ""]
    head = "| area | " + " | ".join(s["tag"] for s in sets) + " |"
    lines += [head, "|---" * (len(sets) + 1) + "|"]
    for key, label in QUALITY:
        cells = []
        for s in sets:
            v = s["quality"].get(key)
            area = s["raw"]["areas"].get(key) or {}
            cells.append("—" if v is None else f"{v:.1f} % ({area.get('correct')}/{area.get('n')})")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    for key, label in [("facts_kept", "Summary: facts kept"), ("stale", "Summary: stale returned (lower better)"),
                       ("invented", "Summary: invented numbers (lower better)")]:
        cells = ["—" if s["summary"].get(key) is None else f"{s['summary'][key]:.1f} %" for s in sets]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    for key, label in SPEED:
        cells = ["—" if s["speed"].get(key) is None else f"{s['speed'][key]:.1f} tok/s" for s in sets]
        lines.append(f"| Speed: {label} | " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="+")
    ap.add_argument("--png", default=None)
    ap.add_argument("--svg", default=None)
    ap.add_argument("--md", default=None)
    ap.add_argument("--title", default="qbench — DeepSeek V4.1 Flash on four Sparks (TensorFold, Zig engine)")
    a = ap.parse_args()
    sets = [series(Path(p)) for p in a.results]
    text = svg(sets, a.title)
    base = Path(a.png or a.svg or "qbench-compare").with_suffix("")
    svg_path = Path(a.svg) if a.svg else base.with_suffix(".svg")
    svg_path.write_text(text)
    print(f"wrote {svg_path}")
    png_path = Path(a.png) if a.png else base.with_suffix(".png")
    conv = shutil.which("rsvg-convert") or shutil.which("magick") or shutil.which("convert")
    if conv:
        cmd = ([conv, "-o", str(png_path), str(svg_path)] if conv.endswith("rsvg-convert")
               else [conv, str(svg_path), str(png_path)])
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"convert failed: {r.stderr.strip()[:200]}", file=sys.stderr)
            sys.exit(1)
        print(f"wrote {png_path}")
    if a.md:
        Path(a.md).write_text(markdown(sets))
        print(f"wrote {a.md}")
    else:
        print(markdown(sets))


if __name__ == "__main__":
    main()
