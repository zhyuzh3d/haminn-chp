#!/usr/bin/env python3
"""把 v2 的每条新判据各改坏一次，确认抓住它的正是点名那一条断言。

每行是 (说明, 文件, 原文, 替换, 必须出现在输出里的那句断言)。最后一列是关键：这份脚本
跑的测试可能因为别的原因失败，只有输出里出现**点名那一句**才算抓住 —— 一个恒红的检查
不算证据，只看退出码会把已经被抓住的变异误判成逃逸。

    python3 tests/.mutate_spec.py
"""
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC_TEST = "tests/test_spec.py"
CAPABILITIES = "hamdraw_chp/capabilities.py"
SERVER = "hamdraw_chp/server.py"
SETTINGS = "hamdraw_chp/settings.py"
FAMILIES = "hamdraw_chp/families/__init__.py"
QWEN = "hamdraw_chp/families/qwen_image.py"
#: S1 之后「输出地址由谁拼」这条判据住在后端里 —— 变异必须跟着它走，否则锚点
#: 找不到就静默 SKIP，而 SKIP 与 CAUGHT 在退出码上看不出区别。
INPROC = "hamdraw_chp/backends/comfy_inproc.py"
KEYS = "hamdraw_chp/keys.py"
#: 语音那一段的判据大多住在 speech.py 里 —— 变异必须跟着它走（锚点找不到就是 SKIP，
#: 而 SKIP 与 CAUGHT 在退出码上分不出来）。
SPEECH = "hamdraw_chp/speech.py"

#: 管理面（S4）。控制台有两份被判据看着的产物：**代码**与**那一页 HTML**。
#: 页面也要能变异 —— "页面上没有改凭据的入口"这条判据，只有在"往页面里加一个入口就
#: 会红"被证明过之后才算数。
ADMIN = "hamdraw_chp/admin.py"
ADMIN_PAGE = "hamdraw_chp/admin.html"

#: 服务模式（S5）。**两个后端共用那一半**（``records.py``）也在名单里 —— 它是
#: 「两种模式同一个回答」的落点，正是最该被盯着别分叉的一份代码。
COM_HTTP = "hamdraw_chp/backends/comfy_http.py"
RECORDS = "hamdraw_chp/backends/records.py"
CLI = "hamdraw_chp/cli.py"

#: 服务模式的**前提**：这个包得能在没有 ComfyUI 的机器上 import 起来（``serve``
#: 唯一的理由就是那种机器）。这条路上有两处代码在判断"这里没有 ComfyUI"：
#: 包入口 ``__init__.py`` 与 ``server.py`` 的后端绑定。
INIT = "hamdraw_chp/__init__.py"

#: 凭据的字母表（业主 2026-10-13 定：字母、数字、``-``、``_``）横跨三处 ——
#: 定义在 ``keys.py``，两个收口在控制台与配置节点。三处都要有一条变异。
NODES = "hamdraw_chp/nodes.py"

#: 变异会把某一处改坏, 而"改坏"的一种样子就是让某条路径变成死等。没有上限的话
#: 一次死等就把整个脚本拖住, 读的人分不清"它在跑"和"它卡住了"。
RUN_TIMEOUT_SECONDS = 60

MUTATIONS = [
    # --- 规则表 ---------------------------------------------------------- #
    (
        "规则名不再按字面 -2- 切分",
        CAPABILITIES,
        '"txt-ref-2-img": {"modalities": ("txt", "ref"), "output": "img"},',
        '"txt-ref2img": {"modalities": ("txt", "ref"), "output": "img"},',
        "规则名必须有且只有一个 -2-",
    ),
    (
        "模态表与规则名脱节（名字里少了 msk，表里却有）",
        CAPABILITIES,
        '"txt-msk-ref-2-img": {"modalities": ("txt", "msk", "ref"), "output": "img"},',
        '"txt-msk-ref-2-img": {"modalities": ("txt", "ref"), "output": "img"},',
        "名字里的模态要与表里一致",
    ),
    (
        "规范序被破坏（msk-ref-txt 这种拼法混进来）",
        CAPABILITIES,
        '"txt-msk-ref-2-img": {"modalities": ("txt", "msk", "ref"), "output": "img"},',
        '"msk-ref-txt-2-img": {"modalities": ("msk", "ref", "txt"), "output": "img"},',
        "模态必须按规范序写",
    ),
    (
        "类别条目自己手写一份 signature",
        CAPABILITIES,
        '        "category": "fast",\n        "rule": "txt-ref-2-img",',
        '        "category": "fast",\n        "signature": "hand-written-2-img",\n        "rule": "txt-ref-2-img",',
        "类别条目不许手写 signature / input",
    ),
    (
        "别名机制复活（category_of 悄悄认 quick）",
        CAPABILITIES,
        '    entry = CATEGORY_TABLE.get(str(name or "").strip().lower())',
        '    entry = CATEGORY_TABLE.get({"quick": "fast"}.get(str(name or "").strip().lower(), str(name or "").strip().lower()))',
        "别名与旧拼写一律不认",
    ),
    # --- 画幅 ------------------------------------------------------------ #
    (
        "帧表的顺序被换掉（默认画幅随之改变）",
        CAPABILITIES,
        '    "fast": [\n        {"ratio": "1:1", "resolution": ["512x512"]},\n        {"ratio": "4:3", "resolution": ["576x384"]},',
        '    "fast": [\n        {"ratio": "4:3", "resolution": ["576x384"]},\n        {"ratio": "1:1", "resolution": ["512x512"]},',
        "的帧表变了",
    ),
    (
        # 三档低/中/高是**同一个比例**里的一张列表, 中档必须在第 0 位（它才是默认）。
        # 把低档挪到最前面, 每个客户端不打招呼就换成了更小的画幅 ——
        # 抓住它的就是那条连顺序一起钉住的 9:16 断言。
        "低档被插到 9:16 那一档的最前面（默认画幅被悄悄换掉）",
        CAPABILITIES,
        '    "render": [\n        {"ratio": "9:16", "resolution": ["768x1344", "512x896", "896x1568"]},',
        '    "render": [\n        {"ratio": "9:16", "resolution": ["512x896", "768x1344", "896x1568"]},',
        "9:16 那一档给的是",
    ),
    (
        # 高档的高 1600、低档的高 500 是业主定的两条硬边界。越界之后画幅仍然是个
        # 看着很正常的数字, 所以除了这里没有第二处会报。
        # 变的是 generate 那一份 —— 改 render 会先被上面那条 9:16 顺序断言撞上（它把
        # 那一档整条列表钉住了）, 于是这条边界断言自己反而永远轮不到。
        "高档高越过 1600（16 GB 卡跑不动的那一档）",
        CAPABILITIES,
        '    "generate": [\n        {"ratio": "9:16", "resolution": ["768x1344", "512x896", "896x1568"]},',
        '    "generate": [\n        {"ratio": "9:16", "resolution": ["768x1344", "512x896", "968x1696"]},',
        "高档高不许超过 1600",
    ),
    (
        "generate 那一档被改（两族画幅分了家）",
        CAPABILITIES,
        '    "generate": [\n        {"ratio": "9:16", "resolution": ["768x1344", "512x896", "896x1568"]},',
        '    "generate": [\n        {"ratio": "9:16", "resolution": ["768x1344", "512x896", "880x1568"]},',
        "generate 的帧表变了",
    ),
    (
        "分辨率改回 chp/1 的一对数字",
        CAPABILITIES,
        '    "fast": [\n        {"ratio": "1:1", "resolution": ["512x512"]},',
        '    "fast": [\n        {"ratio": "1:1", "resolution": [[512, 512]]},',
        "分辨率必须是字符串",
    ),
    (
        "成员校验放宽成「能解析成 WxH 就收」",
        CAPABILITIES,
        '    if wanted not in allowed:\n        raise ValueError("unsupported_size")\n    return wanted',
        '    resolution_size(wanted)\n    return wanted',
        "必须拒掉帧外的",
    ),
    (
        "装配期断言 1 只看有没有帧条目，不看有没有分辨率",
        CAPABILITIES,
        '        canvases = sum(len(entry.get("resolution") or [])\n                       for entry in frames if isinstance(entry, dict))\n        if not canvases:',
        '        if not frames:',
        "没有帧必须装配期就报错",
    ),
    (
        "装配期断言 2（(category, resolution) 唯一）被摘掉",
        CAPABILITIES,
        '                if key in seen:\n                    raise ValueError(f"FRAMES 里 ({category}, {resolution}) 出现了两次")\n                seen.add(key)',
        '                seen.add(key)',
        "重复的 (category, resolution) 必须在装配期就报错",
    ),
    (
        # 这一条改的是"能力覆盖哪些场景是**派生**的"：分组键把文件那半边摘掉之后，
        # 给 inpaint 单配一个 checkpoint 不再产生第二条能力 —— 文档就会声称
        # inpaint 跑的是 fast 那个模型，而提交时用的却是另一个。
        # 注意它**不会**被文档那条"两条"抓住（家族仍把 render 分开），抓住它的是
        # check_abilities_grouping 里"inpaint 独立后应是三条"这句。
        "能力不再按文件分组（分组键只剩家族）",
        CAPABILITIES,
        '        key = (family_of(category), tuple(sorted(resolved["files"].items())))',
        '        key = (family_of(category),)',
        "inpaint 独立后应是三条",
    ),
    # --- 必填项与 render / generate 的分界（2026-10-01） ----------------- #
    # 业主定稿：render 与 generate 的**必要参数都包括 seed、画幅**，其余旋钮取部署侧
    # 默认。所以"缺了就替它挑一个"是本轮最想挡住的一类退化 —— 挑出来的那个值和客户端
    # 下一次挑的很可能不是同一个，而"沉默地换了一张画幅"从成图上看不出来。
    (
        "画幅不再是必填（缺了替它挑一档）",
        SERVER,
        '        if not _sent(body, "resolution"):',
        '        if False:',
        "缺 resolution 要报 unsupported_size",
    ),
    (
        "种子不再是必填（缺了替它挑一个）",
        SERVER,
        '        if not _sent(body, "seed"):',
        '        if False:',
        "缺 seed 要报 bad_request",
    ),
    (
        # 「这条规则收不收参考图」是从模态表**算出来**的一条判据。把它改成恒真之后，
        # 文档里的 generate 会变成"也收参考图" —— 客户端照着读就会去附一张。
        "收不收参考图改成恒真（文档里 generate 也收图）",
        CAPABILITIES,
        '    return bool(entry) and has_reference(str(entry["rule"]))',
        '    return bool(entry)',
        "generate 不收参考图",
    ),
    (
        # 文档对了还不够：**服务端真的拒收**才算数。收下再丢掉是最糟的一种答法，
        # 客户端会以为那张图起作用了。这条守的是请求侧那半边。
        "服务端不再拒收参考图（收下再丢掉）",
        SERVER,
        '        if not capabilities_module.accepts_image(name) and _sent(body, "image_base64"):',
        '        if False:',
        "纯文生图收到参考图要报 bad_image",
    ),
    # --- 加速档案（A1X 默认那条路） --------------------------------------- #
    (
        # 一条 sigma 表只在**它自己那档步数**上成立：表长 = 步数 + 1。对不上就当没有，
        # 拿一张用错的表去采样比不加速还糟（图会糊得没有道理）。
        "sigma 表长度不再等于步数 + 1（LoRA 挂到不对的步数上）",
        QWEN,
        '        and len(sigmas) - 1 == int(step)',
        '        and True',
        "步数对不上时不许挂 LoRA",
    ),
    (
        # LoRA 必须在 KV 缓存**之前**：反了就是拿没挂 LoRA 的模型建缓存，加速白做，
        # 而且外面完全看不出来（图照出，只是慢）。
        "KV 缓存接在 LoRA 之前（加速白做）",
        QWEN,
        '"inputs": {"model": model_source, "device": str(cache_device or "auto"),',
        '"inputs": {"model": ["1", 0], "device": str(cache_device or "auto"),',
        "KV 缓存接在 LoRA 之后",
    ),
    (
        # 客户端没发 step 时，默认步数要取**加速档案自己那一档**：拿类别表的 20 当默认，
        # 一台配好加速的机器就会默认跑在 20 步上，而客户端以为自己拿到的是最快那条路。
        "默认步数不取加速档案那一档（配了加速也跑类别默认）",
        FAMILIES,
        '    if requested is None and profile:\n        step = int(profile["steps"])',
        '    if False:\n        step = int(profile["steps"])',
        "加速时采样器要换成 SamplerCustomAdvanced",
    ),
    (
        # 档案要**按类别**取。共用之后 generate 会挂上 render 那支 4 步 LoRA，
        # 而它自己那张 6 步的表就永远没人用 —— 出图直接糊掉。
        "加速档案不分类别（generate 与 render 共用一支）",
        SETTINGS,
        '    stored = (load().get("accelerators") or {}).get(str(category or "").strip().lower())',
        '    stored = (load().get("accelerators") or {}).get("render")',
        "只配了 render, generate 仍然没加速",
    ),
    (
        # 上一条改的是设置层（守的是"查得出来"）。这一条改的是**家族层把档案交出去
        # 这一步**, 守的是"交出去了": 设置层照旧分类别, 于是只有真的看那张图才抓得住。
        # （把档案改成按名字丢掉 generate 那一份 —— 这是"读了但没用"的反面。
        #   不用"取错类别"来变异: 两支 LoRA 的步数不同, 取错会先在步数枚举那里被拒,
        #   报出来的是 unsupported_steps, 读的人看不出是档案分派坏了。）
        "家族层把 generate 的加速档案丢掉",
        FAMILIES,
        '    if profile:\n        arguments["accelerator"] = profile',
        '    if profile and name != "generate":\n        arguments["accelerator"] = profile',
        "generate 也要走加速那条路",
    ),
    (
        # 图里引用一个不存在的 LoRA 会让整张图校验不过（invalid_workflow）—— 那句报错
        # 与"这台机器根本没配加速"长得一模一样，而这两件事的修法完全不同。
        "配了却没装的 LoRA 照样往图里写",
        SERVER,
        '    if backend.absent("loras", lora):',
        '    if False:',
        "LoRA 不在 models/loras 里就不许往图里写",
    ),
    # --- 两个通道与顶层闸门 ---------------------------------------------- #
    (
        "顶层闸门改成照收不误（ignored 永远是空表）",
        SERVER,
        '    ignored = sorted(str(field) for field in body if field not in RECOGNISED_FIELDS)',
        '    ignored = []',
        "被忽略的顶层字段要逐个点名",
    ),
    (
        "ext_params 被丢掉（不回显、也不交给家族）",
        SERVER,
        '    ext = dict(raw_ext) if isinstance(raw_ext, dict) else {}',
        '    ext = {}',
        "ext_params 要原样回显",
    ),
    (
        "ext_params 的未知键改成报 400",
        SERVER,
        '        raw_ext = body.get("ext_params")\n        ext = dict(raw_ext) if isinstance(raw_ext, dict) else {}',
        '        raw_ext = body.get("ext_params")\n'
        '        if isinstance(raw_ext, dict) and set(raw_ext) - {"step", "negative_prompt"}:\n'
        '            return _fail("bad_request", "unknown extension parameter")\n'
        '        ext = dict(raw_ext) if isinstance(raw_ext, dict) else {}',
        "应当被受理",
    ),
    (
        "chp_params 的未知键把整个请求带崩（连密码都不认了）",
        SERVER,
        '    params = body.get("chp_params")\n    if not isinstance(params, dict):\n        return ""\n    return str(params.get("password") or "").strip()',
        '    params = body.get("chp_params")\n    if not isinstance(params, dict) or set(params) - {"password"}:\n        return ""\n    return str(params.get("password") or "").strip()',
        "chp_params 的未知键不许影响鉴权",
    ),
    (
        # S2 重写了这段，锚点跟着换：原来那两条语句现在住在 _key_of 里。
        "密码只读头部，不读字段",
        SERVER,
        '    tokens = (_token_of(request), _body_token(body))',
        '    tokens = (_token_of(request), "")',
        "默认 key 从字段里来也算数",
    ),
    (
        "小数的 step 又被静默取整",
        CAPABILITIES,
        '    if number != number or number != int(number):\n        raise ValueError("unsupported_steps")\n',
        "",
        "该报 unsupported_steps",
    ),
    (
        # S5 之后「输出地址由谁拼」这条判据住在**两个后端共用**的那份里
        # （``backends/records.py``）—— 它必须只有一处，否则两种模式迟早走样。
        "输出地址不再由 API_ROOT 拼（客户端拿到的路径和文档公布的不是同一条）",
        RECORDS,
        '"url": f"{capabilities_module.API_ROOT}/jobs/{job_id}/output/{len(files)}",',
        '"url": f"/cvp/jobs/{job_id}/output/{len(files)}",',
        "输出地址必须由 API_ROOT 拼出",
    ),
    (
        # 只换 backend 不换那个清单闭包 = 文档在描述一台作业已经不会去的机器。
        # 判据在 S5 的「让两边真的不一致」那一段里：上游装着而本机没有的那个模型。
        # 同一个洞有两半，各一条变异：**没有**那个闭包（认领在 main() 最前面那条），
        # 与闭包**重建成了另一台机器**的清单（认领在 S5 那段"让两边真的不一致"）。
        "换了后端却没换「清单从哪来」（闭包干脆没建）",
        SERVER,
        '    backend = backends.get(name)\n    _abilities_of = backend.abilities(_configured_models)\n    return backend',
        '    backend = backends.get(name)\n    return backend',
        "点名后端时那个「清单从哪来」的闭包要一起重建",
    ),
    (
        "闭包重建成了另一台机器的清单（文档在描述作业不会去的那台）",
        SERVER,
        '    backend = backends.get(name)\n    _abilities_of = backend.abilities(_configured_models)\n    return backend',
        '    backend = backends.get(name)\n'
        '    _abilities_of = backends.get(backends.DEFAULT).abilities(_configured_models)\n'
        '    return backend',
        "服务模式按上游的清单判",
    ),
    # --- 文档骨架与正名 -------------------------------------------------- #
    (
        "契约版本被改成别的数",
        CAPABILITIES,
        'SPEC = "chp/2"',
        'SPEC = "chp/3"',
        "契约版本必须是 chp/2",
    ),
    (
        "文档里的插件版本被钉死成一个字面量（反面教材）",
        CAPABILITIES,
        '"plugin": {"id": PLUGIN_ID, "label": deepcopy(PLUGIN_LABEL), "version": __version__},',
        '"plugin": {"id": PLUGIN_ID, "label": deepcopy(PLUGIN_LABEL), "version": "2.4.5"},',
        "文档播报的插件版本必须就是源码里的版本",
    ),
    (
        "endpoints 少一个键",
        CAPABILITIES,
        '    "cancel": f"{API_ROOT}/jobs/{{job_id}}/cancel",\n',
        "",
        "endpoints 八个键",
    ),
    # --- 提交幂等键 ------------------------------------------------------ #
    (
        "幂等键查了但当成没见过（每次都排一个新作业）",
        SERVER,
        '        known = _REQUESTS.get(request_id)\n        if known is None:',
        '        known = None\n        if known is None:',
        "同键同内容必须被认出来是重放",
    ),
    (
        "重放照抄第一次那份（不读此刻的状态）",
        SERVER,
        '            return _json({"job": _describe(subject, running, pending,\n'
        '                                          await backend.history(str(subject["id"]))),\n'
        '                          "replayed": True}, status=202)',
        '            return _json({"job": _describe(subject, running, pending, None),\n'
        '                          "replayed": True}, status=202)',
        "要读此刻的状态, 而不是照抄第一次那份",
    ),
    (
        "指纹不比对内容（一个键把任何改动都吞掉）",
        SERVER,
        '        if str(known.get("fingerprint") or "") != fingerprint:',
        '        if False:',
        "同键换内容要 duplicate_request",
    ),
    (
        "密码进了指纹（一次正常的重发被当成换了内容）",
        SERVER,
        '                  if key not in ("chp_params", "request_id")}',
        '                  if key not in ("request_id",)}',
        "chp_params 不该进指纹",
    ),
    (
        "提交失败不还键（用户被自己上一次失败挡住）",
        SERVER,
        '        # 走到这里说明这次提交没有把键绑上作业 —— 无论是哪一条返回, 键都还回去。\n'
        '        # 成功了的话它已经绑在作业上, 这个调用是个空操作(见 ``_release_request``)。\n'
        '        _release_request(request_id)',
        '        pass',
        "失败的提交要把键还回去",
    ),
    (
        "作业被淘汰时它占的键不走（键指向一个不存在的作业）",
        SERVER,
        '                for spent, entry in list(_REQUESTS.items()):\n'
        '                    if str(entry.get("job_id") or "") == key:\n'
        '                        _REQUESTS.pop(spent, None)\n',
        "",
        "作业被淘汰时, 它占的幂等键要一起还回去",
    ),
    (
        "request_id 不算已知字段（发出去只会被忽略并点名）",
        SERVER,
        '    "image_base64", "mask_base64", "ext_params", "chp_params",\n    "request_id",\n})',
        '    "image_base64", "mask_base64", "ext_params", "chp_params",\n})',
        "request_id 是认得的字段, 不许进 ignored",
    ),
    (
        "非字符串的 request_id 被静默忽略（客户端以为自己在重试）",
        SERVER,
        '    if not isinstance(raw, str):\n'
        '        return "", _fail("bad_request", "request_id 必须是字符串。", detail={"request_id": raw})',
        '    if not isinstance(raw, str):\n        return "", None',
        "非字符串的 request_id 要 bad_request",
    ),
    (
        "上限两处各写一份（服务端自己写了个数）",
        SERVER,
        "MAX_REQUEST_ID_CHARS = capabilities_module.MAX_REQUEST_ID_CHARS",
        "MAX_REQUEST_ID_CHARS = 42",
        "服务端判的上限要与文档发布的 maxLength 同源",
    ),
    (
        "应答只在重放时才带 replayed",
        SERVER,
        '                      "replayed": False}, status=202)',
        '                      }, status=202)',
        "应答里每次都要带 replayed",
    ),
    # --- S1 · 后端抽离 ---------------------------------------------------- #
    # 这条判据（计划 §4.1）本来只能靠一条 grep 查，现在它也是断言。变异就是"让耦合
    # 长回来"—— 一个多余的 import 就足够，不用真的调用它。
    (
        "ComfyUI 的耦合又长回协议层",
        SERVER,
        'from . import backends\n',
        'import folder_paths  # mutation probe\nfrom . import backends\n',
        "server.py 里不该再出现 folder_paths",
    ),
    # --- S2 · key 两态 + 两层授权（计划 §3.2.1 / §3.3） ------------------- #
    # 前两条方向相反, 两条都要在 —— 把公开态当成漏掉的一支、或把老用户的空密码部署
    # 判死, 是这件事最容易出的两种错, 而它们在一条断言里只有一种是红的。
    (
        "一把 key 都没配也不再免检（老用户的空密码部署被判死）",
        SERVER,
        '    if not default and not entries:\n        return _open_record()\n',
        '    if False:\n        return _open_record()\n',
        "一把 key 都没配时 /chp/info 要 200",
    ),
    (
        "配了 key 之后 info 又改回「未授权也回答」",
        SERVER,
        '    record = _key_of(request)\n    if record is None:\n        return _unauthorized()\n',
        '    record = _key_of(request) or _open_record()\n',
        "配了 key 之后无 key 要 401",
    ),
    (
        "401 不再自证是 CHP（去掉 spec）",
        SERVER,
        '    return _fail("unauthorized", spec=capabilities_module.SPEC)',
        '    return _fail("unauthorized")',
        "401 要带 spec 自证是 CHP",
    ),
    (
        "别的错误码也带上 spec（响应形状被改）",
        SERVER,
        '    if spec is not None:\n',
        '    if True:\n',
        "别的错误码不许带 spec",
    ),
    # 「播报层过滤」要两边一起少。**分开两条变异**: 只过滤一边正是最常见的漏法,
    # 而两种漏法的表现不同（多一条规则 / 多一条能力）—— 一条变异证伪不了另一条。
    (
        "按 key 过滤时只记得 abilities（rules 仍全给）",
        CAPABILITIES,
        '        "rules": rules(allowed),',
        '        "rules": rules(),',
        "只授权 fast ⇒ rules 只剩它",
    ),
    (
        "按 key 过滤时只记得 rules（abilities 仍全给）",
        CAPABILITIES,
        '    for category in _allowed_categories(allowed):',
        '    for category in _allowed_categories(None):',
        "abilities 必须与 rules 同步少",
    ),
    (
        "空授权集被当成「全部」（撤权变成授权）",
        KEYS,
        '    if ALL in names:\n        return None\n    return set(names)',
        '    if ALL in names or not names:\n        return None\n    return set(names)',
        "空授权集不等于「全部」",
    ),
    (
        "执行层不校验 category（只靠界面藏起来）",
        SERVER,
        '        if not keys_module.permits(record, name):',
        '        if False:',
        "未授权的 category 要 403",
    ),
    (
        "默认 key 也走 key 表查找（配置节点那个密码失效）",
        SERVER,
        '    if default:\n        for token in tokens:\n',
        '    if False:\n        for token in tokens:\n',
        "默认 key 要能过门",
    ),
    # --- 非 ASCII 取值（中文密码 / 中文 key） ------------------------------ #
    (
        # compare_digest 只吃 ASCII 的 str，喂它一个含中文的 str 直接抛 TypeError。
        # 后果不是拒收，是**整条请求 500** —— 实测过：中文密码打进来，
        # 默认 key 与 key 表两条路都炸。两处比对各留一条变异。
        "中文 key 退回 str 比对（含非 ASCII 就抛异常，不是拒绝）",
        KEYS,
        'return hmac.compare_digest(token.encode("utf-8"), key.encode("utf-8"))',
        'return hmac.compare_digest(token, key)',
        "key 表里那把中文 key 要能进门",
    ),
    (
        "中文默认密码退回 str 比对（配置节点那个密码被打成 500）",
        SERVER,
        '            if token and keys_module.matches(token, default):',
        '            import hmac as _hmac\n            if token and _hmac.compare_digest(token, default):',
        "中文默认密码也要能进门",
    ),
    # --- 语音（第九个顶层键） --------------------------------------------- #
    (
        # 顶层键少了第九个：客户端会以为这个插件不会说话（而那正是老插件的长相）。
        "文档少了 speech 段（语音能力凭空消失）",
        CAPABILITIES,
        '        payload["speech"] = deepcopy(speech)',
        '        payload["speech_"] = deepcopy(speech)',
        "九个规范键",
    ),
    (
        # 键数由上面那条变异守着（它删 cancel），这一条守的是**值**：文档里播报的地址
        # 必须就是真注册的那一条 —— 两个都对不上的话，客户端按文档去请求会撞 404。
        "endpoints 里的语音地址不是注册的那一条",
        CAPABILITIES,
        '    "speech": f"{API_ROOT}/speech",',
        '    "speech": f"{API_ROOT}/voice",',
        "语音地址必须从文档里读",
    ),
    (
        "语音的模态写成 img（与图片侧那条纯文生图撞名）",
        SPEECH,
        'OUTPUT = "sph"',
        'OUTPUT = "img"',
        "语音的规则名不许与图片侧撞名",
    ),
    (
        # 段与段的接口那一端：`input` 与它指的键写成两个不一样的名字（`/v1` 漏一个就够）。
        # 客户端拿 input 去 speech.input_schemas 里取值会取空，而**不会有任何报错**。
        "规则条目 input 与 schema 的键对不上（客户端取到空 schema）",
        SPEECH,
        '        "input": SCHEMA_KEY,',
        '        "input": RULE,',
        "规则条目 input 指向的 schema 必须在 speech 段里",
    ),
    (
        # 同一条接口的另一端：schema 那一头整份不给了。
        "语音段不再播报 input_schemas（有规则、有音色，却没有请求体长什么样）",
        SPEECH,
        '        "input_schemas": {SCHEMA_KEY: schema()},',
        '        "input_schemas": {},',
        "规则条目 input 指向的 schema 必须在 speech 段里",
    ),
    (
        "schema 里 voice 不必填（客户端以为可以省略，而这不是服务的承诺）",
        SPEECH,
        '        "required": [TEXT_FIELD, "voice"],',
        '        "required": [TEXT_FIELD],',
        "schema 里 voice 是必填",
    ),
    (
        "规则条目里手写一份 signature（不再由模态拼出）",
        SPEECH,
        '        "signature": RULE,          # 与图片侧同一个不变量：由模态拼出来的名字就是规则名',
        '        "signature": "hand-written-2-sph",',
        "签名不许手写",
    ),
    (
        "空音色表也不再报（客户端拿到一条点不动的选项）",
        SPEECH,
        '    if not entries:\n        raise ValueError("语音能力至少要有一个音色")',
        '    if False:\n        raise ValueError("语音能力至少要有一个音色")',
        "语音能力至少要有一个音色",
    ),
    (
        "音色 id 重复也不报（两个音色同名）",
        SPEECH,
        '        if name in seen:\n            raise ValueError(f"音色 {name} 出现了两次")',
        '        if False:\n            raise ValueError(f"音色 {name} 出现了两次")',
        "音色 id 不许重复",
    ),
    (
        "默认音色写死成一个名字（而不是菜单第一项）",
        SPEECH,
        '        voice = menu[0] if menu else ""',
        '        voice = "vivian"',
        "省略 voice 要取菜单第一项",
    ),
    (
        "音色成员校验放宽成「非空字符串即可」",
        SPEECH,
        '    if voice not in menu:\n        raise SpeechError("unsupported_voice",',
        '    if not voice:\n        raise SpeechError("unsupported_voice",',
        "未知音色要 400 unsupported_voice",
    ),
    (
        "整包也回 audio/pcm（两种形状一种容器）",
        SPEECH,
        'AUDIO_TYPES = {"pcm": "audio/pcm", "wav": "audio/wav"}',
        'AUDIO_TYPES = {"pcm": "audio/pcm", "wav": "audio/pcm"}',
        "stream:false ⇒ audio/wav",
    ),
    (
        # 省略 response_format 时该按 stream 配对。这条**由前一句抓住**（内容类型先变红）
        # —— 两条断言守的是同一个洞的两端，写在这里是为了让"整包也当裸 PCM"这条
        # 意图有一个按名字的东西指着它。
        "省略 response_format 不再与 stream 配对（整包也当裸 PCM）",
        SPEECH,
        '    default_format = STREAM_FORMAT if stream else WHOLE_FORMAT',
        '    default_format = STREAM_FORMAT',
        "stream:false ⇒ audio/wav",
    ),
    (
        # 泄露的两种最现实的样子：把 url 塞进文档，或把引擎原话塞进响应。
        "引擎地址塞进 speech.abilities[].files（文档泄露内网地址）",
        SPEECH,
        '        "files": {"engine": str(config["engine"])},',
        '        "files": {"engine": str(config["engine"]), "url": str(config["url"])},',
        "引擎地址不许出现在文档里",
    ),
    (
        # 泄露最现实的样子：**码还是对的**，但把引擎的原话当成给用户看的那句话。
        # 所以这条变异必须保住 no_engine，否则先红的会变成"码不对"，而"有没有漏"
        # 那条断言根本没机会说话 —— 那样它就成了一条永远轮不到的摆设。
        "引擎原话透传给客户端（码对、话里带着它与引擎之间的一切）",
        SPEECH,
        '                    _log_failure(url, f"HTTP {answer.status} {detail}")\n'
        '                    raise failure_of(answer.status)',
        '                    _log_failure(url, f"HTTP {answer.status} {detail}")\n'
        '                    raise SpeechError(failure_of(answer.status).code, detail)',
        "失败响应里不许有引擎令牌",
    ),
    (
        "语音段不按 key 过滤（不能说话的 key 也拿到整段）",
        SPEECH,
        '    if allowed is not None and CATEGORY not in allowed:',
        '    if False:',
        "没有 speak 授权 ⇒ 三张空表",
    ),
    (
        # 「read 了但没用」的经典形态：先校验，再**顺手**把文本译一遍。
        "语音的文本也过一遍翻译（中文被念成英文）",
        SERVER,
        '        fields = speech_module.validate(body)\n',
        '        fields = speech_module.validate(body)\n'
        '        fields["text"] = (await translate_module.ensure_english(fields["text"]))[0]\n',
        "语音的 text 永不翻译",
    ),
    (
        "语音这条路由不进执行层校验（只靠界面藏起来）",
        SERVER,
        '    if not keys_module.permits(record, speech_module.CATEGORY):',
        '    if False:',
        "只授权画图的钥匙念不了语音",
    ),
    # --- 控制台（S4，管理面） --------------------------------------------- #
    (
        # 写坏的凭据文件不许变成"谁都进得来"：空密码是"文件写坏了"，不是"没设密码"。
        "凭据文件密码为空时当成放行（空密码 = 谁都进得来）",
        ADMIN,
        '    if not password:',
        '    if False:',
        "空密码是写坏了 ⇒ 回默认值",
    ),
    (
        # 同一个 `except` 里住着两种坏法，所以这里要**两条**变异（一条一种签名）：
        # 这一条把"读不出来"整条改成回空凭据 —— 它先撞在"没写文件时要用默认值"上，
        # 也就是文件不存在那一半。
        "凭据文件读不出来时回一个空凭据（而不是回默认值）",
        ADMIN,
        '    except (OSError, ValueError):\n        return record',
        '    except (OSError, ValueError):\n        return {"user": "", "password": ""}',
        "没写文件时要用代码里的默认值",
    ),
    (
        # 另一半：文件在、但解不开。这条只坏"损坏"这一种，文件不存在照旧回默认值 ——
        # 于是它必然打在"解不开的凭据文件回默认值"那句上，而不是被前一句盖过去。
        "凭据文件损坏时回一个空凭据（文件不存在那一半照旧）",
        ADMIN,
        '    except (OSError, ValueError):\n        return record',
        '    except ValueError:\n        return {"user": "", "password": ""}\n'
        '    except OSError:\n        return record',
        "解不开的凭据文件回默认值",
    ),
    (
        # 控制台必须是 Basic 那条独立的线。少一次 scheme 检查，"拿一份合法载荷换个前缀"
        # 就能用数据面的载体进门 —— 而那正是管理面与数据面共钥匙的第一步。
        "控制台不检查 scheme（Bearer 里塞一份 Basic 载荷也能进门）",
        ADMIN,
        '    if value[:6].lower() != "basic ":\n        return None',
        '    if not value:\n        return None',
        "同一份凭据换个 scheme 也不行",
    ),
    (
        # 凭据是缓存住的（业主口径：改完要重启）。去掉缓存 = 谁有文件权限，谁改完立刻生效。
        "控制台凭据不再缓存（改文件就立刻生效，不必重启）",
        ADMIN,
        '    if _CREDENTIALS is None:\n        _CREDENTIALS = _read()',
        '    _CREDENTIALS = _read()',
        "换了文件但还没重启 ⇒ 旧凭据照用",
    ),
    (
        "控制台的 401 也带上 spec（把自己的形状混进协议里）",
        SERVER,
        '        {"error": "unauthorized", "message": "需要控制台凭据（用户名与密码）。"},',
        '        {"error": "unauthorized", "spec": "chp/2",\n'
        '         "message": "需要控制台凭据（用户名与密码）。"},',
        "控制台不是协议的一部分, 401 里不许有 spec",
    ),
    (
        # 没有这个头，浏览器不会弹登录框 —— 于是页面就必须自带一个登录表单，
        # 而"页面上没有改凭据的入口"那条判据会跟着一起垮。
        "控制台的 401 不带 WWW-Authenticate（浏览器不再弹登录框）",
        SERVER,
        '        status=401, headers=admin_module.challenge(),',
        '        status=401, headers={},',
        "控制台的 401 要带 WWW-Authenticate",
    ),
    (
        "控制台页面多调一条不属于它的路由",
        ADMIN_PAGE,
        "await call('GET', '/chp/admin/capabilities')",
        "await call('GET', '/chp/capabilities')",
        "页面只能调控制台自己那几条路由",
    ),
    (
        "控制台页面上多出一个密码输入框（改凭据的入口）",
        ADMIN_PAGE,
        '<input type="text" id="keyvalue" placeholder="key（留空即自动生成）" size="36">',
        '<input type="text" id="keyvalue" placeholder="key（留空即自动生成）" size="36">\n'
        '      <input type="password" id="newpass" placeholder="新密码">',
        "页面上不许有任何改凭据的入口",
    ),
    (
        "清单外的 category 也收下（控制台可以给不存在的场景发授权）",
        ADMIN,
        '    refused = [item for item in unknown(cleaned) if item]\n    if refused:',
        '    refused = [item for item in unknown(cleaned) if item]\n    if False:',
        "清单外的 category 要拒收",
    ),
    (
        # 控制台与 /chp/info 必须同源：写死 True 会让管理员以为一切都配好了。
        "控制台把 ready 写死成 True（与 /chp/info 各说各话）",
        ADMIN,
        '            "ready": bool(ability.get("ready")),',
        '            "ready": True,',
        "控制台与 /chp/info 必须同源",
    ),
    (
        # 默认钥匙是"只看不碰"的：它不在 key 表里，控制台也没有权限改它，
        # 所以把它的值印出来只会多一处泄漏面。
        "控制台把默认钥匙的值也印出来（只读行变成泄漏面）",
        ADMIN,
        '            "label": "默认钥匙（配置节点的密码 / HAMDRAW_PASSWORD）",\n            "key": "",',
        '            "label": "默认钥匙（配置节点的密码 / HAMDRAW_PASSWORD）",\n'
        '            "key": settings_module.password(),',
        "默认钥匙的值不许出现在控制台里",
    ),
    (
        "控制台改完 key 不落盘（只回执，不生效）",
        ADMIN,
        '        entries[index] = merged\n        store(entries)\n        return merged',
        '        entries[index] = merged\n        return merged',
        "撤掉 speak 之后立刻就不能念了",
    ),
    (
        "「换一把」不真的换（旧钥匙继续有效）",
        ADMIN,
        '        if fields.get("regenerate"):',
        '        if False:',
        "要求换一把就得换一把",
    ),
    (
        # 删不存在的 id 也报成功 ⇒ 控制台会告诉管理员"删掉了"，而表里那行还在。
        "删不存在的 id 也报成功（静默的假回执）",
        ADMIN,
        '    if len(kept) == len(entries):\n        return False',
        '    if False:\n        return False',
        "再删一次要 404",
    ),
    (
        # 数据面也认 Basic（取 `:` 之后那段当 key）⇒ 同值就意味着控制台密码顺带
        # 成了一把数据面钥匙。这条规矩是"三把钥匙分三条线"里最容易被忘掉的一环。
        "表里可以登记与控制台凭据同值的 key",
        ADMIN,
        '    if keys_module.matches(offered, credential["password"]) \\\n'
        '            or keys_module.matches(offered, credential["user"]):',
        '    if False:',
        "与控制台凭据同值的 key 要拒收",
    ),
    (
        "key 表写出来是世界可读的（0644）",
        ADMIN,
        '    os.chmod(temporary, 0o600)',
        '    os.chmod(temporary, 0o644)',
        "权限要是 0600",
    ),
    (
        "就地覆盖 key 表（原子写退化，临时文件留在盘上）",
        ADMIN,
        '    os.chmod(temporary, 0o600)\n    os.replace(temporary, destination)',
        '    os.chmod(temporary, 0o600)\n'
        '    destination.write_text(temporary.read_text(encoding="utf-8"), encoding="utf-8")',
        "写完不许留下 .tmp",
    ),
    (
        # 授权域名少一个「语音」⇒ 控制台根本授不出 speak（那它就没法管朗读这件事）。
        "控制台的授权域里没有 speak（语音授不出来）",
        ADMIN,
        '    return [*capabilities_module.categories(), speech_module.CATEGORY]',
        '    return list(capabilities_module.categories())',
        "图片侧五个 + speak",
    ),
    # --- 服务模式（S5） --------------------------------------------------- #
    (
        # 「问不到」与「不敢判」在插件模式里是同一件事（都在本机磁盘上），在服务
        # 模式里**不是**：问不到上游就是一台机器不在，那种状态下不能让作业过。
        "上游不在也当成「不敢判」（文档说一切都好，提交才失败）",
        COM_HTTP,
        '    if _LISTING is None:\n        return True',
        '    if False:\n        return True',
        "上游不在时一条能力都不许是 ready",
    ),
    (
        # 一个答非所问的 object_info 会被当成"它一件模型都没有" —— 那就是把一次
        # 通信故障说成了别人的配置问题。
        "上游答非所问也算答上了",
        COM_HTTP,
        '    if not isinstance(info, dict):\n        return None',
        '    if not isinstance(info, dict):\n        return {}',
        # ⚠ 抓它的**不是**上面那条"问不到上游"（那次是连接失败，跟这里无关），
        #   而是末尾那条"答非所问的清单不算答上了" —— 期望写错就会报成 ESCAPED。
        "答非所问的清单不算答上了",
    ),
    (
        # 反过来的一半：真答了"我这里什么都没有"必须算答上了，否则一个空实例
        # 会被永远当成"上游不在"，而运维怎么查都是对的。
        "上游答了「我一件都没有」却被当成没答",
        COM_HTTP,
        '    return folders\n\n\nasync def refresh',
        '    return folders or None\n\n\nasync def refresh',
        "问到了但一件都没有, 那是答上了",
    ),
    (
        "不告诉调用方为什么一个都跑不了（服务模式下的 ready:false 变成了哑的）",
        COM_HTTP,
        '        if not resolved["ready"] and _LISTING is None:\n'
        '            resolved["reason"] = capabilities_module.NO_UPSTREAM\n',
        "",
        "上游不在时提交要回 no_upstream",
    ),
    (
        "读了 reason 却不用（还是报「你没配模型」）",
        SERVER,
        '    if reason:\n        return {}, _fail(reason, detail={"category": category, "folder": folder})\n',
        '    if False:\n        return {}, _fail(reason, detail={"category": category, "folder": folder})\n',
        "上游不在时提交要回 no_upstream",
    ),
    (
        # 码在表里才有那句话与那个状态码；少了它，_fail 会退回 400 bad_request，
        # 于是"上游不在"变成"你的请求写错了"。
        "上游不在那个码不在错误表里",
        SERVER,
        '    capabilities_module.NO_UPSTREAM: 409,\n',
        "",
        "no_upstream 的状态码要是 409",
    ),
    (
        "文档不再播报错误码集合（客户端只好自己抄一份）",
        SERVER,
        '            errors=sorted(ERROR_STATUS),\n',
        '            errors=[],\n',
        "文档的 errors 里要有那个码",
    ),
    (
        # 用上游的 prompt_id 当自己的作业号 ⇒ 换一台上游就能撞上别人的号，
        # 而且"这个号是谁的"再也说不清（计划 §4.3 要的正是发自己的号）。
        "服务模式直接拿上游的 prompt_id 当作业号",
        COM_HTTP,
        '    job_id = str(uuid.uuid4())\n',
        '    job_id = str(prompt_id)\n',
        "服务模式要发自己的作业号",
    ),
    (
        "参考图不传给上游（图里指着一个上游没有的文件）",
        COM_HTTP,
        '    for inputs, image in _loaders(graph):\n        await _offer_reference(inputs, image)',
        '    for inputs, image in []:\n        await _offer_reference(inputs, image)',
        "图里那一格要改成上游答的名字",
    ),
    (
        "按我们发过去的名字改写，不问上游它把文件放哪了",
        COM_HTTP,
        '    inputs["image"] = f"{subfolder}/{uploaded}" if subfolder else uploaded\n',
        '    inputs["image"] = f"{INPUT_SUBFOLDER}/{name}"\n',
        "图里那一格要改成上游答的名字",
    ),
    (
        # 上游清单的节点名写错 ⇒ 一个模型都读不出来，文档说"上游什么都没有"。
        # 这类错只有对着**写死的**那份 object_info 才照得出来。
        # ⚠ 不能指望"逐字节相同"抓它: 读不出东西时那一格是"上游没这个节点 = 不敢判
        #   = 不缺"，于是文档照样 ready、两份照样一样 —— 必须打在"读出来了什么"上。
        "上游清单的节点名写错（一个模型都读不出来）",
        COM_HTTP,
        '    "checkpoints": ("CheckpointLoaderSimple", "ckpt_name"),',
        '    "checkpoints": ("CheckpointLoader", "ckpt_name"),',
        "上游答的那几个 checkpoint 名字要能读出来",
    ),
    (
        # 别人的作业混进我们的队列 ⇒ queue_position 变成"别人的号码"，
        # 而那个数会被当真地显示给用户。
        "不是这台服务交的作业也出现在队列里",
        COM_HTTP,
        '        if job_id:\n            found.append(job_id)',
        '        found.append(job_id)',
        "不是这台服务交的作业不许冒充成我们的",
    ),
    (
        "服务模式把端口写死（改配置不生效）",
        CLI,
        '        "port": serve["port"],',
        '        "port": 8889,',
        "改了配置就要生效",
    ),
    (
        "端口读了却不去绑它",
        CLI,
        '    site = web.TCPSite(runner, host, port)',
        '    site = web.TCPSite(runner, "127.0.0.1", 8889)',
        "绑定的必须是配置里那个地址",
    ),
    (
        "服务模式的 app 不带请求体上限（大 body 直接进内存）",
        CLI,
        '    application = web.Application(client_max_size=server.MAX_BODY_BYTES)',
        '    application = web.Application()',
        "服务模式的 app 要把请求体上限带上",
    ),
    (
        "端口不夹进合法区间（0 会被当成「随便挑一个」）",
        SETTINGS,
        'SERVE_PORT_RANGE = (1, 65535)',
        'SERVE_PORT_RANGE = (0, 65535)',
        "端口 0 要被夹进合法区间",
    ),
    (
        # 斜杠是**两处**都在去（写文件那一侧 `_merge`、读出来那一侧 `serve()`），
        # 所以只断言 `serve()` 的话这条变异是等价的 —— 抓它的那条断言读的是
        # 另一个公开读者（`load()`）：手写进文件的那一份本身就该是干净的。
        "上游地址尾部的斜杠不去（拼出来是双斜杠）",
        SETTINGS,
        '            base["serve"]["upstream"] = value.strip().rstrip("/")',
        '            base["serve"]["upstream"] = value.strip()',
        "上游地址尾部的斜杠要去掉",
    ),
    # --- 服务模式的前提：没有 ComfyUI 也要能 import -------------------------- #
    (
        # 这一条是**原来那行代码**：`server.py` 在 import 时就把进程内那个后端绑上，
        # 而只有它 import ComfyUI。于是 `python -m hamdraw_chp serve` 在"没有 ComfyUI
        # 的机器"上连 import 都过不去 —— 而那种机器正是这个入口唯一的理由。
        "后端在 import 时就选定（服务模式在没有 ComfyUI 的机器上起不来）",
        SERVER,
        "backend: Any = None",
        "backend: Any = backends.get()",
        "没有 ComfyUI 也要能 import",
    ),
    (
        # 后端没绑上时 `register_routes` 不许伸手去问它。
        "没绑后端时仍然去问后端要路由表",
        SERVER,
        '    if backend is None:\n        return False\n',
        "",
        "没有 ComfyUI 也要能 import",
    ),
    (
        # 「放过 ComfyUI 不在」与「放过所有 import 错误」只差一个字 —— 后者会把
        # "这包坏了"说成"这里没有 ComfyUI"，读的人就去错的地方找了；更要紧的是，
        # 插件会在 ComfyUI 里静悄悄地一个人都不注册。
        "把「没有 ComfyUI」的宽厚扩大到所有 import 错误",
        INIT,
        '    return str(error.name or "") in COMFYUI_MODULES',
        "    return True",
        "应当判成 「这包坏了」",
    ),
    (
        # 两种路由表只差一处写法：插件那份是 RouteTableDef（`get(path)` 返回装饰器），
        # 服务那份是活的 UrlDispatcher（`add_get(path, handler)`）。写死成前者，
        # 服务模式第一行路由就炸 —— 实测炸过一次，而当时的替身正是**这个形状**。
        "路由只按 ComfyUI 那种表挂（服务模式第一行就炸）",
        SERVER,
        '    if hasattr(table, "add_" + method):',
        "    if False:",
        "服务模式要把同一批路由挂到自己的 app 上",
    ),
    (
        # 反过来：写死成服务那种表，插件那一半一条路由都挂不上。
        # ⚠ 抓它的**不是**某条 `check(...)` —— 插件那一半是在 `import hamdraw_chp`
        #   时登记路由的（ComfyUI 就这么读它），所以这一条一改，测试进程连 import
        #   都过不去，没机会走到任何断言。证据因此是那句 AttributeError：替身按
        #   ComfyUI 的形状造（`get(path)` 返回装饰器），**根本没有 `add_get`**。
        #   这也正是判据本身 —— 一条只认 aiohttp dispatcher 的 `_bind` 挂不上插件。
        "路由只按 aiohttp 那种表挂（插件那一半一条都挂不上）",
        SERVER,
        '    if hasattr(table, "add_" + method):',
        "    if True:",
        "object has no attribute 'add_get'",
    ),
    # --- 凭据的字母表：字母、数字、- 和 _ ----------------------------------- #
    (
        # 这是那条规矩的**唯一定义**。放松它，两个收口就都成了摆设。
        "凭据字母表放松成「什么字符都收」",
        KEYS,
        'ALPHABET = re.compile(r"[A-Za-z0-9_-]+")',
        'ALPHABET = re.compile(r".+")',
        "凭据的字母表只认英文大小写字母、数字",
    ),
    (
        "控制台收下不认得的 key（规矩只写在文档里）",
        ADMIN,
        "    if not keys_module.spelling_ok(offered):",
        "    if False:",
        "控制台不该收下",
    ),
    (
        "配置节点收下不认得的密码（默认钥匙不受同一条规矩管）",
        NODES,
        "        if password and not keys_module.spelling_ok(password):",
        "        if False:",
        "应当被拒，而不是悄悄存下来",
    ),
]

originals = {}
for _, file, _, _, _ in MUTATIONS:
    originals.setdefault(file, (ROOT / file).read_text(encoding="utf-8"))

#: 动手之前先把**所有**锚点对一遍。对不上的一条会静默 SKIP，而 SKIP 会把后面几十条
#: 变成一张长长的"没抓住"清单 —— 真正的原因反而埋在最上面。实测踩过一次：
#: `known = None` 作为上一次运行的残留留在 ``server.py`` 里（那次进程被 SIGKILL，
#: 恢复代码根本没机会跑），幂等测试必红，于是它之后的所有断言都报"没抓住"，
#: 看起来像"新加的东西全没守住"。宁可在改坏任何东西之前就喊停。
_stale = [name for name, file, find, _, _ in MUTATIONS if find not in originals[file]]
if _stale:
    print("锚点对不上，一条变异都没跑 —— 先看这几处是不是被改过、挪走了，")
    print("或者源文件里还留着上一次没还原的变异：")
    for _name in _stale:
        print("  " + _name)
    sys.exit(3)


def restore_originals() -> None:
    for file, body in originals.items():
        (ROOT / file).write_text(body, encoding="utf-8")


def _bail(signum, _frame) -> None:
    """被 SIGTERM 杀掉时 ``finally`` 是不跑的 —— 那一次源文件就留在改坏的样子上。

    这个脚本动的是**真源码**，所以恢复不能只写在 ``finally`` 里：实测过一次被
    SIGTERM (工具调用被中断) 打断，``POLL_RETRY`` 就被留在 99 上了。
    """
    restore_originals()
    print(f"\n收到信号 {signum} —— 已把源文件还原，退出。")
    sys.exit(2)


for _signal in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    signal.signal(_signal, _bail)

escaped = []
try:
    for name, file, find, replace, expected in MUTATIONS:
        path = ROOT / file
        original = originals[file]
        if find not in original:
            escaped.append(name + "（锚点没找到，改不动）")
            print("SKIP    " + name)
            continue
        path.write_text(original.replace(find, replace, 1), encoding="utf-8")
        try:
            done = subprocess.run([sys.executable, str(ROOT / SPEC_TEST)],
                                  capture_output=True, text=True,
                                  timeout=RUN_TIMEOUT_SECONDS)
            output = done.stdout + done.stderr
        except subprocess.TimeoutExpired as expired:
            # 卡住了也是"没抓住"：一条跑不完的测试不算证据。
            output = ((expired.stdout or "") if isinstance(expired.stdout, str) else "") \
                + ((expired.stderr or "") if isinstance(expired.stderr, str) else "") \
                + f"\n（这条变异跑过了 {RUN_TIMEOUT_SECONDS} 秒还没结束）"
        finally:
            path.write_text(original, encoding="utf-8")
        caught = expected in output
        line = next((row.strip() for row in output.splitlines()
                     if "AssertionError" in row or "Error" in row), "(没有报错)")
        print(("CAUGHT  " if caught else "ESCAPED ") + name + "\n        " + line)
        if not caught:
            escaped.append(name + " —— 期望看到: " + expected)
        if path.read_text(encoding="utf-8") != original:
            raise SystemExit(file + " 没有还原")
finally:
    restore_originals()

if escaped:
    print("\nv2 规范变异检查 FAILED:\n  " + "\n  ".join(escaped))
    sys.exit(1)
print("\nv2 规范变异检查: ok（" + str(len(MUTATIONS)) + " 处变异，全部按名字抓住）")
