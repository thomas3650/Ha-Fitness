"""The errors the services raise and the adapters map.

REST maps them to 404, 409, 422 and 503 with a `detail`; MCP turns them into a `ToolError`. `DatabaseTooNew` stops the
start.
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


class DatabaseTooNew(Exception):
    """The database is at a revision this code doesn't know."""
