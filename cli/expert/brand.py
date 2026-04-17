"""ASCII brand + helpers — shared visual identity across the CLI.

The logo uses the classic *ANSI Shadow* figlet font for the word ``EXPERT``
paired with a small knowledge glyph box on the right (`[ ≡ ]`, three stacked
lines = a book/corpus). This mirrors the design language of the author's
other CLI tools (see ``feliperbroering/eai``) while keeping a distinct
accent so they read as a family.

The brand renders with zero emoji characters — visual cues come from
Unicode box-drawing, Rich colors, and restrained accent tokens.
"""

from __future__ import annotations

from rich.console import Console
from rich.text import Text

from . import __version__

# The logo is split into (a) the ANSI-shadow wordmark and (b) a small
# knowledge-glyph box rendered to the right. Rendering them as two columns
# keeps them in sync regardless of terminal width and lets us tint them
# independently.
_WORDMARK = (
    "███████╗██╗  ██╗██████╗ ███████╗██████╗ ████████╗",
    "██╔════╝╚██╗██╔╝██╔══██╗██╔════╝██╔══██╗╚══██╔══╝",
    "█████╗   ╚███╔╝ ██████╔╝█████╗  ██████╔╝   ██║   ",
    "██╔══╝   ██╔██╗ ██╔═══╝ ██╔══╝  ██╔══██╗   ██║   ",
    "███████╗██╔╝ ██╗██║     ███████╗██║  ██║   ██║   ",
    "╚══════╝╚═╝  ╚═╝╚═╝     ╚══════╝╚═╝  ╚═╝   ╚═╝   ",
)

_GLYPH = (
    "         ",
    "  ╭───╮  ",
    "  │ ≡ │  ",
    "  ╰───╯  ",
    "         ",
    "         ",
)

TAGLINE = "ground a model on your docs. ship it as an API."
SUBTITLE = "declarative ultra-specialist agents on Cloud Run — Gemini long-context, Context Cache, persistent memory."

# Accent colors — picked to read well on both dark and light terminals and
# to stay distinct from `eai` (which leans green/cyan).
_ACCENT = "bright_cyan"
_DIM = "grey50"
_HEADLINE = "bold white"


def render_brand(console: Console, *, include_version: bool = True) -> None:
    """Render the full brand block (wordmark + glyph + tagline)."""
    for wm, gl in zip(_WORDMARK, _GLYPH, strict=True):
        line = Text()
        line.append(" ")
        line.append(wm, style=_ACCENT)
        line.append(gl, style=_DIM)
        console.print(line)

    console.print()
    headline = Text()
    headline.append(" ")
    headline.append(TAGLINE, style=_HEADLINE)
    console.print(headline)

    subtitle = Text()
    subtitle.append(" ")
    subtitle.append(SUBTITLE, style=_DIM)
    console.print(subtitle)

    if include_version:
        console.print()
        ver = Text()
        ver.append(" ")
        ver.append("expert ", style=_ACCENT)
        ver.append(f"v{__version__}", style=_DIM)
        ver.append("   ")
        ver.append("MIT", style=_DIM)
        ver.append("   ")
        ver.append("github.com/feliperbroering/expert-agent", style=_DIM)
        console.print(ver)


__all__ = ["SUBTITLE", "TAGLINE", "render_brand"]
