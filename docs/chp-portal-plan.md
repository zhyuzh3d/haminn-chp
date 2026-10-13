# CHP 全面升级与 TTS 接入开发计划

> **副标题**：把 CHP 从「ComfyUI 的绘图协议」升级为「**Haminn 综合入口程序**」—— 本机所有本地模型的一个门面，
> 并接入第一类非绘图能力（**TTS**），同时补上 key 授权与 web 控制台。
>
> **本文只写：定性是什么、定稿是什么、怎么改、什么顺序、判据是什么。不写实现代码。**
>
> **与既有文档的关系**
> - [`plans/chp-v2-plan.md`](../plans/chp-v2-plan.md)：v2 定稿，图片侧已完成并在 A1X 验收。**本文不改它任何一条。**
> - [`plans/chp-spec.md`](../plans/chp-spec.md)：规范正文。本文 §3 是对它的**加法**。
> - [`plans/chp-speech-plan.md`](../plans/chp-speech-plan.md)：本计划的**前身**，只覆盖 TTS 那一半。
>   本文把它**整体吸收**（§3.4 的 `speech` 段、§5 的客户端改动、§9 的真机验收都源自它），
>   并在其上加了 key、控制台、服务模式、改名。
>   ⇒ **执行时以本文为准**；那份文档保留为「为什么这么定」的推理过程。
>
> **口径来源**：业主 2026-10-12 全天逐条口述（见 §13 的定稿清单）。

---

## 0 一句话范围

**CHP 仍然只有一个根 `/chp`、一份信息文档、一套错误码；`spec` 仍是 `chp/2`。**
本轮做四件加法：**① 信息文档改为需要 key 并只播报该 key 的可用能力；② 加第九个顶层键 `speech`（TTS）；③ 加 key 表与控制台；④ 加一个能脱离 ComfyUI 独立运行的入口。**
另外做一次**改名**：CHP 的含义从「ComfyUI Haminn Protocol」改为「**Consolidated Haminn Portal**」（中文「Haminn 综合入口程序」），
ComfyUI 里那个插件改称「**CHP 插件**」（简称 **CHPCP**）。

---

## 0.1 第二轮核查修订（2026-10-13，逐条读代码得出）

本节把**上一版计划里被代码推翻的论断**集中记下来，供核对。**每一条都已在下文对应小节改掉**；
这里只做索引，不重复内容。判据一律现查，命令写在括号里。

| # | 上一版怎么写的 | 代码实际是什么 | 改在哪 |
|---|---|---|---|
| 1 | 「`package-plugin.py` 搬到 CHP 仓，**脚本内容一行不改**」 | `SOURCE = ROOT / "comfyui-plugin"`（`tools/package-plugin.py:20`）—— 搬完之后 `<CHP>/comfyui-plugin` 不存在，脚本立刻废 | §4.6、§14.8 |
| 2 | S-1 判据②「新仓 `package-plugin.py --check` 报 `plugin archive ok`」 | `--check` 的分支是 **`if not ARCHIVE.exists(): raise SystemExit`**（`:102`）⇒ 新仓 `release/` 为空时**必红**；而 §14.8 又要求「新仓 `release/` 从空开始」。两条自相矛盾 | §8 S-1 改为**跨仓 sha256 相等** |
| 3 | §14.8 `git rm --quiet plans/chp-speech-plan.md` | 该文件 **未跟踪**（`git ls-files --error-unmatch` 失败）⇒ `git rm` 报 `did not match any files` | §14.8 |
| 4 | §2.1 的 PoseGi 改名点位 | 漏了 **`PoseGi/app/services/translate.js:77`** —— 那里有一整条协议选择项写着同一个旧串（与 `providers.js:44` 是同一件事的第二份副本，且**没有任何测试钉着它**） | §2.1 |
| 5 | §14.3 铁律3 的判据「hamdraw 里 `grep "package-plugin"` 只剩文档一句」 | 会**假绿**：`hamdraw/CONTRIBUTING.md:48` 写着 `python3 tools/package-plugin.py --check`，搬迁后这句是错的，但它长得就像「文档指引」 | §14.3、§14.8 |
| 6 | §2.1 说 27/29/14 个文件；§5 说 20/15/11 | 两处**自相矛盾**且都不准。实测（大小写敏感、排除 `.git`）：**hamdraw 25 / chataxi 12 / PoseGi 27**；只算 `app/` 是 **5 / 7 / 11** | §2.1、§5 统一成一个口径 |
| 7 | §10/§12「`haminnapp` 里 `ComfyUI` 只有 1 处」 | 实测 **2 处**（`NativeHttpClient.kt:718` + `androidTest/.../NativeHttpConnectionReuseInstrumentedTest.kt:29`），都是注释。零 CHP 的结论不变 | §10 |
| 8 | §1.4「`families/` 549 行」、§14.1「`tests/` 2135 行」 | 实测 **`families/` 754 行**（146+204+295+109）、**`tests/` 2161 行**。包总计 3823、测试 2161、合计 5984（对得上） | §1.4、§14.1 |
| 9 | §3.3「`document()` 只多一个可选参数」 | `rules()` 与 `abilities()` 都是**自己遍历 `CATEGORY_TABLE`** 的模块级函数（`capabilities.py:580` / `:594`）⇒ 只给 `document()` 加参数**过滤不到它们** | §4.2 |
| 10 | §3.2「无 key ⇒ 401」 | `_authorized()` **在密码为空时直接 `return True`**（`server.py:245-247`），`hamdraw/README.md:61` 也写着「密码留空则不校验」⇒ **一把 key 都没配时服务是公开的**，那条断言会红 | 新增 §3.2.1 |
| 11 | §4.2「鉴权复用 `_authorized()`」 | 执行层校验要知道**命中的是哪把 key**，而 `_authorized()` 只回 `bool` ⇒ 拿不到授权集 | §4.2 新增 `_key_of()` |
| 12 | §4.4「三个配置文件放 `hamdraw_chp/`」 | **`package-plugin.py` 不看 `.gitignore`**：它对 `hamdraw_chp/` 整树 `rglob`，只排除 `__pycache__`/`.pyc`（`:60-62`）。三个运行时文件若在构建树里，**会被打进发布 zip** | 新增 §4.4.1（安全） |
| 13 | §4.5 控制台用 Basic | 数据面的 `_token_of()` 也认 Basic（`server.py:221-233`，取 `:` 之后那段）⇒ 两套 Basic 会互认 | §4.5 加一条分界 |
| 14 | §5.2/§5.5 只提「PoseGi `providers.js:527` 有测试钉着」（1 处） | 「这个地址不是 CHP 服务」实测被 **三处测试/变异 + 三处实现** 钉着：`chataxi/tests/runtime.test.mjs:1676`、`chataxi/tests/.mutate-chp.mjs:221-222`、`PoseGi/tests/discovery.test.mjs:309`；实现点是 `hamdraw/providers.js:559`、`chataxi/model-services.js:665`（+ `i18n-en.js:1071`）、`PoseGi/providers.js:527` | §5.2、§5.5 |
| 15 | §14.5「旧链接一个都不动」 | 那条规矩管的是**文件**，不是**页面按钮**。官网现在挂着**三个按钮、三个不同版本**：`hamdraw/index.html:150`=v3.0.0、`:204`=v3.1.1、`posegi/index.html:143`=v2.3.0 | §14.5 拆成两句 |
| 16 | §2.1/§5.5 的行号 | `verify.mjs` 第四条内嵌断言在 **221**（不是 220）；`PoseGi/app/services/providers.js` 的 `chpInfoRequest` 在 **508**（不是 506） | 已在原文校正 |
| 17 | §5.5 说 `tests/providers.test.mjs:96` 是 label | ✅ 正确（`:96` 就是 `plugin: { …, label: … }` 那一行） | 不改 |
| 18 | §6.1 说「现有 `.gitignore` 只有 `__pycache__/`、`*.pyc`、`.DS_Store`」 | 那三条在 **hamdraw 仓根**（`hamdraw/.gitignore`）；`comfyui-plugin/.gitignore` **根本不存在** | §4.4 说清是哪一份 |

**结论：协议与阶段划分不用动**（§3 的加法、§4 的抽离、§8 的顺序都经得起读代码）；
要改的是**搬迁的机械细节**、**key 的两处边界**、**打包的安全排除项**、**官网链接那一句话**，以及一批行号与计数。

**三处「一读代码就变强」的改动**（不是修错，是升级；**三条都已在 `/tmp` 里跑过对照实验**）：

1. **搬迁的判据从「跑得通」升级为「证得同」**：新仓重建的 v3.1.1 zip，其 `sha256` 必须**等于**搬迁前 hamdraw 那份
   （`172ab450c4f883d3f746ed87ea5783bf372387020f6bfac339cff0933a6bc5fb`）。
   这一条同时证明「搬的是同一批字节」与「`SOURCE` 那一行改对了」——比任何 `grep` 都硬（§8 S-1）。
   **实测**：把 `hamdraw_chp/` + `README.md` + `package-plugin.py`（只把 `SOURCE` 改成 `ROOT`）放进一个空目录重建，
   sha256 **与上面那串逐字符相同**。⇒ 这一条不是设想，是已验证的判据。
2. **三个网站按钮指向 `latest`**：把「漂移」在**页面上**也一并消灭，而不只是在 happ 里（§14.5）。
3. **打包器加排除项**：key 文件不许进 zip（§4.4.1）。
   **实测**：把三个假密钥文件放进 `hamdraw_chp/` 后用**现有**脚本打包 ⇒ zip 里真的多出
   `['hamdraw_chp/chp_admin.json', 'hamdraw_chp/chp_keys.json', 'hamdraw_chp/hamdraw_settings.json']`；
   加上排除名单后 ⇒ **`[]`**，且 sha256 回到那串 pristine 值（证明排除项不改变其它任何字节）。
   ⇒ 这条闸门**已被证明会红**，不是摆设。

---

## 1 定性：CHP 是什么、不是什么

### 1.1 三个名字，各有各的层

| 名字 | 指什么 | 出现在哪 |
|---|---|---|
| **CHP** = Consolidated Haminn Portal / Haminn 综合入口程序 | **数据面的门面服务**本身：一个端口、一把 key、一份能力文档 | 文档、网页、happ 的协议卡名 |
| **CHP 插件**（**CHPCP** = CHP ComfyUI Plugin） | 装在 ComfyUI 里的那个插件/节点，是 **CHP 的 ComfyUI 后端** | `/chp/info` 的 `plugin.label`、ComfyUI 画布、安装说明 |
| **CHP 控制台** | CHP 的**管理面**：管 key 与 key 的授权 | 只在本机/局域网浏览器里 |

**改名只落在「自称与产物名」这一层**（§2）。上次改名（ComfyUI HamDraw Plugin → ComfyUI Haminn Protocol）
就是这么做的，`comfyui-plugin/hamdraw_chp/__init__.py` 的 docstring 里已经立过这条规矩：
*"the protocol was renamed, not the deployment."*

### 1.2 三个面，职责不许混

```
数据面   happ ──► CHP（路由 + 能力播报）──► 各后端（ComfyUI / TTS / 翻译）
管理面   CHP 控制台（本机或局域网 + 独立凭据）──► 只管 key 与 key 的授权
控制面   A1X control-plane :8188（设备原有的）──► 管容器与显存，CHP 不接管
```

**控制面实测（2026-10-12 当场）**：

```
PID 2503  已跑 10h53m
/usr/bin/python3 /home/AOKZOE/AI/minimax-h3/releases/control-plane/current/web/server.py
127.0.0.1:8188/  →  401 {"error":"authentication_required"}     （/api /docs /openapi.json /status 全 401）
```

⇒ 它是**宿主上的一个进程**（不是容器），**自己的名字就叫 `control-plane`**，且**全部路由在鉴权后**。

### 1.3 CHP 做什么 / 明确不做什么

**做**：把一个请求**路由**到正确的后端；**如实播报**此刻能用什么；**统一**鉴权、错误码、发现流程。

**不做 GPU 调度**（业主已定，本文确认）。四条理由：

1. **分层已天然对上**：控制台 = 控制面，CHP = 数据面。显存容量、模型加载时间、当前谁在跑，
   与 `accelerators`、上游地址同属「**只对那台机器成立**」的部署侧事实（v2 已两次把这类事实挡在 HTTP 之外）。
2. **调度只能有一个仲裁者**。控制台已在管容器与显存；CHP 再来一套 = **两个调度器抢同一张卡** ——
   最难查的一类故障：偶发、跟时序有关、两边日志都自认为对。
3. **CHP 的价值在统一契约，不在统一调度**。适配器只需知道「**怎么调它**」，不需知道「**它怎么进显存**」。
4. **别接管一个会漂的接口**。那是 `minimax-h3` 的 `control-plane`，带自己的发布结构（`releases/.../current/`）。

**但「不调度」不等于「不负责」** —— CHP 必须承担一条对应责任，否则 happ 会撞上「模型还没醒」的黑洞（见 §3.3、§3.6）：

- 信息文档里**如实**标出可用性（`ready` / `missing` 字段今天就有）；
- 请求打到没唤醒的后端**不能是 500**，要回一个明确的「正在唤醒 / 暂不可用」+ 可重试语义；
- 「第一次请求慢」是**后端的性质**，由后端自己扛（TTS 容器首次请求触发加载，ComfyUI 本来就常驻）。

⇒ **CHP 的调度逻辑 = 0**，但对 happ 的承诺仍然完整：**永远只看到「能用」或「暂时不能用，稍后再试」**。

**何时才该把调度收回 CHP**：同一张卡上出现「两个后端必须互斥」而控制台管不了时。
到那天加的应当是**「互斥」这一条规则**，不是一整套调度器。

**不去问控制面要就绪状态**：它全部路由要鉴权，CHP 不欠它的接口，也不把两个项目的版本线拴在一起。
CHP 自己探（探不到就报不可用），这与「后端缺席 ≠ 服务缺席」是同一条。

### 1.4 现状清点（本次读代码得出，是全部改动的依据）

`hamdraw/comfyui-plugin/hamdraw_chp/`（5984 行含测试）—— **S-1 之后这个路径变成 `<CHP>/hamdraw_chp/`**（§14.2）。本节按**搬迁前**的位置写，S-1 之后路径按 §14.2 读：

| 文件 | 行数 | 对 ComfyUI 的依赖 |
|---|---|---|
| `capabilities.py` | 679 | **零**（协议与两张表；`document()` 的注释明写「本模块是规范，不许依赖碰网络或 ComfyUI 模型目录的那部分」） |
| `settings.py` | 445 | **零**（只有 json / os / pathlib） |
| `translate.py` | 380 | **零**（只有 aiohttp，已在调外部服务 8022） |
| `families/` | 754 | **零**（图构造器，只吐 dict；`__init__` 146 + `checkpoint` 204 + `qwen_image` 295 + `graph` 109） |
| `server.py` | 1184 | **八行、四类**：`import folder_paths`(`:109`) + `folder_paths.get_*`(`:268`/`:385`/`:704-706`) + `PromptServer.instance`(`:197`/`:200`) + `import execution`(`:990`)。S1 的判据是 `grep -cE` **== 0**，四类一起算 |
| `nodes.py` | 330 | **一处**：`import folder_paths`（只给配置节点做下拉） |
| `__init__.py` | 36 | 入口：注册节点 + `ROUTES_REGISTERED = register_routes()` |

**结论：它本来就是「一个库 + 两个薄薄的 ComfyUI 适配层」。** 所以「一个包、两个入口」是**把它写进目录结构**，不是重写。

---

## 2 命名与冻结线

### 2.1 要改的显示名（改名清单，含一处门禁）

| 位置 | 现在 | 改成 |
|---|---|---|
| `capabilities.py:54` `PLUGIN_LABEL`（**`/chp/info` 里 happ 实际读到的那行**） | `{"zh": "CHP 插件（ComfyUI Haminn Protocol）", "en": "CHP plugin (ComfyUI Haminn Protocol)"}` | `{"zh": "CHP 插件（CHPCP）", "en": "CHP plugin (CHPCP)"}` |
| `comfyui-plugin/README.md` 标题 + 首段 | `# CHP 插件 — ComfyUI Haminn Protocol` | CHP = Haminn 综合入口程序；本目录是它的 ComfyUI 后端 |
| `hamdraw_chp/__init__.py` / `server.py` 的 docstring | 同上 | 同上 |
| `plans/chp-spec.md` 标题 + 文档示例里的 label | `# ComfyUI Haminn Protocol（CHP）v2` | CHP = Consolidated Haminn Portal；`spec` 值仍是 `chp/2` |
| `hamdraw/app/services/providers.js:8` 协议卡名 | `"CHP 插件（ComfyUI Haminn Protocol，推荐）"` | 新名（**改了必须同步改门禁**，见下行） |
| ⚠ `hamdraw/tools/verify.mjs:187` | **断言的就是上面那个字符串** | 同步改成新字符串（是更新期望值，不是放宽断言） |
| `hamdraw/tests/providers.test.mjs:96` | fixture 里的 label | 同步 |
| `hamdraw/README.md:32,54`、`guid.md:12` | 「CHP 插件（ComfyUI Haminn Protocol）」 | 同步 |
| `chataxi` 侧 **12** 个文件提到 CHP（`app/` 7 个：`catalog.js` / `model-services.js` / `draw.js` / `model-single-editor.js` / `models.js` / `store.js` / `i18n-en.js`；另加 `README.md` / `tests/runtime.test.mjs` / `tests/ui-flow.mjs` / **`tests/.mutate-chp.mjs`** / `tools/verify.mjs`） | 协议描述文案 | 同步（**`.mutate-chp.mjs` 上一版漏列**，见 §0.1 第 14 条） |
| 官网 `haminnweb/public/pages/happs.html`(1) + `public/downloads/happs/life.airen.hamdraw/happ-info.json`(2) | 同上 | 同步 |
| `hamdraw` 的 `CONTRIBUTING.md:48` | `python3 tools/package-plugin.py --check  # 只在改动触及 CHP 插件时` | **S-1 必须改** —— 脚本搬走之后这句话是错的（改指 `haminn-chp` 仓）。上一版漏了它，而它**长得像文档指引**，会骗过 §14.3 铁律3 的 grep 判据 |
| **PoseGi** `README.md`、`app/services/providers.js:44`（协议卡名）、**`app/services/translate.js:77`（协议选择项，上一版漏了）**、`app/components/settings.js:871` | 「CHP 插件（ComfyUI Haminn Protocol）」 | 同步 |
| **PoseGi** `app/services/providers.js:533` 的注释 | 「信息接口是**公开**的（密码错了也照答，由 `auth.authorized` …）」 | **必须改** —— 改成 401 后这句话就是错的（详见 §5.2） |
| **PoseGi** `tests/fixtures/chp-info-3.1.0.json` | 一份含旧 label 的完整文档快照 | **不改**它，**另存** `chp-info-3.2.0.json`（详见 §5.2.1） |
| **PoseGi** `app/assets/models/ikea.js:52` | 命中「CHP」 | **假命中，不许改** —— 那是一段 base64 网格数据里凑出的三个字母 |
| ~~`haminnapp`（宿主）的商店页与 `MainActivity.kt`~~ | ~~有 CHP 字样~~ | **已撤销：该仓源码零命中**（详见 §12） |

**读 CHP 的 happ 有三个：HamDraw、Chataxi、PoseGi。** 计数用**一个口径**（大小写敏感、排除 `.git`，
含测试与工具 —— 这才是「要改的字节在哪」的完整答案），**不要再分两套数**（上一版 §2.1 写 27/29/14、
§5 写 20/15/11，两处自相矛盾且都不准）：

| 仓 | 全仓命中文件 | 其中 `app/` 里（= 真正要改的源码） |
|---|---|---|
| `hamdraw` | 25 | **5**：`core/namespace.js` · `components/settings.js` · `services/store.js` · `services/image-engine.js` · `services/providers.js` |
| `chataxi` | 12 | **7**：`features/model-single-editor.js` · `features/models.js` · `data/i18n-en.js` · `data/store.js` · `services/model-services.js` · `services/catalog.js` · `services/draw.js` |
| `PoseGi` | 27 | **11**（`providers.js` / `settings.js` / `translate.js` / `store.js` / `image-engine.js` / `utils.js` / `namespace.js` / `app.js` / `features/editor.js` / `features/self-test.js` / `assets/models/ikea.js`——**末一个是假命中**） |

⇒ **S7（改名）的检查清单以现查为准，不照本表枚举。** 本表就已经漏过一处（`PoseGi/translate.js`），
枚举必漏 —— 判据要写 `grep -rlI "ComfyUI Haminn Protocol" <仓> --exclude-dir=.git` **现查**，再逐条看一眼是不是假命中。

**ImaHamster（`life.airen.imahamster`，视觉助手）不读 CHP** —— 实测**全仓零命中**
（`grep -rlI "CHP" imahamster --exclude-dir=.git` ⇒ 0），所以**本轮不升级**。

**英文文案同步**：`PLUGIN_LABEL` 是双语的；Chataxi 新增中文文案必须同时补 `app/data/i18n-en.js`（项目硬规矩）。

### 2.2 冻结线（一个字不动）

| 冻结项 | 值 | 为什么不能动 |
|---|---|---|
| 根路径 | `/chp` | 已发布客户端的既有地址（虽然客户端从 `endpoints` 读，但根是规范写死的） |
| 规范版本 | `spec: "chp/2"` | 线上标识，不是缩写的承诺；升版本会让还没更新的绘图卡白挨「插件比应用新」 |
| 包名 / 目录名 / `PLUGIN_ID` | `hamdraw_chp` | 改了会让每个老用户的 `custom_nodes/hamdraw_chp/` 变成两份，或逼他们手工删 |
| 环境变量前缀 | `HAMDRAW_*` | 同上，且已有部署在用它 |
| 设置文件名 | `hamdraw_settings.json` | 同上 |
| **ComfyUI 节点的输入名** | `nodes.py` 的 `INPUT_TYPES` 键 | **已存的工作流 JSON 以这些名字为键**，改了老用户的工作流就报错。语义变了（「密码」→「默认 key」）只改文档与提示文案，**不改键名** |
| **发布包名** | `hamdraw-comfyui-plugin-v<ver>.zip` | **已发出的下载链接**按这个名字（官网两个页面上就有），改名就是让它们 404 ⇒ 独立成仓**也不改名**（§14.3）。注：`verify.mjs:224` 的正则与 `embed-plugin.py` **本轮随内嵌链一起删除**（§5.5），不再是理由 |
| **官网 CHP 落地页路径** | `https://haminn.airen.life/chp.html` | 它被**编译进三个 happ 的源码**（§5.5）⇒ 改它要连发三个 happ。**页内容随时可改，路径不能动** |
| **官网 CHP 下载别名** | `public/downloads/chp/hamdraw-comfyui-plugin-latest.zip` | 「永远指向最新版」的**唯一**一条链接：页面只认它，**不认版本号** ⇒ 插件升版不必改页面、更不必重发 happ。**版本化文件只增不改，别名每次发布覆盖**；这条不变量由 `tools/check-site.py` 守着（§14.5.1） |
| **插件 zip 在官网的新家** | `public/downloads/chp/` | 新页面从第一天就指向这里；`downloads/hamdraw/` 里的旧链接**一个都不动**（§14.5） |
| 历史发布产物文件名、`intro/` 目录 | —— | 既有定稿 |

---

## 3 协议升级（对 `chp-spec.md` 的加法）

### 3.1 `spec` 不动，仍是 `chp/2`

依据是规范自己那条规矩（v2 §1.1 规矩 2）：**「未知顶层键客户端必须忽略」**。
这条规则存在的唯一理由就是让插件能加一节而不弄坏已发布的客户端。本轮三处加法都靠它：

| 加法 | 位置 |
|---|---|
| `speech` 段 | 顶层键，第九个 |
| `endpoints.speech` | `endpoints` 第八个键 |
| key 授权 | 不新增顶层键 —— 它改变的是**已有键的内容**（见 §3.3） |

### 3.2 `/chp/info` 改为**需要 key**

**这是本轮唯一一处会改变既有可见行为的地方**，必须讲清楚。

| | 今天 | 本轮起 |
|---|---|---|
| 无 key / 错 key（**且已配至少一把 key**ᴬ） | **200**，正常返回文档，靠 `auth.authorized: false` 告知 | **401 `unauthorized`** |
| 无 key / 错 key（**一把都没配**ᴬ） | **200**，全部能力 | **200**，全部能力（**逐字不变**，见 §3.2.1） |
| 有 key | 200，返回全部能力 | 200，**只返回这把 key 能用的能力** |

ᴬ 前提写在这里是有意的：`_authorized()` 在**没有任何钥匙**时返回 `True`（`server.py:245-247`），
所以「无 key ⇒ 401」只在配了 key 之后才成立。**两条都要有单测**（§3.2.1）。

**为什么可以这么改（原设计的好处一点没丢）**：原设计「未授权也回答」的唯一目的是「一次调用同时告出『地址对』和『密码错』」。
改成 401 之后，客户端仍然能区分三件事，而且分得更清：

| 现象 | 含义 |
|---|---|
| 连不上 / 超时 | 地址不对，或服务没起 |
| **401** | **地址对、是 CHP、但 key 不对** |
| 200 但 `spec` 不是 `chp/*` | 地址通了，但那不是 CHP |

⇒ **客户端零信息损失。** 而且这是必须的：文档内容从此**依赖 key**，未授权状态下已经没有「正确的文档」可答。

**`auth` 段保留**（不删字段，删字段是破坏）：`required: true`、`authorized: true`
—— 语义变成「本服务需要钥匙，而你带的这一把是对的」。

**401 的响应体要能自证是 CHP**（加法，成本为零）：

```json
{ "error": "unauthorized", "spec": "chp/2", "message": "访问密码不正确…" }
```

在既有 `_fail` 结构上只多一个 `spec`（**实现上就是给 `_fail()` 加一个可选的 `spec=` 参数**，
`server.py:207`；**只有 401 用它**，其余错误码的响应形状**一个字节都不变** —— 客户端是按形状解析的）。
理由见 §5.2：客户端本来会按「地址可能填错」去试两三个候选路径，
**没有这个字段，它就只能靠猜 URL 来判断「这是 CHP，只是钥匙不对」还是「那里根本没有插件」** ——
而这两种情况给用户的下一步动作完全不同。有了 `spec`，401 变成一个**确定的答案**。

### 3.2.1 边界：**一把 key 都没配**时，服务是公开的（不许忘）

`_authorized()` 今天的第一句是 `expected = _password(); if not expected: return True`（`server.py:245-247`），
`hamdraw/README.md:61` 也明写「密码留空则不校验」。这条**不能在本轮被无声地取消** —— 用户的工作流与卡片里
存的可能就是空密码。⇒ **规范里写死这两态**：

| 部署形态 | 行为 | 为什么 |
|---|---|---|
| **没配任何 key**（`chp_keys.json` 不存在或 `keys: []`，且配置节点的密码与 `HAMDRAW_PASSWORD` 都为空） | **`/chp/info` 返回 200，带全部能力；`auth.required: false`** | 与今天**逐字相同**：空密码就是公开服务。老用户零改动 |
| **配了至少一把 key**（默认 key 非空，或 key 表里有条目） | **`auth.required: true`**；无 key / 错 key ⇒ **401**；每个端点都校验 | 「没有 key 就等于什么都没有对外」（§3.3）**只在配了 key 之后**才成立 |

**所以 §3.3 那句「不设全局开关」的准确表述是**：「对外」的开关**就是**「有没有配 key」这一件事，
不需要第三个布尔量。**判据必须带上这一条**，否则 S2 的「无 key ⇒ 401」会在**空密码部署**上红：

```
无 key ⇒ 401        （前提：已配至少一把 key）
无 key ⇒ 200 全能力  （前提：一把都没配）
```

⚠ 这一条同时影响 §9 的真机验收第 2 条 —— 单测里两条都要写，别只写前一条。

### 3.3 key 授权：**播报**与**执行**两层，缺一不可

**授权粒度 = `category`**（即对外的一个接口/场景），**不按模型文件** —— 模型文件名只对那台机器成立，而 key 是设备级的，粒度太细没有意义。

**第一层 · 播报**：`/chp/info` 返回的 `rules`、`abilities`、`input_schemas`、`speech`
**全部按该 key 的授权集过滤** —— 播报「这把 key 实际能用到的完整文法」。
理由与 v2 那条「文档不能声称一个它不会用的模型」是同一条：happ 的槽是靠 `signature` 匹配的，
如果文档里有一条它打不通的规则，槽里就会出现一个点不动的选项。

**第二层 · 执行（承重，最容易漏）**：`/chp/jobs` 与 `/chp/speech` **每次都要校验**请求的 `category`
是否在该 key 的授权集里，不在就 **403 `forbidden_capability`**。

> **`/chp/info` 按 key 少列几项 ≠ 权限。** 只知道 category 名字的人可以绕过界面直接 POST。
> **「看不到」是障眼法，「拒收」才是权限。** 这条不写下来一定会漏。

**「对外可用」不需要第三个开关**：因为 `/chp/info` 现在需要 key，**没有 key 就等于什么都没有对外**。
所以「对外可用的模型」完全由「有没有一把 key 授权它」决定 —— 不设全局开关，少一层就少一处「为什么它不出现」的歧义。

### 3.4 顶层键 `speech`（TTS）

（本节吸收 `chp-speech-plan.md` §2，判据见其 §6，此处只留定稿。）

```json
"speech": {
  "rules": [
    { "category": "speak", "rule": "txt-2-sph", "needs": { "text": true } }
  ],
  "abilities": [
    { "name": "qwen3-tts-0.6b", "ready": true, "missing": [],
      "files": { "engine": "qwen3-tts-12hz-0.6b-customvoice-q8_0.gguf" },
      "audio": { "sample_rate": 24000, "channels": 1, "formats": ["pcm", "wav"], "streaming": true },
      "voices": [ { "id": "vivian", "label": "Vivian", "languages": ["zh","en"] }, "…共 9 个" ] }
  ]
}
```

**五处定稿**（每条都是把 v2 的既有想法平移到语音）：

1. **两张表照旧**：`rules` 是「客户端要什么」，`abilities` 是「谁能答」。
2. **音色菜单是手写的 `voices`，顺序即规范**（同 `frames`）：第一个即默认音色；客户端**只选不算**、服务端**成员校验**、
   未知音色回 `unsupported_voice`。`/v1/voices` 是空的 ⇒ 这张表**只能**由实现手写并播报。
3. **模态加一个字**：`sph`（speech）。`txt-2-sph` 落进规范已有的 `<模态> -2- <输出>` 文法
   （`capabilities.py:105 signature_of` 就是按字面 `-2-` 派生的），**不新增轴**。
4. **`audio` 是这份能力自己的输出规格**，客户端**读它、不猜它**。
5. **`files.engine` 用引擎自己的模型文件名**，与图片侧 `files.checkpoint` 同一个位置、同一个道理。

**字段名 `text` 而不是 `prompt`（承重）**：`prompt` 在 CHP 里带副作用 —— `rules[].prompt.language: "en"`
会让服务端在提交路径上**自动翻译**（`translate.py` 的 `ensure_english`），把中文念成英文。
**speech 的文本永不翻译**，这一句写进规范。`text` 还与模态名 `txt` 同字，符合既有构词法。

**`endpoints` 加第八个键**：`"speech": "/chp/speech"`（地址必须从文档里读，这是 §1.6 的规则）。

### 3.5 传输：**一条路由，`stream` 决定内容类型**（不套作业模型）

契约从此有**两种传输**，这是本轮最需要说明的决定。

| | 图片（今天） | 语音（本轮） |
|---|---|---|
| 形态 | 提交作业 → 轮询 → 取件 | **一次请求，边合成边回字节** |
| 为什么 | 一张成品图 20~45 s，必须有进度、排队、取消 | 一句话 1~2 s，**慢的正是首字节** |
| 路由 | `/chp/jobs` 等五个 | `/chp/speech` 一个 |

**不套作业模型**三个理由：① Chataxi 的朗读链路就是「逐段 PCM 进播放队列」，
套作业模型 = 合成完 → 取件 → 才能播，白丢 1 个 RTT 加整段合成时间；
② 排队位次、`progress`、`cancel`、`output/{index}` 为 1.5 秒音频全是死重；
③ 引擎本来就是这么说话的（`stream: true` → 分块 PCM）。

`stream: false` ⇒ 一次返回整个 `audio/wav`。同一个端点、两种内容类型，是引擎已有的行为，白送。
**错误一律是 JSON，且在开始写 body 之前就用状态码定好** —— 客户端的判据是「先看状态码，非 2xx 就按 JSON 解析」。

### 3.6 错误码（在 v2 §6 的表上加四条）

| 码 | HTTP | 文案 | 何时 |
|---|---|---|---|
| `forbidden_capability` | 403 | 这把 key 没有这个能力 | §3.3 第二层 |
| `unsupported_voice` | 400 | 这台引擎没有这个音色，请从信息接口 `speech.abilities[].voices` 里取 | 音色成员校验 |
| `no_engine` | 409 | 没有可用的语音引擎，请先在 CHP 配置里填好语音服务地址 | 引擎未配 / 连不上 / 引擎 401 |
| `speech_failed` | 502 | 语音引擎没有正常应答 | 引擎 500 或其他 |

**关键一条**：后端侧的任何失败（连不上 / 令牌错 / 后端 500）**都不许把后端地址或令牌漏给客户端**，
统一收敛成上面的码，明细**只进那台机器的日志**。这是 `translate.py` 已经在遵守的规矩（*never leaks the internal address*）。

**「正在唤醒」不新增错误码**：它复用既有的 `busy`（可重试语义），客户端看到 `busy` 就是「稍后再试」。
不新增一个「在加载」的码 —— 那会让客户端区分两个它其实不需要区分的状态。

---

## 4 插件侧改动

### 4.1 S1 · Backend 接口抽离（纯重构，零行为变化）

**目标**：把 `server.py` 里那**四处** ComfyUI 耦合收进一个后端对象，让协议层只认接口。

```
hamdraw_chp/backends/__init__.py      接口说明 + 一个取后端的函数（不搞 registry、不搞装饰器、不搞 import 扫描
                                      —— 与 families/ 同一条风格：一屏能看完全部实现）
hamdraw_chp/backends/comfy_inproc.py  今天 server.py 里那四件事原样搬进来
```

接口（今天只需要这五个动词）：

| 动词 | 现在在 `server.py` 的哪里 |
|---|---|
| `abilities(files_of)` → 模型清单与就绪状态 | `_available_files` / `_checkpoint` / `_model_files` / `_accelerator` / `_absent` / `_abilities_of` |
| `queue()` → (running, pending) | `_queue_snapshot`（`PromptServer` 的队列） |
| `submit(graph)` → prompt_id | `_prompt_server()` + `import execution` 的 `validate_prompt` + 入队 |
| `state(prompt_id, ...)` → 状态与进度 | `_history_entry` / `_status_of` / `_error_of` / `_state_of` / `_queue_position` |
| `outputs(prompt_id)` → 产物列表 | `_outputs_of` / `_safe_output_path` |
| `cancel(prompt_id)` | `_drop_pending` / `_interrupt_running` |

**判据（机械可查）**：

- `comfyui-plugin/tests/test_spec.py` 与 `tests/test_mask_graph.py` **全绿**；
- `grep -cE "folder_paths|PromptServer|import execution" hamdraw_chp/server.py` **等于 0**；
- A1X 上 `/chp/info` 与升级前**逐字节相同**（同一个 key 下）。

**`nodes.py` 的 `folder_paths` 留在原地** —— 它属于配置节点的下拉选项，与 HTTP 服务无关。

### 4.2 S3 · `speech`：新模块 + 一条路由

`hamdraw_chp/speech.py`，照 `translate.py` 的形状写（这是既有模式的复用，不是新发明）：

| 职责 | 与 `translate.py` 的对应 |
|---|---|
| `describe()` → 文档里的 `speech` 段 | `translate.describe()` 给的 `translation` 段 |
| `validate(body)`，音色成员校验在这里 | `translate.ensure_english()` 的位置 |
| `async def speak(...)`，aiohttp 转发到 `settings.speech()["url"]` | `_ask()` |
| 引擎错误 → 三条 CHP 错误码，地址与令牌**只进日志** | `describe()` 的 *never leaks the internal address* |
| 出厂音色表（手写 9 个） | `settings.RECOMMENDED_CHECKPOINT` 的同性质 |

`capabilities.py` 加**三处**可选参数（**不是一个** —— `rules()` 与 `abilities()` 各自遍历 `CATEGORY_TABLE`，
只给 `document()` 加参数**过滤不到它们**，而「播报层过滤」正是 §3.3 的第一层）：

```python
def rules(allowed: set[str] | None = None) -> list[dict]: …          # allowed=None ⇒ 全部（内部调用/测试）
def abilities(files_of, allowed: set[str] | None = None) -> list: …  # 同上；按 category 过滤后再分组
def document(*, files_of, allowed=None, authorized, auth_required,
             translation, speech=None, auth_hint="", errors=None): …
```

**现有逻辑一行不改**：`allowed=None` 时 `rules()` / `abilities()` 的行为与今天逐字节相同
（`document()` 内部传给它们的也是 `None`）。过滤是**同一个遍历上加一个成员判断**，不是第二套表。

`ENDPOINTS` 加 `"speech": f"{API_ROOT}/speech"`。`server.py` 加一条
`routes.post(f"{API_ROOT}/speech")(speech_endpoint)`，流式回写用
`web.StreamResponse`（`Content-Type` 与 `X-Sample-Rate` 在 `prepare()` 之前设好）。

**鉴权不是「复用 `_authorized()`」那么轻** —— 执行层（§3.3 第二层）要知道**命中的是哪把 key**才能查它的授权集，
而 `_authorized()` 只回一个 `bool`（`server.py:245`）。⇒ 加一个**取钥匙**的函数，`_authorized` 变成它的薄包装：

```python
def _key_of(request, body=None) -> dict | None:
    """命中的那把 key 的记录（含 categories）；没配任何 key 时返回一个全权的哨兵。"""
    #  ① 没配任何 key ⇒ 返回 {"categories": ["*"], "source": "open"}   （§3.2.1 的公开态）
    #  ② 先比对默认 key（nodes.py 的密码 / HAMDRAW_PASSWORD）⇒ {"categories": ["*"], "source": "default"}
    #  ③ 再查 chp_keys.json ⇒ 命中返回那条记录；都没命中 ⇒ None

def _authorized(request, body=None) -> bool:
    return _key_of(request, body) is not None
```

三个调用点（`info` / `create_job` / 新的 `speech_endpoint`）**都改用它**取 `_key_of(...)`，
`info` 把 `allowed=set(record["categories"])` 传进 `document()`（`"*"` ⇒ `None`），
后两个做执行层校验。**`_token_of()` 的取值规则一个字不改**（Header → Bearer/Basic/X-HamDraw-Password → body 的 `chp_params.password`），
所以老卡片的四种写法继续有效。

### 4.3 S5 · 服务模式：一个包、两个入口

```
入口 A（今天就有，一个字不改）
  ComfyUI 加载 __init__.py ──► 注册节点 + register_routes() ──► 挂在 ComfyUI 自己的端口上

入口 B（新增）
  python -m hamdraw_chp serve ──► 自带 aiohttp app ──► 自己绑端口（默认 127.0.0.1:8889）
```

**模式由「谁启动它」决定，不做自动探测魔法。** 而且 `register_routes()` **今天就已经在没有
`PromptServer` 时返回 `False`**（`server.py:1155`，`__init__.py:33` 接住并打一行提示）—— 守卫是现成的。

```
hamdraw_chp/__main__.py         只有几行：交给 cli
hamdraw_chp/cli.py              argparse + 起 aiohttp app（这里是唯一 import aiohttp 入口的地方）
hamdraw_chp/backends/comfy_http.py   服务模式的上游后端
```

**`comfy_http.py` 真正要新写的只有「作业的身份映射」**：

| | 插件模式 | 服务模式 |
|---|---|---|
| `job_id` | 就是 ComfyUI 的 `prompt_id` | 自己生成，需维护 `haminn job_id → prompt_id` |
| 队列状态 | `PromptServer` 白给 | `GET {upstream}/queue` 重建 |
| 历史 / 输出 | 同进程直接读 | `GET {upstream}/history/{prompt_id}` |
| 取消 | 同进程 | `POST {upstream}/interrupt` |
| **模型清单（`abilities[].files`）** | `folder_paths` 读磁盘 | **`GET {upstream}/object_info` 的枚举**（`CheckpointLoaderSimple` 等节点的输入枚举就是模型清单） |

最后一行是**关键选择**：服务模式的「有哪些模型」必须来自**上游自己的枚举**，
而不是「这台机器上另有一份目录」。这样文档说的就是上游真有的东西。

**上游地址只在部署侧配置**（§6），**永不许来自请求体** —— 否则一个 key 就变成「拿你的钥匙打任意地址」。
这条与 `translate.url` 同规。

**服务模式的六个实现决定**（S5 落地时定，写在这里免得以后被"顺手简化"）：

1. **要问上游的三件事是 `async`**（`queue` / `history` / `output_path`），在进程内并不需要
   `await`。两种模式的**形状必须一样**，否则协议层就得知道自己挂在哪个后端上 ——
   而这个接缝存在的全部理由就是让它不必知道。
2. **两种模式共用的那半只有一份代码**（`backends/records.py`：状态机、队列位置、
   历史记录里的产物、一个类别的模型文件解析）。分两份的话，判据①的"逐字节相同"迟早只是巧合。
3. **模型清单是快照，不是每次现问**（`comfy_http.refresh()` + `available`/`absent` 读快照）。
   词表里那两个是同步函数，而且这样 `/chp/info` **永远不等上游** —— 上游慢或不在时，
   文档照样是即时答复。服务模式多一个错误码 `no_upstream`（409）：上游不在是**这个模式
   独有**的一种故障，把它说成 `no_model` 会把人指到错的配置文件上。
4. **参考图先落在本机暂存目录，提交时上传**（`POST /upload/image`），并按**上游答的那个
   名字**改写图里那一格；产物反向取回（`GET /view`）再交给 `FileResponse`。服务模式
   与上游**不假设共享文件系统** —— 假设共享是那种"本机测得通、换台机器就废"的设计。
   （作业号也因此由本服务自己发，见上表；映射在内存里，所以进程重启前提交的作业
   只能回 `not_found`，与"从来不存在的号"同一个答案。）
5. **后端由"启动它的那一个"点名，`import` 时谁都不绑**（`__init__.py` 点 inproc、
   `cli.main()` 点 http）。这不只是风格：进程内后端**就是** import ComfyUI 的那一半，
   绑定写在 import 时，`python -m hamdraw_chp serve` 就在"没有 ComfyUI 的机器"上连
   import 都过不去 —— 而那种机器正是这个入口唯一的理由。实测踩过：`server.py` 里一句
   `backend = backends.get()` 就够让 `serve` 起不来，而离线自检（替身齐全）全绿。
6. **路由表两种形状，在一处合一**（`server._bind`）：ComfyUI 交给插件的是
   `RouteTableDef`（`table.get(path)` **返回一个装饰器**），服务模式挂的是活的
   `web.Application().router`（`add_get(path, handler)`，返回 `None`）。这是本轮**唯一**
   被替身藏住的真缺陷：离线自检的假路由表按前一种形状造的，于是"服务模式第一行路由就
   `TypeError`"在自检里是绿的。判据因此改成两种形状**各留一个替身**、各自都要挂上。


**判据（三条，一条比一条硬）**：

1. 服务模式下，同一个 key 的 `/chp/info` 与插件模式**逐字节相同**（`endpoints` 是**相对路径**，
   所以连地址都不用例外）—— 「两种模式是同一个协议」的唯一证据；
2. **上游不在时 `/chp/info` 仍返回 200**，`abilities` 为空 / `ready: false`，`errors` 里说明原因
   —— 「后端缺席 ≠ 服务缺席」；
3. 端口与绑定从配置读（默认 `127.0.0.1:8889`），改配置即生效，**客户端一行不改**。

> 端口为什么可以不锁定：`endpoints` 里存的是**相对路径**（`capabilities.py:60-66`，值形如 `/chp/info`），
> 客户端用「自己配的 base + 文档里的路径」拼。**换端口不改客户端、不改文档。**

### 4.4 S4 · 管理面：三个配置文件，按「谁能写」分开

**这不是风格问题，是结构性保证。** 「控制台不能改凭据」如果靠纪律，一个 bug 就破了；
靠文件分离，控制台**根本没有那把钥匙**。

| 文件 | 谁写 | 内容 |
|---|---|---|
| `hamdraw_settings.json`（既有） | 插件配置节点 + 运维手工 | 模型角色、采样、加速档案、`translate`、**`speech`**、**`serve`** |
| **`chp_admin.json`**（新增） | **只能本机（SSH / 文件编辑器）** | 控制台用户名与密码 |
| **`chp_keys.json`**（新增） | **控制台读写** | key 表：每把 key 的字符串、标签、授权 categories、创建时间 |

- 三者都在 `hamdraw_chp/` 目录里，与 `settings.path()` 同处（`settings.py:111-115`：默认就是**包目录内**的
  `hamdraw_settings.json`，可用 `HAMDRAW_SETTINGS_FILE` 类环境变量改路径）。
  **三个都要进 `.gitignore`** —— ⚠ 注意**是哪一份**：`comfyui-plugin/.gitignore` **不存在**；
  现在真正生效的是 **hamdraw 仓根**的 `hamdraw/.gitignore`（内容正是 `__pycache__/` / `*.pyc` / `.DS_Store`）。
  搬迁后**CHP 仓自己的 `.gitignore` 要重新写一份**（仓根变了，那份不再覆盖它）。判据（S4 ⑤）照旧是
  `git check-ignore -v <三个文件名>` 三条都命中。
- `chp_admin.json` **不存在时用代码里的默认值**：`hamster` / `imahamster`；
  **改了它要重启才生效**（业主口径）。
- **控制台页面上不出现任何修改凭据的表单/接口** —— 这是判据之一（§8 S4）。

**默认 key 与向后兼容**：`nodes.py` 里那个「密码」字段与 `HAMDRAW_PASSWORD` 环境变量
**继续有效**，语义升级为「**默认 key**」，权限 `["*"]`（全能力）。
⇒ 老用户的工作流与 happ 卡片**零改动**继续能用。它在控制台里**只读显示**（来源不是 key 表）。

**key 表的数据形状**：

```json
{ "schema": "chp-keys/v1",
  "keys": [ { "id": "k_…", "label": "A1X 上的 Chataxi", "key": "…",
              "categories": ["fast", "inpaint", "speak"], "created": "2026-10-12T23:00:00+08:00" } ] }
```

`categories: ["*"]` 表示全部。**key 明文存储** —— 它与 `settings` 里的引擎令牌同级信任、
只在本机可读，且管理员需要能把它复制给别人。文件权限按 0600 要求。

#### 4.4.1 ⚠ 安全：**打包器必须排除这三个文件**（本轮唯一新增的安全要求）

**这是一个真实的洞，不是洁癖。** `tools/package-plugin.py` 对 `hamdraw_chp/` **整树 `rglob`**，
排除项**只有** `__pycache__` 与 `.pyc`（`:60-62`），**它不看 `.gitignore`**：

```python
files.extend(path for path in target.rglob("*")
             if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
```

而 `settings.path()` 默认就落在**包目录内**。⇒ 只要构建机上那份 `hamdraw_chp/hamdraw_settings.json`
存在（装了插件又排过一次队列的机器就是这种情况），**它连同里面的 `translate.token` / `speech.token`
会被打进发布 zip**；本轮再往同一目录放 `chp_keys.json`（**里面的 key 直接就是访问凭据**），洞就更大。

**处置（S-1 随搬迁一起做，一次改到位）**：

1. `package-plugin.py` 的过滤条件加一个**显式名单**（写死文件名，不用 glob —— 名单越笨越好审）：
   `{"hamdraw_settings.json", "chp_admin.json", "chp_keys.json"}`，命中即跳过；
2. **构建时若发现它们在树里，打一行警告**（不是静默跳过）—— 「这台机器上有过期的密钥文件」是运维要知道的事；
3. **判据（机械可查，已实测两态）**：在 `hamdraw_chp/` 里放三个假密钥文件，跑一次 `package-plugin.py`，
   然后 `python3 -c "import zipfile,glob;print([n for n in zipfile.ZipFile(<zip>).namelist() if n.endswith('.json')])"`：

   | 状态 | 实测输出 |
   |---|---|
   | **修之前**（现有脚本） | `['hamdraw_chp/chp_admin.json', 'hamdraw_chp/chp_keys.json', 'hamdraw_chp/hamdraw_settings.json']` ← **真的会泄漏** |
   | **修之后** | `[]`，且 zip 的 sha256 回到 pristine 值（`172ab450…`）⇒ 排除项**不改变其它任何字节** |

   ⇒ 这条已按「先看变异」的规矩**证明会红、且修好即绿**，不是设想。

> ⚠ 顺带记一条**事实**而不是风险：目前仓里**没有**这三个文件（`ls hamdraw_chp/*.json` ⇒ 空），
> 已发布的 v3.1.1 zip 内容清单也确认**只有 12 个源码条目**（另加 2 个目录条目）。所以**今天没有泄漏**；
> 这一条是为「本轮往那个目录里新放两个密钥文件」这个**将要发生**的改动补上的闸门。

### 4.5 S4 · 控制台（CHP 的一部分，与 happ 无关）

| 项 | 定稿 |
|---|---|
| 位置 | `/chp/admin/*`，**同一个服务、同一个端口** |
| **文档可见性** | **不写进 `endpoints`** —— happ 只从 `endpoints` 读地址，所以它**永远不知道控制台存在**，契约保持干净 |
| 鉴权 | 独立的一条线：**Basic（用户名 + 密码）**，与数据面的 `Bearer <key>` **完全分开**（⚠ 数据面的 `_token_of()` **也认 Basic** —— `server.py:221-233` 会把 `Basic` 解出来取 `:` 之后那段当 key。⇒ **`/chp/admin/*` 必须是独立路由族，不经过数据面的 `_token_of()`**；并且 **key 表里不许登记与 `chp_admin.json` 同值的 key**，否则控制台凭据会顺带变成数据面钥匙） |
| 绑定 | 跟主服务同绑定；**服务模式的默认绑定是 `127.0.0.1`**，要局域网自己改成 `0.0.0.0` |
| 能力边界 | **只能管 key 与 key 的授权集**。**不能新增能力**、不能改模型配置、不能改凭据 |
| 页面形态 | 一份纯静态 HTML + 一组 admin API，**不引构建链**（CHP 今天没有静态资源目录，`nodes.py` 里没有 `WEB_DIRECTORY`） |

**接口最小集**：

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/chp/admin/` | 静态页（key 列表 + 编辑表单） |
| `GET` | `/chp/admin/capabilities` | **只读**：已设定的模型/接口清单（来自代码注册的 category 表），带 `ready`/`missing` |
| `GET` / `POST` / `DELETE` | `/chp/admin/keys` / `/chp/admin/keys/{id}` | key 的增删改（写 `chp_keys.json`） |

**「可用模型只能从已设定的列表里选」怎么落实**：`/chp/admin/capabilities` 的清单
**就是** `capabilities.CATEGORY_TABLE`（代码注册的），页面上的勾选项**只能**出自它；
`POST /chp/admin/keys` 收到清单外的 category **一律拒收**（与数据面的 `unsupported_category` 同一条纪律）。
**控制台里不存在「添加一个模型」这个动作。**

**能力的两层分界（必写进规范，否则一定被踩）**：

| 层 | 谁定 | 生效方式 |
|---|---|---|
| **能力的存在与形状**（有哪些对外接口、走什么图、什么 signature） | **开发者改代码** | 改完**重启** |
| **能力的开关与授权**（哪把 key 能用哪些接口） | **管理员点控制台** | 热生效（写 `chp_keys.json`） |

「图构造是逻辑，不该数据化」—— 让控制台能新增能力，会退化成在图数据库里手工拼 JSON，之后没人能查。

### 4.6 打包：**逻辑零改动，但路径常量要改一行**（S-1 之后它住在新仓）

`tools/package-plugin.py` 的顶层条目是**整个目录** `("hamdraw_chp", "README.md")`
⇒ `__main__.py` / `cli.py` / `backends/` / 控制台静态页**放进 `hamdraw_chp/` 里就自动进包**。
版本号仍只从 `hamdraw_chp/version.py` 读，zip 名与插件 HTTP 上报的数字永不漂移。

**S-1 把这个脚本连同包一起搬到 CHP 仓**（它跟产物走）——
⚠ **但「一行不改」是错的**，上一版这么写是没读脚本。搬完**必须改两处**，都只有一两行：

| 要改的 | 现在 | 改成 | 为什么 |
|---|---|---|---|
| `SOURCE`（`tools/package-plugin.py:20`） | `ROOT / "comfyui-plugin"` | **`ROOT`** | 新仓里**没有 `comfyui-plugin/` 这一层**。不改 ⇒ 脚本立刻 `missing plugin path: hamdraw_chp` 退出 |
| 条目过滤（`:60-62`） | 只排除 `__pycache__` / `.pyc` | 再加那**三个文件名**（§4.4.1） | 密钥文件不许进 zip |

`VERSION_FILE` / `ARCHIVE` / `plugin_directories()` 全部由 `SOURCE` 派生 ⇒ **自动跟着对**，不用动。
`ENTRIES = ("hamdraw_chp", "README.md")` 也**不用动**（搬迁后 `README.md` 就在 `ROOT` 下，正是它的新家）。

**这一处改动有判据，而且是全计划里最硬的一条**：改完之后在新仓跑
`python3 tools/package-plugin.py`，产出的 zip 其 `sha256` 必须**等于**搬迁前 hamdraw 那份
`release/hamdraw-comfyui-plugin-v3.1.1.zip` 的 `sha256`（实测 `172ab450c4f883d3f746ed87ea5783bf372387020f6bfac339cff0933a6bc5fb`）。
**字节相同 = `SOURCE` 改对了 + 搬的是同一批文件**，一条命令同时证明两件事（详见 §8 S-1）。

**hamdraw 侧随后一件插件相关的东西都不留**（业主 2026-10-13 定，详述 ⇒ §5.5 / §14.3）：
不内嵌 zip、不 vendored、不引用产物名 —— 三个 happ 只在界面上写一句「到官网下载」加一个稳定 URL。

⇒ **给 ComfyUI 用户：还是那个 ZIP、还是 `custom_nodes/hamdraw_chp/`、安装步骤一个字不变**，
只是**从官网取而不是从 happ 取**。他不需要知道有第二种模式。
**不新增加工产物**（独立运行用的是同一个包）。正式发布（GitHub release + 官网下载位）是**独立动作**，本计划不含。

---

## 5 客户端改动

**读 CHP 的 happ 有三个：HamDraw、Chataxi、PoseGi**（计数口径与逐仓清单 ⇒ §2.1，**以现查为准**）。
**ImaHamster 不读 CHP**（实测全仓零命中），本轮不升级。

本轮客户端侧有**两处非加法改动**，都只有在「文档按 key 分内容」与「info 改为需要 key」之后才存在。
**两处都会静默劣化、而不是干脆报错**，所以必须专门盯着。

### 5.1 ⚠ 缓存单例 —— hamdraw 与 PoseGi 各有一份（必须改）

```
hamdraw/app/services/providers.js:196    var chpInfo = null;
hamdraw/app/services/providers.js:224    function chpRemember(document) { … chpInfo = document; … }
PoseGi/app/services/providers.js:406     var chpDocument = null;
PoseGi/app/services/providers.js:407     function chpRemember(document) { … chpDocument = document; … }
```

**Chataxi 没有这个问题** —— 它的 `chpInfo()` 是函数、每次真发请求，不缓存。
**两个仓各改一处，不要顺手给 Chataxi 加缓存。**

今天文档内容只取决于插件配置，一份全局缓存是对的。**按 key 分内容之后**，
同一份缓存会让**A 机器的能力出现在 B 机器的界面上** —— 最坏是**授权泄漏**
（用受限 key 配的服务，界面上显示出另一把全权 key 的能力）。

⇒ **两个仓都改成按服务（至少按 `endpoint + key`）分桶。**

**判据**：同一进程内先发现 key A 的服务、再发现 key B 的服务，B 的界面**不得**出现 A 的能力。

### 5.2 ⚠ 401 会被误报成「这个地址不是 CHP 服务」（三个仓都要改）

**这一条我先前判断错了，这里更正。** 本来以为三个仓都已有 `401|unauthorized` 的文案映射
（`providers.js:371`、`PoseGi/providers.js:609`）就够了 —— **不够**，因为那些映射在**下游**，
而 info 的抓取循环**把错误咽掉了**：

```
hamdraw/app/services/providers.js:537-560   chpInfoRequest()
  546  ensureOk(response, requestHeaders);                          ← 401 在这里抛
  547  catch (error) { if (!firstError) firstError = error;
  552    if (Number(error && error.status) > 0) answered = true;    ← 状态码 > 0 ⇒ 认定「有人应答过」
  553    continue; }
  559  if (answered) throw new Error("这个地址不是 CHP 服务，请确认插件已安装且 ComfyUI 已重启");

chataxi/app/services/model-services.js:648-666   chpInfo()
  658  if (response.status < 200 || response.status >= 300) continue; ← 401 落到这里，继续试下一个候选
  665  if (answered) throw new Error("这个地址不是 CHP 服务：请在 ComfyUI 中确认已安装 CHP 插件并重启");
```

⇒ **照今天这样改完直接上，用户把 key 写错时会看到「这个地址不是 CHP 服务，请确认插件已安装」** ——
把他指向完全错误的排查方向。401 必须被当成**一个确定的答案**（地址对、是 CHP、钥匙不对），**立刻停、不 fall through**。

**协议侧给一个确定的判据（加法，成本为零）**：CHP 的 401 响应体固定为
`{"error": "unauthorized", "spec": "chp/2"}` —— 在既有 `_fail` 结构上多一个 `spec`。
这样客户端**不必靠猜 URL** 就能确认「这是 CHP，只是钥匙不对」，并与「200 但没 `spec`（不是 CHP）」区分开。

**三个仓的处理**：

| 客户端 | 改动 |
|---|---|
| hamdraw `providers.js` | info 抓取循环里 `error.status === 401`（或响应体带 `spec`）⇒ **立即 throw「访问密码不正确」**，不 `continue`、不置 `answered = true` |
| chataxi `model-services.js` | `response.status === 401` ⇒ **立即 throw「访问密码不正确」**（今天会 `continue`） |
| PoseGi `providers.js` | 同 hamdraw（`chpInfoRequest` 是同一形状，定义在 **`:508`**，catch 在 `:520-526`，throw 在 `:527`） |

- `auth.authorized` 那条分支**保留不删**（老插件仍走它），只是不再是唯一路径。
- **PoseGi `app/services/providers.js:533` 那句注释必须改** —— 它写着「信息接口是**公开**的（密码错了也照答，
  由 `auth.authorized` …）」。改成 401 后这句话就是错的，留着会让下一个人照着它写代码。
- **403 新文案**：`forbidden_capability` ⇒「这把 key 没有这个能力」（中英文都要补），三个仓各加一条用例。
  ⚠ **别和 PoseGi 已有的「能力已被拒绝」撞义**：`PoseGi/app/services/providers.js:666` 已把
  `能力已被拒绝|拒绝了此能力|CAPABILITY_DENIED` 归成**宿主的能力授权**这一类 —— 与 CHP 的 key 授权是两件事，
  **不要复用那一串**。
- ⚠ **「这个地址不是 CHP 服务」被六处钉着，改文案要一起改**（上一版只提了 `PoseGi/providers.js:527` 一处，
  漏了五处）。**三处实现**：`hamdraw/app/services/providers.js:559`、
  `chataxi/app/services/model-services.js:665`（+ 它的英文在 `chataxi/app/data/i18n-en.js:1071`）、
  `PoseGi/app/services/providers.js:527`；**三处测试/变异**：
  `chataxi/tests/runtime.test.mjs:1676`（`assert.rejects(…, /这个地址不是 CHP 服务/)`）、
  `chataxi/tests/.mutate-chp.mjs:221-222`（**变异脚本按这个字面串改代码** —— 改了文案它就变异空转）、
  `PoseGi/tests/discovery.test.mjs:309`（`message.indexOf("不是 CHP 服务") >= 0`）。
  **§5.5 代价第 3 条要往这句里加 URL，就必须动这六处。**
- ⚠ **hamdraw 的变异脚本没有覆盖这条路径**：`hamdraw/tests/.mutate-chp.mjs` 里
  `grep -nE "不是 CHP|unauthorized|401"` ⇒ **零命中**。所以 S6 那条「401 ⇒ 访问密码不正确」的变异
  **在 hamdraw 侧要新写一条**（照 `chataxi/tests/.mutate-chp.mjs:221` 那两行的形状：把 `if (status === 401) throw` 改成 `if (false)`），
  否则「新断言必须被至少一次变异证伪」这条规矩在 hamdraw 上是空的。

### 5.2.1 `PoseGi/tests/fixtures/chp-info-3.1.0.json` 怎么处理

PoseGi 把一份**完整的信息文档快照**当测试夹具，夹具名里带**插件版本号**（`3.1.0`），
内容含 `"spec": "chp/2"`、`"version": "3.1.0"` 与旧 label。

⇒ **不要改那份 3.1.0 的** —— 它按名字就是「3.1.0 那一刻的文档」，改了就毁了它的意义。
**新增 `chp-info-3.2.0.json`**（含 `speech` 段、八键 `endpoints`、新 label，以及**一把受限 key 过滤后的形态**），
旧用例继续指旧夹具 —— 这正是「夹具名带版本号」这个惯例的用途。

### 5.3 Chataxi 侧（吸收 `chp-speech-plan.md` §4）

| 位置 | 改动 |
|---|---|
| `app/services/catalog.js` | 加一个 `chp-speech` 家族（`discovery: "chp"`, `streaming: true`） |
| `app/services/model-services.js` | `discover()` 加一条分支（`kind === "tts"` 且 `discovery === "chp"` ⇒ `discoverChpSpeech`）；`resolveTts` 三行（`chpAbsolute(service, service.endpoints.speech)`） |
| `app/services/tts.js` | `requestBody()` 加一条分支 `{ text, voice, language, response_format, stream }`；`pcmStreamProfile()` 加一条 `{ kind: "raw", format: "pcm", sampleRate: 卡片里的 audio.sample_rate }`。**流式播放链路一行都不用重写** |
| `app/features/model-single-editor.js` | `defaultEndpoint(kind)` 让 `chp-speech` 家族也预填同一个 CHP 地址 |
| `app/data/i18n-en.js` | 新增文案全部补英文 |

**槽的匹配用 `signature`，不用新字段**（业主 2026-10-12 定）：happ 的槽声明「我出 `img`、我能给 `txt`/`ref`」，
按「输入模态 ⊆ 可提供的」匹配 ⇒ 自然同时收 `txt-2-img` 与 `txt-ref-2-img`（HamDraw 生图槽今天正需要同时看到两者）。

> **`signature` 是「形状」不是「用途」**：将来若两个能力同为 `txt-2-img` 而用途不同（快速草图 / 高质量渲染），
> signature 分不出来 —— 那时用现成的 `category`，**不要再加第三个轴**。

### 5.4 一处已知的将就（记下来，不返工）

happ 的数据区把「绘图」与「朗读」分成两个槽（`image-profiles` / `tts-profiles`），
所以用户**会在两个地方各配一次同一台 CHP**。本轮**接受**（不改数据模型，风险大收益小）。
真要顺手就在语音卡加一个「用绘图卡那台机器」的按钮 —— 那是**另一件事**。

### 5.5 三个 happ 都不再附带插件：改成本机提示 + 官网链接（业主 2026-10-13 定）

**现状**：只有 **HamDraw** 内嵌了插件包，链子是一条四段的：
`release/…zip` → `tools/embed-plugin.py` → `app/assets/comfyui-plugin.js`（87 KB base64）
→ `index.html:143` 的脚本表 → 设置页那颗「下载 ComfyUI 插件」按钮（`settings.js:57-83` 写入、`:158` 渲染）。
**Chataxi 与 PoseGi 本来就没有插件包**，只有说明文字。

**改成**：三个 happ 都**不带任何插件字节**；在用户**选到 CHP 那个接口模式时**，在该表单**底部**多一句提示。

**形态就是「一行纯文字 + 一个普通链接」**（业主 2026-10-13 00:47 定，比上一版更简单）：

> **CHP 是 Haminn 综合入口程序：装在运行 ComfyUI 那台电脑上，把本机模型统一成一个接口。
> 请到 Haminn 官网下载：<https://haminn.airen.life/chp.html>**

**简化在哪（三条都不要做）**：

- **不要按钮**：不是「打开官网」按钮，就是那句话里的链接。
- **不要应用内流程**：不拦截、不特判、不写 JS。那是个普通 `<a href>`，用户点它时由宿主把**同帧外跳**
  交给**安卓系统默认浏览器**（`MainActivity.kt:1306`）—— **happ 里一行代码都不用写**。
- **不要应用内下载**：不改 `.download`、不落文件、不调宿主文件通道。插件是装到**电脑**上的，
  在手机上落一个 zip 正是本轮要消灭的那条弯路。

⚠ **上面引文里「装在运行 ComfyUI 那台电脑上」那半句，是唯一还没定的一处**（§14.9 第 3 条）：
你上一条的精简版没写它。**默认按引文留着**（一句话的成本，挡掉「装在手机上」这个最常见的误装）；
要删说一声即可 —— 官网页首屏第一句也写着它，删了也不丢信息，差别只是「在哪一步看到」。

英文同一句（草稿，与中文一起定死）：*CHP is the Haminn Consolidated Portal: it sits on the computer that runs
ComfyUI and puts that machine's local models behind one interface. Get it from the Haminn website:
<https://haminn.airen.life/chp.html>.*

| 仓 | 删掉 | 提示的落点 |
|---|---|---|
| **hamdraw** | `app/assets/comfyui-plugin.js`、`index.html` 那一项、`settings.js` 的 `downloadPlugin()`（`:57-83`）与那颗按钮（`:158` + `:231` 的 onclick 绑定）、`tools/embed-plugin.py`、`tools/verify.mjs` 的四条内嵌断言（**`:221` / `:222` / `:223-225`**） | `app/components/settings.js` 的 `renderModels()`，`chp` 分支 —— 就是今天那颗按钮的位置（`:158`） |
| **chataxi** | （无） | `app/features/model-single-editor.js` 的 `noteHtml`（`:68`，渲染在 `:81`，**正是表单底部**）；只有家族是 CHP 时才出 |
| **PoseGi** | （无） | `app/components/settings.js` 的 `renderModelForm()`（`pickerRow("protocol", …)` 在 `:211`）表单底部，只有 `draft.protocol` 是 CHP 时出。**使用说明里那句「接上自己的模型」（`:871`）也补同一个 URL** |

**四条必须遵守**：

1. **链接必须走同帧导航**：写成 `<a href="https://haminn.airen.life/chp.html">`，**绝不加 `target="_blank"`**。
   宿主没有 window 处理器 —— hamdraw 自己在 `settings.js:381-385` 写明了这件事；
   `_blank` 会**静默什么也不做**，是最容易犯、也最难发现的一种坏。
2. **URL 里不许有版本号。** 它被编译进 happ 源码：带版本号就是「插件一升版，三个 happ 的提示同时过时」——
   正是本轮要消灭的那类漂移，而且改它要重发三个 happ。⇒ **只有稳定路径进源码。**
3. **URL 不能来自 CHP 文档。** 这里有个**循环依赖**：`/chp/info` 得**先有装好的插件**才读得到，
   而这句话要说给**还没有插件**的人听。⇒ **只能由 happ 自带这个常量**；
   CHP 的 `endpoints` / `abilities` **一律不播报下载地址**（写进 §7 的「不做」）。
4. **一句中文 ⇔ 一句英文。** hamdraw 与 PoseGi 用 `t("…","…")`；**Chataxi 是硬编码中文 + 查表**
   ⇒ 新句子必须同时进 `app/data/i18n-en.js`（项目硬规矩）。

**那句话要说清两件事**：CHP 是什么（本机模型的统一入口）、去哪儿取（官网那一页）。
「**装在那台跑 ComfyUI 的电脑上，不是手机**」这半句，**官网首屏第一句就写着它**（页面已按此写），
所以 happ 那句留不留都行 —— 业主的精简版没留，也**不丢**这个信息，只是晚一步看到。
⚠ 若不留，**不要**改成「安装 CHP」这种含糊说法：用户在手机上读它，会以为装到手机上。

**收益（三条，都有实证）**：

- **两条版本线解耦**：今天插件升级要连带重发 happ 才能送到用户手里；改完只需官网换一个 zip。
- **「happ 里的插件悄悄过期」这一类被结构性消灭。** 实证：仓里那份内嵌资产自称
  `hamdraw-comfyui-plugin-v3.0.0.zip`（生成于 09-29），而 `release/` 里最新的插件 zip 已经是
  **`v3.1.1`**（10-01）—— 也就是**现在发出去的 hamdraw 带的是 v3.0.0**。
  这不是谁手滑，是「字节内嵌」这种做法的固有代价：**它没有天然的同步点**。改成官网取，这类漂移不存在。
- **happ 包小 87 KB**，且 hamdraw 与插件之间**再没有任何构建顺序**要守（§14.3 铁律①整条作废）。

**代价（必须承认）**：

- **首次安装多一步**：要在浏览器里打开页面、解压进 `custom_nodes`、重启 ComfyUI。
  但今天那条路是「把文件写到手机上，再想办法送到跑 ComfyUI 的机器」——
  **对「ComfyUI 在另一台机器上」这个主场景，改完其实是变简单了。**
- **离线首启**：手机没网也能装 happ，但提示打不开。**接受**（CHP 本来就要求本机有一台跑着 ComfyUI 的机器）。
- **可发现性下降**：提示只在「选到 CHP」时出现。**补一条**：把同一个 URL 也放进 CHP 相关的错误文案
  —— 尤其 §5.2 那句「这个地址不是 CHP 服务」，那正是用户最需要它的时刻。
  ⚠ 该句被**六处**钉着（见 §5.2 末条 —— 三处实现 + `chataxi/tests/runtime.test.mjs:1676` +
  `chataxi/tests/.mutate-chp.mjs:221-222` + `PoseGi/tests/discovery.test.mjs:309`），**改文案必须同步改这几处**，
  否则改的是一条「测试还在绿、变异已经空转」的文案。

---

## 6 配置模型

### 6.1 `hamdraw_settings.json` 新增项

```json
{
  "schema": "hamdraw-comfy-settings/v1",
  "checkpoints": { "…既有…": "" },
  "sampling":    { "…既有…": {} },
  "accelerators":{ "…既有…": {} },
  "translate":   { "…既有…": {} },

  "speech": {
    "url": "http://127.0.0.1:8021",
    "token": "",
    "engine": "qwen3-tts-12hz-0.6b-customvoice-q8_0.gguf",
    "voices": ["vivian","serena","uncle_fu","dylan","eric","aiden","ono_anna","sohee","ryan"],
    "sample_rate": 24000,
    "timeout": 60.0
  },

  "serve": { "host": "127.0.0.1", "port": 8889, "upstream": "http://127.0.0.1:8188" }
}
```

| 档 | 键 | 不给会怎样 |
|---|---|---|
| **必要（语音）** | `speech.url` | 播报 `abilities[].ready: false`，请求回 `409 no_engine` |
| 必要（引擎要） | `speech.token` | 引擎回 401 ⇒ 同样收敛成 `no_engine` |
| 有可用默认 | `speech.voices` / `sample_rate` / `timeout` | 用出厂值照跑；`voices` 是**这台机器上引擎支持的名字**，换引擎才要改 |
| 只用于播报 | `speech.engine` | 只进 `files.engine`，不影响跑 |
| **仅服务模式** | `serve.host` / `serve.port` / **`serve.upstream`** | 用默认 `127.0.0.1:8889`；**插件模式忽略这一档**（绑定由 ComfyUI 决定） |

环境变量照 `HAMDRAW_*` 的既有拼法加：`HAMDRAW_SPEECH_URL`、`HAMDRAW_SPEECH_TOKEN`。
（既有先例：`settings.py:229 translate()` 的形状是 `url = env(HAMDRAW_TRANSLATE_URL) or stored["url"]`
—— **env 覆盖 + settings 存默认值**。语音照抄。**上游地址与引擎令牌只从部署侧来，永不走 HTTP。**）

### 6.2 三把钥匙，分属三条线（不许混）

| 钥匙 | 谁对谁 | 存哪 |
|---|---|---|
| **数据面 key** | happ ↔ CHP | `chp_keys.json`（+ 默认 key 来自配置节点 / `HAMDRAW_PASSWORD`） |
| **控制台凭据** | 管理员 ↔ 控制台 | `chp_admin.json`（**只能本机改**） |
| **引擎令牌** | CHP ↔ TTS 引擎 | `hamdraw_settings.json` 的 `speech.token`（**永不进文档、永不进响应**） |

**凭据的字母表 = 英文大小写字母、数字、`-`、`_`**（业主 2026-10-13 定，中文不必支持）。
规矩卡在**收进来那一刻**（`keys.ALPHABET` + 控制台建 key + 配置节点那格密码），
而不是在比对时替非 ASCII 绕路 —— `hmac.compare_digest` 遇到非 ASCII 的 `str` 会抛，
所以那种"支持"以前是拿一条 500 换来的。**送上来的**那一串不受这条规矩管：不匹配就是
一句 `401`（比对照旧按字节走）。`chp_admin.json` 是运维自己写的文件，**读它的时候不拦**
—— 拦了就是把自己锁在门外。

**管理面与数据面不许共用同一把钥匙** —— 数据面 key 泄漏 = 白用模型；若还能进控制台，就是**能改授权、能给自己造 key = 接管**。

---

## 7 明确不做

- **不做 ASR / 视频 / 图片以外的任何类型**。引擎的 `/v1/audio/transcriptions` 今天返回空
  （装的是 TTS 不是 ASR）—— 这一条不是纪律，是事实。
- **CHP 不做 GPU 调度**（§1.3）。
- **不接管 A1X `control-plane`（8188）的任何接口**（§1.2）。
- **不新增第三条 speech 规则**（不做声音到声音、不做音色克隆）。引擎有 `/v1/audio/speech-to-speech`，本轮不碰。
- **不做 speech 的作业模型**（§3.5）。
- **不做多引擎并行播报**：`abilities` 的形状允许多条，本轮只配一台。
- **不把引擎地址或令牌播报进文档**，也不放进任何响应。
- **控制台不能新增能力、不能改凭据、不能改模型配置**（§4.5）。
- **不加全局「对外可用」开关**（§3.3 —— 没有 key 就等于没有对外）。
- **不升 `spec`**、**不动 `/chp` 路径 / `PLUGIN_ID` / `HAMDRAW_*` / 设置文件名 / ComfyUI 节点输入名**（§2.2）。
- **不新建第二个发布产物**（§4.6）。
- **不做任何形式的 happ 内置插件分发**：不内嵌字节、不 vendored zip、也不在 `/chp/info` 里播报下载地址
  （循环依赖 —— 读得到文档的人已经装好了插件，§5.5 第 3 条）。三个 happ 只说一句话加一个 URL。
- **不打发布包**；**已存在**的官网下载位与直链一个都不动（新增的 `chp.html` 页与 `downloads/chp/` 属 **S-1b**，见 §8）。
- **不动 ImaHamster**（`life.airen.imahamster`，视觉助手）—— 它**不读 CHP**（全仓只有 1 处无关的 grep 命中），
  本轮**不升级**。**不是**「与语音无关」这么笼统：PoseGi 同样与语音无关，但它读 CHP，所以它要升级。
- **不动 hamdraw happ 的功能**：它是画图工具，不需要朗读（只改它读 CHP 的那一层，见 §5.1/§5.2）。

---

## 8 阶段与验收判据

| 阶段 | 内容 | 判据（可执行） |
|---|---|---|
| **S-1** | **CHP 独立成仓 + hamdraw 断开内嵌**（详述 ⇒ §14）。插件源码移出 `hamdraw/`，成为独立仓 `haminn-chp`；**hamdraw 侧一件插件资产都不留**（§5.5） | ① 新仓 `python3 tests/test_spec.py` 与 `test_mask_graph.py` **全绿**（实测搬迁前已是全绿，所以这一条只是防回归）；② **搬迁的硬判据 —— 字节相同**：在新仓跑 `python3 tools/package-plugin.py`，产物 zip 的 `sha256` **等于**搬迁前 hamdraw 那份 v3.1.1（`172ab450c4f8…0f6bfac339cff0933a6bc5fb`）。⚠ **不要写 `--check`** —— `--check` 要求 `release/` 里已有该 zip（`package-plugin.py:102`），而新仓 `release/` 是空的，必红（§0.1 第 2 条）；③ 新仓打包器**排除项生效**：树里放三个假密钥文件后重打包，zip 内 `.json` 条目 **== `[]`**（§4.4.1）；④ `hamdraw/app/assets/comfyui-plugin.js` 与 `hamdraw/tools/embed-plugin.py` **文件不存在**；⑤ `hamdraw` 里这三条 **各 == 0**：`grep -rn "comfyuiPlugin" app index.html tools`、`grep -rn "data-plugin-download" app index.html tools`、`grep -rn "embed-plugin" app index.html tools`（**分成三条、不写竖线**，避开 BSD grep 那条坑）；⑥ `hamdraw` 里 `grep -rnE "comfyui-plugin/" README.md guid.md CONTRIBUTING.md` **只剩「已独立成仓」的指引**，且 **`CONTRIBUTING.md:48` 那句 `tools/package-plugin.py --check` 已改指新仓**；⑦ 三个 happ 各跑自己的 verify —— hamdraw 侧**只用与插件相关的那几条**，不拿整份当判据（§14.6） |
| **S-1b** | **官网 CHP 页 `public/chp.html` + 下载位 `public/downloads/chp/` + 三个 happ 换提示句**（§5.5、§14.5.1）。**页先上线，happ 才换提示** —— 否则提示指向 404 | ① `haminnweb/public/chp.html` 在，**头部/页脚由 `tools/build-site-nav.py` 拥有**，中英双写在；**判据写「`build-site-nav.py --check` 的输出里不出现 `chp.html`」**，⚠ **不要写「全区绿」** —— 实测它同时报 **3 个 stale**（`chataxi/` `hamdraw/` `posegi/` 的 `index.html`，**S-1b 之前就红**，与本次无关），写「全区绿」就永远红；② `python3 tools/check-site.py`、`python3 tools/check-bilingual.py` 全绿；③ `python3 tools/package-chp-download.py --source <zip> --check` 报 `latest alias in sync`；④ `chp.html` 里对下载位**只出现 `…-latest.zip` 一个**（`grep -oE "downloads/chp/[A-Za-z0-9._-]+" public/chp.html \| sort -u` 只剩一行）；⑤ **官网三个下载按钮改指别名**（§14.5）：`grep -rnE "downloads/hamdraw/hamdraw-comfyui-plugin" public/hamdraw/index.html public/posegi/index.html` ⇒ **0**，且 `grep -rc "downloads/chp/hamdraw-comfyui-plugin-latest.zip" public/hamdraw/index.html public/posegi/index.html` ⇒ **各有命中**；⚠ 这两页当前是 `build-site-nav.py --check` 报的 stale 页 ⇒ 改它们**必须用 `python3 tools/build-site-nav.py <page>` 重生成**，不许手改头尾；⑥ 三个 happ 各跑 `verify` 全绿；⑦ **新断言**：三处提示的 URL 常量**逐字相同**（`grep -rho "https://haminn.airen.life/chp.html" hamdraw/app chataxi/app PoseGi/app \| sort -u \| wc -l` **== 1**）、锚点里**没有 `target="_blank"`**、文案**双语都在**；⑧ **真机点一下**：三个 happ 各点一次，都真的跳到系统浏览器那一页（`MainActivity.kt:1306` 的同帧外跳） |
| **S0** | 规范：`plans/chp-spec.md` 加三节 | 条文齐全：`speech` 段（含 `txt-2-sph`、`voices` 顺序即规范）、`endpoints` 八键、**info 需 key**、**403 `forbidden_capability`**、**控制台不是协议的一部分且不进 `endpoints`**、「speech 文本永不翻译」、「CHP 不做调度」六句都在 |
| **S1** | **Backend 接口抽离**（纯重构） | `test_spec.py` + `test_mask_graph.py` 全绿；`grep -cE "folder_paths|PromptServer|import execution" hamdraw_chp/server.py` **== 0**（用 `-E`，**不要写 `\|`** —— BSD grep 会把 `\|` 当字面竖线，静默返 0，恰好让这条判据变成假绿）；A1X 上 `/chp/info` 与升级前逐字节相同 |
| **S2** | key 表 + 按 key 过滤 + **执行层校验** | 离线**五条**：① **一把 key 都没配 ⇒ 200 且全能力**（`auth.required: false`）；② **配了 key 后**无 key / 错 key ⇒ 401（响应体带 `spec: "chp/2"`）；③ key 只授权 `fast` ⇒ 文档里 **`rules` 与 `abilities` 同时少**（不许只少一边）；④ 用该 key 打 `generate` ⇒ **403 `forbidden_capability`**（**执行层**，不是靠界面藏起来）；⑤ 默认 key（配置节点的密码 / `HAMDRAW_PASSWORD`）⇒ 全部可用。**每条新断言都被至少一次按名字命中的变异证伪**（含 §5.2 末条点出的「hamdraw 侧要新写的那条」） |
| **S3** | `speech`：模块 + `settings.speech()` + `document(speech=…)` + `ENDPOINTS` + `/chp/speech` | 照 `chp-speech-plan.md` §6 的 S1–S3 那套（流式 `audio/pcm` / 整包 `audio/wav` / 坏音色 400 / 错 key 401 / 引擎失败收敛成 `no_engine` 且**响应里无地址无令牌**） |
| **S4** | 管理面：`chp_admin.json` + `chp_keys.json` + `/chp/admin/*` + 静态页 | ① 默认凭据能登录；② **页面与 API 里不存在任何修改凭据的入口**（在静态页源码与 admin 路由表里都查不到）；③ `POST /chp/admin/keys` 传一个清单外的 category ⇒ 拒收；④ 改 `chp_admin.json` 后**重启**才生效；⑤ 三个配置文件都在 `.gitignore` 里 |
| **S5** | 服务模式：`__main__.py` + `cli.py` + `backends/comfy_http.py` | ① 同一个 key 下 `/chp/info` 与插件模式**逐字节相同**；② 上游不在时 `/chp/info` 仍 200 且 `errors` 里有说明；③ 改 `serve.port` 后客户端**一行不改**仍可用 |
| **S6** | 客户端：**hamdraw / PoseGi** 的缓存分桶 + **三个仓**的 401 处理 + PoseGi 那句注释 + Chataxi 的 tts 分支 + 3.2.0 夹具 | `node tools/verify.mjs` **三个仓**全绿（三个仓都有这个入口 —— 已核实）；**新用例**：401 ⇒「访问密码不正确」（**不是**「这个地址不是 CHP 服务」）、403 ⇒「这把 key 没有这个能力」；**缓存分桶用例**（key A 的能力不得出现在 key B 的界面）；PoseGi 新增 `tests/fixtures/chp-info-3.2.0.json` 且 **3.1.0 那份仍在**（它被 3 份测试读着：`discovery` / `settings` / `chp-jobs`）。⚠ **变异要按仓补**：`chataxi/tests/.mutate-chp.mjs` 已有「不是 CHP 服务」那两条（`:221-222`），**hamdraw/tests/.mutate-chp.mjs 零命中，要新写**（§5.2 末条）；PoseGi 的变异脚本是 `tests/.mutate-chp.py`（**Python，不是 mjs**，别去找错文件） |
| **S7** | 改名（§2.1 全表） | `hamdraw` 的 `tools/verify.mjs:187` 与 `tests/providers.test.mjs:96` 同步改后**全绿**；三个仓 + 官网 **现查** `grep -rlI "ComfyUI Haminn Protocol" <仓> --exclude-dir=.git` 得到的那份清单**逐条看过**，除历史计划文档（`plans/chp-*.md`、`docs/chp-portal-plan.md`）与**假命中**（`PoseGi/app/assets/models/ikea.js` 的 base64）外不再有残留。⚠ **判据写「现查」，不照 §2.1 的枚举** —— 那份表上一版就漏过 `PoseGi/app/services/translate.js:77`（§0.1 第 4 条） |
| **S8** | **A1X 真机验收**（§9 七条） | 见 §9 |
| **S9** | 设备热更新 + 真机朗读 | 读回 `sha256` **MATCH**；**朗读一句话真的出声**（需业主自己在卡片里填地址与 key，见 §9 注） |

**S2 的断言与变异**（照既有 `.mutate_*.py` 手法：**按名字命中**才算抓住）：

| 断言 | 变异（必须报红） |
|---|---|
| **一把 key 都没配 ⇒ 200 且全能力**（§3.2.1） | 让「没有任何 key」也走 key 表查找 ⇒ 变成 401。**专抓「把公开态当成漏掉的一支」** —— 这一条方向与下面那条相反，两条必须同时绿 |
| 无 key / 错 key（**已配 key**）⇒ `401` | 把 info 改回「未授权也回答」 |
| 401 响应体带 `spec: "chp/2"` | 去掉 `_fail(..., spec=…)` 传到 payload 的那一行 |
| 文档按 key 过滤（`rules` / `abilities` **同步**少） | 只过滤 `abilities` 忘了 `rules`（**上一版只写了这一条变异，现在它同时守着 `rules(allowed=…)` 这个新签名**） |
| **执行层**：未授权 category ⇒ 403 | **只删掉 `create_job` 里的校验**（这一条专抓「只做播报层」这个最常见的漏） |
| 默认 key ⇒ 全能力 | 让默认 key 也走 key 表查找 |
| 文档里不出现后端地址与令牌 | 把 `speech.url` 塞进 `speech.abilities[].files` |
| `speech` 文本不经过 translate | 让 `speak` 复用 `ensure_english` |
| 打包器排除密钥文件（§4.4.1） | 从过滤名单里删掉一个文件名 ⇒ zip 内容清单里 `.json` 条目非空 |

---

## 9 S8 · A1X 真机验收（七条）

按技能 `a1x-comfy-device` 的闭环：**逐文件传、清 `__pycache__`、重启 `minimax-h3-comfy`、两侧 `sha256sum` 逐一对照**。

1. `GET http://192.168.124.31:8189/chp/info` **带正确 key**：多出 `speech` 段；`endpoints` **八个**键；
   `spec` **仍是 `chp/2`**；`plugin.version == "3.2.0"`；`errors` 里多出四条新码；
   `plugin.label` 已是新名（`CHP 插件（CHPCP）`）。
2. **授权两态**（顺序不能颠倒 —— 先确认公开态，再装 key 验 401）：
   - **一台都没配 key 时**：`GET /chp/info` **不带 key** ⇒ **200**、`auth.required: false`、能力全在
     （这是「老用户零改动」的直接证据，§3.2.1）。
     ⚠ **2026-10-13 实测：A1X 不是这一态**（`hamdraw_settings.json` 里配了 `password` ⇒ 今天
     `auth.required` 就已经是 `true`）⇒ 这一条**在这台机器上不可达**，不能靠真机证。
     它由 `test_spec.py` 的两条离线用例守着（§3.2.1 那两条必须同时绿），真机只能证下面两条；
   - 再放一把 key 进 `chp_keys.json`（**在设备上手工放，别让工具代填**）⇒ **不带 key** ⇒ `401` 且响应体带 `spec`；
   - **带一把只授权 `speak` 的 key** ⇒ 文档里只有语音那一节（`rules` 与 `abilities` 同时少），
     且用这把 key 打 `/chp/jobs` ⇒ **403 `forbidden_capability`**。
3. `speech.abilities[0].voices` **恰好 9 条**且顺序等于设置里那份；`audio.sample_rate == 24000`、`streaming == true`。
4. **流式**：`POST /chp/speech`，`{text:"你好，这是一次测试。", voice:"vivian", stream:true}` ⇒
   `Content-Type: audio/pcm`，**首字节在 1 s 内到达**（量 TTFB），总字节数与文本长度相称。
5. **整包**：同一次请求改成 `stream:false` ⇒ `Content-Type: audio/wav`，body 以 `RIFF` 开头。
6. **九个音色逐个**跑一遍，全部 2xx 且字节数非零（这是「能不能获得它的音色」的直接答案）。
7. **没有旁效**：同一把全权 key 下，`rules` / `abilities` 与图片侧**逐项与升级前一致**（加法不许碰旧的两表）。

> **2026-10-14 实测：①–⑦ 全部通过**（`hamdraw_chp/` 21 个文件传到 A1X、两侧 sha256 逐一相同、
> 重启 `minimax-h3-comfy`；逐条数字 ⇒ 当日日志）。两处做法与本节写法不同，都以实测为准：
> **第 7 条**没有拿"升级前那份 `/chp/info`"比（它已经被覆盖了），而是用部署前的备份（3.1.1 源码）
> 与本机 3.2.0 **逐项比对** `RULES` / `FRAMES` / `CATEGORY_TABLE` / `INPUT_SCHEMAS` /
> `abilities(...)` / `categories()` —— 同一台机器、同一份设置，**六项全 IDENTICAL**，比字符串比对硬；
> **引擎地址与令牌没有留在设备上**（验收时临时写入、验完按 sha256 原样还原）：它是部署决定，
> 由业主填一次，`speech.url` 见 §6.1。第 2 条的第一支在这台机器上不可达（见上）。

> **注（必读）**：真机上要让 Chataxi 出声，需要**业主自己在朗读槽配一张 CHP 卡并保存 key**。
> 那张卡是他的数据；按既有规矩（`AGENTS.md`：密钥只在用户明确保存后写入），
> **不代填、不把 CHP key 或引擎令牌写进 happ 数据区。**
> 验收时用**只存在内存的探针卡片**（`discover(..., {persist:false})`）证明链路通，再由他保存。

---

## 10 版本与落地顺序

| 物 | 现在 | 改成 | 理由 |
|---|---|---|---|
| `spec` | `chp/2` | **`chp/2`（不动）** | 三处加法的载体是「未知顶层键必须忽略」，图片侧契约一个字没变 |
| **新仓 `haminn-chp`** | 空仓（2026-10-12 23:53 建） | 承接 `comfyui-plugin/` 全部源码；**不引入第二套版本号** —— 版本仍是 `hamdraw_chp/version.py`，发布打 tag `v<同号>` | 一个东西一个版本号；zip 名与 `/chp/info` 上报的号永远同源（§14.4） |
| 插件（`version.py`） | `3.1.1` | **`3.2.0`** | 加法、向后兼容，走第二段 |
| hamdraw 仓 | 当前值 | 升第三段（`haminn.json` / `app/core/namespace.js` / `README.md` 三处同步）**——但本轮这两处正被业主在制品占用，递增递延到在制品落地那次**（§14.6） | 搬迁改的是源码文件（删目录、删 2 个文件、改 4 个文件），按规矩要升；只是同一批文件有冲突，不能叠层 |
| chataxi 仓 | 当前值 | 升第三段（同上三处） | 改了 `catalog.js` / `model-services.js` / `tts.js` / i18n |
| **PoseGi** 仓 | `0.1.25` / code `26` | **`0.1.26`**（升第三段，`haminn.json` / `app/core/namespace.js` / `README.md` 三处同步） | **它读 CHP**（29 个文件）：缓存分桶、401 处理、`providers.js:533` 注释、改名文案、3.2.0 夹具。**没有功能改动，但必须升级** |
| **ImaHamster** 仓 | `0.1.46` / code `47` | **不动** | **源码零 CHP 命中** |
| **`haminnapp` 仓（宿主）** | 当前值 | **不动** | **源码零 CHP 命中**（大小写敏感，实测 0 个文件）。`ComfyUI` 全仓共 **2 处、都是注释**（`NativeHttpClient.kt:718` 与 `app/src/androidTest/.../NativeHttpConnectionReuseInstrumentedTest.kt:29`）—— 上一版写「只有 1 处」漏了 androidTest 那处。它内嵌的 `assets/store/`（= `haminnweb/public/shell/` 的逐字节镜像）里也没有 CHP 字样。详见 §12 |
| **`haminnweb` 仓（官网）** | **站点自身没有版本号**（只有 Shell 发布包有 `version`/`versionCode`，本轮**不碰 `public/shell/`**） | **不升版本** —— 新增 `public/chp.html` 与 `public/downloads/chp/`，另外改两个工具（`build-site-nav.py` 登记新页、`check-site.py` 加一条 latest 断言） | 官网**不是 happ**、没有 `haminn.json` ⇒ 这套「升第三段 / 三处同步」的规矩对它不适用。它的正确门是 `check-site.py` + `check-bilingual.py` + `build-site-nav.py --check` 三道 |

```
S-1（独立成仓 + 断开内嵌）→ S-1b（官网 CHP 页 + 三个 happ 的提示）→ S0 → S1 → S2 → S3 → S4 → S5 → S6 → S7 → S8（A1X 真机）→ S9（推设备）
```

- **S-1 先做**：**搬迁**本身零协议变化、可回退，且做完之后 S0–S5 的插件改动**只在一个仓里改**，不用再跨仓看两边。
  它同时是 S1 的前置 —— 抽 `backends/` 这种结构改动，在独立仓里做才不会再动到 hamdraw。
  ⚠ **S-1 现在多了一处真实的行为变化**：hamdraw 那颗「下载 ComfyUI 插件」按钮没了（§5.5）⇒ 不再是纯重构。
  回退仍然干净：资产文件与那段代码都在 git 里，`git checkout` 即可（§11）。
- **S-1b 必须在 S-1 之后、且官网那页先上线**：提示句里那个 URL 指向它，页不在就是 404。
  这两步合起来才是「CHP 与 happ 彻底分离」，所以**不要把它推到 S7** —— S7 是改名，与这件事无关。
- **S1 是插件侧的地基**（S3 的 speech 后端、S5 的服务模式都挂在它上面），**且它是纯重构、可回退**。
- **S8 通过之前不碰设备**（v2 的同一条纪律）。
- **改名（S7）与前七步同批执行**：`「CHP 语音」`这个新家族名本来就要写进 chataxi 的
  `catalog.js` / `i18n-en.js`，与改名落在**同一批文件**里，一次改完只跑一次 verify。
  **S-1b 的提示句也落在同一批文件里**（chataxi 的 `model-single-editor.js` + `i18n-en.js`）
  ⇒ 文字口径要一次定死，别 S-1b 写一遍、S7 再改一遍。
- 正式发布（GitHub release + 官网下载位 + 同步到服务器）是 S9 之后的**独立动作**，
  而**这一次的发布动作已经定死**（业主 2026-10-13 定，完整口径 ⇒ §14.5.1）：
  **插件打包成 zip → 复制进 `haminnweb/public/downloads/chp/` → 确认 `latest` 指向这个 zip → 同步到网站服务器。**
  **S-1 改变了这次发布的三处**：插件 zip 的 GitHub Release 改挂在 `haminn-chp` 仓；hamdraw 的 release
  仍挂 happ 包但**不再挂插件 zip**；**不再有任何「内嵌插件副本」要同步**（§14.5）。

---

## 11 风险与回滚

| 风险 | 处置 |
|---|---|
| **`/chp/info` 改 401 打断已发布的 hamdraw** | §5.2：两个仓**都已经有 401 的文案映射** ⇒ 大概率零改动正确；但**必须实测确认**而不是假定。`auth.authorized` 分支**保留不删**（老插件仍走它） |
| **文档按 key 分内容 × 客户端模块级缓存 = 授权泄漏** | §5.1：**改成按服务分桶**，并加一条跨 key 的用例。这是本轮最容易被漏的一处 |
| **只做播报层过滤、忘了执行层校验** | §3.3 第二层 + S2 表里那条**专抓它**的变异（只删 `create_job` 里的校验） |
| `speech` 流式转发在 ComfyUI 的 aiohttp 里首字节被拖慢 | S8 第 4 条**量 TTFB**；若明显劣于直连，退到「文档播报地址、happ 直连」（`chp-speech-plan.md` §1.4 方案 1）—— **退路是设计好的，不是临时的** |
| 服务模式下「上游有哪些模型」与插件模式读到的不一致 | S5 判据①要求 `/chp/info` **逐字节相同**；`comfy_http` 从上游 `object_info` 枚举读，不读本地磁盘 |
| 三个配置文件被误提交（含凭据） | §4.4：三个都进 `.gitignore`（**注意是哪一份** —— `comfyui-plugin/.gitignore` 根本不存在），S4 判据⑤ 用 `git check-ignore -v` 查一遍 |
| **密钥文件被「合法地」打进发布 zip**（比误提交更隐蔽：它绕过 `.gitignore`，因为它压根不看它） | §4.4.1：`package-plugin.py` 加显式排除名单 + 命中时打警告；判据是「放三个假文件后 zip 里 `.json` 条目 == `[]`」。**已实测两态**（修前会列出三个、修后为空） |
| **判据假绿**：`grep "package-plugin"` 只剩「文档一句」这条，会被 `CONTRIBUTING.md:48` 骗过（它像指引，其实是错的） | §14.3 铁律3：判据改成「命中**逐条看过** + 不许出现**可执行写法**」 |
| **搬迁的「跑得通」判据掩盖路径错误**：`--check` 在有空 `release/` 的新仓必红，容易被误读成「搬坏了」 | §8 S-1 判据②换成 **跨仓 sha256 相等**（已实测：改对 `SOURCE` 后重建，字节逐一致） |
| **官网三个按钮永远指向旧版插件**（v3.0.0 / v3.1.1 / v2.3.0 同时挂在页面上） | §14.5：**文件不动、按钮改指 `latest`**；改页要用 `build-site-nav.py` 重生成（那两页本来就是 stale 页） |
| ComfyUI 重启会带走语音（多了一个耦合） | 已知并接受；与 `translate` 今天的处境完全一样。服务模式是它的解法，但**不是本轮的必须** |
| happ 里存着旧卡（没有 `speech` 那节） | 报「插件没有语音能力，请升级插件」，**不是静默不出声** |
| **happ 里那句提示的 URL 打不开 / 写错** | 它被**编译进三个 happ**（§5.5）⇒ 改一次要重发三个。判据：S-1b ④ **真机点一次**（同帧外跳），不靠读代码。URL 定稿后进冻结线（§2.2） |
| **提示只出现在「选到 CHP」时，用户找不到它** | 接受。**补**：CHP 相关的错误文案也带同一个 URL（§5.5 代价第 3 条），那是用户真正需要它的时刻 |
| **提示句里的文案在 S-1b 与 S7 被改两遍** | §10：S-1b 与 S7 落在同一批文件（chataxi 的 `model-single-editor.js` + `i18n-en.js`）⇒ **文字口径一次定死** |
| **S-1 搬迁：把业主的在制品卷进搬迁提交** | §14.6：提交**点名到文件**，绝不 `git add -A` / `git add tools/`；**`verify.mjs` 用索引层只暂存本次那几个 hunk**；搬迁提交**不碰任何版本号** |
| **S-1 搬迁：拿整份 `verify.mjs` 全绿当判据** | §14.6：在制品让 verify 处于「未验完」状态 ⇒ **只用 §8 里 S-1 那几条**判 |
| 插件的「版本悄悄漂移」 | **这一类随内嵌链一起消失**（§5.5 收益第 2 条，实证：资产是 v3.0.0 而产物已 v3.1.1）。改完只有一个出处：`haminn-chp` 仓的 `version.py` |
| 插件回滚 | 宿主 `.bak-<日期>/` 拷回 + 重启容器 |
| happ 回滚 | 热更新前的版本仍在设备上，直接回推 |
| 官网 `/chp/` 页改坏 / 被删 | 它是三个 happ 提示句的唯一落点 ⇒ **路径进冻结线**（§2.2），发布后抽查一次可达即可 |
| **S-1 整体回滚** | 搬迁与断开内嵌都是源码改动 ⇒ 反向 `git revert` 那一条提交（资产文件、`embed-plugin.py`、那颗按钮、四条门禁断言全在 git 里）。**新仓留着不碍事**（空转） |

---

## 12 本轮不解决（留档）

- **happ 的两个槽各配一次同一台 CHP**（§5.4）。
- **happ 不再附带插件**（业主 2026-10-13 定，§5.5）：离线首启时那句提示打不开，**接受** ——
  CHP 本来就要求本机有一台跑着 ComfyUI 的机器。也不做「扫码/局域网互推」这类补丁式分发。
- **官网 `/chp/` 页面的形态**：本轮只要它「说清 CHP 是什么、装在哪台机器、去哪儿下载」并真的给出 zip。
  美化、多语言排版按站点既有风格走，**不做单独设计**。
- **控制台的美观与国际化**：本轮只要求能用，中文界面（管理员是业主本人）。
- **控制台的「重新生成 key」之外的 key 生命周期**（过期、限流）：不做，需要时再加。
- **服务模式的容器化 / systemd 单元**：本轮只提供 `python -m hamdraw_chp serve`，谁管进程是部署的事。
- **宿主 `haminnapp`：已核实「不动」，不再是待定项。** 曾以为它的商店页（`app/src/main/assets/store/**`）与
  `MainActivity.kt` 里有 CHP 字样 —— **那是 `grep -i` 的误判**：命中的是 `devSwitchPanel` / `dispatchPublic`
  里的子串 `chP`。大小写敏感地搜 `CHP`，**全仓零命中**；`ComfyUI` 共 **2 处，都是 Kotlin 注释**
  （`NativeHttpClient.kt:718` 与 `app/src/androidTest/java/life/airen/haminn/NativeHttpConnectionReuseInstrumentedTest.kt:29`）。
  另注：`assets/store/` 是**宿主内置的那份「Haminn 应用库」控制面**（装/管 happ、开发态切换、设置、分享的页面），
  与 `haminnweb/public/shell/` **逐字节相同**（只少一个 `shell.zip`，官网那份是权威源）。
  `LocalContentGateway.forStore()` 把它挂在伪源 `https://store.haminn.invalid/` 上从 assets 提供；
  `OfficialShellManager` 有 `LOCAL`（用这份内嵌副本，装机即可用/离线可用）与 `ONLINE`（从官网下载
  `haminnshell-v<ver>-release.zip` 覆盖）两态 —— **它是首启与离线的兜底控制面，不是商店后端**。
  商店页上的 happ 资料走宿主桥 `apps.list` / `apps.installOnline`，**本仓不含任何 CHP 字面** ⇒ 改名在官网落一次即可，
  宿主**不需要重新构建 APK**。以上都核实过：这份内嵌副本与官网**内容全等**（`diff -rq` 只报 `shell.zip`）。
  以后再核这类「某仓有没有某字符串」，**一律用大小写敏感搜索**，`-i` 会制造假命中。

---

## 13 业主定稿清单（逐条可核对）

| # | 定稿 | 来源 |
|---|---|---|
| 1 | CHP = **Consolidated Haminn Portal**，中文「**Haminn 综合入口程序**」（不叫门户） | 2026-10-12 22:58 |
| 2 | ComfyUI 里那个插件叫「**CHP 插件**」，简称 **CHPCP** | 同上 |
| 3 | `/chp/info` 的 `plugin.label` = `{"zh": "CHP 插件（CHPCP）", "en": "CHP plugin (CHPCP)"}` | 2026-10-12 23:28 |
| 4 | **一个 key 接全部能力**，不做 per-happ 身份；但**每把 key 可配不同的可用模型** | 22:58 / 23:28 |
| 5 | **`/chp/info` 改为需要 key**，只返回该 key 的可用列表 | 2026-10-12 23:38 |
| 6 | **不做新 `kind` 字段**，happ 靠**现成的 `signature`/iorule** 自己判断能不能用 | 23:28 |
| 7 | 端口**可配、不锁定**（建议默认 8889） | 23:10 |
| 8 | 控制台是 **CHP 的一部分**，与本机或局域网有关、与 happ 无关 | 23:10 / 23:28 |
| 9 | 控制台**只能管 key 与 key 的可用模型**；**不能新增能力**；可用模型只能从**已设定的列表**里选 | 23:38 |
| 10 | 控制台凭据 = 固定用户名密码（默认 `hamster` / `imahamster`），**独立的配置文件**，**只能登录本机改**，改后重启生效 | 23:28 / 23:38 |
| 11 | A1X 调度服务**与 CHP 无关**，它只保障 CHP 设定的本地接口可被找到并路由给 happ | 23:28 |
| 12 | **所有可用模型都由管理员手工改代码开发添加**（控制台不参与） | 23:28 |
| 13 | **改名与 TTS 改造同一批执行** | 23:28 |
| 14 | 本轮**只接 TTS**，不考虑 ASR / 视频 | 2026-10-12 早 |
| 15 | Chataxi 与 CHP 插件**都可以改、可以升** | 同日 |
| 16 | **Chataxi / PoseGi / HamDraw 都要升级**（三个读 CHP 的 happ）；**ImaHamster 不用升级**（不涉及 CHP） | 2026-10-12 23:50 |
| 17 | **改 CHP 不涉及 `haminnapp/` 与 `imahamster/`** —— 两者源码**零 CHP 命中**（大小写敏感核实） | 2026-10-12 23:58 |
| 18 | **CHP 从 hamdraw 里移出，独立成一个项目**，放到上一层的独立文件夹，远程对应 `git@github.com:zhyuzh3d/haminn-chp.git`（该仓 **2026-10-12 23:53 已建好，PUBLIC、空仓**） | 2026-10-12 23:58 |
| 19 | **三个 happ 都不再内嵌 CHP 的 zip 包**：用户选到 CHP 服务时，**在该表单底部多一句提示**说明 CHP 是什么、**需要到 Haminn 官网下载**。CHP **彻底从 happ 中分离** | 2026-10-13 00:14 |
| 20 | 因此 hamdraw 的 `embed-plugin.py` / `vendor/` / `app/assets/comfyui-plugin.js` / 那颗下载按钮**全部删除**；门禁改为**反向断言**（这几样不许回来） | 同上（§5.5） |
| 21 | **提示就一行纯文字 + 一个普通链接**：不要按钮、不要应用内打开、不要应用内下载；**点击链接交给安卓系统默认浏览器** | 2026-10-13 00:47 |
| 22 | 官网那一页的文件名定为 **`chp.html`**（`https://haminn.airen.life/chp.html`，不是 `/chp/` 目录）：CHP 的**介绍与下载都在这一页** | 2026-10-13 00:47 |
| 23 | **CHP 的正式发布动作**固定四步：**打包 zip → 复制到 haminnweb 的对应目录 → 确保 `latest` 下载链接指向这个 zip → 同步到网站服务器**（逐条可执行 ⇒ §14.5.1） | 2026-10-13 00:50 |

---

## 14 阶段 S-1 · CHP 独立成仓 + happ 断开内嵌

> 这一节是 **S-1 的详述**。它先于 S0，因为搬完之后 S0–S5 的插件改动**只在一个仓里改**。
> **协议零变化**：不改根路径、不改 `spec`、不改任何端口或地址。
> ⚠ **但不是零行为变化**（业主 2026-10-13 改口径）：hamdraw 那颗「下载 ComfyUI 插件」按钮随内嵌链一起删掉，
> 换成一句到官网的提示（§5.5，落地在 S-1b）。回退仍干净 —— 一切都在 git 里。

### 14.1 为什么能干净拆出去（读代码得出）

**逐文件的 ComfyUI 依赖清单见 §1.4，不在此重复**（重复一遍等于让两处各自漂移）。结论仍然是那一句：
**它本来就是「一个库 + 两个薄薄的 ComfyUI 适配层」**——

- ComfyUI 依赖**只落在 `server.py`（四处）与 `nodes.py`（一处）**；
- `capabilities.py` / `settings.py` / `translate.py` / `families/` **零依赖**；
- `tests/`（2 份测试 + 2 个变异脚本，**2161 行**）**也是零依赖** —— `test_spec.py` 的 docstring 自己写着
  「不需要 ComfyUI、不需要网络、不需要 aiohttp」。

⇒ 这是一个**独立仓的完整形状**。搬的是目录，不是代码。

### 14.2 目标形态

**新仓（本地目录名见 §14.9 待定；remote 已定）**：

```
<CHP>/                           remote: git@github.com:zhyuzh3d/haminn-chp.git
├── hamdraw_chp/                 ← 包。**冻结：名字不改**（§2.2）
│   ├── version.py               ← **版本唯一出处**
│   ├── capabilities.py  server.py  settings.py  translate.py  nodes.py
│   └── families/
├── tests/                       ← test_spec.py / test_mask_graph.py / 两个变异脚本
├── tools/package-plugin.py      ← 从 hamdraw 搬来（它是产物构建器，跟产物走）
├── plans/chp-spec.md  chp-v2-plan.md  chp-plan.md  chp-review.md  chp-speech-plan.md
├── docs/chp-portal-plan.md      ← 本文件（搬完就在这儿）
├── release/                     ← hamdraw-comfyui-plugin-v<ver>.zip（本仓产出）
├── README.md                    ← 由 hamdraw/comfyui-plugin/README.md 升格
└── LICENSE  .gitignore  .github/
```

**hamdraw 侧（彻底断开：一件插件资产都不留，业主 2026-10-13 定）**：

```
hamdraw/
├── （vendor/ 不存在）        ← 不要建它
├── （tools/embed-plugin.py 已删）
├── （app/assets/comfyui-plugin.js 已删）
└── README.md · guid.md       ← 只多一行「CHP 已独立成仓，见 haminn-chp」的指引
```

hamdraw 与插件之间**唯一的连接是一句散文和一个官网 URL**（那句提示在 S-1b 落地）。
不再有 zip、不再有构建顺序、不再有版本同步 —— **这条链整条作废**：
`release/*.zip` → `embed-plugin.py` → `app/assets/comfyui-plugin.js` → `index.html` 脚本表 → 下载按钮。

> `release/` 里那 4 个历史插件 zip **原地不动**（历史产物既有定稿，§14.8 末）。
> 改完之后**没有任何代码读它们**，它们只是历史。

### 14.3 三条铁律（2026-10-13 重写）

1. **hamdraw 侧零插件资产。** 不内嵌、不 vendored、不引用产物名。
   旧的「必须有 zip 在仓里」那条已作废 —— 它成立的唯一理由是「happ 读不了自己打包的文件」，
   而现在**没有任何字节要进 happ**（`fetch` / `XMLHttpRequest` 被 `connect-src 'none'` 拒这件事仍然是事实，
   只是与本轮无关了）。判据：hamdraw 里 `comfyuiPlugin` / `data-plugin-download` / `embed-plugin` **各零命中**。

2. **包名不改**：仍是 `hamdraw-comfyui-plugin-v<ver>.zip`。
   **唯一还成立的理由**是「已发出的下载链接」——官网 `hamdraw` 与 `posegi` 两个页面上就写着这个名字，
   改了就是让它们 404。它曾被 `verify.mjs:224` 的正则与 `embed-plugin.py` 一起钉着，**那两处本轮删除**。
   独立成仓**不等于**改产物名。

3. **hamdraw 不再构建插件。** `tools/package-plugin.py` 搬去 CHP 仓；hamdraw 侧删掉它。
   判据：hamdraw 里 `grep -rn "package-plugin" .` 只剩文档里指向新仓的一句。
   ⚠ **这条判据会假绿** —— `hamdraw/CONTRIBUTING.md:48` 里就有一句
   `python3 tools/package-plugin.py --check  # 只在改动触及 CHP 插件时`，它长得像「文档指引」，
   但**搬迁之后它是错的**（脚本已不在本仓）。⇒ 判据要写**两条**：
   ① `grep -rn "package-plugin" .` 的命中**逐条看过**（不是数个数）；
   ② `grep -rn "package-plugin" hamdraw --include=* -r` 里**不许**出现 `tools/package-plugin.py` 这种**可执行写法**，
   只允许「见 `haminn-chp` 仓的 `tools/package-plugin.py`」这种**指路写法**。

### 14.3.1 happ 里那句提示的四个约束（属 S-1b，与本案同批）

见 §5.5：**同帧导航（不加 `target="_blank"`）**、**URL 不带版本号**、**URL 不来自 CHP 文档**、
**就一行纯文字（不要按钮、不要应用内打开、不要应用内下载）**。
再加一条给本节的：那个 URL 是**官网的稳定路径** `https://haminn.airen.life/chp.html`，
**页可以改，路径不能改**（已进冻结线 §2.2）。

### 14.4 版本：CHP 仓**不引入第二套版本号**

- 版本 = `hamdraw_chp/version.py` 的 `__version__`，**仍是唯一出处**（zip 名与 `/chp/info` 上报都从它派生）。
- **不给新仓另立一个「仓版本」**。CHP 不是一个 happ，没有 `haminn.json`，加第二套号只会制造
  「仓 1.0.0 里的插件是 3.2.0」这种要去解释的落差。
- 发布形态：Git tag **`v<version.py 的号>`**（例如 `v3.2.0`），Release 附件 = 那个 zip。
- **`version.py` 在哪个仓，哪个仓就有升它的责任** ⇒ 搬完之后，插件升版本**不再动 hamdraw，也不动任何 happ** ——
  三个 happ 里**没有任何一个数字跟着插件走**（内嵌资产与 `embed-plugin.py` 都已删除，§5.5）。
  **这就是业主改口径真正买到的东西：插件的版本线从此只属于 CHP 自己。**

### 14.5 仓外要同步的地方

| 位置 | 现在 | 改成 |
|---|---|---|
| `haminnweb/public/hamdraw/index.html` | GitHub 源码链 `github.com/zhyuzh3d/hamdraw/tree/main/comfyui-plugin` | **`github.com/zhyuzh3d/haminn-chp`** |
| `haminnweb/public/hamdraw/index.html` + `public/posegi/index.html` 的**下载按钮** | 三个按钮、**三个不同版本**：`hamdraw/index.html:150`=v3.0.0、`hamdraw/index.html:204`=v3.1.1、`posegi/index.html:143`=v2.3.0 | ⚠ **上一版把这条写错了**：它说「旧链接一个都不动」，但那条规矩管的是**文件**（`downloads/hamdraw/*.zip` 一个都不删），**不是页面上的 `href`**。改一个 `href` **不会让任何人 404**，而留着它 = **官网上永远挂着三个过期的插件版本**，正是本轮要消灭的那类漂移。⇒ **拆成两句**：**文件原地不动**（历史制品），**三个按钮的 `href` 一起改成 `https://haminn.airen.life/downloads/chp/hamdraw-comfyui-plugin-latest.zip`**。同一批改、只改 `href`，不删文件、不改页结构 |
| **（承上）页面改动的落地方式** | —— | `hamdraw/index.html` 与 `posegi/index.html` **当前正是 `build-site-nav.py --check` 报的 stale 页**（实测 3 个 stale：`chataxi/` `hamdraw/` `posegi/`）。⇒ 改它们**必须用 `python3 tools/build-site-nav.py <page>` 重生成头尾**，不许手改；判据见 §8 S-1b ⑤ |
| **`haminnweb/public/chp.html`（新增，S-1b）** | 不存在 | **三个 happ 提示句的唯一落点**，也是 CHP 的介绍页：说清 CHP 是什么、装在哪台机器、怎么装、从哪儿下载。**路径进冻结线**（§2.2）⇒ 内容可改，`chp.html` 不能改。**头部与页脚由 `tools/build-site-nav.py` 拥有**（已登记进它的 `PAGES`），**不许手写** |
| **`haminnweb/public/downloads/chp/`（新增，S-1b）** | 不存在 | 插件 zip 在官网的新家 + `chp.json` 描述文件；**页面只认 `…-latest.zip` 这一个别名**（不认版本号） |
| 官网「应用广场」与两个产品页 | 只在页面里提 CHP | 加一条指向 `chp.html` 的入口（**可选**，但既然页建好了，指一次最省事） |
| 技能 `haminn-public` §3.1 | hamdraw 三步：`package-plugin.py` → `embed-plugin.py` → `package.py` | **hamdraw 与插件彻底无关**：happ 发布就是原来那一步（`package.py`）。插件发布**整条搬进 CHP 仓**：构建 zip → 打 tag `v<ver>` → Release 挂 zip → **按 §14.5.1 四步放到官网并同步**。**「先有 zip 再有其他」的顺序禁令跟着搬进 CHP 仓** |
| hamdraw 的 GitHub Release | 附件含插件 zip | **不再挂插件 zip**（改挂 `haminn-chp`）；happ 包照旧 |
| **`haminnweb/tools/check-site.py`** | 只查页面与 APK 元数据 | **已加**一条 CHP 别名断言（`:78-81`，**无条件执行**）⇒ **`public/downloads/chp/` 成了站点检查的硬依赖**，删了它就红。这是有意的（就是那条别名不变量，§14.5.1），但要**记下来**：以后有人清理官网时删掉那个目录，报的是 `FileNotFoundError` 而不是一句人话。⇒ 顺手让它先判存在再解析：读不到就 `SystemExit('CHP download folder is missing: public/downloads/chp/')` |

**这次同步比上一版少了什么**：上一版要维护 `vendor/` 里的 zip 与内嵌资产的同步，
**现在那一整类工作不存在了** —— 官网换一个 zip 就完事。这也是 S-1b 能把整件事收在「一页 + 三句话」里的原因。

### 14.5.1 CHP 的正式发布动作（业主 2026-10-13 定，四步）

**触发条件**：只有业主明确说「正式发布」。平时一律不动官网下载位、不打发布包（§7）。

```
① 打包   在 CHP 仓：python3 tools/package-plugin.py
          ⇒ release/hamdraw-comfyui-plugin-v<ver>.zip
② 复制   放到官网：haminnweb/public/downloads/chp/
          版本化文件 + 覆盖 latest 别名 + 写 chp.json
③ 确认   latest 确实指向这个 zip（字节一致）—— 由工具做，不许手工 cp
④ 同步   只传本次变更路径到网站服务器，并核对该 URL 可取
```

**②③ 由一条命令完成**（`haminnweb/tools/package-chp-download.py`）：

```sh
cd haminnweb
python3 tools/package-chp-download.py --source ../haminn-chp/release/hamdraw-comfyui-plugin-v3.2.0.zip
# ⇒ chp download ok: hamdraw-comfyui-plugin-v3.2.0.zip (n bytes, <sha 前 12 位>…), latest alias in sync
```

它做的四件事，每一件都对着一条既有规矩：

| 它做什么 | 为什么 |
|---|---|
| 从 **zip 内部的 `hamdraw_chp/version.py`** 读版本，并与文件名比对 | 挡住「改了名没改内容」的旧包被发出去（`package-plugin.py` 同一条纪律） |
| 版本化文件**只增不改**（同名而字节不同 ⇒ 报错退出） | 已发布制品不得覆盖 |
| `latest` 别名**每次覆盖**成这一次的这一份 | 它就是「永远指向最新版」的那一条链接 |
| 写 `chp.json`（version / file / latest / bytes / sha256）并当场自校验 | 让**门禁**也能验它，而不是只在发布那一刻对 |

**③ 的不变量由门禁替我们守**（`haminnweb/tools/check-site.py` 里已加）：

```
assert (folder/chp['latest']).read_bytes()==plugin   # 'CHP latest alias is not the current plugin zip'
```

⇒ 别名一旦漂移（手工换过 zip、或换了 zip 忘了别名），`check-site.py` 立刻红。
**这条断言已用变异证明会红**：往别名尾部追加一个字节 ⇒
`AssertionError: CHP latest alias is not the current plugin zip`；还原即绿。

**页面这一侧永远不用动。** `chp.html` 里对下载位**只有一处**，写的正是别名：

```
https://haminn.airen.life/downloads/chp/hamdraw-comfyui-plugin-latest.zip
```

⇒ **插件升版不必改页面、不必重发三个 happ、也不必重发官网任何一页** —— 一并消灭的就是
§5.5 里那条「happ 里的插件悄悄过期」。判据：`grep -oE "downloads/chp/[a-z0-9.-]+" public/chp.html | sort -u`
**只剩一行**。

**明确不做**：① 不新增第二个加工产物（独立运行用的是同一个包）；② 不改 `downloads/hamdraw/` 下的旧链接与旧文件；
③ **不在 `chp.html` 里写版本号** —— 那正是别名要消灭的东西。

> **实现状态（2026-10-13，haminnweb 本地）**：`public/chp.html`、`public/downloads/chp/`（含 `chp.json` 与
> v3.1.1 的两份 zip）、`tools/package-chp-download.py`、`check-site.py` 的那条断言、以及
> `build-site-nav.py` 里对 `chp.html` 的登记**都已写好并通过三道门**（`check-site.py` /
> `check-bilingual.py` / `build-site-nav.py --check`）。**尚未提交、尚未同步到服务器、没有发布任何东西。**

### 14.6 ⚠ 与业主在制品共存（查询时实测，不是假设）

`git status --short` 显示 hamdraw 工作树里有**未提交的在制品**（容器节点模型相关）：

```
 M AGENTS.md   app/components/canvas.js   app/core/namespace.js
 M app/features/self-test.js   haminn.json   tests/rotation.test.mjs   tools/verify.mjs
```

**三件事跟着确定：**

1. **只有一处真重叠：`tools/verify.mjs`。** 搬迁动 `comfyui-plugin/`（整目录删）、`tools/package-plugin.py`、
   `tools/embed-plugin.py`、`app/assets/comfyui-plugin.js`、`index.html`、`app/components/settings.js`、
   `README.md`、`guid.md`、`plans/chp-*.md`；在制品全在 `app/components/canvas.js`、`app/core/namespace.js`、
   `app/features/self-test.js`、`tests/rotation.test.mjs`、`haminn.json`、`AGENTS.md` —— **与上面不相交**。
   ⚠ **`tools/verify.mjs` 两边都要改**：本次要在它里面**删掉那四条内嵌断言**（S-1 判据④的落点），
   它同时被在制品占用。**实测过、可以共存**：在制品的 hunk 在 `:437` 与 `:444`，
   本次要动的那段在 `:218-226`，**相隔 200 多行、不重叠**。
   ⇒ 用**索引层**只暂存本次那几个 hunk（`git add -p tools/verify.mjs`，或把本次 patch `git apply --cached`），
   **绝不 `git add tools/` / `git add -A`**。这正是项目既有做法：同一文件里既有业主在制品又有我的改动时，用索引层构造。
2. **搬迁提交不碰任何版本号。** 版本三处里的两处（`haminn.json`、`app/core/namespace.js`）
   **正被在制品占用**（在制品已把 `0.5.46 → 0.5.47`）⇒ 搬迁里再递增就是**在同一份未提交的改动上叠层**。
   ⇒ **hamdraw 本轮的版本递增递延给在制品落地那次提交**（§10 已记）。
3. **`index.html` 与 `settings.js` 不在在制品里**（核实过），所以「删脚本表那一项」与「按钮换提示」
   这两处可以正常提交，不涉及索引层。

**判据必须分开。** 在制品让 `verify.mjs` 处于「已改、且是业主还没验完的新断言」状态 ⇒
**拿整份 `verify.mjs` 全绿当搬迁成功的判据，会把在制品的红当成搬迁搞坏了**（或反之）。
⇒ 搬迁验收只跑 §8 里 S-1 那几条**与插件相关的**判据，加上 §14.8 末尾那几条反向检查。

### 14.7 历史怎么带（推荐 + 备选）

查出的事实：hamdraw 仓**总共只有 9 个提交**，其中触及 `comfyui-plugin/` 的 **5 个**，
且最早那条就是仓的第一次提交 —— `83c17ac Init: HamDraw 命名下的全新起点`。

| 方案 | 做法 | 评价 |
|---|---|---|
| **A（推荐）** | 新仓一次 `Initial import` 提交，正文写明来源：`Imported from zhyuzh3d/hamdraw@<sha> (path: comfyui-plugin/)` | 与项目既有先例一致（三库都是**全新历史**）；新仓第一条提交自带出处指针；不重写任何历史 |
| B（备选） | `git subtree split --prefix=comfyui-plugin -b chp-split` → push 到新仓 | 带 5 条历史。但那 5 条的上下文（提交信息里讲的是 HamDraw 的版本线）在新仓里读起来是错的，收益有限 |

**两个方案都不重写 hamdraw 的历史** —— `comfyui-plugin/` 的旧提交在 hamdraw 里原样保留
（删目录只是新提交，不是历史重写）。

### 14.8 机械步骤（可执行）

**全部从项目根执行**（`/Users/zhyuzh/BaiduTongbu/2026.09.10hermitapp/`），下面 `<CHP>` 是 §14.9 待定的目录名：

```sh
# 1. 前置检查：确认 comfyui-plugin 自己没有未提交改动（有就先停下问业主）
cd hamdraw && git status --short
git status --short -- comfyui-plugin        # ⇒ 必须为空

# 2. 新仓：从快照建（方案 A）；<src> 是搬迁时的 HEAD
cd ..                                        # 回到项目根
git -C hamdraw rev-parse --short HEAD        # 记下 <src>，下面写进提交信息
# ⚠ 只预建「要放单个文件」的目录。绝不能预建 <CHP>/tests 或 <CHP>/hamdraw_chp —— 
#   目标目录已存在时，cp -R <src> <dst>/ 会变成 <dst>/<basename>，即 <CHP>/tests/tests。
mkdir -p <CHP>/tools <CHP>/plans <CHP>/docs <CHP>/release
cp -R hamdraw/comfyui-plugin/hamdraw_chp  <CHP>/      # ⇒ <CHP>/hamdraw_chp
cp -R hamdraw/comfyui-plugin/tests        <CHP>/      # ⇒ <CHP>/tests
cp    hamdraw/comfyui-plugin/README.md    <CHP>/
cp    hamdraw/tools/package-plugin.py     <CHP>/tools/
cp    hamdraw/plans/chp-*.md              <CHP>/plans/
cp    hamdraw/docs/chp-portal-plan.md     <CHP>/docs/
find <CHP> -name __pycache__ -type d -prune -exec rm -rf {} +     # 拷贝会带过来
find <CHP> -name '*.pyc' -delete
ls <CHP> <CHP>/tests                                  # 只应看到一层 tests，不是 tests/tests

# 2b. ⚠ 搬迁**必须**改的三行（§4.6 / §4.4.1）—— 说「一行不改」是上一版的错
#     tools/package-plugin.py:20    SOURCE = ROOT / "comfyui-plugin"   ⇒   SOURCE = ROOT
#                                   （新仓没有 comfyui-plugin/ 这一层；不改就 missing plugin path 退出）
#     tools/package-plugin.py:60-62 条目过滤再加 {hamdraw_settings.json, chp_admin.json, chp_keys.json}
#                                   并在命中时打一行警告（密钥文件不许进 zip）
#     VERSION_FILE / ARCHIVE / plugin_directories() / ENTRIES 全部由 SOURCE 派生 ⇒ **不用动**
#     改完立刻自证（这一步就是 §8 的 S-1 判据②，数字已实测）：
cd <CHP> && python3 tools/package-plugin.py           # ⇒ created release/hamdraw-comfyui-plugin-v3.1.1.zip
shasum -a 256 release/hamdraw-comfyui-plugin-v3.1.1.zip
#   ⇒ 172ab450c4f883d3f746ed87ea5783bf372387020f6bfac339cff0933a6bc5fb
#   与 ../hamdraw/release/hamdraw-comfyui-plugin-v3.1.1.zip 的 sha256 **相等**才算搬对了
cd ..                                                 # 回到项目根，继续下一步

git -C <CHP> init && git -C <CHP> add -A
git commit -m "Initial import from zhyuzh3d/hamdraw@<src> (path: comfyui-plugin/)"
git remote add origin git@github.com:zhyuzh3d/haminn-chp.git
git push -u origin main

# 3. hamdraw 侧收口（删目录 + 断开内嵌，一次完成）      ← 此时 cwd = 项目根
cd hamdraw
#   手工改**五个**文件（上一版说四个，漏了 CONTRIBUTING.md）：
#     README.md（:32/:54/:56/:92/:96/:126 等）、guid.md（:12/:41）—— 路径与「插件源码在本仓」改指 haminn-chp
#     CONTRIBUTING.md:48 —— `python3 tools/package-plugin.py --check` 改指 haminn-chp 仓
#                          （**不改它就是 §14.3 铁律3 判据的假绿**）
#     index.html:143 —— 脚本表里删掉 ./app/assets/comfyui-plugin.js 那一项
#     app/components/settings.js —— 删 downloadPlugin()（:57-83，含它上面那段解释性注释）、
#                                   那颗按钮（:158）与它的 onclick 绑定（:231），
#                                   位置留给 S-1b 的那句提示（§5.5）
#     tools/verify.mjs —— 删四条内嵌断言（**:221** 下载按钮、**:222** 脚本表、**:223-225** 资产内容两条），
#                         位置留给 S-1b 的反向断言（§5.5）
git rm --quiet app/assets/comfyui-plugin.js
git rm --quiet tools/embed-plugin.py        # 内嵌链整条作废（§14.3 铁律①）
rm -rf comfyui-plugin                       # 含 __pycache__ 等未跟踪残留，git rm 会被它绊住
git add -A -- comfyui-plugin                # 记录这批删除
git rm --quiet tools/package-plugin.py      # 构建器跟产物走了（点名到文件）
git rm --quiet plans/chp-spec.md plans/chp-v2-plan.md plans/chp-plan.md plans/chp-review.md
#   ⚠ 上面这 4 份是**已跟踪**的（`git ls-files` 核实过），用 git rm；
#     `plans/chp-speech-plan.md` 与 `docs/chp-portal-plan.md` **都是未跟踪的新文件**
#     （`git ls-files --error-unmatch` 失败）⇒ 对它们用 **`rm`**，用 `git rm` 会报
#     `fatal: pathspec … did not match any files`（§0.1 第 3 条）
rm plans/chp-speech-plan.md
rm docs/chp-portal-plan.md
git add README.md guid.md CONTRIBUTING.md index.html app/components/settings.js
git add -p tools/verify.mjs                 # ← 索引层：只暂存本次那几个 hunk（在制品在 :437/:444）
git commit -m "Move the CHP plugin out to the haminn-chp repository"   # ← 不碰任何版本号（§14.6）

# 3b. 校验「只暂存了自己的改动」——这一步不能省
git diff --cached --stat tools/verify.mjs   # ⇒ 只应是 :221-225 附近那几行
git diff --stat tools/verify.mjs            # ⇒ 剩下的仍是业主在制品，留在工作区（§14.6）

# 4. 验证（见 §8 的 S-1 行）
cd ../<CHP> && python3 tests/test_spec.py && python3 tests/test_mask_graph.py
#   ⚠ **不要写 `package-plugin.py --check`** —— 它要求 release/ 里已有那个 zip（脚本 :102），
#     而 2b 已经构建过一次、zip 现在就在 ⇒ 这一步**现在可以**跑 --check 了（搬完才有）；
#     但在**空旷新仓**上它必红（§0.1 第 2 条）。判据本体是 2b 那条 **sha256 相等**。
python3 tools/package-plugin.py --check                 # ⇒ plugin archive ok（此时 zip 已由 2b 生成）
#   密钥文件排除项的判据（§4.4.1）：放三个假文件再打包，zip 里不许有 .json
printf 'x' > hamdraw_chp/hamdraw_settings.json
printf 'x' > hamdraw_chp/chp_admin.json
printf 'x' > hamdraw_chp/chp_keys.json
python3 tools/package-plugin.py >/dev/null
python3 -c "import zipfile,glob;z=[n for n in zipfile.ZipFile(sorted(glob.glob('release/hamdraw-comfyui-plugin-v*.zip'))[-1]).namelist() if n.endswith('.json')];print('JSON IN ZIP:',z);assert z==[]"
rm hamdraw_chp/hamdraw_settings.json hamdraw_chp/chp_admin.json hamdraw_chp/chp_keys.json
cd ../hamdraw
grep -rn "comfyuiPlugin" app index.html tools          # ⇒ 空
grep -rn "data-plugin-download" app index.html tools   # ⇒ 空
grep -rn "embed-plugin" app index.html tools           # ⇒ 空
grep -rn "package-plugin" README.md guid.md CONTRIBUTING.md   # ⇒ 逐条看过，只允许「见 haminn-chp 仓」的指路写法
ls app/assets/comfyui-plugin.js                        # ⇒ No such file
node tools/verify.mjs 2>&1 | grep -i plugin            # 只看插件那几条（§14.6）
```

⚠ **`git add` 一律点名到文件**：`tools/` 下有业主在制品（`tools/verify.mjs`），
`git add tools/` 或 `git add -A` 会把它一起暂存（§14.6）。**`verify.mjs` 走 `-p` 走索引层。**

**上一版那个 `embed-plugin.py` 改法（把版本来源从 `version.py` 换成 `vendor/`）整条作废** ——
本轮**不建 `vendor/`、不改这个脚本、直接删掉它**。
连它那个「`vendor/` 里恰好一个 zip」的守卫也一并取消：**没有输入，就没有「指向错了 zip」这种故障**
（这正是删掉内嵌换来的简化，§5.5）。

**`release/` 里那 4 个历史插件 zip（`v2.3.0` / `v2.4.0` / `v3.0.0` / `v3.1.1`）原地不动、不删、不迁** ——
历史产物既有定稿。改完之后**没有任何代码读它们**（`embed-plugin.py` 已删），它们只是历史。
**搬迁这一提交里不要建 `hamdraw/vendor/`**（那一版根本不存在），也不要把 `v3.1.1` 拷进 hamdraw 的任何新目录 ——
新的分发点是**官网** `haminnweb/public/downloads/chp/`，那是 **S-1b** 的事（首次发布即本次，见 §14.5.1）。
**新仓的 `release/` 从空开始**，它的第一个产物是 `v3.2.0`。

### 14.9 待业主拍的两点，以及待点头的一处（第 3 条）

1. **本地目录名**：你说的是 `CHP/`（大写）；GitHub 仓名是 `haminn-chp`。两者不统一要不要紧？
   项目根下现状本来就大小写混杂（`PoseGi` 大写、`hamdraw` / `chataxi` 小写）。
   **我按你的原话默认 `CHP/`**；想统一成 `chp/` 或 `haminn-chp/` 说一声。
2. **`plans/chp-*.md` 五份 + 本计划**：**全部搬去 CHP 仓**（规范与决策记录是 CHP 的资产），
   hamdraw 只在 `README.md` 留一行「CHP 已独立成仓，见 `haminn-chp`」。
   另一条同样自洽的路是 hamdraw 留副本不删 —— 但那会有两份会各自漂移的规范，**我不推荐**。
3. **S-1b 的话怎么说** —— **2026-10-13 00:47 业主已定两条**（见 §5.5 与 §13 第 21 / 22 条），**余一条待你点头**：
   - 官网那一页定名 **`https://haminn.airen.life/chp.html`**（**不是 `/chp/` 目录**）；已进冻结线（§2.2）。
   - 提示句**就是一行纯文字 + 一个普通链接**：**不做按钮、不做应用内打开、不做应用内下载**；
     点击链接由宿主交给**安卓系统默认浏览器**。
   - **「装在那台跑 ComfyUI 的电脑上」那半句：仍在等你一句话**（§5.5 引文里留着它）。
     它就是一句话的成本，挡掉「装在手机上」这个最常见的误装；你上一条的精简版没写它 ⇒
     **默认按草稿留着**，要去掉说一声。留不留都不丢信息 —— 官网页首屏第一句写着它（`chp.html` 已按此写），
     差别只是「在哪一步看到」。

**其余我按上面执行。**
