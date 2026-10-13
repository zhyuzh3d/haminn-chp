"""CHP plugin for ComfyUI — the reference implementation of Consolidated Haminn Portal.

Drop this folder into ``ComfyUI/custom_nodes/`` and restart ComfyUI.  Then:

1. Open the **HamDraw 配置 (Config)** node, set the password you want your
   drawing app to send, pick the checkpoint each category uses, fill in the
   three files the Qwen categories need, name the accelerator LoRA each of them
   runs with (and paste its sigma schedule), and Queue once.  Leaving the
   password empty turns authentication off.
2. Point the client at this machine's address; it discovers the rest through
   ``GET /chp/info``.

The plugin ships its own graphs for all five categories — ``fast``,
``inpaint``, ``upscale``, ``render`` and ``generate`` — so no API workflow
export is ever needed.  The contract is described in ``plans/chp-spec.md``.

``render`` 与 ``generate`` 是同一族模型的两条路：前者必须带一张参考图（定妆照、
姿势骨架、随手一张照片），后者是纯文生图、一个字节的输入图都不带。客户端**从规则
本身**就能读出这件事（``rules[].signature`` 里有没有 ``ref``），不必试探。

CHP is the protocol; ``hamdraw_chp`` is one implementation of it.  That is why
the package, the ``/chp`` root and ``hamdraw_settings.json`` keep their names
while the prose says "CHP": the protocol was renamed, not the deployment.

Two things were added in 3.2.0 without touching the image side of the contract
(``spec`` is still ``chp/2``):

* **Speech** — ``POST /chp/speech`` turns text into a voice through the TTS
  engine already installed on this machine.  It is the one route that is not a
  job: one request, bytes coming back as they are made (``stream`` picks bare
  PCM or a whole WAV).  See :mod:`hamdraw_chp.speech`.
* **A key table and a console** — ``chp_keys.json`` grants each client its own
  key and its own categories, and the console at ``/chp/admin/`` is the only
  thing that writes it.  The console is **not part of the contract**: it is
  deliberately absent from ``endpoints``, because a client reads its addresses
  from the document.  See :mod:`hamdraw_chp.admin`.
* **A second entry point** — ``python -m hamdraw_chp serve`` speaks the same
  protocol on a machine where the plugin is not loaded, by asking an upstream
  ComfyUI over HTTP instead of reading this process's disk.  One package, one
  version, one document; only the backend differs.  See :mod:`hamdraw_chp.cli`.
  **It follows that this file must import without ComfyUI**: the plugin half is
  allowed to be absent, and says so itself (see the print at the bottom).
"""

from __future__ import annotations

from typing import Any

#: Modules only ComfyUI provides.  **Only these names are forgiven** when missing:
#: any other ``ModuleNotFoundError`` is this repository's own import being wrong,
#: and swallowing it would turn "there is no ComfyUI on this machine" and "this
#: package is broken" into one message — the reader then looks in the wrong place.
COMFYUI_MODULES = frozenset({
    "folder_paths", "nodes", "execution",
})


def missing_is_comfyui(error: ModuleNotFoundError) -> bool:
    """Is this "ComfyUI is not installed here", or "this repository is broken"?

    The distinction is the whole reason the guard below may exist at all.  A
    blanket ``except ModuleNotFoundError`` would also swallow a typo'd import of
    this project's own — and then a plugin install inside ComfyUI would quietly
    register *no nodes at all*, which is the kind of failure that hides for
    months.  只有下面这几个名字算"这里没有 ComfyUI"。
    """
    return str(error.name or "") in COMFYUI_MODULES


from . import backends as backends_module  # noqa: E402
from . import server as server_module  # noqa: E402

try:
    # **插件那一半**：这个进程就是 ComfyUI 进程，所以节点定义与进程内后端都在这儿接上。
    # 两个入口各自点名自己的后端（另一个在 `cli.main()`），`server.py` 自己谁都不猜。
    from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

    server_module.use_backend(backends_module.DEFAULT)
except ModuleNotFoundError as missing:
    # 没有 ComfyUI ⇒ 这里起的不是插件那一半，而是服务模式（`python -m hamdraw_chp serve`）。
    # 那就什么都不接：插件那一半缺席由下面那句 print 照实说，后端留给 `cli.main()`。
    # （没有这一段，`serve` 连 import 都过不去 —— 而 `__init__` 末尾那句 print 还在
    # 一本正经地告诉你去跑它。）
    if not missing_is_comfyui(missing):
        raise
    NODE_CLASS_MAPPINGS: dict[str, Any] = {}
    NODE_DISPLAY_NAME_MAPPINGS: dict[str, Any] = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

ROUTES_REGISTERED = server_module.register_routes()

if not ROUTES_REGISTERED:
    # **这句话必须对两种启动方式都成立。** 这里没有 ComfyUI 并不总是出错：本仓还有
    # 第二个入口 ``python -m hamdraw_chp serve``，它的路由挂在自己的 aiohttp app 上，
    # 而那是加载完本文件之后才发生的事。所以说的是"插件那一半没接上"，并顺手指出去路，
    # 而不是一句在服务模式下看着像故障的抱怨。
    print("[CHP] 未检测到 ComfyUI 服务实例，插件那一半的 HTTP 路由未注册。"
          "（若你要的是服务模式：python -m hamdraw_chp serve）")
