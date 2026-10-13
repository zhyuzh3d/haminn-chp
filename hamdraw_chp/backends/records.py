"""The half of the backend vocabulary that is *the same* in both modes.

An in-process backend and an HTTP backend read their answers from completely
different places, but they must give the **same answers**: a client that watches
a job, reads its outputs or asks how many are ahead of it cannot be able to tell
which mode it is talking to.  Everything in this module is therefore written in
terms of a ComfyUI *history entry*, a *queue pair* and a *configured model list*
— shapes that both modes hold in their hands and neither of which knows where it
came from.

Two consequences, both deliberate:

* nothing here imports ComfyUI, ``aiohttp`` or the settings file.  These are
  judgements about data, and :mod:`hamdraw_chp.backends.comfy_inproc` has to stay
  importable off a ComfyUI machine (the offline tests do exactly that);
* nothing here *decides* what "missing" means.  Asking whether a model file is
  installed is a question about a machine, so :func:`resolve_category` takes the
  answer as an argument — that is the one place the two backends are allowed to
  differ, and they do (an unreadable listing means "cannot judge" in-process, and
  "cannot promise anything" over HTTP).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .. import capabilities as capabilities_module

#: Enough to name the media type of an output without trusting a header.
MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


# --------------------------------------------------------------------------- #
# the queue's own shapes
# --------------------------------------------------------------------------- #

def prompt_id_of(item: Any) -> str:
    """The ``prompt_id`` inside one queue item, or ``""``.

    A queue item is a tuple whose second slot is the id (in-process) and a JSON
    array with the same layout (over HTTP).  Read through one function so the two
    modes cannot disagree about which slot it is.
    """
    try:
        return str(item[1])
    except (TypeError, IndexError, KeyError):
        return ""


def status_of(entry: dict[str, Any] | None) -> str:
    """``"success"`` / an error word / ``""`` — out of a history entry's status."""
    if not isinstance(entry, dict):
        return ""
    status = entry.get("status")
    if not isinstance(status, dict):
        return ""
    return str(status.get("status_str") or "")


def error_of(entry: dict[str, Any] | None) -> str:
    """What went wrong, in ComfyUI's own words — or ``""``.

    ``"节点名: 原因"`` rather than a code: it is the only sentence that tells an
    operator that a model file is missing, and it is deliberately not flattened
    into something the protocol layer would have to guess at.
    """
    if not isinstance(entry, dict):
        return ""
    status = entry.get("status")
    messages = status.get("messages") if isinstance(status, dict) else None
    for entry_message in messages or []:
        if isinstance(entry_message, (list, tuple)) and len(entry_message) >= 2 and entry_message[0] == "execution_error":
            data = entry_message[1] if isinstance(entry_message[1], dict) else {}
            detail = str(data.get("exception_message") or data.get("exception_type") or "").strip()
            node = str(data.get("node_type") or "").strip()
            return f"{node}: {detail}".strip(": ") if node or detail else "execution_error"
    return ""


def state_of(job: dict[str, Any], running: list[str], pending: list[str],
             entry: dict[str, Any] | None) -> str:
    """The full status call's state — the one that reads the history entry first."""
    if job.get("cancelled"):
        return "cancelled"
    outcome = status_of(entry)
    if outcome == "success":
        return "completed"
    if outcome:
        return "failed"
    if entry is not None:
        return "completed"
    job_id = job["id"]
    if job_id in running:
        return "running"
    if job_id in pending:
        return "queued"
    return "unknown"


def progress_state(job_id: str, job: dict[str, Any] | None, entry: dict[str, Any] | None,
                   running: list[str], pending: list[str]) -> str:
    """The light polling call's state.

    Deliberately a second function rather than a branch of :func:`state_of`: the
    poller has no tracked job to consult (it may be asking about a job from a
    previous process) and must answer from the queue alone, which is a different
    algorithm with different inputs.  Merging them would mean one of the two
    calls quietly changing its answer.
    """
    if job is not None:
        return state_of(job, running, pending, entry)
    if entry is not None:
        return "completed" if not status_of(entry) or status_of(entry) == "success" else "failed"
    if job_id in running:
        return "running"
    if job_id in pending:
        return "queued"
    return "unknown"


def queue_position(job_id: str, running: list[str], pending: list[str]) -> int | None:
    """How many jobs are ahead of this one; ``0`` while it is the one running.

    Unlike a percentage, this is a number every implementation can actually
    compute, which is why the progress endpoint reports it and not an estimate.
    """
    if job_id in running:
        return 0
    if job_id in pending:
        return pending.index(job_id)
    return None


# --------------------------------------------------------------------------- #
# outputs
# --------------------------------------------------------------------------- #

def outputs(job_id: str, entry: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Finished images, as paths a client can fetch — never a base to re-join.

    ``job_id`` is the **CHP** job id, not a ComfyUI ``prompt_id``: the URL is what
    a client read out of the document, and in service mode the two ids are not
    the same string.  The address is built from
    :data:`hamdraw_chp.capabilities.API_ROOT`, which is the same root
    ``endpoints.output`` publishes, so the address a client reads out of the
    document and the address it is handed back here are the same string.
    """
    if not isinstance(entry, dict):
        return []
    outputs_map = entry.get("outputs")
    if not isinstance(outputs_map, dict):
        return []
    files: list[dict[str, Any]] = []
    for node_output in outputs_map.values():
        if not isinstance(node_output, dict):
            continue
        for image in node_output.get("images") or []:
            if not isinstance(image, dict):
                continue
            filename = str(image.get("filename") or "").strip()
            if not filename:
                continue
            suffix = Path(filename).suffix.lower()
            files.append(
                {
                    "index": len(files),
                    "filename": filename,
                    "subfolder": str(image.get("subfolder") or ""),
                    "type": str(image.get("type") or "output"),
                    "media_type": MEDIA_TYPES.get(suffix, "image/png"),
                    "url": f"{capabilities_module.API_ROOT}/jobs/{job_id}/output/{len(files)}",
                }
            )
    return files


# --------------------------------------------------------------------------- #
# one category's model files
# --------------------------------------------------------------------------- #

def resolve_category(category: str, configured: Any,
                     absent: Callable[[str, str], bool]) -> dict[str, Any]:
    """One category's ``{files, ready, missing}``, from two halves.

    ``configured`` is the **deployment half** — which file names the operator
    wrote for this category's roles.  ``absent(folder, name)`` is the **machine
    half** — whether that file is really installed, asked of whichever backend
    knows.  Splitting them here is what lets the document say which file is
    missing instead of only that something is, and it is also why this function
    takes the judgement rather than making it.
    """
    entry = capabilities_module.CATEGORY_TABLE[str(category)]
    roles = [str(role) for role in entry.get("roles") or []]
    chosen = configured if isinstance(configured, dict) else {}
    files: dict[str, str] = {}
    missing: list[str] = []
    for role in roles:
        name = str(chosen.get(role) or "").strip()
        files[role] = name
        if not name or absent(capabilities_module.ROLE_FOLDERS.get(role, ""), name):
            missing.append(role)
    return {"files": files, "ready": not missing, "missing": missing}


__all__ = [
    "MEDIA_TYPES", "error_of", "outputs", "progress_state", "prompt_id_of",
    "queue_position", "resolve_category", "state_of", "status_of",
]
