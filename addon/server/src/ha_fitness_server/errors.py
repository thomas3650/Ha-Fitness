"""The errors the services raise and the adapters map.

REST maps them to 404, 409, 422 and 503 with a `detail`, a `code` and a `field` (D65); MCP turns them into a
`ToolError`. `SessionError` carries its own status and a `{code, message}` detail, for the session routes only.
`DatabaseTooNew` stops the start.
"""

from typing import ClassVar


class Refusal(Exception):
    """A refusal REST answers with `detail`, a stable `code` and the `field` it is about (D65).

    `code` defaults to the class's own `default_code`, which each subclass sets; nothing raises a bare `Refusal`.
    `field` is null where the refusal is about no one field. `str()` stays the message, which MCP sends as it is.
    """

    default_code: ClassVar[str]

    def __init__(
        self, message: str, *, code: str | None = None, field: str | None = None
    ) -> None:
        """Keep the code and the field for the adapters."""
        super().__init__(message)
        self.code = code or self.default_code
        self.field = field


class NotFound(Refusal):
    """The thing asked for doesn't exist."""

    default_code = "not_found"


class Conflict(Refusal):
    """The write clashes with what is stored, for example a name already in use."""

    default_code = "conflict"


class Invalid(Refusal):
    """The input breaks a rule; `detail` is a text or a JSON-able dict that says how."""

    default_code = "invalid"

    def __init__(
        self, detail: object, *, code: str | None = None, field: str | None = None
    ) -> None:
        """Keep the detail for the adapters."""
        super().__init__(str(detail), code=code, field=field)
        self.args = (detail,)
        self.detail = detail


class Unavailable(Refusal):
    """Something the write needs, such as Home Assistant, can't be reached."""

    default_code = "unavailable"


class SessionError(Exception):
    """A session command or read is refused (step 5 spec §3.5): `status` is 404, 409 or 422, `code` is a word.

    The codes are `not_found`, `conflict` and `invalid`.
    """

    def __init__(self, status: int, code: str, message: str) -> None:
        """Keep the status, the code and the message for the adapters."""
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class DatabaseTooNew(Exception):
    """The database is at a revision this code doesn't know."""
