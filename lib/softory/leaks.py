"""The gate's ``no_secrets`` check: no key, token, private key, or secret file in the lines a unit adds.

Only the unit's own commits count, read the way ``lane_paths`` reads them, so an inherited line is
checked on the unit that wrote it. A merge commit counts for what it adds beyond git's automatic merge. Placeholder values (example, dummy, changeme, ``${VAR}``) and the
charter's ``secrets.allow`` patterns don't count. The owner can waive a false positive on one unit.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

from . import verify
from .gitlocal import git

PATTERNS = [
    ("private key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{50,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Stripe live key", re.compile(r"\b[rs]k_live_[0-9A-Za-z]{20,}")),
    ("API secret key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{32,}")),
    ("JSON web token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("hard-coded secret", re.compile(
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret)\b"
        r"[\"']?\s*[:=]\s*[\"']([^\"'\s]{12,})[\"']")),
]
SECRET_FILES = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
                ".npmrc", ".pypirc", "credentials.json")
SAFE_FILES = (".env.example", ".env.sample", ".env.template", "*.pub")
PLACEHOLDER = re.compile(r"(?i)example|dummy|sample|placeholder|changeme|change-me|your[_-]|xxxx|<[^>]*>|\$\{|"
                         r"process\.env|os\.environ|getenv|fake|test|redacted")
LIMIT = 20  # findings reported per unit


def findings(root: Path, base: str, sha: str, inherited: list[str], allow: list[str]) -> list[str] | None:
    """What looks like a secret in the unit's own added lines, as ``path:line: kind``. None if git can't tell."""
    listed = git(root, "rev-list", sha, f"^{base}")
    if listed.returncode != 0:
        return None
    mine = set(listed.stdout.split())
    below = [f"^{c}" for c in dict.fromkeys(inherited) if c in mine and c != sha]
    scope = [sha, f"^{base}", *below]
    shown = git(root, "log", "--no-merges", "--no-renames", "-p", "-U0", "--format=", *scope, "--")
    names = git(root, "log", "--no-merges", "--no-renames", "--name-only", "--diff-filter=AM", "-z", "--format=",
                *scope, "--")
    merges = git(root, "rev-list", "--merges", *scope)
    if shown.returncode != 0 or names.returncode != 0 or merges.returncode != 0:
        return None
    patches, files = [shown.stdout], names.stdout
    for merge in merges.stdout.split():  # what a merge added itself, beyond git's automatic merge of its parents
        baselines = verify.merge_baselines(root, merge)
        if baselines is None:
            return None
        for against in baselines:
            added = git(root, "diff", "--no-renames", "-U0", against, merge, "--")
            named = git(root, "diff", "--no-renames", "--name-only", "--diff-filter=AM", "-z", against, merge, "--")
            if added.returncode != 0 or named.returncode != 0:
                return None
            patches.append(added.stdout)
            files += named.stdout
    # File names come from git's own list, not the patch text: a binary file (.p12, a DER .key) has no patch.
    found = [f"{path}: a secret file is committed" for path in dict.fromkeys(files.replace("\n", "\0").split("\0"))
             if path and _secret_file(path)]
    allowed = [re.compile(p) for p in allow]
    for patch in patches:
        _scan(patch, allowed, found)
    return list(dict.fromkeys(found))


def _scan(patch: str, allowed: list[re.Pattern[str]], found: list[str]) -> None:
    path, line = "", 0
    for text in patch.splitlines():
        if text.startswith("+++ "):
            path = text[6:] if text.startswith("+++ b/") else ""
            continue
        if text.startswith("@@"):
            match = re.search(r"\+(\d+)", text)
            line = int(match.group(1)) if match else 0
            continue
        if not text.startswith("+") or not path:
            continue
        kind = _kind(text[1:], allowed)
        if kind:
            found.append(f"{path}:{line}: {kind}")
        line += 1


def _secret_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if any(fnmatch.fnmatch(name, p) for p in SAFE_FILES):
        return False
    return any(fnmatch.fnmatch(name, p) for p in SECRET_FILES)


def _kind(text: str, allowed: list[re.Pattern[str]]) -> str | None:
    if any(p.search(text) for p in allowed):
        return None
    for kind, pattern in PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        value = match.group(1) if match.groups() else match.group(0)
        if kind == "hard-coded secret" and PLACEHOLDER.search(value):
            continue
        return kind
    return None


def check(root: Path, charter: dict[str, Any], sha: str | None, inherited: list[str]) -> dict[str, Any] | None:
    """The gate's check, or None when the charter turns scanning off."""
    settings = charter.get("secrets") or {}
    if not settings.get("scan", True):
        return None
    if not sha:  # verify and process_paths already need a commit; with neither set, there's nothing to read
        return {"check": "no_secrets", "pass": True, "detail": "no commit recorded, so nothing to scan"}
    found = findings(root, charter["git"]["base"], sha, inherited, list(settings.get("allow") or []))
    if found is None:
        return {"check": "no_secrets", "pass": False,
                "detail": f"git can't compare {sha[:12]} with the base {charter['git']['base']}, so nothing was "
                          "scanned. Set git.base in the charter to a branch this repository has, or ask the owner "
                          "to waive this unit"}
    if not found:
        return {"check": "no_secrets", "pass": True, "detail": "no secrets in the lines its own commits add"}
    listed = "; ".join(found[:LIMIT]) + (f"; and {len(found) - LIMIT} more" if len(found) > LIMIT else "")
    return {"check": "no_secrets", "pass": False,
            "detail": f"possible secrets: {listed}. Remove them from the history (a new commit isn't enough: rewrite "
                      "the unit's branch), rotate any real one, or ask the owner to waive a false positive"}
