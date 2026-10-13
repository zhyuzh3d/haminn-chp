"""The backend seam: the one place the protocol layer may assume ComfyUI.

``server.py`` speaks CHP and nothing else.  Everything that has to know it is
running *inside* a ComfyUI process — where the model files are, what the queue
holds, how a graph is validated and enqueued, which file on disk an output
names — is asked of a backend through the small vocabulary below.  Two backends
are planned, and they answer the same questions from different places:

* :mod:`~hamdraw_chp.backends.comfy_inproc` — in-process: reads
  ``folder_paths`` / ``PromptServer`` / ``execution`` directly.  This is the
  ComfyUI plugin, and it is what runs today.
* :mod:`~hamdraw_chp.backends.comfy_http` — out-of-process: asks an upstream
  ComfyUI over HTTP.  This is ``python -m hamdraw_chp serve``, and it exists so
  the same protocol can be spoken on a machine where the plugin is not loaded.

The vocabulary, which is also the whole of it:

======================  =========================================================
``abilities(files_of)`` 模型清单与就绪状态 —— 返回 ``category -> {files, ready,
                        missing}``；``files_of`` 是「运维在配置里写了哪几个文件名」
                        的那一半（部署事实），后端补上「装了没装」那一半（机器事实）
``await queue()``       ``(running, pending)`` 两个作业号列表
``await submit(graph)`` → 作业号；校验不过/入队失败抛 :class:`BackendUnavailable`
``state_of`` / ``progress_state`` / ``queue_position`` / ``status_of`` / ``error_of``
                        状态与进度 —— 两条算法不同（完整态与轻量轮询），所以是两个函数
``await history(job_id)``  那一次运行的历史记录，或 ``None``
``outputs(job_id, entry)``  产物列表，含客户端要用的 ``url``
``await output_path(...)``  产物落在本机的哪个路径（服务模式把它取回来再给）
``await cancel(...)``   撤掉排队中的 / 打断正在跑的
======================  =========================================================

**「要问那台跑着 ComfyUI 的机器」的问题一律是 ``async`` —— 包括在进程内并不需要
await 的那三个**（``queue`` / ``history`` / ``output_path``）。服务模式下它们是 I/O，
而在进程内它们是内存里的一次查询；两者的**形状必须一样**，否则协议层就得知道自己
挂在哪个后端上，而这个接缝存在的全部理由就是让它不必知道。

四个关于文件的问题（``available`` / ``absent`` / ``input_directory`` /
``output_path``）与两个接线问题（``routes`` / ``limit_body``）也在同一层。 路由
**在 ``server.py`` 里显式登记** —— 服务模式要把同一批 handler 挂到自己的 aiohttp
app 上，所以「有哪些路由」不能藏进后端。

**两种模式必须给出同样的回答，所以那些回答只有一份**：作业状态、进度、队列位置、
历史记录里的产物、一个类别解析出来的模型文件，全部住在
:mod:`~hamdraw_chp.backends.records`，由两个后端共用。 一个后端只写**从哪儿取**，
不写**取到之后怎么说**。

**这里没有 registry，没有装饰器，没有 import 扫描** —— 与 ``families/`` 同一条风格：
一屏能看完全部实现，多一个后端就是多一个模块、多一行 :data:`BACKENDS`。
"""

from __future__ import annotations

from typing import Any


class BackendUnavailable(Exception):
    """This machine cannot take the job — carries the CHP error code to answer with.

    Raised rather than returned as a ``(prompt_id, error)`` pair so the happy path
    in ``server.py`` stays readable: a submission either hands back an id or
    raises, and the HTTP layer's one ``except`` turns it into the same ``_fail``
    it would have produced itself.

    ``code`` is always a CHP code (``invalid_workflow`` / ``internal`` / …) and
    never a backend's own diagnostic: an upstream address or token that leaked
    through here would end up in front of a user, which §4.8 forbids for speech
    and this class extends to everything else.  明细只进那台机器的日志。
    """

    def __init__(self, code: str, message: str = "", detail: Any = None) -> None:
        super().__init__(message or code)
        self.code = str(code)
        self.message = message
        self.detail = detail


#: Explicit on purpose, like :data:`hamdraw_chp.families.FAMILIES`.  Two backends
#: do not need a plugin API; a reader can see every backend in one screen.
BACKENDS: dict[str, str] = {
    "inproc": "comfy_inproc",
    "http": "comfy_http",
}

#: What ``get()`` picks when nobody says.  The plugin is the default because that
#: is where every existing user is; service mode is an explicit choice made by
#: whoever typed ``serve`` (§4.3 —— 模式由「谁启动它」决定，不做自动探测).
DEFAULT = "inproc"

#: The service-mode backend's name, spelled once.  ``cli.py`` asks for it by name
#: instead of writing the string a second time — the two places that must agree
#: about it are this table and the launcher.
SERVICE = "http"


def get(name: str = DEFAULT) -> Any:
    """The backend this process uses, as a module.

    A module and not an instance: every question the vocabulary asks is about the
    machine this process is running on, and that machine has no per-request
    configuration to carry around.  ``comfy_http`` is imported only when asked
    for, so a plugin install never needs the service-mode dependencies.
    """
    from importlib import import_module

    key = str(name or DEFAULT).strip().lower()
    module_name = BACKENDS.get(key)
    if module_name is None:
        raise ValueError("unknown_backend")
    return import_module(f".{module_name}", __name__)


__all__ = ["BACKENDS", "BackendUnavailable", "DEFAULT", "SERVICE", "get"]
