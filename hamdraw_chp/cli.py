"""``python -m hamdraw_chp serve`` — CHP without ComfyUI under it.

The plugin and the service are **one protocol and one package**: the same
``server.py``, the same handlers, the same document, the same key table.  What
changes is who started the process, and therefore which backend answers the
questions that can only be answered by the machine the models live on:

    ComfyUI loads ``hamdraw_chp``   →  in-process backend  →  ComfyUI's own port
    ``python -m hamdraw_chp serve`` →  HTTP backend        →  a port of our own

Which is why this file is small, and why it is the **only** place an aiohttp
*application* is built: the protocol layer registers routes onto whatever route
table it is handed (``server.register_routes``), so a service is a route table
plus a port.

Where the port comes from, in order of authority: ``hamdraw_settings.json``'s
``serve`` block, which is also where the upstream ComfyUI's address lives.  Both
are deployment facts and neither is ever taken from a request (§4.3) — the bind
address because a client must not be able to choose it, the upstream because a key
that could name it would turn CHP into a proxy for any address.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from aiohttp import web

from . import backends, server, settings as settings_module
from .backends import comfy_http

#: The verbs this program answers to.  One, today: a second entry point that did
#: something other than serve would be a second program, and this package is one.
VERBS = ("serve",)

#: 打印在启动行里的横幅。它说三件事: 绑在哪、上游是谁、文档在哪个地址 ——
#: 前两件是运维刚配的那两个值, 第三件是他要去试的那一条 URL。
BANNER = "CHP 服务模式：{verb} 监听 {host}:{port}，上游 {upstream}，文档 {document}"


def plan() -> dict[str, Any]:
    """What this process should be: the verb, the address, the upstream.

    Read from the settings file on every call rather than cached — an operator
    who edits a port and restarts must not also have to remember to clear
    something.
    """
    serve = settings_module.serve()
    return {
        "verb": VERBS[0],
        "host": serve["host"],
        "port": serve["port"],
        "upstream": serve["upstream"],
        "document": f"http://{serve['host']}:{serve['port']}{server.API_ROOT}/info",
    }


def build_app() -> web.Application:
    """The service's aiohttp app, with the CHP routes on it.

    The body ceiling is given to the application at construction because that is
    where aiohttp keeps it; the manual check in ``server.py`` remains the one that
    decides, in both modes.  Routes are attached through the ordinary
    ``register_routes`` — the same function the plugin calls — so a route added
    there appears here for free and cannot be forgotten.
    """
    application = web.Application(client_max_size=server.MAX_BODY_BYTES)
    if not server.register_routes(application.router):
        # 走不到: 路由表是这里给的, 不是问后端要的。真走到这里说明接线断了, 而
        # "服务起来了但一条路由都没有" 是那种只有日志能说清的事故。
        raise RuntimeError("路由未注册")
    return application


async def serve(application: web.Application, host: str, port: int) -> None:
    """Bind and run until cancelled — including the list refresher.

    The refresher starts here rather than in the backend because it needs a
    running loop, and it is a *service* concern: the plugin reads its model list
    from the disk it is already on, so there is nothing to keep fresh there.
    """
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    refreshing = asyncio.ensure_future(comfy_http.keep_fresh())
    try:
        await asyncio.Event().wait()
    finally:
        refreshing.cancel()
        await runner.cleanup()


def main(argv: list[str] | None = None) -> int:
    chosen = plan()
    parser = argparse.ArgumentParser(
        prog="python -m hamdraw_chp",
        description="以服务模式跑 CHP：同一个协议，不需要在 ComfyUI 里装插件。")
    parser.add_argument("verb", nargs="?", default=chosen["verb"], choices=VERBS,
                        help="要做什么（默认 serve）")
    parser.parse_args(argv)

    # **先换后端，再接线。** 这个模块是被两个入口 import 的，所以模式只能在这里定；
    # 顺序反过来的话，第一条被接上的路由就是照着插件模式判的。
    server.use_backend(backends.SERVICE)
    application = build_app()
    print(BANNER.format(verb=chosen["verb"], host=chosen["host"], port=chosen["port"],
                        upstream=chosen["upstream"], document=chosen["document"]))
    try:
        asyncio.run(serve(application, chosen["host"], chosen["port"]))
    except KeyboardInterrupt:
        return 0
    return 0


__all__ = ["BANNER", "VERBS", "build_app", "main", "plan", "serve"]
