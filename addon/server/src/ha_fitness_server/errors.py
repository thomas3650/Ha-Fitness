"""The errors the services raise and the adapters map.

REST maps them to 404, 409, 422 and 503 with a `detail`; MCP turns them into a `ToolError`. `SessionError` carries its
own status and a `{code, message}` detail, for the session routes only. `DatabaseTooNew` stops the start.
"""


class NotFound(Exception):
    """The thing asked for doesn't exist."""


class Conflict(Exception):
    """The write clashes with what is stored, for example a name already in use."""


class Invalid(Exception):
    """The input breaks a rule; `detail` is a text or a JSON-able dict that says how."""

    def __init__(self, detail: object) -> None:
        """Keep the detail for the adapters."""
        super().__init__(detail)
        self.detail = detail


class Unavailable(Exception):
    """Something the write needs, such as Home Assistant, can't be reached."""


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
