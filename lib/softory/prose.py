"""Records are read by people. Tablet's roles wrote "blocks265", "assignedJade" and "retain2a5checkpoint":
the model dropped the space before a number or a name, and nothing between softory and the database
changes a record's text, so it was stored and shown that way. A record written like that is refused,
and the role writes it again."""

from __future__ import annotations

import re
from typing import Any

from .errors import SoftoryError

#: The coordination CLI's options, and softory's own, that hold sentences.
OPTIONS = ("--body", "--title", "--description", "--acceptance", "--next-steps", "--context", "--decision",
           "--required-changes", "--note", "--rationale", "--issue", "--requested-decision", "--resolution",
           "--scope", "--reason", "--why", "--ask", "--recommend", "--needs")
_CODE = re.compile(r"`[^`]*`")
_NOT_PROSE = re.compile(r"[/\\_=@]|[.:]\w")  # a path, a link, a file name, key=value, stack:name
_ID = re.compile(r"[A-Z]+\d+")  # REVIEW-TASK91
_HASH = re.compile(r"[0-9a-f]{7,40}")
_TERM = re.compile(r"(?:sha|md|base|utf|ipv|oauth|http|arm|amd|u?int|float|mp|python|wcag)\d+", re.IGNORECASE)
_NUMBER = re.compile(r"[A-Za-z][a-z]{2,}\d[A-Za-z0-9]*|\d+[a-z]{4,}")


def fused(text: str, roles: list[str] | None = None) -> list[str]:
    """The words in ``text`` that run into a number or a role's name, in order. Code in backticks, paths,
    links, IDs, commit hashes, and names such as sha256 are left alone."""
    name = re.compile(r"[A-Za-z]*[a-z](?:%s)" % "|".join(re.escape(r.capitalize()) for r in roles)) if roles else None
    found: list[str] = []
    for token in _CODE.sub(" ", text or "").split():
        if _NOT_PROSE.search(token.rstrip(".,;:")):
            continue
        for word in re.split(r"[^A-Za-z0-9]+", token):
            if _ID.fullmatch(word) or _HASH.fullmatch(word) or _TERM.fullmatch(word):
                continue
            if (_NUMBER.fullmatch(word) or (name and name.fullmatch(word))) and word not in found:
                found.append(word)
    return found


def check(texts: list[Any], roles: list[str]) -> None:
    found = [word for text in texts for word in fused(str(text or ""), roles)]
    if found:
        raise SoftoryError(
            f"Words are run together: {', '.join(dict.fromkeys(found))}. Write it again in full sentences with a "
            "space between every word, number and name, IDs in full (BUG-265, not 265), and code in `backticks`.",
            "invalid_arguments")


def values(args: list[str]) -> list[str]:
    """The text of every sentence option in a command line, in either spelling."""
    out = []
    for i, arg in enumerate(args):
        name, has_value, value = arg.partition("=")
        if name in OPTIONS:
            out.append(value if has_value else args[i + 1] if i + 1 < len(args) else "")
    return out
