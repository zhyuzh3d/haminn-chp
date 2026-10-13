"""The out-of-process backend: this process talks to a ComfyUI over HTTP.

``python -m hamdraw_chp serve`` speaks CHP on a machine where the plugin is not
loaded, and this is what answers the vocabulary's questions from there.  The half
of it that must not change between modes — job state, progress, queue position,
the outputs of a history entry, one category's resolved files — is *the same
code* as the in-process backend (:mod:`hamdraw_chp.backends.records`), because a
client must not be able to tell the two apart.  What is written here is only what
genuinely differs: **where the answers come from**.

Five differences, and each one has a consequence:

* **the model list** comes from the upstream's own ``object_info`` enumerations,
  never from a listing on this disk.  The document has to speak about the machine
  that will run the job, and only the upstream can say what that machine has
  (§4.3).  Because that is a request and the vocabulary's ``available`` /
  ``absent`` are synchronous, the list is **kept in a snapshot** refreshed by
  :func:`refresh` — which is also what keeps ``/chp/info`` instant when the
  upstream is slow or gone: the document never waits on it.
* **job identity.** A ``prompt_id`` is the upstream's handle on its own queue, so
  this backend mints CHP job ids and keeps the map.  Everything the protocol
  layer sees — ``queue()``'s lists, ``history()`` — is translated back to our ids,
  so ``/chp/jobs/{id}`` means the same thing in both modes.  The map is in
  memory: a job submitted before this process started can no longer be named, and
  ``not_found`` is the honest answer for it.
* **reference images** are uploaded (``POST /upload/image``) before the graph is
  queued, and each ``LoadImage`` input is rewritten to the name the upstream
  answered with.  A graph naming a file the upstream cannot open is a job that
  fails at validation, however carefully it was built here.
* **outputs** are fetched (``GET /view``) into a temporary file, because
  ``server.py`` serves them with ``web.FileResponse`` and this process does not
  have them on disk.
* **the queue** is asked for rather than read, and only *our* jobs are reported:
  a job nobody here submitted has no CHP id, and ``queue_position`` would be a
  number about somebody else's job.  That is also why ``pending`` here counts our
  own queue against the ``busy`` ceiling.

**The upstream address comes from ``hamdraw_settings.json`` and from nowhere
else** — never a request field (§4.3).  A key that could name the upstream would
be a key that turns CHP into a proxy for any address, which is the same rule
``translate.url`` and ``speech.url`` already follow.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import aiohttp

from .. import capabilities as capabilities_module
from .. import settings as settings_module
from . import BackendUnavailable
from . import records
from .records import (MEDIA_TYPES, error_of, outputs, progress_state, prompt_id_of,  # noqa: F401
                      queue_position, resolve_category, state_of, status_of)

#: The same client name the plugin sends, so ComfyUI's own UI is not surprised by
#: two strangers with different names when only one of them is talking.
CLIENT_ID = "hamdraw"

#: The subfolder reference images live in, on both sides of the wire.  It is the
#: same name the plugin uses locally (``server.INPUT_SUBFOLDER``), because the
#: graph is built before either mode knows which one it is.
INPUT_SUBFOLDER = "hamdraw"

#: One upstream call.  Short on purpose: these are small control requests on a LAN
#: link, and an upstream that takes ten seconds to answer is an upstream that is
#: not there — waiting longer would only make our own clients wait too.
TIMEOUT = 10.0

#: How often the snapshots are refreshed.  It is also the age of the worst answer
#: ``/chp/info`` can give about the model list, which is why it is not minutes.
REFRESH_SECONDS = 15.0

#: Where each ComfyUI folder's file names can be read out of ``object_info``.
#: The enumeration on a loader node's input **is** the folder's listing — that is
#: the upstream's own answer to "what do you have", asked instead of guessing.
FOLDER_NODES: dict[str, tuple[str, str]] = {
    "checkpoints": ("CheckpointLoaderSimple", "ckpt_name"),
    "diffusion_models": ("UNETLoader", "unet_name"),
    "text_encoders": ("CLIPLoader", "clip_name"),
    "vae": ("VAELoader", "vae_name"),
    "loras": ("LoraLoader", "lora_name"),
}

#: The node whose ``image`` input names a file the upstream must be able to open.
LOADER_NODE = "LoadImage"

#: Where a reference image lands before it is uploaded, and where a fetched output
#: lands before it is served.  Both are this machine's temporary directory: they
#: are load/unload points, not storage — nothing here is meant to survive.
INPUT_DIRECTORY = Path(tempfile.gettempdir()) / "haminn-chp-input"
OUTPUT_DIRECTORY = Path(tempfile.gettempdir()) / "haminn-chp-output"

#: 我们自己的作业号 → 上游的 ``prompt_id``，以及反向的那一张。 反向那张是必需的：
#: 上游的队列与历史只认 ``prompt_id``，而协议层交给这里的一律是我们的号。
_PROMPTS: dict[str, str] = {}
_JOBS: dict[str, str] = {}

#: 上游清单的快照。``None`` = **这一次没问到**（上游不在，或答得不成样子）；
#: ``{}`` = 问到了但它没有这几个节点。 两者的区别就是"不敢判"与"真的没有"。
_LISTING: dict[str, list[str]] | None = None
_LISTED_AT = 0.0

_PENDING: bool = False


class _Unreachable(Exception):
    """No answer from the upstream at all — an absence, not an HTTP error."""


# --------------------------------------------------------------------------- #
# talking to the upstream
# --------------------------------------------------------------------------- #

def _upstream() -> str:
    return str(settings_module.serve()["upstream"]).rstrip("/")


def _url(path: str, query: dict[str, Any] | None = None) -> str:
    address = f"{_upstream()}{path}"
    if query:
        address = f"{address}?{urlencode({key: value for key, value in query.items() if value != ''})}"
    return address


def _log_failure(path: str, detail: str) -> None:
    """A line in this machine's log — never in a response.

    Same rule as the speech engine's: what went wrong with the *upstream* is
    operational detail, and the client gets a code it can act on.
    """
    print(f"[hamdraw_chp] 上游 {path} 调用失败: {detail}")


async def _call(method: str, path: str, *, payload: Any = None, upload: bytes | None = None,
                content_type: str = "", query: dict[str, Any] | None = None) -> tuple[int, bytes]:
    """One call to the upstream, returning ``(status, body)``.

    Raises :class:`_Unreachable` when there is no answer at all — refused
    connection, timeout, a body that never finished.  The distinction is load
    bearing: "the upstream said no" is a diagnosis, "the upstream is not there"
    is a different one, and they need different sentences.
    """
    url = _url(path, query)
    headers = {"Content-Type": content_type} if content_type else {}
    timeout = aiohttp.ClientTimeout(total=TIMEOUT)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(method, url, json=payload, data=upload,
                                       headers=headers) as answer:
                return answer.status, await answer.read()
    except Exception as exc:  # noqa: BLE001 — 任何传输层故障都归成同一句"问不到"
        _log_failure(path, f"{type(exc).__name__}: {exc}")
        raise _Unreachable(f"{type(exc).__name__}: {exc}") from None


async def _json_call(method: str, path: str, *, query: dict[str, Any] | None = None,
                     payload: Any = None, upload: bytes | None = None,
                     content_type: str = "") -> tuple[int, Any]:
    status, body = await _call(method, path, query=query, payload=payload, upload=upload,
                              content_type=content_type)
    try:
        return status, json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return status, None


def _multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes]]) -> tuple[bytes, str]:
    """A form body, spelled out rather than borrowed from ``aiohttp.FormData``.

    Fifteen lines for one upload, and the reason is the offline tests: they drive
    this backend through a stand-in session, and a body they can read as bytes is
    a request they can check (does it carry the file name? the subfolder?) instead
    of a black box they can only count.
    """
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                     f"{value}\r\n".encode("utf-8"))
    for name, (filename, blob) in files.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
                     f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'
                     .encode("utf-8") + blob + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# --------------------------------------------------------------------------- #
# the model list — a snapshot, refreshed by the service
# --------------------------------------------------------------------------- #

def _enumerations(info: Any) -> dict[str, list[str]] | None:
    """``object_info`` → ``{folder: [file names]}``, or ``None`` if it is unusable."""
    if not isinstance(info, dict):
        return None
    folders: dict[str, list[str]] = {}
    for folder, (node, field) in FOLDER_NODES.items():
        entry = info.get(node)
        inputs = entry.get("input") if isinstance(entry, dict) else None
        for section in ("required", "optional"):
            block = inputs.get(section) if isinstance(inputs, dict) else None
            values = block.get(field) if isinstance(block, dict) else None
            if isinstance(values, list) and values and isinstance(values[0], list):
                folders[folder] = [str(item) for item in values[0]]
                break
    return folders


async def refresh() -> bool:
    """Ask the upstream what it has; ``True`` when it answered.

    Called by the service's refresher (``cli.py``) and by nothing else, because
    this is the only part of the vocabulary that is a *deployment* fact rather
    than a per-request one.  What it leaves behind is a snapshot that the
    synchronous ``available`` / ``absent`` read — which is what keeps the
    discovery document from ever blocking on the upstream.
    """
    global _LISTING, _LISTED_AT
    try:
        status, payload = await _json_call("GET", "/object_info")
    except _Unreachable:
        status, payload = 0, None
    listing = _enumerations(payload) if status == 200 else None
    _LISTING, _LISTED_AT = listing, time.monotonic()
    return listing is not None


def listed_at() -> float:
    """When the snapshot was last written (``0`` = never).  For a log line."""
    return _LISTED_AT


async def keep_fresh() -> None:
    """Refresh forever, at :data:`REFRESH_SECONDS`, until cancelled.

    An upstream that is down is not an error here — the snapshot becomes "cannot
    see it" and the document says so — so this loop never gives up and never
    raises: the service has to stay useful while the thing it talks to restarts.
    """
    global _PENDING
    if _PENDING:
        return
    _PENDING = True
    try:
        while True:
            await refresh()
            await asyncio.sleep(REFRESH_SECONDS)
    except asyncio.CancelledError:
        _PENDING = False
        raise


def forget() -> None:
    """Drop every cache: the snapshot and the job map.

    A test wants this between cases; an operator wants it after pointing the
    service at a different ComfyUI.
    """
    global _LISTING, _LISTED_AT
    _LISTING, _LISTED_AT = None, 0.0
    _PROMPTS.clear()
    _JOBS.clear()


# --------------------------------------------------------------------------- #
# models
# --------------------------------------------------------------------------- #

def available(folder: str) -> list[str]:
    """The upstream's own enumeration of that folder — empty when we could not ask."""
    listing = _LISTING
    if listing is None:
        return []
    return list(listing.get(str(folder), []))


def absent(folder: str, name: str) -> bool:
    """Is this file missing from a **reachable** upstream?

    Read this next to ``comfy_inproc.absent``: they differ on purpose, in exactly
    one case.  There, an unreadable listing means "cannot judge", because the
    listing comes from this very disk and ComfyUI may still be starting up — so a
    job is let through and ComfyUI's own validation says no if it really is
    missing.  Here an unreadable listing can also mean **the machine that runs the
    job does not answer at all**, and that is not a state to let work through in:
    every name is reported missing, the document says ``ready: false`` for every
    category, and a submission is refused with ``no_upstream`` instead of being
    queued for nobody.

    A reachable upstream that simply has no such loader node keeps the in-process
    meaning: cannot judge, so not missing.
    """
    if not name:
        return False
    if _LISTING is None:
        return True
    listing = available(folder)
    return bool(listing) and name not in listing


def abilities(files_of: Any) -> Any:
    """Same shape as the in-process one, plus ``reason`` when nothing can run.

    The extra key is what turns "not ready" into an answerable question.  A
    caller reading ``ready: false`` on every category cannot tell "you have not
    picked a model yet" from "the machine that runs the jobs is not answering",
    and those two have nothing in common: one is fixed on the config page, the
    other on the other box.  ``reason`` carries the CHP error code for the second
    case — the same code a submission in that state is refused with, and the same
    one listed in the document's ``errors``.
    """
    def resolve(category: str) -> dict[str, Any]:
        resolved = resolve_category(category, files_of(str(category)), absent)
        if not resolved["ready"] and _LISTING is None:
            resolved["reason"] = capabilities_module.NO_UPSTREAM
        return resolved

    return resolve


# --------------------------------------------------------------------------- #
# the queue and its history
# --------------------------------------------------------------------------- #

def _ours(items: Any) -> list[str]:
    """Translate one of the upstream's queue lists into **our** job ids.

    A job nobody here submitted is left out: it has no CHP id to report, and a
    list that mixed the two would make ``queue_position`` a number about somebody
    else's job.
    """
    found: list[str] = []
    for item in items or []:
        job_id = _JOBS.get(prompt_id_of(item), "")
        if job_id:
            found.append(job_id)
    return found


async def queue() -> tuple[list[str], list[str]]:
    try:
        status, payload = await _json_call("GET", "/queue")
    except _Unreachable:
        return [], []
    if status != 200 or not isinstance(payload, dict):
        return [], []
    return _ours(payload.get("queue_running")), _ours(payload.get("queue_pending"))


async def history(job_id: str) -> dict[str, Any] | None:
    """That run's entry, fetched by the prompt id it was queued under.

    ``None`` for a job this process never queued — the map is in memory, so a job
    from before the last restart of the service cannot be named any more.  That is
    the same answer a job that never existed gets, and there is no honest third
    one to give: the upstream's history is keyed by *its* ids and we do not have
    the one we would have to ask for.
    """
    prompt_id = _PROMPTS.get(str(job_id), "")
    if not prompt_id:
        return None
    try:
        status, payload = await _json_call("GET", f"/history/{prompt_id}")
    except _Unreachable:
        return None
    if status != 200 or not isinstance(payload, dict):
        return None
    entry = payload.get(prompt_id)
    return entry if isinstance(entry, dict) else None


# --------------------------------------------------------------------------- #
# submitting
# --------------------------------------------------------------------------- #

def _loaders(graph: Any) -> list[tuple[dict[str, Any], str]]:
    """Every ``LoadImage`` input that names one of **our** reference images.

    Only paths under :data:`INPUT_SUBFOLDER` are touched: a graph that names a
    file somebody else put on the upstream is not ours to rewrite.
    """
    found: list[tuple[dict[str, Any], str]] = []
    for node in (graph or {}).values():
        if not isinstance(node, dict) or str(node.get("class_type") or "") != LOADER_NODE:
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        image = str(inputs.get("image") or "")
        if image.startswith(f"{INPUT_SUBFOLDER}/"):
            found.append((inputs, image))
    return found


async def _offer_reference(inputs: dict[str, Any], image: str) -> None:
    """Upload the file behind one ``LoadImage`` input, then rewrite that input.

    **以它答的那个名字为准**, not the one we sent: the upstream may keep the
    subfolder, may move the file, and may rename a collision — and the graph has
    to name the file that will actually be there.
    """
    local = INPUT_DIRECTORY / image
    if not local.is_file():
        raise BackendUnavailable("internal", "参考图暂存文件不见了。")
    name = Path(image).name
    body, content_type = _multipart(
        {"subfolder": INPUT_SUBFOLDER, "type": "input", "overwrite": "true"},
        {"image": (name, local.read_bytes())},
    )
    try:
        status, payload = await _json_call("POST", "/upload/image", upload=body,
                                          content_type=content_type)
    except _Unreachable:
        raise BackendUnavailable(capabilities_module.NO_UPSTREAM) from None
    if status != 200:
        raise BackendUnavailable("internal", "参考图上传失败。")
    answer = payload if isinstance(payload, dict) else {}
    subfolder = str(answer.get("subfolder") or "").strip("/")
    uploaded = str(answer.get("name") or "").strip() or name
    inputs["image"] = f"{subfolder}/{uploaded}" if subfolder else uploaded


async def submit(graph: dict[str, Any]) -> str:
    """Queue the graph upstream and hand back **our** job id for it."""
    prompt_id = await _enqueue(graph)
    job_id = str(uuid.uuid4())
    _PROMPTS[job_id] = prompt_id
    _JOBS[prompt_id] = job_id
    return job_id


async def _enqueue(graph: dict[str, Any]) -> str:
    for inputs, image in _loaders(graph):
        await _offer_reference(inputs, image)
    try:
        status, payload = await _json_call("POST", "/prompt",
                                           payload={"prompt": graph, "client_id": CLIENT_ID})
    except _Unreachable:
        raise BackendUnavailable(capabilities_module.NO_UPSTREAM) from None
    if status == 200 and isinstance(payload, dict) and payload.get("prompt_id"):
        return str(payload["prompt_id"])
    if status == 400:
        raise BackendUnavailable("invalid_workflow", _refusal(payload),
                                 detail={"node_errors": (payload or {}).get("node_errors")})
    raise BackendUnavailable("internal", "上游拒绝了这个任务。")


def _refusal(payload: Any) -> str:
    """ComfyUI's own sentence about why the graph would not queue.

    Carried out verbatim, exactly as the in-process backend carries the one
    ``execution.validate_prompt`` produced: "节点名: 原因" is the only place the
    reason exists, and it is what lets an operator see that a model file is
    missing instead of reading "校验失败".
    """
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        details = str(error.get("details") or "").strip()
        return " ".join(part for part in (message, details) if part)
    if isinstance(error, str):
        return error
    nodes = payload.get("node_errors")
    if isinstance(nodes, dict) and nodes:
        return "; ".join(f"{name}: {json.dumps(value, ensure_ascii=False)}"
                         for name, value in nodes.items())
    return ""


async def cancel(job_id: str, running: list[str], pending: list[str]) -> bool:
    """Drop it from the upstream queue, or interrupt it if it is the one running.

    Which of the two applies is still read off the queue lists the caller already
    has, so the decision stays in one place — and it is the *same* decision the
    in-process backend makes, even though the two are spelled with different
    upstream calls.
    """
    prompt_id = _PROMPTS.get(str(job_id), "")
    if not prompt_id:
        return False
    if job_id in pending:
        return await _delete_queued(prompt_id)
    if job_id in running:
        return await _interrupt(prompt_id)
    return False


async def _delete_queued(prompt_id: str) -> bool:
    try:
        status, _ = await _call("POST", "/queue", payload={"delete": [prompt_id]})
    except _Unreachable:
        return False
    return status == 200


async def _interrupt(prompt_id: str) -> bool:
    try:
        status, _ = await _call("POST", "/interrupt", payload={"prompt_id": prompt_id})
    except _Unreachable:
        return False
    return status == 200


# --------------------------------------------------------------------------- #
# files
# --------------------------------------------------------------------------- #

def input_directory() -> Path:
    """Where a reference image is written **before** it is uploaded.

    Not the upstream's input folder — this machine cannot write there, and
    pretending otherwise is how a graph ends up naming a file that does not
    exist.  The upload in :func:`submit` is what puts it where it is needed.
    """
    return INPUT_DIRECTORY


async def output_path(kind: str, subfolder: str, filename: str) -> Path | None:
    """Fetch one output from the upstream into a local file, or ``None``.

    ``server.py`` answers ``/chp/jobs/{id}/output/{index}`` with
    ``web.FileResponse``, so it needs a path rather than a stream.  Downloading it
    here keeps that handler identical in both modes, at the cost of one fetch per
    client request — which is the right trade for images a phone asks for once.
    """
    name = Path(str(filename or "")).name
    if not name:
        return None
    try:
        status, body = await _call("GET", "/view",
                                   query={"filename": name, "subfolder": subfolder or "",
                                          "type": kind or "output"})
    except _Unreachable:
        return None
    if status != 200 or not body:
        return None
    directory = OUTPUT_DIRECTORY / (str(subfolder or "").replace("/", "_") or "root")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / name
    destination.write_bytes(body)
    return destination


# --------------------------------------------------------------------------- #
# wiring
# --------------------------------------------------------------------------- #

def routes() -> Any:
    """``None`` — this backend has no route table of its own.

    The plugin attaches its handlers to ComfyUI's; the service builds an
    ``aiohttp`` app and attaches the same handlers to *that*
    (``cli.build_app``), which is why routes are registered in ``server.py`` and
    never in a backend.
    """
    return None


def limit_body(bytes_count: int) -> None:
    """Nothing to do: the service's app carries the ceiling from birth.

    ``web.Application(client_max_size=…)`` is the whole mechanism in this mode, so
    there is no second place to set it — and the manual check in ``server.py``
    stays the load-bearing one in both modes.
    """
    return None


__all__ = [
    "CLIENT_ID", "FOLDER_NODES", "INPUT_DIRECTORY", "INPUT_SUBFOLDER", "LOADER_NODE",
    "MEDIA_TYPES", "OUTPUT_DIRECTORY", "REFRESH_SECONDS", "TIMEOUT", "abilities",
    "absent", "available", "cancel", "error_of", "forget", "history",
    "input_directory", "keep_fresh", "limit_body", "listed_at", "output_path",
    "outputs", "progress_state", "queue", "queue_position", "refresh",
    "resolve_category", "routes", "state_of", "status_of", "submit",
]
