"""Render a terminal transcript as the SVG the README shows.

    python docs/launch/transcript_svg.py "title" < transcript.txt > docs/img/name.svg

A line starting with ``$`` or ``>`` is a command, ``==`` is an installer step, ``#`` a remark,
``Brain: OK`` the verdict; everything else is plain output.
"""

from __future__ import annotations

import sys
from html import escape

COLOURS = {"$": "#7dd3fc", ">": "#7dd3fc", "==": "#fbbf24", "#": "#94a3b8", "Brain: OK": "#4ade80"}


def svg(title: str, lines: list[str]) -> str:
    h = 56 + 22 * len(lines)
    dots = "".join(
        f'<circle cx="{x}" cy="20" r="6" fill="{c}"/>'
        for x, c in ((22, "#ff5f57"), (42, "#febc2e"), (62, "#28c840"))
    )
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="820" height="{h}" '
        f'viewBox="0 0 820 {h}" font-family="SFMono-Regular, Menlo, Consolas, monospace" '
        'font-size="14">',
        f'<rect width="820" height="{h}" rx="10" fill="#0f172a"/>',
        dots,
        '<text x="410" y="25" text-anchor="middle" fill="#94a3b8" font-size="12">'
        f"{escape(title)}</text>",
    ]
    for i, line in enumerate(lines):
        fill = next((c for k, c in COLOURS.items() if line.lstrip().startswith(k)), "#e2e8f0")
        y = 56 + 22 * i
        out.append(f'<text x="24" y="{y}" fill="{fill}" xml:space="preserve">{escape(line)}</text>')
    return "\n".join(out) + "\n</svg>\n"


if __name__ == "__main__":
    sys.stdout.write(svg(sys.argv[1], sys.stdin.read().rstrip("\n").split("\n")))
