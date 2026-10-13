"""The in-process backend: this *is* the ComfyUI process.

Everything here reads the objects ComfyUI puts in ``sys.modules`` when the plugin
runs inside it — ``folder_paths`` for the model directories, ``server.PromptServer``
for the queue, ``execution`` for graph validation.  The code was moved out of
``server.py`` verbatim (§4.1 of ``docs/chp-portal-plan.md``): the protocol layer
has to be able to answer these same questions about a ComfyUI that lives on
another machine (see ``comfy_http``), and it cannot do that while the answers are
spelled in terms of ``PromptServer.instance``.

**What is left here is only what differs from the HTTP backend.**  The answers
that must come out identical in both modes — job state, progress, queue position,
the outputs of a history entry, one category's resolved model files — live in
:mod:`hamdraw_chp.backends.records` and are imported below, because "two modes,
one protocol" is a claim about those answers and duplicating them would make it
untrue the first time one copy changed.

Three judgements moved with the code, because they are judgements and not
mechanics:

* :func:`absent` — an unreadable listing means "cannot judge", never "missing";
* :func:`abilities` — never raises, because a document has to answer even when
  nothing is configured, and "not ready" *is* an answer;
* :func:`submit` — validation failing is ``invalid_workflow`` **with ComfyUI's own
  sentence attached**, because that is the only place the reason exists.  It is
  deliberately not flattened into ``internal``: "节点名: 原因" is what lets an
  operator see that a model file is missing.

**The three questions the upstream has to be asked are ``async``**, even though
this backend answers them without awaiting anything: ``queue()``, ``history()``
and ``output_path()`` are I/O in service mode, so their shape is I/O here too.
A difference in shape would be a difference the protocol layer has to know about,
which is exactly what this seam exists to prevent.
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
from .records import MEDIA_TYPES, error_of, outputs, progress_state, prompt_id_of  # noqa: F401
from .records import queue_position, resolve_category, state_of, status_of  # noqa: F401

#: Sent as ``client_id`` on every queued prompt.  One name, because this plugin
#: is one client; ComfyUI's own UI uses it to tell whose job is running.
CLIENT_ID = "hamdraw"



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

    The body is :func:`records.resolve_category` plus this machine's own
    :func:`absent` — the single line where the two modes are allowed to differ.
    """
    def resolve(category: str) -> dict[str, Any]:
        return resolve_category(category, files_of(str(category)), absent)

    return resolve


# --------------------------------------------------------------------------- #
# the queue and its history
# --------------------------------------------------------------------------- #

async def queue() -> tuple[list[str], list[str]]:
    """``(running, pending)`` — prompt ids, because here the job *is* the prompt.

    ``async`` although nothing is awaited: over HTTP the same question is a
    ``GET``, and a vocabulary whose shape changes with the backend would leak the
    backend into the protocol layer (see the module docstring).
    """
    instance = server()
    prompt_queue = getattr(instance, "prompt_queue", None) if instance is not None else None
    if prompt_queue is None:
        return [], []
    try:
        running, pending = prompt_queue.get_current_queue()
    except Exception:
        return [], []
    return [prompt_id_of(item) for item in running], [prompt_id_of(item) for item in pending]


async def history(prompt_id: str) -> dict[str, Any] | None:
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


# --------------------------------------------------------------------------- #
# files on this disk
# --------------------------------------------------------------------------- #

async def output_path(kind: str, subfolder: str, filename: str) -> Path | None:
    """One output file, or ``None`` — the resolve-and-contain check lives here.

    The three roots are a ComfyUI fact (``get_output_directory`` and friends), so
    the lookup belongs to this layer; what the caller does with the answer is the
    protocol layer's business.

    ``async`` for the same reason as :func:`queue`: in service mode the bytes are
    on another machine and fetching them is I/O.  Here it is a path.
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
        return bool(await _maybe_await(remover(lambda item: prompt_id_of(item) == job_id)))
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
