"""The CHP HTTP API — the reference implementation of Consolidated Haminn Portal.

Three kinds of endpoint, and nothing else:

    GET  /chp/info                        what this server can do        (key)
    POST /chp/jobs                        submit one job                 (key)
    GET  /chp/jobs/{id}                   state, prompt, outputs         (key)
    GET  /chp/jobs/{id}/progress          state only — the polling call  (key)
    GET  /chp/jobs/{id}/output/{index}    fetch a finished image         (key)
    POST /chp/jobs/{id}/cancel            drop a queued job              (key)
    POST /chp/translate                   pre-translate a prompt         (key)

``/chp/info`` is the one a client calls first, and it answers with the contract
**as far as this key is allowed to see it**: the rules (what shape of input each
category takes), the abilities (which model files can serve them, and which
canvases they can make), whether speech is available, and the key's own category
set applied to all of them at once.

It **needs a key** — but only once one is configured.  A deployment with no
password and an empty key table answers ``200`` with everything, exactly as
before, so nobody's existing card or workflow breaks; from the first configured
key onward a missing or wrong key is ``401``.  Both states are decided in one
function (:func:`_keys_configured`) rather than at each call site, because the
two of them failing to agree is the failure this design is most exposed to.

The contract itself is defined in ``plans/chp-spec.md``; the table it is built
from lives in :mod:`hamdraw_chp.capabilities`.

The paths never carry a version.  The protocol version travels in the document
as ``spec``, so a client never has to guess a newer path, and a server may add
categories and fields without breaking one that is already shipped: a client is
required to ignore what it does not know.

Roots
-----
``/chp`` is the only root.  ``/cvp`` — the root this plugin served before it was
renamed — is gone.  A client is required to read its addresses out of the
document's ``endpoints``, so a client that hardcoded a root is precisely the
client this version promises nothing to.  Nothing else is served either: the
``/hamdraw/v1`` projections went the same way when their only consumer moved.

Backends
--------
This module speaks CHP and nothing else: it does not import a single ComfyUI
module.  Every question that can only be answered by the machine the models live
on — which files are installed, what the queue holds, how a graph is validated
and enqueued, where an output is on disk — goes through
:mod:`hamdraw_chp.backends`, which is a module of functions with one screen of
vocabulary.  The in-process backend is today's behaviour, moved verbatim; the
HTTP backend is what lets ``python -m hamdraw_chp serve`` speak this same
protocol on a machine where the plugin is not loaded.  Routes are registered
*here*, not in the backend, because service mode attaches this same set of
handlers to its own aiohttp app.

**Both entries import this module**, so which backend is in use cannot be decided
at import time: **each entry names its own** — ``__init__.py`` binds the
in-process one (that process is ComfyUI), ``cli.main()`` calls :func:`use_backend`
before it wires anything.  Nothing is bound here, and that is load-bearing rather
than tidy: the in-process backend is the one that imports ComfyUI, so binding it
at import time would leave ``python -m hamdraw_chp serve`` unable to start on
exactly the machines that entry exists for.  Nothing else may switch it — the two
modes are the same protocol, and the moment this layer starts branching on which
one it is, they are not.

Everything whose answer has to be asked of the *running* ComfyUI is ``async``,
including the three that need no ``await`` in-process (``queue``, ``history``,
``output_path``): over HTTP they are requests, and a vocabulary whose shape
changed with the backend would leak the backend into this layer.

Authentication
--------------
A **key** protects every endpoint, ``/chp/info`` included.  A request that
carries a body sends it in ``chp_params.password``; a ``GET``, and a ``POST``
with no body, send it as ``Authorization: Bearer <key>`` instead — a secret has
no business in a URL or a log line.  The header is still accepted everywhere, and
so are ``Basic`` and ``X-HamDraw-Password``.  A missing or wrong key answers
``401 unauthorized`` and nothing is queued; that response alone carries
``spec``, so a client can tell "this is CHP, the key is wrong" from "there is no
plugin here" without guessing at URLs.

There are two kinds of key and they are not interchangeable:

* the **default key** — the password in the ``HamDrawConfig`` node, or
  ``HAMDRAW_PASSWORD``.  It is what every existing card and workflow already
  holds, it keeps working unchanged, and it means *every* category.
* the **key table** — ``chp_keys.json`` (see :mod:`hamdraw_chp.keys`), where a key
  names the categories it may use.

``/chp/info`` speaks each key's own subset of the tables, and the *execution*
layer re-checks the category on every submit — because leaving something out of
a document is a courtesy to a UI, not a permission (§3.3).

**Nothing configured at all** (no default key and an empty table) leaves the
deployment public and ``/chp/info`` answering ``200`` with everything, which is
the behaviour that shipped before keys existed.  Leaving the password empty
therefore still disables the check — until a key table entry exists, and
``auth.required`` says which of the two states this is.

Images are uploaded inline as base64 in the job body and are written into
``input/hamdraw/`` before the graph runs, so a built-in graph can reference
them through the ordinary ``LoadImage`` node.

Speech
------
``POST /chp/speech`` turns text into a voice, and it is the **one route that is
not a job**: a sentence takes a second or two and the slow part is the first
byte, so there is no queue to watch, nothing to cancel and no second call to
fetch the result.  ``stream`` picks the shape instead — bare PCM in chunks, or
one whole WAV — and ``response_format`` follows it unless the client says
otherwise.  The engine itself lives behind :mod:`hamdraw_chp.speech`; its address
and its token stay on this machine, and a failure becomes one of three codes
(``unsupported_voice`` / ``no_engine`` / ``speech_failed``) with nothing of the
engine in the response.

Errors on this route are **JSON with a status code, decided before a byte of
audio is written** — the client's rule is "look at the status first".  That is
why the engine's answer is opened before the response is prepared: a failure
found afterwards cannot be turned back into a status code by anyone.

Translation
-----------
A category whose text encoder only reads English declares
``prompt.language: "en"``.  When such a job arrives with a prompt that is not
pure ASCII, the server translates it itself — memory first, backend second, and
the original text if both fail — so a client that knows nothing but how to POST
a job cannot feed a model something it cannot read.  A client may translate
earlier and show the user the result; that is a recommendation, not a rule.
Every answer says which of the two happened through ``prompt`` /
``prompt_source`` / ``translated``.

Extension parameters
--------------------
Two channels, kept apart by *layer* rather than by who fills them in:
``ext_params`` is the model layer (the spec defines no field in it at all — it
is carried and echoed verbatim), ``chp_params`` is the CHP layer (today only
``password``).  This implementation reads two keys of its own out of
``ext_params``, ``step`` and ``negative_prompt``; that is its behaviour, not a
term of the contract, and it is written down in this plugin's README.

``resolution`` 与 ``seed`` 是**必填**的顶层字段（2026-10-01 起）：画幅是"这次要多
大"、种子是"可不可以重来"，两件都是客户端唯一说得准的事。其余旋钮（步数、采样器、
cfg、参考图权重）都取部署侧配好的默认值，客户端想动就走 ``ext_params``。

加速档案（少步数蒸馏 LoRA + 它自己的 sigma 表）**不走 HTTP**：它按类别配在
``hamdraw_settings.json`` 的 ``accelerators`` 里，因为一个 LoRA 的文件名只对装了它的
那台机器成立。配了却没装会**静默降级**到不加速（并留一行日志），而不是让整张图校验
不过 —— 后者的报错和"没配"长得一模一样。

Submission identity
-------------------
``request_id`` is optional, and the only field a client sends to say "this is
the same submission I already sent once".  A submit that is answered *after*
the client gave up is not a lost job — the graph did run — but until this field
existed there was no way for the client to ask about it, so the retry queued a
second job and the first one's image nobody ever fetched.  With the field: the
same key and the same content returns the original job (live state, not a copy
of the first answer), a second *job* is never queued, and the reply says
``replayed: true``.  A key may hold only one submission — a different body
under the same key is ``duplicate_request``, not a silent second job.  A
submission that failed to queue gives its key back.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import threading
import time
import uuid
from typing import Any

from aiohttp import web

from . import admin as admin_module
from . import backends
from . import capabilities as capabilities_module
from . import families
from . import keys as keys_module
from . import speech as speech_module
from . import settings as settings_module
from . import translate as translate_module
from .version import __version__

API_ROOT = capabilities_module.API_ROOT
INPUT_SUBFOLDER = "hamdraw"

#: The one backend this process uses.  **Not chosen here** — chosen by whoever
#: started the process, with :func:`use_backend` (§4.3 —— 模式由「谁启动它」决定，
#: 不做自动探测)：``__init__.py`` binds the in-process one (this is the plugin) and
#: ``cli.main()`` binds the HTTP one (this is the service).
#:
#: It is deliberately left unbound at import time, and that is not tidiness: the
#: in-process backend is the one that imports ComfyUI, so binding it here would
#: make ``python -m hamdraw_chp serve`` **unable to start on a machine without
#: ComfyUI** — which is the only machine that entry point exists for.
backend: Any = None

MAX_BODY_BYTES = 32 * 1024 * 1024
MAX_TRACKED_JOBS = 256
MAX_PENDING_JOBS = 8

AUTH_HINT = "密码在 ComfyUI 的 CHP 插件配置节点里设置。"

#: 顶层只认这些。其余顶层字段一律忽略，名字进 ``job.ignored`` —— 回执不是可选项：
#: 没有它，「``steps`` / ``negative_prompt`` 搬进 ``ext_params``」对客户端就是静默失效。
RECOGNISED_FIELDS = frozenset({
    "category", "resolution", "prompt", "seed", "ref_strength",
    "image_base64", "mask_base64", "ext_params", "chp_params",
    "request_id",
})

#: ``request_id`` 的长度上限。它是发布的 schema 里的一条 (``maxLength``)，所以这个数
#: 由 :mod:`hamdraw_chp.capabilities` 定义，这里只是取一个短名字 —— 两处各写一份数字，
#: 迟早会有一处忘了改。
MAX_REQUEST_ID_CHARS = capabilities_module.MAX_REQUEST_ID_CHARS

ERROR_STATUS = {
    "unauthorized": 401,
    "bad_request": 400,
    "unsupported_category": 400,
    "unsupported_size": 400,
    "unsupported_steps": 400,
    "bad_image": 400,
    "bad_mask": 400,
    "stretched_reference": 400,
    "invalid_workflow": 400,
    "forbidden_capability": 403,
    "unsupported_voice": 400,
    "no_model": 409,
    # 服务模式独有: 它自己不跑模型, 所以"那台跑模型的机器不在"是一件能发生的事。
    # 码本身定义在 ``capabilities`` 里 —— 后端要判定它, 这里要回它, 一个字面量两处用。
    capabilities_module.NO_UPSTREAM: 409,
    "no_engine": 409,
    "speech_failed": 502,
    "busy": 429,
    "duplicate_request": 409,
    "not_found": 404,
    "internal": 500,
}

ERROR_MESSAGES = {
    "unauthorized": "访问密码不正确，请在 ComfyUI 的 CHP 插件配置节点里核对密码。",
    "bad_request": "请求体不是合法 JSON。",
    "unsupported_category": "不认识这个场景，请从信息接口的 rules 里取 category。",
    "unsupported_size": "该场景没有这个分辨率，请从它的帧表里挑一个。",
    "unsupported_steps": "这个步数不被接受。（step 是本实现自己的扩展参数，取值见插件 README。）",
    "bad_image": "参考图不是合法的 base64 PNG/JPEG。",
    "bad_mask": "局部重绘必须提供蒙版图。",
    "stretched_reference": "参考图的宽高比和这次任务的分辨率不一致：按分辨率缩放会把它压变形，而变形之后从成图上完全看不出来。请按任务分辨率合成参考图再提交。",
    "invalid_workflow": "内置工作流校验失败，可能是模型或节点缺失。",
    "forbidden_capability": "这把 key 没有这个能力。",
    "unsupported_voice": "这台引擎没有这个音色，请从信息接口 speech.abilities[].voices 里取。",
    "no_engine": "没有可用的语音引擎，请先在 CHP 配置里填好语音服务地址。",
    "speech_failed": "语音引擎没有正常应答。",
    "no_model": "没有可用的模型，请先在 CHP 插件配置节点里选好这个场景要用的模型。",
    capabilities_module.NO_UPSTREAM:
        "服务模式连不上上游 ComfyUI：请核对配置里的 serve.upstream，以及那台机器是否正在运行。",
    "busy": "队列已满，请稍后再试。",
    "duplicate_request": "这个 request_id 已经用过了：重发同一次提交请沿用同一个 request_id，换一份内容请换一个 request_id。",
    "not_found": "找不到这个任务。",
    "internal": "服务器内部错误。",
}

_JOBS: dict[str, dict[str, Any]] = {}
#: ``request_id`` → ``{"fingerprint": …, "job_id": … | None}``。``job_id`` 为空 = 这次
#: 提交**正在处理中**（还在翻译或校验），作业号还没生成。与 ``_JOBS`` 同一把锁：
#: 一次提交要么两处都写进去，要么两处都没有。
_REQUESTS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.RLock()


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def _json(payload: Any, status: int = 200) -> web.Response:
    return web.json_response(payload, status=status, dumps=lambda value: json.dumps(value, ensure_ascii=False))


def _fail(code: str, message: str = "", *, status: int | None = None, detail: Any = None,
          spec: str | None = None) -> web.Response:
    payload: dict[str, Any] = {"error": code}
    if spec is not None:
        # **只有 401 用它**（§1.1.1）。一个客户端本来会按「地址可能填错」去试两三个
        # 候选路径；有了这一项，「是 CHP、只是钥匙不对」就成了一个确定的答案，而不是
        # 靠猜 URL 猜出来的。其余错误码的响应形状一个字节都没变 —— 客户端是按形状解析的。
        payload["spec"] = spec
    payload["message"] = message or ERROR_MESSAGES.get(code, code)
    if detail is not None:
        payload["detail"] = detail
    return _json(payload, status or ERROR_STATUS.get(code, 400))


def _password() -> str:
    try:
        return settings_module.password()
    except Exception:
        return ""


def _token_of(request: web.Request) -> str:
    header = str(request.headers.get("Authorization") or "").strip()
    lowered = header.lower()
    if lowered.startswith("bearer "):
        return header[7:].strip()
    if lowered.startswith("basic "):
        try:
            decoded = base64.b64decode(header[6:].strip()).decode("utf-8", "replace")
            return decoded.split(":", 1)[-1].strip()
        except (binascii.Error, ValueError):
            return ""
    return str(request.headers.get("X-HamDraw-Password") or "").strip()


def _body_token(body: Any) -> str:
    """``chp_params.password`` — the carrier a request that has a body uses."""
    if not isinstance(body, dict):
        return ""
    params = body.get("chp_params")
    if not isinstance(params, dict):
        return ""
    return str(params.get("password") or "").strip()


def _keys_configured() -> bool:
    """Is this deployment protected at all?  —— 也就是「对外」的那个开关。

    两件事只要有一件成立就算配了钥匙：配置节点里那个密码非空，或 key 表非空。

    **「一把都没配 ⇒ 公开」是今天的既有行为，不许被无声取消**：用户的工作流与卡片里
    存的可能就是空密码（``hamdraw/README.md``：「密码留空则不校验」）。所以「没有 key
    就等于什么都没有对外」（§3.3）这句**只在配了 key 之后**才成立 —— 这里就是那两个
    前提的唯一出处。
    """
    return bool(_password()) or bool(keys_module.read())


def _open_record() -> dict[str, Any]:
    """The sentinel for a deployment with nothing configured (``source: "open"``).

    A record and not a boolean, because every caller downstream wants the same
    shape: the document needs a category set, and the job path needs one to check
    against.  ``["*"]`` here means exactly what it means in the key table.
    """
    return {"categories": [keys_module.ALL], "source": "open"}


def _key_of(request: web.Request, body: Any = None) -> dict[str, Any] | None:
    """Which key this request carried — its record, or ``None`` for a refusal.

    Three steps, in this order, and the order carries the behaviour:

    1. **nothing configured** ⇒ the open sentinel.  Checked *first* on purpose:
       ``_authorized`` used to return ``True`` the moment the password was empty,
       and moving that check after the table lookup would turn every legacy
       empty-password deployment into a 401.
    2. **the default key** — the config node's password and ``HAMDRAW_PASSWORD``,
       still the same string users have in their cards and workflows.  Its
       meaning is upgraded rather than replaced: full rights (``["*"]``).
    3. **the table**, where a key may hold any subset of the categories.

    Both carriers are tried at every step — the header first, then the body's
    ``chp_params.password`` — because a ``GET`` has no body to put a secret in and
    a ``POST`` must not have to put it in a URL or a log line.
    """
    entries = keys_module.read()
    default = _password()
    if not default and not entries:
        return _open_record()

    tokens = (_token_of(request), _body_token(body))
    if default:
        for token in tokens:
            if token and keys_module.matches(token, default):
                return {"categories": [keys_module.ALL], "source": "default"}
    for token in tokens:
        found = keys_module.resolve(token, entries)
        if found is not None:
            return {**found, "source": "table"}
    return None


def _authorized(request: web.Request, body: Any = None) -> bool:
    """A thin wrapper over :func:`_key_of` — callers that only need a yes/no.

    Kept because "did this request get in" is a different question from "which key
    was it", and most call sites only ask the first.  The ones that need the
    second (the document's filtering, the execution-layer check) ask
    :func:`_key_of` directly — a boolean cannot answer them.
    """
    return _key_of(request, body) is not None


def _unauthorized() -> web.Response:
    """The one 401, from the one place — including the ``spec`` that marks it CHP."""
    return _fail("unauthorized", spec=capabilities_module.SPEC)



# --------------------------------------------------------------------------- #
# models
# --------------------------------------------------------------------------- #

def _checkpoint(category: str) -> str:
    try:
        return settings_module.checkpoint(category)
    except Exception:
        return ""


def _model_files(category: str) -> dict[str, str]:
    try:
        return settings_module.model_files(category)
    except Exception:
        return {}


def _configured_models(category: str) -> dict[str, str]:
    """这个类别该用哪几个文件名 —— **部署事实**，运维在配置节点里写的。

    机器事实（装了没装）由后端补上，见 :data:`_abilities_of`。两半分家的理由与
    ``abilities(files_of)`` 的签名同源：一个实现可以把「有哪些模型」读成磁盘清单，
    也可以读成上游 ``object_info`` 的枚举，但「该用哪个名字」永远只由这台机器的
    配置决定。
    """
    entry = capabilities_module.CATEGORY_TABLE[str(category)]
    roles = [str(role) for role in entry.get("roles") or []]
    if "checkpoint" in roles:
        return {"checkpoint": _checkpoint(str(category))}
    return _model_files(str(category))


#: The model-listing callable the discovery document uses, built once **per
#: backend**: the backend answers "are they installed", :func:`_configured_models`
#: answers "which names did the operator write".  ``None`` until a launcher binds
#: one — left as ``None`` it fails loudly the moment anything asks, which is what
#: a process with no launcher deserves.
_abilities_of: Any = None


def use_backend(name: str) -> Any:
    """Point this process at one backend — **the launcher's single call**.

    It exists because both entries import this module: ``import hamdraw_chp`` is
    the plugin and has already run by the time ``python -m hamdraw_chp serve``
    gets a line of its own.  The mode therefore cannot be decided at import time;
    it is decided by the first thing the launcher does, and this is that thing
    (§4.3 —— 模式由「谁启动它」决定，不做自动探测).

    The listing callable is rebuilt here too, because it is a closure over the
    backend.  Leaving the old one behind is precisely the bug this seam exists to
    prevent: a document describing a machine the jobs no longer go to.
    """
    global backend, _abilities_of
    backend = backends.get(name)
    _abilities_of = backend.abilities(_configured_models)
    return backend


def _accelerator(category: str) -> dict[str, Any]:
    """这台机器给这个类别配的加速档案, 已经过"那个 LoRA 到底装没装"这一关。

    配了却没装 ⇒ 不加速, 而且**说出来**。图里引用一个不存在的 LoRA 会让整张图校验不过
    （``invalid_workflow``）, 那是一个和"这台机器根本没配加速"完全不同的故障, 但从客户端
    看到的只有一句"工作流校验失败"。所以这里主动降级并留一行日志, 让"今天为什么慢了"
    有据可查。清单读不出来（ComfyUI 还在启动）不算"没装" —— 那是不敢判, 见
    :func:`hamdraw_chp.backends.comfy_inproc.absent`。
    """
    try:
        profile = settings_module.accelerator(category)
    except Exception:
        return {}
    lora = str(profile.get("lora") or "").strip()
    if not lora:
        return {}
    if backend.absent("loras", lora):
        print(f"[hamdraw_chp] 加速 LoRA {lora} 不在 models/loras 里, {category} 这次不加速。")
        return {}
    return profile


# --------------------------------------------------------------------------- #
# request body
# --------------------------------------------------------------------------- #

def _body_size(bytes_count: int) -> None:
    if bytes_count > MAX_BODY_BYTES:
        raise ValueError("bad_request")


def _decode_image(payload: Any, code: str) -> bytes:
    text = str(payload or "").strip()
    if not text:
        raise ValueError(code)
    if text[:5].lower() == "data:" and "," in text[:96]:
        text = text.split(",", 1)[1]
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError(code) from None
    if not raw:
        raise ValueError(code)
    _body_size(len(raw))
    return raw


def _extension(raw: bytes) -> str:
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if raw[:2] == b"\xff\xd8":
        return ".jpg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return ".webp"
    return ".png"


def _store_image(payload: Any, code: str) -> str:
    raw = _decode_image(payload, code)
    name = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:10]}{_extension(raw)}"
    directory = backend.input_directory() / INPUT_SUBFOLDER
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_bytes(raw)
    return f"{INPUT_SUBFOLDER}/{name}"


def _number_of(value: Any, fallback: Any = None) -> Any:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def _provided(value: Any) -> bool:
    """Did the client actually send this field, rather than spell out an empty one?"""
    return value not in (None, "", [], {})


def _sent(body: dict[str, Any], *names: str) -> bool:
    return any(_provided(body.get(name)) for name in names)


# --------------------------------------------------------------------------- #
# job bookkeeping
# --------------------------------------------------------------------------- #

def _track(job: dict[str, Any], request_id: str = "") -> None:
    """把一个作业记进账，并且在淘汰它的时候把它占的幂等键一起还回去。

    键与作业同生共死：作业被挤出窗口之后还留着一个指向它的键，第二次到达就会
    被答成「正在处理中」—— 那是一个永远不成立的答案，比不认得这个键更糟。
    """
    with _JOBS_LOCK:
        _JOBS[job["id"]] = job
        if request_id:
            known = _REQUESTS.get(request_id)
            if known is not None:
                known["job_id"] = str(job["id"])
        if len(_JOBS) > MAX_TRACKED_JOBS:
            for key in sorted(_JOBS, key=lambda item: float(_JOBS[item]["created"]))[: len(_JOBS) - MAX_TRACKED_JOBS]:
                _JOBS.pop(key, None)
                for spent, entry in list(_REQUESTS.items()):
                    if str(entry.get("job_id") or "") == key:
                        _REQUESTS.pop(spent, None)


def _tracked(job_id: str) -> dict[str, Any] | None:
    with _JOBS_LOCK:
        return _JOBS.get(job_id)


# --------------------------------------------------------------------------- #
# the idempotency key
# --------------------------------------------------------------------------- #

def _fingerprint(body: dict[str, Any]) -> str:
    """这次提交的**内容**指纹 —— 幂等键的对照物。

    只认内容，不认载体：``chp_params`` 装的是密码，它换了写法（或干脆换了值）
    不该让同一次提交变成另一次；``request_id`` 自己当然也不进指纹，否则重发的
    那一次与第一次永远对不上。键排序后序列化，所以客户端把字段换个顺序不算改内容。
    """
    meaningful = {key: value for key, value in body.items()
                  if key not in ("chp_params", "request_id")}
    text = json.dumps(meaningful, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _request_id_of(body: dict[str, Any]) -> tuple[str, web.Response | None]:
    """读到 ``request_id``，或者告诉客户端它写得不对。

    不给、或给一个空串，都算没给 —— 幂等键是**可选**的，旧客户端一个都不发也能照跑。
    但给了别的类型就报错，不静默忽略：悄悄丢掉一个幂等键，等于客户端以为自己在重试，
    而服务端每次都在重来一遍 —— 那正是这个字段要消灭的那件事。
    """
    raw = body.get("request_id")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return "", None
    if not isinstance(raw, str):
        return "", _fail("bad_request", "request_id 必须是字符串。", detail={"request_id": raw})
    value = raw.strip()
    if len(value) > MAX_REQUEST_ID_CHARS:
        return "", _fail("bad_request", f"request_id 不能超过 {MAX_REQUEST_ID_CHARS} 个字符。",
                         detail={"length": len(value), "limit": MAX_REQUEST_ID_CHARS})
    return value, None


def _claim_request(request_id: str, fingerprint: str) -> tuple[str, Any]:
    """这次提交该怎么走：``("fresh" | "replay" | "conflict", 附带的东西)``。

    这个键是**服务端记的**账，判据不是客户端说自己重发过 —— 一个只会重发的客户端
    不需要信任，一个撒了谎的客户端也不过是把自己的两次提交并成一次。

    ``fresh`` —— 键没用过，已经替它占住。占住发生在任何耗时动作之前，所以一次
    提交还在翻译里、客户端已经等超时重发时，第二次到达看到的是「正在处理中」，
    而不是**第二个作业**。
    """
    with _JOBS_LOCK:
        known = _REQUESTS.get(request_id)
        if known is None:
            _REQUESTS[request_id] = {"fingerprint": fingerprint, "job_id": None}
            return "fresh", None
        if str(known.get("fingerprint") or "") != fingerprint:
            return "conflict", _fail(
                "duplicate_request",
                "同一个 request_id 之前提交过另一样的内容；幂等键只用来重发同一次提交。",
                detail={"request_id": request_id, "reason": "different_body"})
        job = _JOBS.get(str(known.get("job_id") or ""))
        if job is None:
            return "conflict", _fail(
                "duplicate_request",
                "这个 request_id 的那次提交还在处理中，请稍后用同一个 request_id 再试一次。",
                detail={"request_id": request_id, "reason": "in_flight"})
        return "replay", job


def _release_request(request_id: str) -> None:
    """这次提交没成 —— 把键还回去。

    否则一次 ``no_model`` / ``bad_image`` 就会把用户自己的重试挡在门外，而他什么都没做错。
    只还「还没绑上作业」的那种：绑上了就说明作业真的进队了，那是重放的对象。
    """
    if not request_id:
        return
    with _JOBS_LOCK:
        known = _REQUESTS.get(request_id)
        if known is not None and not known.get("job_id"):
            _REQUESTS.pop(request_id, None)


def _describe(job: dict[str, Any], running: list[str], pending: list[str],
              entry: dict[str, Any] | None) -> dict[str, Any]:
    state = backend.state_of(job, running, pending, entry)
    job_id = str(job["id"])
    outputs = backend.outputs(job_id, entry)

    payload: dict[str, Any] = {
        "id": job_id,
        "category": str(job.get("category") or ""),
        "state": state,
        "queue_position": backend.queue_position(job_id, running, pending),
        # Never a fabricated number: the CHP contract allows null.
        "progress": None,
        "created": job.get("created"),
        "typical_seconds": job.get("typical_seconds"),
        # The effective values, echoed back: a client that asked for something
        # out of range must be able to read what it actually got instead of
        # assuming its own number took.
        "resolution": str(job.get("resolution") or ""),
        "seed": job.get("seed"),
        "ref_strength": job.get("ref_strength"),
        # Carried through verbatim, so a happ that put its own key in here can
        # read it back — including one the server did not understand.
        "ext_params": dict(job.get("ext_params") or {}),
        "prompt": str(job.get("prompt") or ""),
        "prompt_source": str(job.get("prompt_source") or ""),
        "translated": bool(job.get("translated")),
        "ignored": list(job.get("ignored") or []),
        "outputs": outputs,
    }
    if state == "failed":
        payload["error"] = backend.error_of(entry) or "execution_error"
    return payload


def _progress_payload(job_id: str, job: dict[str, Any] | None, entry: dict[str, Any] | None,
                      running: list[str], pending: list[str]) -> dict[str, Any]:
    """The light polling answer: state and position, never output parsing."""
    return {"id": job_id,
            "state": backend.progress_state(job_id, job, entry, running, pending),
            "queue_position": backend.queue_position(job_id, running, pending),
            "progress": None}


# --------------------------------------------------------------------------- #
# information
# --------------------------------------------------------------------------- #

async def info(request: web.Request) -> web.Response:
    """``GET /chp/info`` — the contract, as far as this key may see it.

    Needs a key once one is configured, and answers that key's own subset of the
    tables.  A refusal is the one ``401`` that carries ``spec``: it is the single
    call a client makes before it knows anything, so it is the one place where
    "this is CHP, the key is wrong" has to be unmistakable — the next thing the
    user is asked to do is completely different from what a wrong *address* asks
    for.

    ``auth_required`` is the deployment-wide fact (is anything configured), while
    ``authorized`` is this request's — always true here, since anything else
    returned above.  The field stays because removing it would break clients
    that read it; its meaning is now "this server wants a key, and yours worked".
    """
    record = _key_of(request)
    if record is None:
        return _unauthorized()
    return _json(
        capabilities_module.document(
            files_of=_abilities_of,
            allowed=keys_module.allowed_of(record),
            authorized=True,
            auth_required=_keys_configured(),
            translation=translate_module.describe(),
            speech=speech_module.describe(keys_module.allowed_of(record)),
            auth_hint=AUTH_HINT,
            errors=sorted(ERROR_STATUS),
        )
    )


# --------------------------------------------------------------------------- #
# jobs
# --------------------------------------------------------------------------- #

def _no_model(category: str, folder: str, name: str = "") -> web.Response:
    """The one ``no_model`` answer, from the one place that decides it.

    ``name`` empty means nothing is configured for that slot, which is a
    different sentence from "the file you picked is not installed" — the operator
    fixes the first in the config node and the second on disk.
    """
    if name:
        message = f"模型 {name} 不在 ComfyUI 的 {folder} 目录里。"
    else:
        message = f"这个场景还没有在 {folder} 里选模型。"
    return _fail("no_model", message=message,
                 detail={"category": category, "folder": folder,
                         "available": backend.available(folder)})


def _resolve_models(category: str) -> tuple[dict[str, str], web.Response | None]:
    """The files this category will run on, or the error to answer with.

    The judgement is :func:`_abilities_of`'s, not a second copy of it.  The
    information document tells a client which files are installed; if submission
    decided that separately the two could disagree, and a client configured from
    the document would be refused anyway — the one failure mode a discovery
    document exists to prevent.  One decision point, so they cannot.

    A backend may add a ``reason`` to a not-ready verdict, and it wins over
    ``no_model``: "you have not picked a model" and "the machine that runs models
    is not answering" are different sentences for different people, and a service
    that reports the first when the second is true sends its operator to the
    wrong file.
    """
    resolved = _abilities_of(category)
    if resolved["ready"]:
        return resolved["files"], None
    role = str(resolved["missing"][0])
    folder = capabilities_module.ROLE_FOLDERS.get(role, role)
    reason = str(resolved.get("reason") or "")
    if reason:
        return {}, _fail(reason, detail={"category": category, "folder": folder})
    name = str(resolved["files"].get(role) or "").strip()
    return {}, _no_model(category, folder, name)


async def create_job(request: web.Request) -> web.Response:
    # The body is read *before* the key is checked, because the key may be in it:
    # a request that carries a body sends ``chp_params.password``, and a secret
    # belongs in neither a URL nor a log line.  Reading it first costs nothing —
    # a successful request needed the body anyway, and aiohttp already bounds it
    # at ``MAX_BODY_BYTES``.
    try:
        body = await request.json()
    except Exception:
        return _fail("bad_request")
    if not isinstance(body, dict):
        return _fail("bad_request")
    # The *record*, not a boolean: this request's category still has to be checked
    # against this key's set, further down (the execution layer, §3.3).
    record = _key_of(request, body)
    if record is None:
        return _unauthorized()

    # The optional idempotency key.  A client that retries a submit it never got an
    # answer to — the host timed out at 180 s, the phone changed networks, the app
    # was killed — has to be able to say "this is the same request as before", and
    # be answered with the *same job*.  Without it the retry is a second job, and
    # the first one's image has nobody left to fetch it.
    request_id, refused_id = _request_id_of(body)
    if refused_id is not None:
        return refused_id
    if request_id:
        # 键在任何耗时的动作**之前**占住：这次提交还在翻译里、客户端已经等超时重发时，
        # 第二次到达看到的必须是「正在处理中」，而不是第二个作业。占住了就一定会还：
        # 下面那一整段是一道门槛，任何一条提前返回（bad_image / no_model / 校验不过 /
        # 入队失败）都由 finally 把键交还给用户 —— 一次失败不该把用户自己的重试挡在门外。
        decision, subject = _claim_request(request_id, _fingerprint(body))
        if decision == "conflict":
            return subject
        if decision == "replay":
            # 重放答的是**同一个作业的此刻**，不是第一次那个 202 的复印件：客户端
            # 之所以重发，正因为上次没收到回音，而那张图很可能早就好了。
            running, pending = await backend.queue()
            return _json({"job": _describe(subject, running, pending,
                                          await backend.history(str(subject["id"]))),
                          "replayed": True}, status=202)

    try:
        # Every top-level field this version does not recognise, echoed back.  This
        # is the receipt that makes a rename visible instead of silent: a client
        # still sending ``capability`` / ``size`` / ``steps`` is told, in the one
        # response it was already reading, that those are no longer the field names.
        ignored = sorted(str(field) for field in body if field not in RECOGNISED_FIELDS)

        # ``category`` is the only spelling.  ``capability`` and ``task`` are not
        # aliases any more — a client that sends one instead is refused, and the
        # ``ignored`` list above says which field it should have used.
        try:
            category = capabilities_module.category_of(body.get("category"))
        except ValueError:
            return _fail("unsupported_category",
                         detail={"category": body.get("category"), "ignored": ignored})
        name = str(category["category"])

        # 执行层（§3.3 第二层，承重）。**播报层少列几项不是权限**：知道 category
        # 名字的人可以绕过界面直接 POST，所以「看不到」是障眼法，「拒收」才是权限。
        # 它排在必填项检查之前：先说「你不可以」，再说「你的请求写错了」—— 反过来的话
        # 一个没有权限的调用者能从报错里把字段规则一条条问出来。
        if not keys_module.permits(record, name):
            return _fail("forbidden_capability",
                         detail={"category": name, "key": keys_module.label_of(record),
                                 "ignored": ignored})

        # 2026-10-01 起, 画幅与种子是**必填**的: 一个是"这次要多大", 一个是"可不可以
        # 重来", 两件都是客户端唯一说得准的事（其余旋钮都属于部署侧）。缺了就说缺了,
        # 而不是替它挑一个默认值 —— 挑出来的那个和它下一次挑的很可能不是同一个。
        if not _sent(body, "resolution"):
            return _fail("unsupported_size", detail={"category": name, "resolution": None,
                                                     "missing": "resolution"})
        if not _sent(body, "seed"):
            return _fail("bad_request", "请求体少了 seed：0 表示每次都不一样，同一个值可以复现。",
                         detail={"category": name, "missing": "seed"})

        # A member of the category's frame table, not a numeric domain: the client
        # picks from the menu the document published, and nothing computes a shape
        # the menu never offered.
        try:
            resolution = capabilities_module.validate_resolution(name, body.get("resolution"))
            width, height = capabilities_module.resolution_size(resolution)
        except ValueError as error:
            code = str(error)
            return _fail(code if code in ERROR_STATUS else "bad_request",
                         detail={"category": name, "resolution": body.get("resolution"),
                                 "ignored": ignored})

        seed_value = _number_of(body.get("seed"), 0)
        seed = int(seed_value or 0)
        if seed < 0:
            return _fail("bad_request", "seed 不能是负数。", detail={"seed": seed_value})

        needs = category.get("needs") or {}
        if needs.get("mask") and not _sent(body, "mask_base64"):
            return _fail("bad_mask")
        if needs.get("image") and not _sent(body, "image_base64"):
            return _fail("bad_image")
        # 反过来也要判: 一条**不带 ref**的规则收到参考图, 是一份它看不懂的请求。
        # 收下再丢掉是最糟的一种答法 —— 客户端会以为那张图起作用了。
        if not capabilities_module.accepts_image(name) and _sent(body, "image_base64"):
            return _fail("bad_image",
                         "这个场景不收参考图：要从零画一张请用 generate，要按图重画请用 render。",
                         detail={"category": name, "rule": str(category["rule"])})

        models, refused = _resolve_models(name)
        if refused is not None:
            return refused

        running, pending = await backend.queue()
        if len(pending) >= MAX_PENDING_JOBS:
            return _fail("busy", detail={"pending": len(pending)})

        try:
            # 参考图是可选的 —— 类别声明 needs.image=false 时, 不带它就是一次纯文生图,
            # 不是"漏了参数"。所以这里判的是"带了没带": 带了才落盘, 带了但不合法照样报
            # bad_image。needs.image 为真的类别在上面已经被拦下, 走不到这里。
            image_name = ""
            if _sent(body, "image_base64"):
                image_name = _store_image(body.get("image_base64"), "bad_image")
            mask_name = ""
            if needs.get("mask"):
                mask_name = _store_image(body.get("mask_base64"), "bad_mask")
        except ValueError as error:
            return _fail(str(error))

        # The model layer, carried and echoed verbatim — the spec defines no field in
        # it.  This implementation reads two keys of its own out of it, ``step`` and
        # ``negative_prompt``, and it reads them *here* rather than in ``families``
        # so that "what was echoed" and "what was used" are the same object.
        raw_ext = body.get("ext_params")
        ext = dict(raw_ext) if isinstance(raw_ext, dict) else {}

        prompt_source = str(body.get("prompt") or "")
        prompt_used, translated = prompt_source, False
        if needs.get("prompt") and str((category.get("prompt") or {}).get("language") or "") == "en":
            prompt_used, translated = await translate_module.ensure_english(prompt_source)

        settings = settings_module.load()
        sampling = settings["sampling"].get(name) or {}
        # 默认值取该类别自己声明的那个; 没有声明的类别（纯文生图, 它没有参考图）
        # 由 capabilities 给一个确定的答案 —— 请求体是一份共享的 schema, 客户端
        # 完全可能发一个对它没有意义的 ref_strength 过来。
        ref_strength = capabilities_module.clamp_ref_strength(
            body.get("ref_strength"), capabilities_module.default_ref_strength(name))

        try:
            graph = families.build(
                spec=category,
                models=models,
                sampling=sampling,
                image=image_name,
                mask=mask_name,
                prompt=prompt_used,
                seed=seed,
                size=(width, height),
                ref_strength=ref_strength,
                ext=ext,
                options=settings_module.family_options(str(category.get("family") or "")),
                accelerator=_accelerator(name),
                filename_prefix=f"hamdraw/{name}",
            )
        except ValueError as error:
            code = str(error)
            return _fail(code if code in ERROR_STATUS else "bad_request")
        except Exception:
            return _fail("internal", "内置工作流生成失败。")

        # 校验与入队都在后端: 它们要摸的对象（那个正在跑的 ComfyUI）只有后端认得。
        # ``invalid_workflow`` 那句里带着 ComfyUI 自己的话 —— 那是"哪个节点、为什么"
        # 唯一存在的地方, 所以原样带出来, 不压成一句 ``internal``。
        try:
            prompt_id = await backend.submit(graph)
        except backends.BackendUnavailable as error:
            return _fail(error.code, error.message, detail=error.detail)

        job = {
            "id": prompt_id,
            "category": name,
            "created": time.time(),
            "typical_seconds": category.get("typical_seconds"),
            "resolution": resolution,
            "seed": seed,
            "ref_strength": ref_strength,
            "ext_params": ext,
            "prompt": prompt_used,
            "prompt_source": prompt_source,
            "translated": translated,
            "ignored": ignored,
            "cancelled": False,
        }
        _track(job, request_id)
        # ``replayed`` 每次都播报, 不是只在重放时才出现: 一个"有时候在有时候不在"的
        # 字段, 客户端得靠"有没有这个键"来判, 而这是最容易被写错的一种读法。
        return _json({"job": _describe(job, running, pending + [prompt_id], None),
                      "replayed": False}, status=202)
    finally:
        # 走到这里说明这次提交没有把键绑上作业 —— 无论是哪一条返回, 键都还回去。
        # 成功了的话它已经绑在作业上, 这个调用是个空操作(见 ``_release_request``)。
        _release_request(request_id)


async def job_status(request: web.Request) -> web.Response:
    if not _authorized(request):
        return _unauthorized()
    job_id = str(request.match_info.get("job_id") or "").strip()
    job = _tracked(job_id)
    entry = await backend.history(job_id)
    if job is None:
        if entry is None:
            return _fail("not_found")
        # A job submitted before this process started: the record is gone but
        # ComfyUI's history still has the outputs, so the job is described from
        # an empty shell rather than reported missing.
        job = {"id": job_id, "category": "", "created": time.time(), "cancelled": False}
    running, pending = await backend.queue()
    return _json({"job": _describe(job, running, pending, entry)})


async def job_progress(request: web.Request) -> web.Response:
    """``GET /chp/jobs/{id}/progress`` — what a client polls while it waits.

    Returns state and queue position only.  It reads the history entry because
    that is the only way to know whether a job that left the queue succeeded,
    but it never walks the outputs, which is the expensive half of the full
    status call.  ``progress`` is ``null``: the contract allows it, and inventing
    a number would be worse than admitting there is none.
    """
    if not _authorized(request):
        return _unauthorized()
    job_id = str(request.match_info.get("job_id") or "").strip()
    job = _tracked(job_id)
    entry = await backend.history(job_id)
    running, pending = await backend.queue()
    if job is None and entry is None and job_id not in running and job_id not in pending:
        return _fail("not_found")
    return _json({"job": _progress_payload(job_id, job, entry, running, pending)})


async def job_output(request: web.Request) -> web.Response:
    if not _authorized(request):
        return _unauthorized()
    job_id = str(request.match_info.get("job_id") or "").strip()
    try:
        index = int(str(request.match_info.get("index") or "0"))
    except (TypeError, ValueError):
        return _fail("bad_request")
    files = backend.outputs(job_id, await backend.history(job_id))
    if index < 0 or index >= len(files):
        return _fail("not_found")
    chosen = files[index]
    path = await backend.output_path(chosen["type"], chosen["subfolder"], chosen["filename"])
    if path is None:
        return _fail("not_found")
    response = web.FileResponse(path)
    response.headers["Cache-Control"] = "private, max-age=3600"
    response.headers["Content-Disposition"] = f'inline; filename="{chosen["filename"]}"'
    return response


async def cancel_job(request: web.Request) -> web.Response:
    if not _authorized(request):
        return _unauthorized()
    job_id = str(request.match_info.get("job_id") or "").strip()
    job = _tracked(job_id)
    running, pending = await backend.queue()
    if job is None and job_id not in running and job_id not in pending:
        return _fail("not_found")
    dropped = await backend.cancel(job_id, running, pending)
    if job is not None:
        job["cancelled"] = True
    elif dropped:
        job = {"id": job_id, "category": "", "created": time.time(), "cancelled": True}
        _track(job)
    if job is None:
        return _fail("not_found")
    running, pending = await backend.queue()
    return _json({"job": _describe(job, running, pending, await backend.history(job_id))})


async def translate_prompts(request: web.Request) -> web.Response:
    """Pre-translate a prompt so a client can show the user the English it will send.

    Optional — a job submitted with Chinese is translated on the way in anyway.
    A text without a non-ASCII character comes back untouched, and so does every
    text when the translator is off or unreachable: the caller decides what to
    do, it never has to handle an error.
    """
    try:
        body = await request.json()
    except Exception:
        return _fail("bad_request")
    if not isinstance(body, dict):
        return _fail("bad_request")
    if not _authorized(request, body):
        return _unauthorized()
    raw = body.get("texts")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        return _fail("bad_request")
    outcome = await translate_module.translate([item for item in raw], target=str(body.get("target") or "en"))
    return _json(outcome)


async def speech_endpoint(request: web.Request) -> web.StreamResponse:
    """``POST /chp/speech`` — one request, bytes coming back as they are made.

    Two shapes on purpose: ``stream: true`` writes bare PCM as the engine produces
    it (which is what a player wants — the slow part is the *first* byte), and
    ``stream: false`` answers with one whole file, for tools that can only do
    "POST once, take one lump".  Both carry ``X-Sample-Rate``: PCM cannot be
    played without it, and a client that always reads it needs no second path.

    Every refusal here is JSON with a status code, and it happens **before the
    response is prepared** — which is why the engine's answer is opened first and
    its verdict read from it.  A failure that arrives after audio has started can
    no longer be a status code (nobody can change a status line once it is sent),
    so it is logged by :mod:`hamdraw_chp.speech` and the connection is dropped,
    which is the only honest thing left.
    """
    try:
        body = await request.json()
    except Exception:
        return _fail("bad_request")
    if not isinstance(body, dict):
        return _fail("bad_request")
    record = _key_of(request, body)
    if record is None:
        return _unauthorized()
    # 执行层（承重）：语音有自己的 category，所以它过的是同一道门 —— 而不是自己
    # 另写一套。少了这一句，一把只授权了画图的 key 就能白念语音。
    if not keys_module.permits(record, speech_module.CATEGORY):
        return _fail("forbidden_capability",
                     detail={"category": speech_module.CATEGORY,
                             "key": keys_module.label_of(record)})
    try:
        fields = speech_module.validate(body)
    except speech_module.SpeechError as refused:
        return _fail(refused.code, refused.message, detail=refused.detail)

    headers = speech_module.headers_of(fields, settings_module.speech())
    started = False
    try:
        async with speech_module.speak(fields) as answer:
            if not fields["stream"]:
                return web.Response(body=await answer.read(), status=200, headers=headers)
            response = web.StreamResponse(status=200, headers=headers)
            await response.prepare(request)
            started = True
            async for chunk in answer.content.iter_chunked(speech_module.CHUNK_BYTES):
                await response.write(chunk)
            await response.write_eof()
            return response
    except speech_module.SpeechError as refused:
        if started:
            raise
        return _fail(refused.code, refused.message, detail=refused.detail)


# --------------------------------------------------------------------------- #
# the console (/chp/admin/*) — a management plane, not part of the contract
# --------------------------------------------------------------------------- #

def _admin_ok(request: web.Request) -> bool:
    """Is this the administrator?  **Basic only**, and never through ``_token_of``.

    The data plane reads a ``Basic`` header as "the part after the colon is the
    key" (``_token_of``), so a console that reused that helper could be opened by
    a data-plane key — which is the whole reason the two planes have two doors.
    """
    return admin_module.authenticates(request.headers.get("Authorization", ""))


def _admin_denied() -> web.Response:
    """401 that a browser understands, and that does **not** look like the data plane's.

    Two deliberate differences from :func:`_unauthorized`: there is no ``spec``
    (the console is not part of the protocol — §4.9 — so it must not answer in the
    protocol's shapes), and there is a ``WWW-Authenticate`` header, which is what
    makes the browser ask for the credential itself instead of the page having to
    carry a login form.
    """
    return web.json_response(
        {"error": "unauthorized", "message": "需要控制台凭据（用户名与密码）。"},
        status=401, headers=admin_module.challenge(),
        dumps=lambda value: json.dumps(value, ensure_ascii=False))


def _admin_error(refused: admin_module.AdminError) -> web.Response:
    return _fail(refused.code, refused.message, detail=refused.detail)


async def admin_page(request: web.Request) -> web.Response:
    """``GET /chp/admin/`` — the static console page."""
    if not _admin_ok(request):
        return _admin_denied()
    try:
        return web.Response(text=admin_module.page(), content_type="text/html", charset="utf-8")
    except OSError as trouble:
        return _fail("internal", f"控制台页面读不到：{trouble}")


async def admin_capabilities(request: web.Request) -> web.Response:
    """``GET /chp/admin/capabilities`` — **read-only**: what the code registered.

    The list *is* ``capabilities.CATEGORY_TABLE`` plus the speech category, and
    ``ready`` / ``missing`` come from the same callable the discovery document
    uses.  There is no way to add an entry here: a capability is code.
    """
    if not _admin_ok(request):
        return _admin_denied()
    return _json(admin_module.capability_rows(_abilities_of))


async def admin_keys_list(request: web.Request) -> web.Response:
    """``GET /chp/admin/keys`` — the table, plus the read-only default key."""
    if not _admin_ok(request):
        return _admin_denied()
    return _json(admin_module.rows())


async def admin_keys_create(request: web.Request) -> web.Response:
    """``POST /chp/admin/keys`` — append one key."""
    if not _admin_ok(request):
        return _admin_denied()
    try:
        body = await request.json()
    except Exception:
        return _fail("bad_request")
    try:
        return _json(admin_module.add(body), status=201)
    except admin_module.AdminError as refused:
        return _admin_error(refused)


async def admin_key_update(request: web.Request) -> web.Response:
    """``POST /chp/admin/keys/{key_id}`` — edit one key (or regenerate its value)."""
    if not _admin_ok(request):
        return _admin_denied()
    try:
        body = await request.json()
    except Exception:
        return _fail("bad_request")
    try:
        return _json(admin_module.update(str(request.match_info.get("key_id") or ""), body))
    except admin_module.AdminError as refused:
        return _admin_error(refused)


async def admin_key_delete(request: web.Request) -> web.Response:
    """``DELETE /chp/admin/keys/{key_id}`` — remove one key.  Takes effect at once."""
    if not _admin_ok(request):
        return _admin_denied()
    identifier = str(request.match_info.get("key_id") or "")
    if not admin_module.drop(identifier):
        return _fail("not_found", "没有这个 id 的 key。", detail={"id": identifier})
    return _json(admin_module.rows())


# --------------------------------------------------------------------------- #
# wiring
# --------------------------------------------------------------------------- #

def _bind(table: Any, method: str, path: str, handler: Any) -> None:
    """Attach one handler to a route table — **two shapes, one meaning**.

    ComfyUI hands the plugin an ``aiohttp.web.RouteTableDef``: ``table.get(path)``
    **returns a decorator** to call with the handler, which is exactly how the
    plugin has always written this.  Service mode attaches to a live
    ``web.Application().router`` (an ``UrlDispatcher``), which takes both at once
    as ``add_get(path, handler)`` and returns ``None``.

    Both are aiohttp, so the difference is easy to miss — and it was: written the
    first way, the service crashed with ``TypeError: 'NoneType' object is not
    callable`` on its very first route.  The offline suite could not see it
    because its fake router was built in ComfyUI's shape.  只差这一处，就在这里
    合一 —— 路由表本身不该有第二份，否则"两种模式跑同一批 handler"只是巧合。
    """
    if hasattr(table, "add_" + method):
        getattr(table, "add_" + method)(path, handler)
    else:
        getattr(table, method)(path)(handler)


def register_routes(routes: Any = None) -> bool:
    """Attach the API to a running server; safe to call once at import.

    ``routes`` may be handed in — service mode passes its own aiohttp app's table
    — and when it is not, it is asked of the backend, which answers ``None``
    outside ComfyUI.  ``False`` therefore means "there is nowhere to attach yet",
    not "this failed"; the caller decides whether that is worth a log line.
    With no backend bound (``python -m hamdraw_chp serve`` before ``cli.main()``
    has named one) the answer is the same ``False``, for the same reason.
    """
    if backend is None:
        return False
    if routes is None:
        routes = backend.routes()
    if routes is None:
        return False
    backend.limit_body(MAX_BODY_BYTES)

    # One root, spelled once.  The alias loop that used to be here existed so
    # ``/cvp`` could serve the same API; a client is now told to read its
    # addresses out of the document's ``endpoints``, so a second spelling of the
    # same thing is a promise this version deliberately stops making.
    _bind(routes, "get", f"{API_ROOT}/info", info)
    _bind(routes, "post", f"{API_ROOT}/jobs", create_job)
    _bind(routes, "get", f"{API_ROOT}/jobs/{{job_id}}", job_status)
    _bind(routes, "get", f"{API_ROOT}/jobs/{{job_id}}/progress", job_progress)
    _bind(routes, "get", f"{API_ROOT}/jobs/{{job_id}}/output/{{index}}", job_output)
    _bind(routes, "post", f"{API_ROOT}/jobs/{{job_id}}/cancel", cancel_job)
    _bind(routes, "post", f"{API_ROOT}/translate", translate_prompts)
    _bind(routes, "post", f"{API_ROOT}/speech", speech_endpoint)
    # 控制台：同一个服务、同一个端口，**但不在 `endpoints` 里**（§4.9）。客户端只从
    # 文档读地址，所以它永远不知道这一族存在；契约因此保持干净。路径常量与那份清单
    # 都在 :mod:`hamdraw_chp.admin` 里 —— 清单是给测试比对用的，两边各写一次才对得上。
    _bind(routes, "get", admin_module.ADMIN_ROOT, admin_page)
    _bind(routes, "get", admin_module.PAGE_PATH, admin_page)
    _bind(routes, "get", admin_module.CAPABILITIES_PATH, admin_capabilities)
    _bind(routes, "get", admin_module.KEYS_PATH, admin_keys_list)
    _bind(routes, "post", admin_module.KEYS_PATH, admin_keys_create)
    _bind(routes, "post", admin_module.KEY_PATH, admin_key_update)
    _bind(routes, "delete", admin_module.KEY_PATH, admin_key_delete)
    return True


__all__ = ["API_ROOT", "register_routes"]
