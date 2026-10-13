"""The in-process backend: this *is* the ComfyUI process.

Everything here reads the objects ComfyUI puts in ``sys.modules`` when the plugin
runs inside it — ``folder_paths`` for the model directories, ``server.PromptServer``
for the queue, ``execution`` for graph validation.  The code was moved out of
``server.py`` verbatim (§4.1 of ``docs/chp-portal-plan.md``): the protocol layer
has to be able to answer these same questions about a ComfyUI that lives on
another machine (see ``comfy_http``), and it cannot do that while the answers are
spelled in terms of ``PromptServer.instance``.

Three judgements moved with the code, because they are judgements and not
mechanics:

* :func:`absent` — an unreadable listing means "cannot judge", never "missing";
* :func:`abilities` — never raises, because a document has to answer even when
  nothing is configured, and "not ready" *is* an answer;
* :func:`submit` — validation failing is ``invalid_workflow`` **with ComfyUI's own
  sentence attached**, because that is the only place the reason exists.  It is
  deliberately not flattened into ``internal``: "节点名: 原因" is what lets an
  operator see that a model file is missing.
"""

from __future__ import annotations

import inspect
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import folder_paths

from .. import capabilities as capabilities_module
from . import BackendUnavailable

#: Sent as ``client_id`` on every queued prompt.  One name, because this plugin
#: is one client; ComfyUI's own UI uses it to tell whose job is running.
CLIENT_ID = "hamdraw"

#: Enough to name the media type of an output without trusting a header.
MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


# --------------------------------------------------------------------------- #
# the running ComfyUI
# --------------------------------------------------------------------------- #

def server() -> Any:
    """``PromptServer.instance``, or ``None`` when this is not ComfyUI.

    Imported here rather than at module scope: ``server`` exists only inside
    ComfyUI, and this module is imported by the offline contract tests too.
    """
    try:
        from server import PromptServer
    except Exception:
        return None
    return getattr(PromptServer, "instance", None)


def routes() -> Any:
    """The aiohttp route table to attach handlers to, or ``None``.

    ``None`` is the point of the function: loaded outside ComfyUI there is no
    route table, and ``server.register_routes()`` answers ``False`` instead of
    raising.  Service mode reuses exactly this guard (§4.3).
    """
    instance = server()
    if instance is None:
        return None
    return getattr(instance, "routes", None)


def limit_body(bytes_count: int) -> None:
    """Give aiohttp the same ceiling :data:`server.MAX_BODY_BYTES` enforces by hand.

    Best-effort on purpose: it is a convenience for the body reader, and the
    manual check is the one that is actually load-bearing.
    """
    instance = server()
    application = getattr(instance, "app", None) if instance is not None else None
    if application is None:
        return
    try:
        application._client_max_size = bytes_count
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# models
# --------------------------------------------------------------------------- #

def available(folder: str) -> list[str]:
    try:
        return [str(item) for item in folder_paths.get_filename_list(folder)]
    except Exception:
        return []


def absent(folder: str, name: str) -> bool:
    """Is this file missing, from a folder whose listing we could actually read?

    An unreadable listing (ComfyUI still starting) means "cannot judge", not
    "missing": the first is a reason to let a job through, the second a reason
    to refuse it, and confusing them refuses work that would have run.
    """
    listing = available(folder)
    return bool(name) and bool(listing) and name not in listing


def abilities(files_of: Any) -> Any:
    """Wrap a deployment's configured names into the discovery document's answer.

    ``files_of`` is the half that is a **deployment fact** — which file names the
    operator wrote in the config node for this category.  What comes back is the
    half that is a **machine fact**: whether those files are on this disk.

    The shape is what the discovery document needs, and it never raises: a
    document has to answer even when nothing is configured, and "not ready" *is*
    an answer.  The judgement is the same one :func:`server._resolve_models`
    makes before queueing, deliberately shared — a client that configures itself
    from this document can then never be surprised by ``no_model`` at submit
    time, which is the one failure mode a discovery document exists to prevent.
    """
    def resolve(category: str) -> dict[str, Any]:
        entry = capabilities_module.CATEGORY_TABLE[str(category)]
        roles = [str(role) for role in entry.get("roles") or []]
        configured = files_of(str(category)) or {}
        files: dict[str, str] = {}
        missing: list[str] = []
        for role in roles:
            name = str(configured.get(role) or "").strip()
            files[role] = name
            if not name or absent(capabilities_module.ROLE_FOLDERS.get(role, ""), name):
                missing.append(role)
        return {"files": files, "ready": not missing, "missing": missing}

    return resolve


# --------------------------------------------------------------------------- #
# the queue and its history
# --------------------------------------------------------------------------- #

def queue() -> tuple[list[str], list[str]]:
    instance = server()
    prompt_queue = getattr(instance, "prompt_queue", None) if instance is not None else None
    if prompt_queue is None:
        return [], []
    try:
        running, pending = prompt_queue.get_current_queue()
    except Exception:
        return [], []
    return [_item_id(item) for item in running], [_item_id(item) for item in pending]


def _item_id(item: Any) -> str:
    try:
        return str(item[1])
    except (TypeError, IndexError, KeyError):
        return ""


def history(prompt_id: str) -> dict[str, Any] | None:
    instance = server()
    prompt_queue = getattr(instance, "prompt_queue", None) if instance is not None else None
    if prompt_queue is None:
        return None
    try:
        found = prompt_queue.get_history(prompt_id=prompt_id)
    except Exception:
        return None
    if isinstance(found, dict):
        entry = found.get(prompt_id)
        if isinstance(entry, dict):
            return entry
        if found and isinstance(next(iter(found.values())), dict):
            return next(iter(found.values()))
    return None


def status_of(entry: dict[str, Any] | None) -> str:
    if not isinstance(entry, dict):
        return ""
    status = entry.get("status")
    if not isinstance(status, dict):
        return ""
    return str(status.get("status_str") or "")


def error_of(entry: dict[str, Any] | None) -> str:
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
# files on this disk
# --------------------------------------------------------------------------- #

def outputs(prompt_id: str, entry: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Finished images, as paths a client can fetch — never a base to re-join.

    The URL is built from :data:`hamdraw_chp.capabilities.API_ROOT`, which is the
    same root ``endpoints.output`` publishes, so the address a client reads out of
    the document and the address it is handed back here are the same string.
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
                    "url": f"{capabilities_module.API_ROOT}/jobs/{prompt_id}/output/{len(files)}",
                }
            )
    return files


def output_path(kind: str, subfolder: str, filename: str) -> Path | None:
    """One output file, or ``None`` — the resolve-and-contain check lives here.

    The three roots are a ComfyUI fact (``get_output_directory`` and friends), so
    the lookup belongs to this layer; what the caller does with the answer is the
    protocol layer's business.
    """
    roots = {
        "output": getattr(folder_paths, "get_output_directory", None),
        "temp": getattr(folder_paths, "get_temp_directory", None),
        "input": getattr(folder_paths, "get_input_directory", None),
    }
    getter = roots.get(kind) or roots["output"]
    if getter is None:
        return None
    try:
        root = Path(getter()).resolve()
    except Exception:
        return None
    parts = [part for part in str(subfolder or "").replace("\\", "/").split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        return None
    candidate = root.joinpath(*parts, str(filename or "").strip()).resolve()
    try:
        if os.path.commonpath([str(root), str(candidate)]) != str(root):
            return None
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def input_directory() -> Path:
    """Where ComfyUI keeps uploaded inputs — the parent of the plugin's subfolder."""
    return Path(folder_paths.get_input_directory())


# --------------------------------------------------------------------------- #
# submitting and cancelling
# --------------------------------------------------------------------------- #

async def submit(graph: dict[str, Any]) -> str:
    """Validate the graph against ComfyUI, queue it, hand back the prompt id.

    Raises :class:`BackendUnavailable` with the CHP code to answer with, so the
    HTTP layer never has to know that "validate said no" is ``invalid_workflow``
    while "no queue" is ``internal``.
    """
    instance = server()
    if instance is None:
        raise BackendUnavailable("internal", "ComfyUI 服务未就绪。")

    prompt_id = str(uuid.uuid4())
    try:
        import execution

        valid = await execution.validate_prompt(prompt_id, graph, ["9"])
    except Exception:
        raise BackendUnavailable("internal", "工作流校验无法执行。") from None

    if not valid or not valid[0]:
        reasons = valid[1] if valid and len(valid) > 1 else ""
        node_errors = valid[3] if valid and len(valid) > 3 else None
        text = reasons if isinstance(reasons, str) else json.dumps(reasons, ensure_ascii=False)
        raise BackendUnavailable("invalid_workflow", text, detail={"node_errors": node_errors})

    outputs_to_execute = valid[2]
    prompt_queue = getattr(instance, "prompt_queue", None)
    if prompt_queue is None:
        raise BackendUnavailable("internal", "ComfyUI 队列不可用。")

    try:
        number = int(getattr(instance, "number", 0))
        instance.number = number + 1
    except Exception:
        number = 0
    extra_data = {"client_id": CLIENT_ID, "create_time": int(time.time() * 1000)}
    try:
        prompt_queue.put((number, prompt_id, graph, extra_data, outputs_to_execute, {}))
    except Exception:
        raise BackendUnavailable("internal", "任务入队失败。") from None
    return prompt_id


async def cancel(job_id: str, running: list[str], pending: list[str]) -> bool:
    """Drop it from the queue, or interrupt it if it is the one running.

    Which of the two applies is read off the queue lists the caller already has,
    so this stays one decision in one place instead of two call sites guessing.
    """
    if job_id in pending:
        return await _drop_pending(job_id)
    if job_id in running:
        return await _interrupt_running()
    return False


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _drop_pending(job_id: str) -> bool:
    instance = server()
    prompt_queue = getattr(instance, "prompt_queue", None) if instance is not None else None
    if prompt_queue is None:
        return False
    remover = getattr(prompt_queue, "delete_queue_item", None)
    if not callable(remover):
        return False
    try:
        return bool(await _maybe_await(remover(lambda item: _item_id(item) == job_id)))
    except Exception:
        return False


async def _interrupt_running() -> bool:
    instance = server()
    prompt_queue = getattr(instance, "prompt_queue", None) if instance is not None else None
    for owner in (prompt_queue, instance):
        if owner is None:
            continue
        for name in ("interrupt_current_processing", "interrupt_processing"):
            action = getattr(owner, name, None)
            if not callable(action):
                continue
            try:
                await _maybe_await(action())
                return True
            except Exception:
                continue
    return False


__all__ = [
    "CLIENT_ID", "MEDIA_TYPES", "abilities", "absent", "available", "cancel",
    "error_of", "history", "input_directory", "limit_body", "output_path",
    "outputs", "progress_state", "queue", "queue_position", "routes", "server",
    "state_of", "status_of", "submit",
]
