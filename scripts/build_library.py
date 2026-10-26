"""Build the add-on's exercise library data from the exercises dataset.

Usage: `uv run python scripts/build_library.py [--source <file>]`

Downloads `data/exercises.json` of https://github.com/hasaneyldrm/exercises-dataset at the commit pinned as
`DATASET_COMMIT` in `addon/server/src/ha_fitness_server/library/__init__.py`, today
`7455efae41b330c265e7cd4b78dfa848e7ce5ebd` (or reads `--source <file>`). Keeps every record of the whole dataset (D64),
keeps the fields the server uses, and writes
`addon/server/src/ha_fitness_server/library/exercises.json`, sorted by id. The output is deterministic, so a re-run
gives no diff. Only the data is used; the media is downloaded by the add-on at runtime.
"""

import argparse
import ast
import json
from pathlib import Path
from typing import Any
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = ROOT / "addon" / "server" / "src" / "ha_fitness_server" / "library"
OUTPUT = LIBRARY / "exercises.json"
SOURCE_URL = "https://raw.githubusercontent.com/hasaneyldrm/exercises-dataset/{commit}/data/exercises.json"


def dataset_commit() -> str:
    """Return `DATASET_COMMIT` from the library package, parsed without importing the server."""
    tree = ast.parse((LIBRARY / "__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "DATASET_COMMIT"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    msg = "DATASET_COMMIT not found in the library package"
    raise SystemExit(msg)


def load(source: Path | None) -> list[dict[str, Any]]:
    """Return the dataset's records, from `source` or downloaded at the pinned commit."""
    if source is not None:
        text = source.read_text(encoding="utf-8")
    else:
        url = SOURCE_URL.format(commit=dataset_commit())
        with urllib.request.urlopen(url, timeout=60) as response:
            text = response.read().decode("utf-8")
    data: list[dict[str, Any]] = json.loads(text)
    return data


def record(raw: dict[str, Any]) -> dict[str, Any]:
    """Return the fields the server keeps for one exercise."""
    return {
        "id": raw["id"],
        "name": raw["name"],
        "equipment": raw["equipment"],
        "body_part": raw["body_part"],
        "target": raw["target"],
        "secondary_muscles": raw["secondary_muscles"],
        "steps": raw["instruction_steps"]["en"],
        "gif": raw["gif_url"],
        "thumbnail": raw["image"],
    }


def main() -> None:
    """Build the library file and print how many exercises it holds."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source",
        type=Path,
        help="read the dataset from this file instead of downloading it",
    )
    args = parser.parse_args()
    exercises = sorted(
        (record(raw) for raw in load(args.source)),
        key=lambda exercise: exercise["id"],
    )
    OUTPUT.write_text(
        json.dumps(exercises, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"{len(exercises)} exercises")


if __name__ == "__main__":
    main()
