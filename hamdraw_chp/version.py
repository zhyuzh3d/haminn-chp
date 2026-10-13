"""The plugin's version, in one place.

``tools/package-plugin.py`` reads this file's number to name the release zip,
and ``server.py`` reports it over HTTP, so a client can tell which build it is
talking to without guessing from the file mtimes.

It lives in its own module rather than in ``__init__.py`` because that one
imports the HTTP layer: anything importing the package would drag
``folder_paths`` and ``aiohttp`` in with it, which is exactly what the offline
tests cannot provide.
"""

from __future__ import annotations

#: 3.2.0 = 加法（第九个顶层键 `speech`、第八个 endpoint、三条新错误码、key 授权），
#: 向后兼容，所以走第二段。``spec`` 仍是 ``chp/2``：图片侧契约一个字没变，
#: 升 ``chp/3`` 会让还没更新的客户端连绘图卡一起报"插件比应用新"，那是白挨的伤。
__version__ = "3.2.0"
