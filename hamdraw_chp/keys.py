"""The data-plane key table — ``chp_keys.json``.

CHP has three kinds of key and they are three deliberately separate lines
(``docs/chp-portal-plan.md`` §6.2):

* the **data-plane key** a client sends to use the models — this file, plus the
  default one the config node stores;
* the **console credential** an administrator uses to manage this table
  (``chp_admin.json``);
* the **engine token** CHP itself sends to the speech engine (``speech.token``
  in ``hamdraw_settings.json``).

They never share a value: a data-plane key leaking means someone else can use the
models, but a console credential leaking means someone else can *grant themselves*
a key.  That is why the console reads and writes this table through a route family
of its own, never through the door a request comes in by.

Keys are stored in clear text on purpose.  The file sits on the machine that
already holds the engine token and the model files, and an administrator has to be
able to copy a key out to hand it to somebody.  Mode 0600.

**A credential is letters, digits, ``-`` and ``_``** (:data:`ALPHABET`) — a rule
enforced where one is *taken in* (the console, the config node) rather than
apologised for at every comparison.

**An absent or unreadable file means "no keys from the table" — never "allow
everything".** Whether the deployment is public is decided elsewhere: it is public
only while *nothing at all* is configured (no default key and no table entry), and
that call belongs to :func:`hamdraw_chp.server._keys_configured`.  This module
answers one question — which entry matches this string — and no other.
"""

from __future__ import annotations

import hmac
import json
import os
import re
from pathlib import Path
from typing import Any

#: Same shape as ``settings.SCHEMA``: a versioned literal so a future change can
#: tell an old file from a new one instead of guessing from its contents.
SCHEMA = "chp-keys/v1"

#: Mirrors ``settings.ENVIRONMENT_FILE`` (``HAMDRAW_SETTINGS``): an environment
#: override for the path, and the package directory when there is none.  The
#: tests point this at a scratch file, which is also what makes them able to run
#: two deployments in one process.
ENVIRONMENT_FILE = "HAMDRAW_KEYS"

FILENAME = "chp_keys.json"

#: The only spelling of "every category".  Anything else in ``categories`` is an
#: exact list, and an empty one is a real answer: it is how an administrator
#: revokes a key without deleting it (the key still opens the door, and what is
#: behind the door is nothing).
ALL = "*"

#: **密码与 key 认得的全部字符：英文大小写字母、数字、``-`` 与 ``_``**（业主 2026-10-13 定）。
#: 中文不必支持，所以它不是"要小心绕开的一种输入"，而是一条**当场拒收**的规矩 ——
#: 与其在比较函数里为非 ASCII 留一条分支（``hmac.compare_digest`` 遇到它会抛，那曾
#: 是一条 500），不如让它根本存不进来。``secrets.token_urlsafe`` 生成的正好落在这个
#: 字母表里，所以"换一把"不用改。
ALPHABET = re.compile(r"[A-Za-z0-9_-]+")


def spelling_ok(value: Any) -> bool:
    """Is this a credential CHP accepts?  空串不算：空 key 是"没给"，不是"给了空的"。"""
    return ALPHABET.fullmatch(str(value or "")) is not None


def path() -> Path:
    override = os.environ.get(ENVIRONMENT_FILE, "").strip()
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent / FILENAME


def read() -> list[dict[str, Any]]:
    """The key entries, as stored — ``[]`` when there is no usable file.

    Never raises and never invents an entry: a file that was hand-edited into
    invalid JSON must not become a deployment where a typo silently grants
    access, and it must not take the plugin down either.  Read fresh every time
    rather than cached — "edit the file, next request sees it" is the whole
    hot-reload story for this table.
    """
    try:
        stored = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(stored, dict):
        return []
    entries = stored.get("keys")
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def matches(token: str, key: str) -> bool:
    """Constant-time equality — the one place in CHP a credential is compared.

    Compared as **UTF-8 bytes**, and that is now belt-and-braces rather than
    accommodation: everything *stored* is ASCII by rule (:data:`ALPHABET`), but
    the token that arrives is whatever somebody typed.  ``hmac.compare_digest``
    raises ``TypeError`` on a ``str`` holding a non-ASCII character, so a client
    who sends 中文 would get a **500** instead of a plain "no" — and a wrong
    credential is an ordinary answer, not an engine fault.

    Every comparison in CHP goes through here on purpose: the same defect lived in
    two places (the default key and this table), and one of them being right while
    the other raises is exactly the shape of bug that hides for months.

    A token that arrived in a header is decoded by the HTTP stack rather than by
    us, so whether it can round-trip a non-ASCII value is not ours to promise —
    if it cannot, the answer is a clean ``401``; the carrier for a request that has
    a body is ``chp_params.password``, which is JSON and therefore real UTF-8.
    """
    return hmac.compare_digest(token.encode("utf-8"), key.encode("utf-8"))


def resolve(token: str, entries: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """The entry whose ``key`` equals ``token``, or ``None``.

    ``entries`` lets a caller that already read the table pass it in, so the
    request path reads the file once per request instead of three times.

    Two deliberate details:

    * **An empty token never matches.**  An entry with an empty ``key`` would
      otherwise turn "the client sent no key" into "the client sent the key that
      opens everything" — the same trap ``_authorized`` avoids by checking the
      open state first.
    * **No early exit.**  The comparison runs against every entry even after one
      has matched, so timing never says how many characters of a key were right.
    """
    if not token:
        return None
    found: dict[str, Any] | None = None
    for entry in read() if entries is None else entries:
        key = str(entry.get("key") or "")
        if key and matches(token, key) and found is None:
            found = entry
    return found


def allowed_of(record: dict[str, Any] | None) -> set[str] | None:
    """The category set to hand to :mod:`hamdraw_chp.capabilities` — ``None`` means all.

    ``None`` (not an empty set) is what the capability tables understand as "do
    not filter", which is why ``["*"]`` has to be translated here rather than
    passed through: an empty set would mean the opposite of what it says.
    """
    raw = (record or {}).get("categories")
    names = [str(item) for item in raw] if isinstance(raw, list) else []
    if ALL in names:
        return None
    return set(names)


def permits(record: dict[str, Any] | None, category: str) -> bool:
    """May this key use that category?

    The **execution layer** (``docs/chp-portal-plan.md`` §3.3, the load-bearing
    half).  What ``/chp/info`` leaves out is a courtesy to the UI; anyone who
    knows a category name can POST it directly, so the refusal has to happen
    here.  "看不到"是障眼法, "拒收"才是权限.
    """
    allowed = allowed_of(record)
    return allowed is None or str(category) in allowed


def label_of(record: dict[str, Any] | None) -> str:
    """How to name a key back to a human without printing the key.

    The console shows ``label`` and falls back to ``id``; a record with neither
    (the default key, the open state) is named by its source.  Never the key
    itself — that is what ``detail`` in an error would leak.
    """
    record = record or {}
    return str(record.get("label") or record.get("id") or record.get("source") or "").strip()


__all__ = ["ALPHABET", "ALL", "ENVIRONMENT_FILE", "FILENAME", "SCHEMA", "allowed_of",
           "label_of", "matches", "path", "permits", "read", "resolve", "spelling_ok"]
