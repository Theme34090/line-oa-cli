from __future__ import annotations

import sys
from importlib import resources
from pathlib import Path

from ..errors import CliError, EXIT_OK


SKILL_DEST = Path.home() / ".claude" / "skills" / "line-oa" / "SKILL.md"


def run(args) -> int:
    try:
        bundled = resources.files("line_oa").joinpath("_skill/SKILL.md")
        text = bundled.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as e:
        raise CliError(f"could not locate bundled skill: {e}")

    SKILL_DEST.parent.mkdir(parents=True, exist_ok=True)
    SKILL_DEST.write_text(text, encoding="utf-8")
    print(f"ok: skill installed to {SKILL_DEST}", file=sys.stderr)
    print("restart Claude Code (or start a new session) for it to load.", file=sys.stderr)
    return EXIT_OK
