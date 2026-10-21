"""The one error type softory raises, so the CLI can print it cleanly."""

from __future__ import annotations


class SoftoryError(Exception):
    """A failure the user can act on. ``code`` mirrors the CLI's style."""

    def __init__(self, message: str, code: str = "softory_error", details: object = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details
