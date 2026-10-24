"""The add-on's Ingress page (spec §9, D27): a read-only status page in the browser's language."""

from functools import cache
from html import escape
from importlib.resources import files
import json

from . import __version__
from .services import Services

LANGUAGES = ("en", "da")
DEFAULT_LANGUAGE = "en"


@cache
def texts(language: str) -> dict[str, str]:
    """Return a language file's texts."""
    raw = files(__package__).joinpath("i18n", f"{language}.json").read_text("utf-8")
    loaded: dict[str, str] = json.loads(raw)
    return loaded


def _quality(parameters: list[str]) -> float:
    """Return the `q` of a language range's parameters; 1 when none is given, 0 when it can't be read."""
    for parameter in parameters:
        name, _, value = parameter.partition("=")
        if name.strip().lower() == "q":
            try:
                return float(value)
            except ValueError:
                return 0.0
    return 1.0


def language(accept_language: str | None) -> str:
    """Return `da` when the most preferred language of `Accept-Language` is Danish, else `en`.

    The highest q wins; at equal q the first one does.
    """
    best_tag, best_q = "", 0.0
    for part in (accept_language or "").split(","):
        tag, *parameters = part.split(";")
        tag = tag.strip().lower()
        q = _quality(parameters)
        if tag and q > best_q:
            best_tag, best_q = tag, q
    return "da" if best_tag.startswith("da") else DEFAULT_LANGUAGE


def render(services: Services, accept_language: str | None) -> str:
    """Return the page's HTML; it reads the database and the media state only, never HA."""
    lang = language(accept_language)
    t = {key: escape(value) for key, value in texts(lang).items()}
    counts = services.library.counts()
    media = services.media.state()
    people = services.people.stored()
    programs = services.programs.summaries()

    media_text = t["media"].format(
        present=media.present, total=media.total, state=t[f"media_{media.state}"]
    )
    exercises_text = t["exercises"].format(
        library=counts["library"], custom=counts["custom"]
    )
    if people:
        people_html = (
            "<ul>"
            + "".join(f"<li>{escape(person.name)}</li>" for person in people)
            + "</ul>"
        )
    else:
        people_html = f"<p>{t['no_people']}</p>"
    if programs:
        rows = "".join(
            "<tr>"
            f"<td>{escape(program.name)}</td>"
            f"<td>{t['on'] if program.active else t['off']}</td>"
            f"<td>{t['list_separator'].join(t[f'weekday_{day}'] for day in program.weekdays) or t['no_weekdays']}</td>"
            f"<td>{t['minutes'].format(minutes=program.total_minutes)}</td>"
            "</tr>"
            for program in programs
        )
        programs_html = (
            "<table><thead><tr>"
            f"<th>{t['program_name']}</th><th>{t['program_state']}</th>"
            f"<th>{t['program_weekdays']}</th><th>{t['program_length']}</th>"
            f"</tr></thead><tbody>{rows}</tbody></table>"
        )
    else:
        programs_html = f"<p>{t['no_programs']}</p>"

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
        f"<h1>{t['heading']}</h1>"
        f"<p>{t['version'].format(version=escape(__version__))}</p>"
        f"<h2>{t['library']}</h2>"
        f"<p>{exercises_text}</p>"
        f"<p>{media_text}</p>"
        f"<h2>{t['people']}</h2>"
        f"{people_html}"
        f"<h2>{t['programs']}</h2>"
        f"{programs_html}"
        f"<h2>{t['links']}</h2>"
        "<ul>"
        f'<li><a href="api/v1/library">{t["library_json"]}</a></li>'
        f'<li><a href="api/v1/health">{t["health"]}</a></li>'
        "</ul>"
        "</body>"
        "</html>"
    )
