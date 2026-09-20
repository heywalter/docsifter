#!/usr/bin/env python3
"""Generate the architecture diagram used by both READMEs.

Two constraints shape it. The picture has to carry one fact before any label is
read -- every layer runs on your machine, and exactly one arrow leaves it -- so
the local work sits inside a labelled boundary and the optional endpoint sits
outside it. And it has to be honest: only the formats the extractors actually
register appear as input, and nothing here trains a model, so nothing here says
it does.

Light and dark come out of one definition, because GitHub renders READMEs in
both themes and a diagram that assumes white is broken in half of them. The
READMEs choose between them with <picture>.

    python3 tools/build_architecture_diagram.py

Edit the bands below, re-run, commit both SVGs.
"""

from __future__ import annotations

import html
import pathlib

OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "docs" / "images"

FONT = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', "
    "Roboto, 'Helvetica Neue', Arial, sans-serif"
)
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"

W = 1100

THEMES = {
    "light": {
        "ink": "#1b2030",
        "muted": "#66708a",
        "faint": "#98a0b4",
        "card": "#ffffff",
        "card_line": "#e4e8f0",
        "boundary": "#c2c9d8",
        "page": "none",
        "shadow": "0.07",
        "bands": {
            "entry": ("#eef4ff", "#d6e4ff", "#2563eb"),
            "rules": ("#eef0ff", "#dcdffb", "#4f46e5"),
            "model": ("#e9f7f3", "#cfeae1", "#0d9488"),
            "llm": ("#fdf4e7", "#f3ddb4", "#c2760c"),
            "state": ("#eef6ee", "#d6e8d8", "#3f8f52"),
        },
    },
    "dark": {
        "ink": "#e9ecf3",
        "muted": "#9aa3b8",
        "faint": "#6e7789",
        "card": "#1a1f2d",
        "card_line": "#2f3749",
        "boundary": "#3b4356",
        "page": "none",
        "shadow": "0.35",
        "bands": {
            "entry": ("#141d2f", "#24344f", "#6f9bf0"),
            "rules": ("#171a2f", "#2a2e56", "#8b8df5"),
            "model": ("#10221f", "#1f403a", "#3bb9a3"),
            "llm": ("#251d10", "#4a3a1c", "#dda44f"),
            "state": ("#141f16", "#26402b", "#6fbd80"),
        },
    },
}

# --- content ----------------------------------------------------------------
INPUTS = ["Markdown", "AsciiDoc", "Plain text"]

BANDS = [
    {
        "key": "entry",
        "eyebrow": "ENTRY POINTS",
        "title": "Start a review",
        "cards": [
            ("CLI", "docsifter"),
            ("Web UI", "docsifter-web"),
            ("GitHub pull request", "signed webhooks"),
        ],
    },
    {
        "key": "rules",
        "eyebrow": "LAYER 1",
        "title": "Rule preview",
        "note": "no model download",
        "cards": [
            ("Terminology", "stable rule IDs"),
            ("Wording", "severity per rule"),
            ("Allowlist", "terms never touched"),
            ("Syntax guard", "code, links, markup"),
        ],
    },
    {
        "key": "model",
        "eyebrow": "LAYER 2",
        "title": "Local small model",
        "note": "runs fully offline",
        "cards": [
            ("1.5B", "default, CPU-friendly"),
            ("7B", "same family, larger"),
            ("Ollama / OpenAI-compatible", "any model id"),
        ],
    },
    {
        "key": "llm",
        "eyebrow": "LAYER 3",
        "title": "LLM second pass",
        "note": "optional, off by default",
        "dashed": True,
        "cards": [
            ("Verify findings", "confirmed / rejected"),
            ("Cross-line context", "contradictions, dead links"),
        ],
    },
    {
        "key": "state",
        "eyebrow": "LOCAL STATE",
        "title": "DOCSIFTER_DATA_DIR",
        "mono_title": True,
        "cards": [
            ("False positives", "re-applied next run"),
            ("SQLite history", "runs and progress"),
            ("Generated reports", "kept 90 days"),
        ],
    },
]

OUTPUTS = [("HTML report", "diffs, severity, rule IDs"), ("Email", "on completion or failure")]

# --- layout -----------------------------------------------------------------
MARGIN_X = 40
BAND_X, BAND_W = 60, 820
STRIP_H = 62
BAND_GAP = 14
ARROW_GAP = 24
BAND_HEAD_H, BAND_CARD_H, BAND_PAD = 46, 52, 18
BAND_H = BAND_HEAD_H + BAND_CARD_H + BAND_PAD
BOUNDARY_LABEL_H = 26

# Derived so the canvas always fits: input strip, the boundary with its label
# and every band, then the output strip.
_TOP = 26
_BOUND_TOP = _TOP + STRIP_H + ARROW_GAP + BOUNDARY_LABEL_H
_BANDS_TOP = _BOUND_TOP + 14
_BOUND_BOTTOM = _BANDS_TOP + len(BANDS) * BAND_H + (len(BANDS) - 1) * BAND_GAP + 14
_OUT_TOP = _BOUND_BOTTOM + ARROW_GAP
H = _OUT_TOP + STRIP_H + 26
EP = (908, 0, 172, 92)  # y filled in once the llm band is placed


def esc(t: str) -> str:
    return html.escape(t, quote=False)


def rect(x, y, w, h, fill, stroke, *, r=10, dash=None, width=1, extra=""):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" rx="{r}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{width}"{d}{extra}/>'
    )


def text(x, y, s, fill, size=13, *, weight=400, anchor="start", mono=False, spacing=None):
    family = MONO if mono else FONT
    sp = f' letter-spacing="{spacing}"' if spacing else ""
    return (
        f'<text x="{x:.0f}" y="{y:.0f}" font-family="{family}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{sp}>{esc(s)}</text>'
    )


def arrow(x1, y1, x2, y2, stroke, *, dash=None, marker="head"):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<path d="M {x1:.0f} {y1:.0f} L {x2:.0f} {y2:.0f}" fill="none" stroke="{stroke}" '
        f'stroke-width="1.6"{d} marker-end="url(#{marker})"/>'
    )


def build(theme: dict) -> str:
    p: list[str] = []
    a = p.append
    bands = theme["bands"]

    a(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'role="img" aria-label="DocSifter reviews Markdown, AsciiDoc and plain text in three '
        f'layers on your machine. Only the optional LLM second pass reaches an external endpoint.">'
    )
    a("<defs>")
    for name, colour in (("head", theme["faint"]), ("head-opt", bands["llm"][2])):
        a(
            f'<marker id="{name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
            f'markerHeight="6" orient="auto-start-reverse">'
            f'<path d="M 0 1 L 9 5 L 0 9 z" fill="{colour}"/></marker>'
        )
    a(
        f'<filter id="lift" x="-25%" y="-25%" width="150%" height="170%">'
        f'<feDropShadow dx="0" dy="1" stdDeviation="1.6" flood-opacity="{theme["shadow"]}"/>'
        f"</filter>"
    )
    a("</defs>")

    y = _TOP

    # --- input strip ---
    a(rect(BAND_X, y, BAND_W, STRIP_H, theme["card"], theme["card_line"], r=12))
    a(text(BAND_X + 24, y + 27, "DOCUMENT INPUT", theme["faint"], 10, weight=700, spacing="0.1em"))
    a(text(BAND_X + 24, y + 46, "what the extractors register", theme["muted"], 11))
    cx = BAND_X + 300
    for label in INPUTS:
        w = 118
        a(rect(cx, y + 16, w, 30, bands["entry"][0], bands["entry"][1], r=8))
        a(text(cx + w / 2, y + 36, label, bands["entry"][2], 12, weight=600, anchor="middle"))
        cx += w + 12
    input_bottom = y + STRIP_H

    # --- boundary opens ---
    bound_top = _BOUND_TOP
    a(
        text(
            MARGIN_X + 16,
            bound_top - 11,
            "YOUR MACHINE",
            theme["faint"],
            11,
            weight=700,
            spacing="0.1em",
        )
    )
    y = _BANDS_TOP

    llm_band_y = None
    band_edges: list[tuple[float, float]] = []
    for band in BANDS:
        fill, line, accent = bands[band["key"]]
        cards = band["cards"]
        head_h, card_h = BAND_HEAD_H, BAND_CARD_H
        h = BAND_H
        dashed = band.get("dashed")

        a(rect(BAND_X, y, BAND_W, h, fill, line, r=12, dash="6 5" if dashed else None))
        a(text(BAND_X + 24, y + 24, band["eyebrow"], accent, 10, weight=700, spacing="0.1em"))
        a(
            text(
                BAND_X + 24 + (len(band["eyebrow"]) * 6.6) + 14,
                y + 24,
                band["title"],
                theme["ink"],
                13.5,
                weight=700,
                mono=band.get("mono_title", False),
            )
        )
        if band.get("note"):
            a(
                text(
                    BAND_X + BAND_W - 24, y + 24, band["note"], accent, 11, weight=600, anchor="end"
                )
            )

        gap = 12
        cw = (BAND_W - 48 - gap * (len(cards) - 1)) / len(cards)
        cx = BAND_X + 24
        for title, sub in cards:
            a('<g filter="url(#lift)">')
            a(rect(cx, y + head_h, cw, card_h, theme["card"], theme["card_line"], r=9))
            a("</g>")
            a(text(cx + 14, y + head_h + 21, title, theme["ink"], 12.5, weight=600))
            a(text(cx + 14, y + head_h + 38, sub, theme["muted"], 10.5))
            cx += cw + gap

        band_edges.append((y, y + h))
        if band["key"] == "llm":
            llm_band_y = (y, y + h)
        y += h + BAND_GAP

    # arrows between bands
    mid = BAND_X + BAND_W / 2
    for (_, bottom), (top, _) in zip(band_edges, band_edges[1:], strict=False):
        opt = llm_band_y is not None and top == llm_band_y[0]
        a(
            arrow(
                mid,
                bottom + 3,
                mid,
                top - 4,
                bands["llm"][2] if opt else theme["faint"],
                dash="4 4" if opt else None,
                marker="head-opt" if opt else "head",
            )
        )

    bound_bottom = _BOUND_BOTTOM
    a(
        rect(
            MARGIN_X,
            bound_top,
            BAND_W + (BAND_X - MARGIN_X) * 2,
            bound_bottom - bound_top,
            "none",
            theme["boundary"],
            r=18,
            dash="7 6",
        )
    )

    # input into the first band
    a(arrow(mid, input_bottom + 3, mid, band_edges[0][0] - 4, theme["faint"]))

    # --- the one hop that leaves ---
    ex, _, ew, eh = EP
    ey = llm_band_y[0] + (llm_band_y[1] - llm_band_y[0]) / 2 - eh / 2
    accent = bands["llm"][2]
    a(rect(ex, ey, ew, eh, bands["llm"][0], bands["llm"][1], r=11, dash="5 4"))
    a(text(ex + 16, ey + 27, "Your LLM endpoint", accent, 12.5, weight=700))
    a(text(ex + 16, ey + 45, "OpenAI-compatible", theme["muted"], 10.5))
    a(text(ex + 16, ey + 61, "self-hosted or vendor", theme["muted"], 10.5))
    a(text(ex + 16, ey + 78, "the only hop off", accent, 10, weight=600))
    a(
        arrow(
            BAND_X + BAND_W + 6,
            ey + eh / 2,
            ex - 8,
            ey + eh / 2,
            accent,
            dash="4 4",
            marker="head-opt",
        )
    )

    # --- output strip ---
    y = _OUT_TOP
    a(arrow(mid, bound_bottom + 3, mid, y - 4, theme["faint"]))
    a(rect(BAND_X, y, BAND_W, STRIP_H, theme["card"], theme["card_line"], r=12))
    a(text(BAND_X + 24, y + 27, "OUTPUT", theme["faint"], 10, weight=700, spacing="0.1em"))
    a(text(BAND_X + 24, y + 46, "written locally", theme["muted"], 11))
    cx = BAND_X + 240
    for title, sub in OUTPUTS:
        w = 280
        a(rect(cx, y + 12, w, 38, bands["state"][0], bands["state"][1], r=9))
        a(text(cx + 14, y + 27, title, theme["ink"], 12.5, weight=600))
        a(text(cx + 14, y + 42, sub, theme["muted"], 10.5))
        cx += w + 14

    a("</svg>")
    return "\n".join(p) + "\n"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, theme in THEMES.items():
        path = OUT_DIR / f"architecture-{name}.svg"
        path.write_text(build(theme), encoding="utf-8")
        print(f"  {path.relative_to(OUT_DIR.parent.parent)}  {path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
