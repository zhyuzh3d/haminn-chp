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
        "输出地址不再由 API_ROOT 拼（客户端拿到的路径和文档公布的不是同一条）",
        INPROC,
        '"url": f"{capabilities_module.API_ROOT}/jobs/{prompt_id}/output/{len(files)}",',
        '"url": f"/cvp/jobs/{prompt_id}/output/{len(files)}",',
        "输出地址必须由 API_ROOT 拼出",
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
        "endpoints 七个键",
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
        '                                          backend.history(str(subject["id"]))),\n'
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
