"""The management plane — ``chp_admin.json`` and the console that writes ``chp_keys.json``.

CHP has three kinds of key and they are three deliberately separate lines
(:mod:`.keys` lists them).  This module owns the second one and, with it, the
only thing in the plugin that may **write** the table the first one reads.

Why this is a module and not four routes inside :mod:`.server`: the separation
between the console credential and the data-plane key has to be structural, not
a matter of discipline.  ``keys.py`` answers exactly one question ("which entry
matches this string") and never writes; everything that can *change* what the
data plane will accept lives here, behind :func:`authenticates`.  A bug in the
routes cannot grant access, because the routes have no door of their own.

Four decisions worth knowing before editing anything here:

* **The credential is read once per process.**  ``chp_admin.json`` is a file an
  administrator edits over SSH, and the owner's rule is that changing it takes
  effect **after a restart** — so this is cached on purpose, unlike the key table
  (which is hot: "edit the file, next request sees it").  :func:`forget` exists
  so a test can model the restart instead of pretending it happened.
* **Basic only, and never through the data plane's door.**  The data plane
  accepts ``Bearer`` / ``Basic`` / ``X-HamDraw-Password`` and reads a ``Basic``
  header as "the part after the colon is the key" — so a console that used the
  same helper could be opened by a data-plane key.  :func:`authenticates` takes
  the header and nothing else, and the routes never touch ``_token_of``.
* **The console may only grant what the code has already registered.**  The
  checkbox list *is* the category table plus the speech category; a name that is
  not on it is refused, the same discipline as the data plane's
  ``unsupported_category``.  There is no "add a model" action anywhere, because
  a capability is code (:mod:`.capabilities` says why).
* **No credential can be edited from here, and the page has no field for one.**
  The browser authenticates with its own Basic dialog (the 401 carries
  ``WWW-Authenticate``), so the HTML contains no login form at all.  That is the
  point of the file split: the console has no way to change the credential
  because the credential is not in the files it may write.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from . import capabilities as capabilities_module
from . import keys as keys_module
from . import settings as settings_module
from . import speech as speech_module

#: Same idea as ``settings.SCHEMA`` / ``keys.SCHEMA``: a versioned literal, so a
#: future change can tell an old file from a new one instead of guessing.
SCHEMA = "chp-admin/v1"

FILENAME = "chp_admin.json"

#: The path override, spelled like ``HAMDRAW_KEYS``.  The default is the package
#: directory — the same three files sit together, which is what makes "one
#: directory, three lines" a thing an operator can see rather than remember.
ENVIRONMENT_FILE = "HAMDRAW_ADMIN"

#: Used only while ``chp_admin.json`` does not exist.  A default password is a
#: deliberate choice here, not an oversight: the console is reachable from the
#: machine that already holds the models, the default is printed in the README,
#: and an administrator who never wrote the file cannot be locked out by it.  Any
#: deployment exposed to a network should replace it — which is what the file is
#: for.
DEFAULT_USER = "hamster"
DEFAULT_PASSWORD = "imahamster"

REALM = "CHP 控制台"

#: A key's own identity.  ``id`` is what the console addresses an entry by: the
#: key string itself must never travel in a URL, where it would land in browser
#: history and in a log line.
ID_PREFIX = "k_"
KEY_BYTES = 24

#: The console's route family.  It lives under ``API_ROOT`` because it is the
#: same service on the same port (the plan's wording: 控制台是 CHP 的一部分), but
#: it is **deliberately absent from ``capabilities.ENDPOINTS``** — a client reads
#: its addresses from the document, so a family that is not in the document is a
#: family no client knows exists.  The contract stays about the models.
ADMIN_ROOT = f"{capabilities_module.API_ROOT}/admin"
PAGE_PATH = f"{ADMIN_ROOT}/"
CAPABILITIES_PATH = f"{ADMIN_ROOT}/capabilities"
KEYS_PATH = f"{ADMIN_ROOT}/keys"
#: ``{key_id}`` is aiohttp's placeholder; an entry is addressed by ``id`` and
#: never by the key string.
KEY_PATH = f"{KEYS_PATH}/{{key_id}}"

#: The console page itself: one static file, no build chain, no asset directory.
PAGE_FILE = "admin.html"

#: Every route the console has, written out as data.  ``register_routes`` wires
#: them one by one (so a reader can see which function serves which path), and
#: the tests compare the wired set against this list — two independent sources,
#: which is what makes "a credential-editing route was added" impossible to do
#: without the acceptance check noticing.
ROUTES: tuple[tuple[str, str], ...] = (
    ("GET", ADMIN_ROOT),
    ("GET", PAGE_PATH),
    ("GET", CAPABILITIES_PATH),
    ("GET", KEYS_PATH),
    ("POST", KEYS_PATH),
    ("POST", KEY_PATH),
    ("DELETE", KEY_PATH),
)


def page() -> str:
    """The console page's bytes.  Read per request so editing it needs no restart
    (it holds no secret — the credential is the browser's, and the table comes
    from the API)."""
    return (Path(__file__).resolve().parent / PAGE_FILE).read_text(encoding="utf-8")


class AdminError(Exception):
    """A refusal that belongs to the console — the caller turns ``code`` into a response.

    Same shape as :class:`hamdraw_chp.speech.SpeechError`, and it carries a
    ``detail`` for the same reason: the console is a form, and a form that is told
    "no" has to be able to say which field.
    """

    def __init__(self, code: str, message: str = "", detail: Any = None) -> None:
        super().__init__(message or code)
        self.code = str(code)
        self.message = message
        self.detail = detail


# --------------------------------------------------------------------------- #
# the console credential
# --------------------------------------------------------------------------- #

def path() -> Path:
    override = os.environ.get(ENVIRONMENT_FILE, "").strip()
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parent / FILENAME


_CREDENTIALS: dict[str, str] | None = None


def _read() -> dict[str, str]:
    """The file, or the defaults.  Never raises — a broken file is not a lockout.

    A hand-edited file that no longer parses must not take the console away from
    the person who is logged in trying to fix it, and it must not quietly become
    "no credential required" either: it falls back to the documented default,
    which is a known value rather than an empty one.
    """
    record = {"user": DEFAULT_USER, "password": DEFAULT_PASSWORD, "source": "default"}
    try:
        stored = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return record
    if not isinstance(stored, dict):
        return record
    user = str(stored.get("user") or "").strip() or DEFAULT_USER
    password = str(stored.get("password") or "")
    if not password:
        # 空密码 = 谁都进不来。这不是"没设密码"，是"写坏了"，所以回默认值，而**不是**
        # 回一个空串 —— 那样 `Basic base64("任意用户名:")` 就中了。
        return record
    return {"user": user, "password": password, "source": "file"}


def load() -> dict[str, str]:
    """The credential in force **for this process** — cached, hence "restart to apply".

    :func:`forget` is the restart, for tests.  Nothing else may clear it: a
    console that re-read the file per request would mean a credential change
    takes effect the moment somebody with file access writes it, which is the
    opposite of what "only this machine can change it, and changing it is a
    deliberate act" buys.
    """
    global _CREDENTIALS
    if _CREDENTIALS is None:
        _CREDENTIALS = _read()
    return dict(_CREDENTIALS)


def forget() -> None:
    """Drop the cache — a test's way of simulating a restart."""
    global _CREDENTIALS
    _CREDENTIALS = None


def challenge() -> dict[str, str]:
    """The header that makes a browser ask, so the page needs no login form."""
    return {"WWW-Authenticate": f'Basic realm="{REALM}", charset="UTF-8"'}


def _basic(header: str) -> tuple[str, str] | None:
    """``Authorization: Basic …`` → ``(user, password)``; anything else → ``None``.

    Only ``Basic``.  Accepting ``Bearer`` here would make a data-plane key an
    administrator credential, which is the one confusion the three lines exist to
    prevent.  Split on the **first** colon: that is what the scheme says, and it
    lets the password contain colons (a data-plane key containing one is why the
    data plane takes the part after the colon rather than the whole string).
    """
    value = str(header or "").strip()
    if value[:6].lower() != "basic ":
        return None
    try:
        raw = base64.b64decode(value[6:].strip(), validate=True).decode("utf-8")
    except Exception:
        return None
    user, _, password = raw.partition(":")
    return user, password


def authenticates(header: str) -> bool:
    """Is this header the administrator's?  Takes the header, and nothing else.

    ``keys.matches`` is the project's single comparison point: it survives
    non-ASCII (``hmac.compare_digest`` raises on a ``str`` holding one) and it is
    constant-time.  Both halves are compared even when the user is wrong, so
    neither half leaks through timing.
    """
    offered = _basic(header)
    if offered is None:
        return False
    record = load()
    user_ok = keys_module.matches(offered[0], record["user"])
    password_ok = keys_module.matches(offered[1], record["password"])
    return bool(user_ok and password_ok)


# --------------------------------------------------------------------------- #
# what the console may grant
# --------------------------------------------------------------------------- #

def categories() -> list[str]:
    """Every name a key may be granted: the image categories, then ``speak``.

    The image side comes from ``capabilities.CATEGORY_TABLE`` — **the same table
    the data plane serves** — and the speech category from :mod:`.speech`.  This
    one place exists because ``capabilities`` cannot import ``speech`` (speech
    imports it) and neither may learn about the console; the union belongs to
    whoever needs it, and today that is only here.
    """
    return [*capabilities_module.categories(), speech_module.CATEGORY]


def unknown(names: Iterable[str]) -> list[str]:
    """Which of these are not grantable — the empty list is the permissive answer."""
    known = set(categories())
    return sorted({str(name) for name in names
                   if str(name) != keys_module.ALL and str(name) not in known})


def capability_rows(files_of: Callable[[str], Any] | None = None) -> list[dict[str, Any]]:
    """The read-only list the page renders its checkboxes from.

    ``ready`` / ``missing`` are the data plane's own judgement (the caller passes
    the same ``files_of`` the discovery document uses), because a console that
    disagreed with ``/chp/info`` about what is runnable would send an
    administrator hunting for a configuration problem that does not exist.
    """
    rows: list[dict[str, Any]] = []
    for name in capabilities_module.categories():
        entry = capabilities_module.category_of(name)
        ability = (files_of or (lambda _category: {}))(name) or {}
        rows.append({
            "category": name,
            "rule": str(entry["rule"]),
            "label": dict(entry["label"]),
            "ready": bool(ability.get("ready")),
            "missing": [str(item) for item in ability.get("missing") or []],
            "source": "image",
        })
    return [*rows, _speech_row()]


def _speech_row() -> dict[str, Any]:
    ability = speech_module.ability_of(settings_module.speech())
    return {
        "category": speech_module.CATEGORY,
        "rule": speech_module.RULE,
        "label": dict(speech_module.rule_entry()["label"]),
        "ready": bool(ability["ready"]),
        "missing": [str(item) for item in ability["missing"]],
        "source": "speech",
    }


def rows() -> list[dict[str, Any]]:
    """The table as the console shows it: the file's entries, then the default key.

    The default key appears **read-only** and without its value.  It is a real key
    — the config node's password, or ``HAMDRAW_PASSWORD`` — and an administrator
    who could not see that it exists would wonder why a deployment with an empty
    table still answers.  Its value is not the console's to publish: the console
    cannot change it, and printing it would put a working credential into a
    browser page and into whatever proxies that response.
    """
    described: list[dict[str, Any]] = []
    for entry in keys_module.read():
        granted = entry.get("categories")
        described.append({
            "id": str(entry.get("id") or ""),
            "label": keys_module.label_of(entry),
            "key": str(entry.get("key") or ""),
            "categories": [str(item) for item in granted] if isinstance(granted, list) else [],
            "created": str(entry.get("created") or ""),
            "source": "table",
        })
    if settings_module.password():
        described.append({
            "id": "",
            "label": "默认钥匙（配置节点的密码 / HAMDRAW_PASSWORD）",
            "key": "",
            "categories": [keys_module.ALL],
            "created": "",
            "source": "default",
        })
    return described


# --------------------------------------------------------------------------- #
# writing the table (the console is the only writer)
# --------------------------------------------------------------------------- #

def _now() -> str:
    """An ISO timestamp with the machine's own offset, second precision."""
    return datetime.now(timezone(timedelta())).isoformat(timespec="seconds")


def _clean_categories(names: Any) -> list[str]:
    """A posted grant list → the list to store, or ``AdminError``.

    ``["*"]`` is kept as the single spelling of "everything" rather than expanded
    into today's five names + ``speak``: a key granted ``*`` and a key granted the
    current list are two different promises, and only the first one keeps working
    when a sixth capability is registered later.
    """
    if names is None:
        return []
    if not isinstance(names, list):
        raise AdminError("bad_request", "categories 必须是一个数组。", detail={"categories": names})
    cleaned = [str(item).strip() for item in names]
    refused = [item for item in unknown(cleaned) if item]
    if refused:
        raise AdminError("unsupported_category",
                         "清单里没有这些场景：控制台只能授权代码里已经注册的 category。",
                         detail={"unknown": refused, "known": categories()})
    return [item for item in cleaned if item]


def _clean_key(value: Any) -> str:
    """A posted key string, or a fresh one.  Never the administrator's own credential.

    The check is not politeness.  The data plane reads a ``Basic`` header as "the
    part after the colon is the key" (``server._token_of``) — so a table entry
    equal to the console's *password* would make ``Basic hamster:imahamster`` open
    the data plane.  Refusing to store one is the only place this can be enforced
    without changing the data plane's existing carriers.
    """
    offered = str(value or "").strip()
    if not offered:
        return secrets.token_urlsafe(KEY_BYTES)
    credential = load()
    if keys_module.matches(offered, credential["password"]) \
            or keys_module.matches(offered, credential["user"]):
        raise AdminError("bad_request",
                         "这把 key 与控制台凭据同值：数据面也认 Basic，"
                         "那样控制台密码会顺带变成一把数据面钥匙。请换一个值。",
                         detail={"reason": "credential_collision"})
    return offered


def _entry(fields: dict[str, Any], *, seed: dict[str, Any] | None = None) -> dict[str, Any]:
    """One posted body → one stored entry.  ``seed`` is the entry being edited.

    Absent fields keep what the entry already had, so "change the label" does not
    silently reset the grants — which is the mistake a form that posts every field
    every time invites.
    """
    seed = seed or {}
    label = str(fields["label"] or "").strip() if "label" in fields \
        else str(seed.get("label") or "").strip()
    granted = _clean_categories(fields["categories"]) if "categories" in fields \
        else _clean_categories(seed.get("categories"))
    key = _clean_key(fields.get("key")) if ("key" in fields or not seed) \
        else str(seed.get("key") or "")
    identifier = str(seed.get("id") or "").strip() or ID_PREFIX + secrets.token_urlsafe(9)
    created = str(seed.get("created") or "").strip() or _now()
    return {"id": identifier, "label": label, "key": key,
            "categories": granted, "created": created}


def store(entries: list[dict[str, Any]]) -> None:
    """Write the table atomically, 0600, in the shape ``keys.read`` expects.

    Atomic because ``keys.read`` runs on every request: a half-written file would
    be read by somebody mid-write and would answer "no keys from the table" — a
    deployment that momentarily locks out, or opens up, depending on what else is
    configured.  0600 because the values in it are credentials.
    """
    destination = keys_module.path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(json.dumps({"schema": keys_module.SCHEMA, "keys": entries},
                                    ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, destination)


def add(fields: Any) -> dict[str, Any]:
    """Append one key.  The answer carries the key value — the one moment an
    administrator needs to copy it out."""
    if not isinstance(fields, dict):
        raise AdminError("bad_request", "请求体必须是一个 JSON 对象。")
    entry = _entry(fields)
    entries = keys_module.read()
    if any(str(item.get("id") or "") == entry["id"] for item in entries):
        raise AdminError("bad_request", "这个 id 已经有了。", detail={"id": entry["id"]})
    store([*entries, entry])
    return entry


def update(identifier: str, fields: Any) -> dict[str, Any]:
    """Edit one key in place, addressed by ``id`` (never by the key itself)."""
    if not isinstance(fields, dict):
        raise AdminError("bad_request", "请求体必须是一个 JSON 对象。")
    wanted = str(identifier or "").strip()
    entries = keys_module.read()
    for index, entry in enumerate(entries):
        if str(entry.get("id") or "") != wanted:
            continue
        merged = _entry(fields, seed=entry)
        if fields.get("regenerate"):
            merged["key"] = _clean_key("")
        entries[index] = merged
        store(entries)
        return merged
    raise AdminError("not_found", "没有这个 id 的 key。", detail={"id": wanted})


def drop(identifier: str) -> bool:
    """Remove one key.  ``False`` when there was nothing to remove."""
    wanted = str(identifier or "").strip()
    entries = keys_module.read()
    kept = [entry for entry in entries if str(entry.get("id") or "") != wanted]
    if len(kept) == len(entries):
        return False
    store(kept)
    return True


__all__ = ["ADMIN_ROOT", "AdminError", "CAPABILITIES_PATH", "DEFAULT_PASSWORD",
           "DEFAULT_USER", "ENVIRONMENT_FILE", "FILENAME", "ID_PREFIX", "KEY_BYTES",
           "KEYS_PATH", "KEY_PATH", "PAGE_FILE", "PAGE_PATH", "REALM", "ROUTES",
           "SCHEMA", "add", "authenticates", "capability_rows", "categories",
           "challenge", "drop", "forget", "load", "page", "path", "rows", "store",
           "unknown", "update"]
