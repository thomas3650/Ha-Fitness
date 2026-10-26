"""The page `/` shows when the website isn't built (website spec §6); English only (D62)."""

from functools import cache
from html import escape
from importlib.resources import files
import json

from . import __version__


@cache
def texts() -> dict[str, str]:
    """Return the English language file's texts."""
    raw = files(__package__).joinpath("i18n", "en.json").read_text("utf-8")
    loaded: dict[str, str] = json.loads(raw)
    return loaded


def render_fallback() -> str:
    """Return the fallback page's HTML: the website isn't built, and the version."""
    t = {key: escape(value) for key, value in texts().items()}
    return (
        "<!DOCTYPE html>"
        f'<html lang="{t["lang"]}">'
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        f"<title>{t['title']}</title>"
        "</head>"
        "<body>"
        f"<p>{t['not_built']}</p>"
        f"<p>{t['version'].format(version=escape(__version__))}</p>"
        "</body>"
        "</html>"
    )
