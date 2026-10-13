"""Turn text into a voice — the first CHP capability that is not an image.

The shape is copied from :mod:`.translate` deliberately: this is the same
situation the plugin has already been in for a year (a local model server that
speaks OpenAI's dialect, wrapped so a client never needs to know where it lives).
Only two things differ — the answer is bigger, and it arrives in pieces — and
neither of them changes the architecture.

Five decisions worth knowing before editing anything here:

* **``text``, never ``prompt``.**  A field called ``prompt`` has a side effect in
  CHP: ``rules[].prompt.language == "en"`` makes the submit path translate it
  (:func:`translate.ensure_english`).  Speech is the one capability whose input
  is *the exact words to be said out loud*, so a rule that translates them turns
  中文 into an English voice reading English.  The name is load-bearing, not
  style — and :func:`validate` is deliberately **synchronous**, so that adding a
  translate call here would need an ``await`` that cannot exist.
* **One route, no job model.**  A sentence takes a second or two and the slow
  part is the *first* byte; a queue position, a progress percentage and a cancel
  would all be dead weight.  ``stream`` picks the shape instead: chunks of bare
  PCM, or one whole WAV file.
* **The voice menu is this file's, order included.**  The engine's ``/v1/voices``
  is empty, so the list can only come from the implementation — and the first
  entry is the default, exactly as a category's first frame is.
* **The engine's address and its token never leave the machine.**  Not into the
  document, not into an error body.  Failures converge onto three codes and the
  detail goes to the log beside the address — the rule :func:`translate.describe`
  states in prose, enforced here by functions whose signatures cannot carry it.
* **``sph`` is a modality, not a new axis.**  ``txt-2-sph`` obeys the same
  ``<modalities> -2- <output>`` grammar as the three image rules, so a client that
  already matches signatures sees one more rule rather than a second protocol.

Nothing in this module may be imported for its side effects other than
:func:`check_voices`, which runs at import time and asserts a fact about the
table below rather than about any deployment.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, AsyncIterator, Iterable

import aiohttp

from . import capabilities
from . import settings as settings_module

#: 语音侧那条规则。模态词表加一个字 ``sph``（speech）而不是 ``aud``: 说得出它是什么。
#: 将来真有音乐/音效再加 ``aud``，两者不混。名字由 :func:`capabilities.join_rule`
#: 拼出来 —— 与图片侧三条规则同一套文法、同一个拼法。
CATEGORY = "speak"
MODALITIES: tuple[str, ...] = ("txt",)
OUTPUT = "sph"
RULE = capabilities.join_rule(MODALITIES, OUTPUT)
SCHEMA_KEY = f"{RULE}/v1"

#: 要念出来的字那个字段的名字。**不叫 prompt** —— 见模块开头第二条。
TEXT_FIELD = "text"

#: 一次能念多少字。上限不是协议条文，是本实现的一道闸：不设的话一段粘贴进来的
#: 长文会占着引擎算很久，而客户端那边等的是一句话。
MAX_TEXT_CHARS = 2000

#: 引擎自己的模型文件名**不是**它的名字（同图片侧 ``ABILITY_NAMES``）: 文档里播报的
#: 是给人看的名字，文件名只作为 ``files.engine`` 那条事实出现。
ABILITY_NAME = "qwen3-tts-0.6b"

#: 两种容器，与引擎自己的两套说法一致：流式给裸 PCM，整包给 WAV。
FORMATS: tuple[str, ...] = ("pcm", "wav")
AUDIO_TYPES = {"pcm": "audio/pcm", "wav": "audio/wav"}

#: **省略 ``response_format`` 时按 ``stream`` 配对**（§2.6 的两列表格）：流式默认裸 PCM、
#: 整包默认 WAV 容器。这正是引擎自己的两种说话方式 —— 一个请求只该选择"怎么听"，
#: 不该顺带要求客户端知道"容器"是第三个旋钮。显式给了 ``response_format`` 就按它。
STREAM_FORMAT = "pcm"
WHOLE_FORMAT = "wav"

#: 引擎固定单声道（实测）。
CHANNELS = 1

#: 往客户端写的分块大小。24 kHz 单声道 s16le 是 48 kB/s，4 KiB ≈ 85 ms ——
#: 比 8 KiB 更跟手，又不至于让每个 chunk 都变成一次系统调用。
CHUNK_BYTES = 4096

#: 出厂音色表：**手写，顺序即规范**（同帧表）。第一个 ``vivian`` 就是默认音色。
#: 语言那一列是这张表知道的事实；一个引擎认得哪些名字是部署侧的事实，见
#: :func:`voices_of`。
VOICES: tuple[dict[str, Any], ...] = (
    {"id": "vivian", "label": "Vivian", "languages": ("zh", "en")},
    {"id": "serena", "label": "Serena", "languages": ("zh", "en")},
    {"id": "uncle_fu", "label": "Uncle Fu", "languages": ("zh", "en")},
    {"id": "dylan", "label": "Dylan", "languages": ("zh", "en")},
    {"id": "eric", "label": "Eric", "languages": ("zh", "en")},
    {"id": "aiden", "label": "Aiden", "languages": ("zh", "en")},
    {"id": "ono_anna", "label": "Ono Anna", "languages": ("zh", "en")},
    {"id": "sohee", "label": "Sohee", "languages": ("zh", "en")},
    {"id": "ryan", "label": "Ryan", "languages": ("zh", "en")},
)


def check_voices(table: Iterable[dict[str, Any]] | None = None) -> None:
    """装配期断言：一个音色都没有的能力，是客户端点不动的选项。

    照 :func:`capabilities.check_frames` 的做法，**只在表上断言，不看部署**：这台
    机器有没有音色是 ``hamdraw_settings.json`` 说了算，那种情况由 ``ready: false``
    如实播报（一条配了引擎却没配音色的部署不该在导入时就炸掉插件）；而"出厂表空了"
    或"两个音色同名"是**这份代码**的事实，谁改的谁当时就该看见。
    """
    entries = tuple(VOICES if table is None else table)
    if not entries:
        raise ValueError("语音能力至少要有一个音色")
    seen: set[str] = set()
    for entry in entries:
        name = str((entry or {}).get("id") or "").strip()
        if not name:
            raise ValueError("音色的 id 不能是空的")
        if name in seen:
            raise ValueError(f"音色 {name} 出现了两次")
        seen.add(name)


check_voices()


class SpeechError(Exception):
    """A refusal that belongs to CHP — the caller turns ``code`` into a response.

    Same shape as :class:`hamdraw_chp.backends.BackendUnavailable`, and separate
    from it on purpose: the two describe different machines, and one being
    unavailable must never be reported as the other being broken.
    """

    def __init__(self, code: str, message: str = "", detail: Any = None) -> None:
        super().__init__(message or code)
        self.code = str(code)
        self.message = message
        self.detail = detail


# --------------------------------------------------------------------------- #
# what the document reports
# --------------------------------------------------------------------------- #

def voices_of(names: Iterable[str]) -> list[dict[str, Any]]:
    """The menu: the machine's own list, decorated with what this table knows.

    Order and membership come from the deployment (``speech.voices``) — never from
    the table above, which exists only to make a menu readable.  A name the table
    has never heard of still gets an entry, labelled by its own id and with an
    empty language list: "the engine answers to this word" is the fact that
    decides whether a client may pick it, and it would be wrong to hide a voice
    the operator just configured because this file is older.
    """
    known = {str(entry["id"]): entry for entry in VOICES}
    menu: list[dict[str, Any]] = []
    for raw in names:
        name = str(raw)
        entry = known.get(name)
        menu.append({
            "id": name,
            "label": str(entry["label"]) if entry else name,
            "languages": [str(item) for item in entry["languages"]] if entry else [],
        })
    return menu


def rule_entry() -> dict[str, Any]:
    """One ``rules[]`` entry for the speech section.

    **``prompt``/``defaults`` 不在这里，那是有意的**：``prompt.language`` 是翻译的
    开关（见模块开头），而 ``defaults`` 装的是参考权重这类图片侧的东西。少一个字段
    就少一条会走错的路。
    """
    return {
        "category": CATEGORY,
        "rule": RULE,
        "signature": RULE,          # 与图片侧同一个不变量：由模态拼出来的名字就是规则名
        "input": SCHEMA_KEY,
        "label": {"zh": "朗读", "en": "Speak"},
        "description": {"zh": "把一段文字念出来。",
                        "en": "Read a piece of text out loud."},
        "needs": {TEXT_FIELD: True},
        "typical_seconds": 1.2,
    }


def schema() -> dict[str, Any]:
    """``txt-2-sph/v1`` —— 语音那一份请求 schema（装在 speech 段里面）。"""
    return {
        "type": "object",
        "required": [TEXT_FIELD, "voice"],
        "properties": {
            TEXT_FIELD: {"type": "string", "maxLength": MAX_TEXT_CHARS,
                         "description": "要念出来的字。**永不翻译** —— 与 prompt 不同。"},
            "voice": {"type": "string",
                      "description": "该能力 voices[] 里的 id；省略即第一个。"},
            "language": {"type": "string", "description": "zh / en / …；省略由引擎取默认。"},
            "response_format": {"type": "string", "enum": list(FORMATS)},
            "stream": {"type": "boolean",
                       "description": "省略 = true。true 回裸 PCM 分块，false 回整个容器。"},
            "speed": {"type": "number"},
        },
        "additionalProperties": True,
    }


def ability_of(config: dict[str, Any]) -> dict[str, Any]:
    """The one ability, as the deployment can actually answer it."""
    menu = voices_of(config["voices"])
    missing: list[str] = []
    if not config["available"]:
        missing.append("url")
    if not menu:
        # 配了引擎却一个音色都没有: 一样是答不了, 而"缺的是哪一档"要说出来。
        missing.append("voices")
    return {
        "name": ABILITY_NAME,
        "ready": not missing,
        "missing": missing,
        "files": {"engine": str(config["engine"])},
        "audio": {"sample_rate": int(config["sample_rate"]), "channels": CHANNELS,
                  "formats": list(FORMATS), "streaming": True},
        "voices": menu,
    }


def describe(allowed: set[str] | None = None) -> dict[str, Any]:
    """The ninth top-level key, filtered for whoever is asking.

    ``allowed is None`` means "no filtering" (the open deployment, and the default
    key).  A key that may not speak gets **three empty tables rather than a missing
    key** — the same choice the image side makes for a key with no categories, and
    for the same reason: a client has to be able to tell "this plugin cannot
    speak" (an older plugin: no ``speech`` key at all) from "this key may not
    speak" (empty tables).  Both are real states and they need different words on
    screen.
    """
    if allowed is not None and CATEGORY not in allowed:
        return {"rules": [], "abilities": [], "input_schemas": {}}
    config = settings_module.speech()
    return {
        "rules": [rule_entry()],
        "abilities": [ability_of(config)],
        "input_schemas": {SCHEMA_KEY: schema()},
    }


# --------------------------------------------------------------------------- #
# one request
# --------------------------------------------------------------------------- #

def validate(body: Any) -> dict[str, Any]:
    """Check one submission and normalise it.  Synchronous on purpose.

    Returns ``{text, voice, response_format, stream}`` — exactly what
    :func:`payload_of` needs and nothing else, so that whatever the client sent
    (``chp_params``, its own extensions) cannot reach the engine by accident.
    """
    if not isinstance(body, dict):
        raise SpeechError("bad_request", "请求体必须是一个 JSON 对象。")

    text = str(body.get(TEXT_FIELD) or "").strip()
    if not text:
        raise SpeechError("bad_request",
                          "要念出来的字不能是空的（字段名是 text，不是 prompt）。")
    text = text[:MAX_TEXT_CHARS]

    menu = [item["id"] for item in voices_of(settings_module.speech()["voices"])]
    voice = str(body.get("voice") or "").strip()
    if not voice:
        # 省略即菜单**第一项** —— 与 ``ext_params.step`` 省略时取该类别自己那一档同一条
        # 规矩：默认值是**表里的一个成员**，不是一个自己算的常量（写死一个名字的话，运维
        # 把菜单换成另一台引擎的音色之后，省略 voice 的客户端会拿到一个不存在的名字）。
        voice = menu[0] if menu else ""
    # 表外的音色是**成员检查**（少了不会走到这里：上面已经回落到第一项了）。
    if voice not in menu:
        raise SpeechError("unsupported_voice",
                          "这台引擎没有这个音色，请从信息接口 speech.abilities[].voices 里取。",
                          detail={"voice": voice, "voices": menu})

    raw_stream = body.get("stream")
    stream = True if raw_stream is None else bool(raw_stream)
    default_format = STREAM_FORMAT if stream else WHOLE_FORMAT
    fmt = str(body.get("response_format") or "").strip().lower() or default_format
    if fmt not in FORMATS:
        raise SpeechError("bad_request",
                          "response_format 只能是 pcm 或 wav。",
                          detail={"formats": list(FORMATS)})

    fields: dict[str, Any] = {"text": text, "voice": voice,
                              "response_format": fmt, "stream": stream}
    language = str(body.get("language") or "").strip()
    if language:
        fields["language"] = language
    speed = body.get("speed")
    if isinstance(speed, (int, float)) and not isinstance(speed, bool) and speed > 0:
        fields["speed"] = float(speed)
    return fields


def payload_of(fields: dict[str, Any]) -> dict[str, Any]:
    """What the engine receives.  **The text goes out exactly as it came in.**

    No model name: which model the engine has loaded is the engine's business, and
    ``speech.engine`` is a fact about the deployment that is *published*, never
    sent (the plan's four-档 rule — "只用于播报"）。
    """
    payload: dict[str, Any] = {
        "input": str(fields["text"]),
        "voice": str(fields["voice"]),
        "response_format": str(fields["response_format"]),
        "stream": bool(fields["stream"]),
    }
    for key in ("language", "speed"):
        if key in fields:
            payload[key] = fields[key]
    return payload


def endpoint_of(url: str) -> str:
    """``http://host:port`` → that address's ``/v1/audio/speech`` (同 ``translate._endpoint``)."""
    value = str(url or "").strip().rstrip("/")
    if value.endswith("/v1/audio/speech"):
        return value
    if value.endswith("/v1/audio"):
        return value + "/speech"
    if value.endswith("/v1"):
        return value + "/audio/speech"
    return value + "/v1/audio/speech"


def failure_of(status: int | None) -> SpeechError:
    """One engine answer → one CHP code.  **Takes a status and nothing else.**

    这个签名就是那条规矩本身：引擎说的话（可能是地址、可能是令牌回显、可能是它
    自己的报错）没有入口，所以它不可能出现在给客户端的响应里。明细由调用方
    :func:`_log_failure` 记在那台机器的日志上。

    ``401``/``403`` 收敛成 ``no_engine`` 而不是一个新码: 对客户端来说"引擎要令牌而
    这台机器没配对"与"引擎没在跑"是同一件事 —— 都要运维去改那台机器，而它自己能做的
    动作一模一样。
    """
    if status in (401, 403):
        return SpeechError("no_engine",
                           "没有可用的语音引擎，请先在 CHP 配置里填好语音服务地址。")
    if status is None:
        return SpeechError("no_engine",
                           "没有可用的语音引擎，请先在 CHP 配置里填好语音服务地址。")
    return SpeechError("speech_failed", "语音引擎没有正常应答。")


def _log_failure(url: str, detail: str) -> None:
    """The one place a failure may be specific — and it is the log, not a response."""
    print(f"[hamdraw_chp] 语音引擎 {url} 没答上: {detail}", flush=True)


def headers_of(fields: dict[str, Any], config: dict[str, Any]) -> dict[str, str]:
    """Content type from the container, and the audio spec the client needs to play it.

    ``X-Sample-Rate`` is on **both** shapes: bare PCM cannot be played without it,
    and a client that reads it always does not need a second code path for the
    whole-file case.
    """
    return {
        "Content-Type": AUDIO_TYPES[str(fields["response_format"])],
        "X-Sample-Rate": str(int(config["sample_rate"])),
        "X-Channels": str(CHANNELS),
    }


@contextlib.asynccontextmanager
async def speak(fields: dict[str, Any]) -> AsyncIterator[Any]:
    """Forward one utterance; yields the engine's answer.

    A context manager rather than a plain coroutine because the caller must learn
    the engine's verdict **before** it commits to a response: an error has to be a
    JSON body with a status code, and once a stream has been prepared there is no
    way to send one.  Everything the transport can get wrong — no address, refused
    connection, the engine's own 401, its 500 — is therefore raised from the
    *entrance* of the ``async with``.  A failure that happens after the first byte
    cannot be turned back into a status code by anyone; the caller logs it and
    drops the connection.
    """
    config = settings_module.speech()
    if not config["available"]:
        raise failure_of(None)
    url = endpoint_of(config["url"])
    headers = {}
    if config["token"]:
        headers["Authorization"] = f"Bearer {config['token']}"
    timeout = aiohttp.ClientTimeout(total=float(config["timeout"]))

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload_of(fields), headers=headers) as answer:
                if answer.status >= 400:
                    detail = (await answer.text())[:200]
                    _log_failure(url, f"HTTP {answer.status} {detail}")
                    raise failure_of(answer.status)
                yield answer
    except SpeechError:
        raise
    except asyncio.CancelledError:
        # 客户端把连接挂了 —— 那不是引擎的错，原样放上去，别翻译成引擎故障。
        raise
    except Exception as exc:
        _log_failure(url, f"{type(exc).__name__}: {exc}")
        raise failure_of(None) from None


__all__ = ["ABILITY_NAME", "AUDIO_TYPES", "CATEGORY", "CHANNELS", "CHUNK_BYTES", "FORMATS",
           "MAX_TEXT_CHARS", "MODALITIES", "OUTPUT", "RULE", "SCHEMA_KEY", "STREAM_FORMAT",
           "TEXT_FIELD", "VOICES", "WHOLE_FORMAT", "SpeechError", "ability_of",
           "check_voices", "describe", "endpoint_of", "failure_of", "headers_of",
           "payload_of", "rule_entry", "schema", "speak", "validate", "voices_of"]
