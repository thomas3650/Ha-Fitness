"""Check the relative links and `@path` imports in the repo's Markdown docs.

Usage: `uv run python scripts/check_links.py`

Reads `CLAUDE.md`, `README.md` and every `docs/**/*.md`. Each relative link target, and each line that is
only `@<path>` (a Claude Code import), must exist, resolved against the file's own folder. Links with a
scheme (`https:`, `mailto:` ...) and pure `#anchor` links are skipped, and so is anything in a fenced code
block or an inline code span. Prints each missing target and exits 1 if there is one.
"""

from collections.abc import Iterator
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
FENCE = re.compile(r"^\s*(```|~~~)")
CODE_SPAN = re.compile(r"`[^`]*`")
LINK = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
IMPORT = re.compile(r"^@(\S+)$")
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def markdown_files() -> list[Path]:
    """Return the Markdown files to check."""
    files = [ROOT / "CLAUDE.md", ROOT / "README.md"]
    files += sorted((ROOT / "docs").rglob("*.md"))
    return [path for path in files if path.is_file()]


def targets(text: str) -> Iterator[tuple[int, str]]:
    """Yield (line number, target) for each link and import outside code."""
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if match := IMPORT.match(line.strip()):
            yield number, match.group(1)
            continue
        for link in LINK.finditer(CODE_SPAN.sub("", line)):
            yield number, link.group(1)


def missing(path: Path) -> Iterator[str]:
    """Yield a message for each target in `path` that doesn't exist."""
    for number, target in targets(path.read_text(encoding="utf-8")):
        if SCHEME.match(target) or target.startswith("#"):
            continue
        relative = target.split("#", 1)[0]
        if not (path.parent / relative).exists():
            yield f"{path.relative_to(ROOT)}:{number}: {target}"


def main() -> int:
    """Check every file; return 1 if a target is missing."""
    problems = [problem for path in markdown_files() for problem in missing(path)]
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
