# CHP 语音（TTS）接入计划 —— 让 CHP 从「画图协议」变成「本地模型协议」，先接 TTS

> **范围**：**本轮只接 TTS，不考虑 ASR / 视频 / 其他类型**（业主 2026-10-12 明确）。
> Chataxi 与 CHP 插件**都可以改、可以升**（业主同日明确）。
> **本文只写：判断是什么、定稿是什么、怎么改、顺序、判据。** 不写实现代码。
> 与 CHP v2 的关系：v2 定稿（[`chp-v2-plan.md`](./chp-v2-plan.md)）已经把图片侧做完并在 A1X 上验收；
> 本文**不改 v2 的任何一条**，只做**加法**。

---

## 0 一句话范围

**在 CHP 文档里加第九个顶层键 `speech`（一个 `rules` + 一组带音色菜单的 `abilities`），在 `endpoints` 里加第八个键 `speech`，
由插件把 `/chp/speech` 转发到本机 TTS 引擎；Chataxi 加一个 `ttsFamilies` 条目 + 一条发现分支，复用它现有的 `openai-speech` 流式代码。**

---

## 1 先说判断：能不能接、适不适合接、接到哪一层

### 1.1 「qwen 这样的 TTS 能不能接进 ComfyUI」

**技术上是能的，但在这台机器上是错的解法。** ComfyUI 有音频节点族，社区也有 TTS 自定义节点包，
所以「把 TTS 做成一个 ComfyUI 工作流」这条路存在。但 A1X 上 TTS **已经是一个独立服务**：

| 容器 | 端口 | 是什么 |
|---|---|---|
| `qwen3-tts-small` | `8021` | **0.6B customvoice GGUF**（`qwen3-tts-12hz-0.6b-customvoice-q8_0.gguf`，backend `qwen3-tts-customvoice`） |
| `qwen3-tts` | `8020` | 1.7B 那一路 |
| `qwen3-translate` | `8022` | CHP 的翻译后端（`translate.url` 指的就是它） |
| `minimax-h3-comfy` | `8189` | ComfyUI 本体 + CHP 插件 |

它有**自己的 GGUF 加载器、自己的音色资产、自己的 OpenAI 兼容 HTTP 接口**。把它「搬进 ComfyUI」
意味着把这套加载逻辑重写成节点图，收益为零、风险是全部：多一份显存占用、多一套要和 ComfyUI 队列抢 GPU 的调度、
多一个「插件升级会不会把语音弄坏」的耦合。
**结论：引擎留在原地，让 CHP 站在它前面。** 这不是妥协 —— 下面 §1.3 会看到，CHP **本来就在这么干**。

### 1.2 A1X 引擎已经给了我们要的一切（实测，2026-10-12 复核）

- `POST /v1/audio/speech`，body `{ input, voice, language, stream, response_format }`；
  **`stream: true` + `response_format: "pcm"` 返回 24 kHz 单声道裸 PCM 分块流**（已实测）。
- **9 个预设音色全部可用**：`vivian`、`serena`、`uncle_fu`、`dylan`、`eric`、`aiden`、`ono_anna`、`sohee`、`ryan`
  （`tara` 是另一族的，500 属预期）。
- `/v1/voices` **是空的** —— 音色清单只能由插件侧手写并播报（这正是 CHP `frames` 的做法）。
- `/v1/audio/transcriptions` 路由存在但**在当前模型下返回空**（装的是 TTS，不是 ASR）
  ⇒ **这条路今天不成立，ASR 更不能接**（与「本轮只接 TTS」正好一致）。
- 引擎用 `Authorization: Bearer <a1x-tts-…>` 鉴权。**这个令牌只从容器 env 读，不写进任何仓库文件。**

**所以「让 Chataxi 获得它的音色」在引擎侧不需要任何改动。** 要改的是**谁去接、按什么口径接**。

### 1.3 决定性发现：CHP 已经在转发一个同机本地模型

读 [`translate.py`](../comfyui-plugin/hamdraw_chp/translate.py) 可以看到：CHP 为了让只懂英文的文本编码器能吃中文提示词，
**自己用 `aiohttp` 去调一个外部 OpenAI 兼容端点**（`translate.url`，出厂默认模型名 `qwen3-0.6b`），
而 `/chp/translate` 是它自己的路由；文档里那条 `translation` 段**只播报能力，从不泄露内网地址**
（`describe()` 原文写着 *never leaks the internal address*）。

也就是说：**「CHP 站在一个非 ComfyUI 的本地模型服务前面，把它包装成 CHP 的接口」在这个代码库里不是新设计，是一个已经跑通的既有模式。**
TTS 与它的差别只有两点：**输出的字节多**、**是流式不是一问一答**。这两点都不改变架构。

### 1.4 三个方案与取舍（回答「接到哪一层」）

| | 方案 0 · 直连 | 方案 1 · CHP 只做发现 | **方案 2 · CHP 转发（推荐）** |
|---|---|---|---|
| 怎么做 | Chataxi 加一张 `custom` / `openai-speech` 卡，地址填 `…:8021/v1/audio/speech` | 文档播报引擎地址 + 音色菜单，happ 读文档后**直连引擎** | happ 只认 CHP；插件把 `/chp/speech` 转发到引擎 |
| 今天的代价 | **约 15 行 catalog**，零新代码 | 中（文档要播报地址，客户端要两套地址/凭据） | 中（插件多一个流式转发路由） |
| happ 要几个地址 | 1（引擎） | **2**（CHP + 引擎） | **1**（CHP） |
| happ 要几个密钥 | 1（引擎令牌）**落在 happ 数据区** | 2（CHP 密码 + 引擎令牌）**引擎令牌同样进 happ** | **1**（CHP 密码；引擎令牌不出那台机器） |
| 音色/语言/采样率从哪来 | 硬编码在 happ 里 | 文档 | 文档 |
| 换引擎（8021→8020、换型号） | 每个 happ 各改一次 | 改文档一处 | **改文档一处，happ 零改动** |
| 局域网外的人能不能蹭到 | 能（引擎直接暴露 + 令牌在客户端） | 能 | 不能（引擎不对外，出题人只有 CHP） |

**推荐方案 2。** 三条理由，按分量排序：

1. **密钥边界**：「本地模型一律经 CHP」最实在的收益不是少写代码，而是**引擎令牌只在 A1X 上**。
   方案 0/1 都会把引擎令牌推进 happ 的数据区 —— 而 Chataxi 自己的规矩是「密钥只在用户明确保存后才写入」
   （`AGENTS.md`）。转发让这条规矩不必破例。
2. **只有一处知道引擎在哪**：将来 0.6B 换 1.7B、换模型文件、换端口，都是**运维在那台机器上改一个设置**，
   三个 happ 一个字节不动 —— 这正是 CHP v2 §1.7「部署参数不进 HTTP」的同一条精神。
3. **有先例**：§1.3。`translate` 已经这么做了一年。

**方案 0 不是错的**，它是「今天就想听见声音」的最短路径（约 15 行）。如果只想快速验证音色好不好听，
先做方案 0 试听、再落方案 2，是合理的顺序；但**不要**停在方案 0 —— 那等于每个 happ 各背一份引擎地址与令牌。

---

## 2 定稿（协议新增）

### 2.1 `spec` **不动**，仍写 `chp/2`；加**第九个顶层键** `speech`

依据是规范自己写的规则（v2 §1.1 规矩 2）：**「顶层键就这八个；未知顶层键客户端必须忽略」**。
这条规则存在的**唯一理由**就是让新插件能加一节而不弄坏已发布的客户端。用在这里正是它的用途。

- **`spec` 保持 `chp/2`** —— 图片侧契约一个字没变，升 `chp/3` 会让还没更新的 Chataxi 的**绘图卡**也跟着报
  「插件比应用新」，那是白挨的伤。
- 插件 `version` 从 **`3.1.1` → `3.2.0`**（加法、向后兼容，走第二段）。
- 加到 `TOP_LEVEL_KEYS`（`tests/test_spec.py:172`）里的是 `speech`，**九个**。

### 2.2 `speech` 段的骨架

```json
"speech": {
  "rules": [
    { "category": "speak", "rule": "txt-2-sph",
      "needs": { "text": true },
      "typical_seconds": 1.2 }
  ],
  "abilities": [
    { "name": "qwen3-tts-0.6b",
      "ready": true, "missing": [],
      "files": { "engine": "qwen3-tts-12hz-0.6b-customvoice-q8_0.gguf" },
      "audio": { "sample_rate": 24000, "channels": 1,
                 "formats": ["pcm", "wav"], "streaming": true },
      "voices": [
        { "id": "vivian",    "label": "Vivian",    "languages": ["zh", "en"] },
        { "id": "serena",    "label": "Serena",    "languages": ["zh", "en"] },
        { "id": "uncle_fu",  "label": "Uncle Fu",  "languages": ["zh", "en"] },
        { "id": "dylan",     "label": "Dylan",     "languages": ["zh", "en"] },
        { "id": "eric",      "label": "Eric",      "languages": ["zh", "en"] },
        { "id": "aiden",     "label": "Aiden",     "languages": ["zh", "en"] },
        { "id": "ono_anna",  "label": "Ono Anna",  "languages": ["zh", "en"] },
        { "id": "sohee",     "label": "Sohee",     "languages": ["zh", "en"] },
        { "id": "ryan",      "label": "Ryan",      "languages": ["zh", "en"] }
      ] }
  ]
}
```

**骨架为什么长这样**（每条都是把 v2 的既有想法平移到语音，不是新发明）：

1. **`rules` + `abilities` 两张表照旧**，含义不变：一条 `rules` 是「客户端**要**什么」（`speak`），
   一条 `abilities` 是「**谁**能答」（一台配好的引擎）。一处引擎、一条能力，今天就是 1 : 1。
2. **音色菜单是手写的 `voices`，顺序即规范**（同 `frames`）：第一个就是默认音色。
   客户端**只选不算**，服务端**成员校验**，未知音色回 `unsupported_voice`。
   `/v1/voices` 是空的，所以这张表**只能**由实现手写并播报 —— 再次印证「不让前端算」这条。
3. **CHP 不约定有哪些音色**（对应 ⑫「不约定支持什么比例与分辨率」）：规范只要求「至少有一个音色」，
   具体清单是**实现的取值**，运维可以在设置里覆盖。
4. **`audio` 是这份能力自己的输出规格**（采样率 / 声道 / 容器 / 支不支持流式），
   客户端**读它、不猜它**。今天引擎固定 24 kHz 单声道。
5. **`files.engine` 用的是引擎自己的模型文件名**，与图片侧 `files.checkpoint` 同一个位置、同一个道理：
   「这台机器上跑的是哪个模型」是可播报的事实，不是秘密。
6. `speech` 段里**任何一层都允许多余字段**（同 v2 §1.1 规矩 3）：写这个字段的 happ 自己读，CHP 播报但不解释。

### 2.3 `endpoints` 加第八个键

§1.6 已经把「地址从文档里读」定为**规则**，所以 `/chp/speech` 的地址**必须**出现在 `endpoints`：

```json
"endpoints": { "info": …, "jobs": …, "job": …, "progress": …, "output": …,
               "cancel": …, "translate": …, "speech": "/chp/speech" }
```

`tests/test_spec.py:277` 那条「endpoints 七个键」的断言**改成八个**（是更新期望值，不是放宽断言）。

### 2.4 IO 规则：扩展模态词汇，加一条 `txt-2-sph`

v2 §1.3 的语法 `<模态> ::= txt | ref | msk | img | glb | 3dgs`，词汇表**本来就与图片无关**
（`glb` / `3dgs` 是给 3D 留的）。语音在本轮加一个字：

```
txt-2-sph       文本 → 语音
```

- `sph`（speech）而不是 `aud`：**说得出它是什么**。将来真有音乐/音效再加 `aud`，两者不混。
- 规范序照旧（`txt` 先）。本轮 `speech` 段**只有这一条规则** —— 对应 v2 §6「不新增第三条规则」的同一条纪律：
  规则不是越多越好，够用就行。

### 2.5 请求体：`POST {endpoints.speech}`

| 字段 | 类别 | 说明 |
|---|---|---|
| `text` | 规则参数，必填 | **要念出来的字**。见下面「为什么叫 `text` 不叫 `prompt`」 |
| `voice` | 规则参数，必填 | 必须是该能力 `voices[]` 里的 `id`；未知 ⇒ `400 unsupported_voice` |
| `language` | 规则参数，可省 | `zh` / `en` / …；省略由实现取默认 |
| `response_format` | 规则参数，可省 | `pcm` / `wav`；省略取该能力 `audio.formats[0]` |
| `stream` | 规则参数，可省 | 省略 = `true`。见 §2.6 |
| `speed` | 规则参数，可省 | 语速倍率；实现不支持就忽略并回显 |
| `chp_params` | 扩展通道 | 有 body 的 POST ⇒ 密码放这里（v2 §1.5 载体表，**无新规则**） |

**为什么叫 `text` 不叫 `prompt`**（这是本轮唯一一处必须讲清楚的命名）：
`prompt` 在 CHP 里带**副作用** —— `rules[].prompt.language: "en"` 会让服务端**在提交路径上自动翻译**
（`translate.py` 的 `ensure_english`）。TTS 的输入是**要原样念出来的话**，
接上翻译规则会把中文念成英文。**字段名在这里是承重的**，不是风格问题。
选 `text` 还有第二条理由：它与模态名 `txt` 同字，与 v2 自己的构词法一致
（`category` ← 规则的 `category`，`resolution` ← 帧表的 `resolution`，`text` ← 模态的 `txt`）。
**speech 的文本永不翻译**，规范里写死这一句。

**为什么不直接做成 OpenAI 的 `input`**：那会让 CHP 的 schema 由外部 API 定义，
而 CHP 的既有做法是把 schema 放在自己的 `input_schemas` 里播报（图片侧就是这么做的）。
本轮**保持 CHP 自己的词汇**，客户端映射一次即可（§3.2 会发现代价其实只有一行）。

`speech` 段同样播报一份 `input_schemas`：`"txt-2-sph/v1"`。

### 2.6 传输：**一条路由，`stream` 决定内容类型**（不套作业模型）

这是本轮最需要说明的一个决定，因为它给契约加了**第二种传输**。

| | 图片（今天） | 语音（本轮） |
|---|---|---|
| 形态 | 提交作业 → 轮询 → 取件 | **一次请求，边合成边回字节** |
| 为什么 | 一张 9:16 成品图要 20~45 s，必须有进度、排队、取消 | 一句话 1~2 s，**而且慢的正是首字节** |
| 路由 | `/chp/jobs` 等五个 | `/chp/speech` 一个 |

**不套作业模型**，三个理由：

1. **Chataxi 要的就是流式**。它的朗读链路是「逐段 PCM 进播放队列」
   （`tts.js` 的 `streamPcm` / `pcmStreamProfile`），这是对话体验的底线。
   套作业模型 = 合成完 → 取件 → 才能播，白丢 1 个 RTT 加整段合成时间。
2. **作业模型那一套在这里全是死重**：排队位次、`progress`、`cancel`、`output/{index}`、
   `typical_seconds` —— 为 1.5 秒的音频付这些，是抄形状不抄理由。
3. **引擎本来就是这么说话的**（`stream: true` → 分块 PCM），转发是最短的路。

**但流式不是唯一选项**：`stream: false` ⇒ 一次返回整个 `audio/wav`。
同一个端点、两种内容类型，正是引擎已有的行为，白送。
（这一条也让「只懂 POST 一次拿一坨」的第三方工具能用 —— 与 v2 对待第三方工具的立场一致。）

| | `stream: true`（默认） | `stream: false` |
|---|---|---|
| `Content-Type` | `audio/pcm` | `audio/wav`（或该 `response_format` 对应的容器） |
| 响应头 | `X-Sample-Rate: 24000`、`X-Channels: 1` | 同左 |
| body | 裸 s16le 分块 | 整个文件 |

**错误一律是 JSON**，且在开始写 body **之前**就用状态码定了（引擎也是这个行为）——
客户端的判据是「先看状态码，非 2xx 就按 JSON 解析」。

### 2.7 新增错误码

沿用 v2 §6 的错误表与 `ERROR_STATUS` 机制，只加三条：

| 码 | HTTP | 文案 |
|---|---|---|
| `unsupported_voice` | 400 | 这台引擎没有这个音色，请从信息接口 `speech.abilities[].voices` 里取 |
| `no_engine` | 409 | 没有可用的语音引擎，请先在 CHP 插件配置节点里填好语音服务地址 |
| `speech_failed` | 502 | 语音引擎没有正常应答 |

**关键一条**：引擎侧的任何失败（连不上 / 令牌错 / 引擎 500）**都不许把引擎地址或引擎令牌漏给客户端**，
统一收敛成上面三条，明细只进那台机器的日志。这是 `translate.py` 已经在遵守的规矩。

### 2.8 部署参数（`hamdraw_settings.json`，HTTP 上永远看不见）

照 v2 §1.7 的四档分类与 `translate` 的既有形状：

```json
"speech": {
  "url": "http://127.0.0.1:8021",
  "token": "",
  "engine": "qwen3-tts-12hz-0.6b-customvoice-q8_0.gguf",
  "voices": ["vivian", "serena", "uncle_fu", "dylan", "eric",
             "aiden", "ono_anna", "sohee", "ryan"],
  "sample_rate": 24000,
  "timeout": 60.0
}
```

| 档 | 键 | 不给会怎样 |
|---|---|---|
| **必要** | `url` | 给不出 `no_engine`（403/409），`speech.abilities` 播报 `ready: false` |
| **必要（引擎要）** | `token` | 引擎回 401 ⇒ 同样收敛成 `no_engine` |
| **有可用默认** | `voices` / `sample_rate` / `timeout` | 用出厂值照跑；`voices` 是**这台机器上引擎支持的那几个名字**，换引擎才要改 |
| 只在特殊机器上改 | `engine` | 只用于播报（`files.engine`），不影响跑 |

环境变量照 `HAMDRAW_*` 的既有拼法加两个：`HAMDRAW_SPEECH_URL`、`HAMDRAW_SPEECH_TOKEN`。
**`token` 与现有的 CHP 密码同一个信任级别**（都在 `hamdraw_settings.json`），但**两者是两把不同的钥匙**：
前者是「happ ↔ CHP」，后者是「CHP ↔ 引擎」。

---

## 3 插件侧改动

### 3.1 新模块 `hamdraw_chp/speech.py`（照 `translate.py` 的形状写）

| 职责 | 与 `translate.py` 的对应 |
|---|---|
| `describe()` → 文档里的 `speech` 段 | `translate.describe()` 给的 `translation` 段 |
| `validate(body) -> (text, voice, format, stream)`，音色成员校验在这里 | `translate.ensure_english()` 的位置 |
| `async def speak(...)`，用 `aiohttp` 转发到 `settings.speech()["url"]` | `_ask()` |
| 引擎错误 → 三条 CHP 错误码，地址与令牌**只进日志** | `describe()` 的 *never leaks the internal address* |
| 出厂音色表（手写） | `settings.RECOMMENDED_CHECKPOINT` 的同性质 |

`capabilities.py` **只多一个参数**，不碰任何现有逻辑：

```python
def document(*, files_of, authorized, auth_required, translation, speech=None, ...):
    ...
    if speech is not None:
        payload["speech"] = deepcopy(speech)
```

`ENDPOINTS` 加一个键（`"speech": f"{API_ROOT}/speech"`）—— 与 §1.6「路径写在一个模块常量里」一致。

### 3.2 `server.py`

- 新路由 `routes.post(f"{API_ROOT}/speech")(speech_endpoint)`。
- 鉴权**复用 `_authorized()`**：POST 有 body ⇒ 自动走 `chp_params.password`；`Authorization` 头也照收。
  **一行鉴权代码都不新写。**
- 流式回写用 `web.StreamResponse` + `await response.write(chunk)`；
  `Content-Type` 与 `X-Sample-Rate` 在 `prepare()` 之前设好。
- `ERROR_STATUS` 加三条（§2.7），`ERROR_MESSAGES` 加对应文案 —— `/chp/info` 的 `errors` 自动多播三条。

### 3.3 打包产物名与网站下载位

**不动。** 与 v2 的处置一致：包名/内嵌副本站位绑定在**正式发布**那一次动作里（本计划不含发布）。

---

## 4 Chataxi 侧改动

### 4.1 `app/services/catalog.js` —— 加一个 TTS 家族

```js
{
  id: "chp-speech", name: "CHP 语音", description: "ComfyUI Haminn Protocol：连接后由插件自报可用的音色",
  type: "chp-speech", protocol: "chp-speech", auth: "bearer", keyOptional: true,
  customEndpoint: true, discovery: "chp", streaming: true, models: [], voices: []
}
```

`endpoint` 留空串，理由与 `imageFamilies` 里那条完全一样（预设地址只在卡片初值那一层给）。

### 4.2 `app/services/model-services.js` —— 加一条发现分支

CHP 那套地址归一的辅助函数（`chpBase` / `chpOrigin` / `chpAbsolute` / `chpUrl` / `chpJobUrl`）**已经是通用的**，
`chpInfo()`（两条候选 + 「地址通了但不是 CHP 文档」与「根本没连上」分开报）**也已经是通用的**。所以：

- `discover()` 里加一层：`kind === "tts"` 且 `definition.discovery === "chp"` ⇒ `discoverChpSpeech(...)`，
  否则走原来的 `discoverTts(...)`。
- `discoverChpSpeech(service, definition)`：
  1. `chpInfo(service.endpoint, headers)`；`auth.required && !auth.authorized` ⇒ 报「密码不正确」（同 `discoverImage`）；
  2. 读 `document.speech`；**没有这一节就报「插件没有语音能力，请升级插件」**（照 `discoverImage` 报「没有 render」的既有做法）；
  3. `service.voices = abilities[0].voices`；`service.models = [{ id: "speak", name: …, audioStreaming: true, formats: audio.formats }]`；
  4. **只存 `service.endpoints` 与 `service.chpOrigin`**（地址从文档读，v2 §1.6 是规则）——
     音色、采样率、容器全部进卡片，`resolveTts` 从卡片就能拿全。
- `resolveTts()`：`family === "chp-speech"` 时，`endpoint` 取值改成
  `chpAbsolute(service, service.endpoints.speech)`。**三行。**

### 4.3 `app/services/tts.js` —— 复用现有流式链路，只加分支

| 函数 | 改动 |
|---|---|
| `headers()` | **不改**：`Authorization: Bearer <CHP 密码>` 是规范允许的载体（v2 §1.5），所以 `chp_params` 这条路本轮不用 |
| `requestBody()` | 加一条分支：`{ text, voice, language, response_format, stream: bool }` |
| `pcmStreamProfile()` | 加一条：`{ kind: "raw", format: "pcm", sampleRate: 卡片里的 audio.sample_rate }` |
| `endpoint()` | 不改（地址已由 `resolveTts` 解析成绝对 URL） |
| `streamPcm()` / `audioPayload()` | **不改** —— `kind: "raw"` 那条路原样吃裸 PCM |

**这就是方案 2 在客户端侧的真实代价：一个 catalog 条目 + 一条发现分支 + 两个 `if`。**
因为 A1X 引擎与 `openai-speech` 的形状本来就一致（24 kHz 单声道裸 PCM），
Chataxi 那条已经调好的流式播放链路**一行都不用重写**。

### 4.4 卡片与文案

- `app/features/model-single-editor.js`：`defaultEndpoint(kind)` 目前只给 `image` 预填 `CHP_DEFAULT_ENDPOINT`；
  改成「`chp-speech` 家族也预填同一个地址」（**同一台机器上的两个槽**）。
- **新增的中文文案必须同时补英文**（项目硬规矩）：`app/data/i18n-en.js` 加
  `"CHP 语音"`、那句 `description`、以及「插件没有语音能力，请升级插件」等错误文案。

### 4.5 一处已知的将就（记下来，不返工）

happ 的数据区把「绘图」与「朗读」分成两个槽（`image-profiles` / `tts-profiles`），
所以用户**会在两个地方各配一次同一台 CHP**（同样的地址、同样的密码）。
本轮**接受这个将就**（不改数据模型，风险大收益小）。
真要顺手，就在语音卡的地址栏加一个「用绘图卡那台机器」的按钮 —— 但那是**另一件事**，不在本轮。

---

## 5 明确不做

- **不做 ASR / 视频 / 图片以外的任何类型**（业主 2026-10-12）。引擎的 `/v1/audio/transcriptions` 今天返回空，
  技术上也不成立 —— 所以这一条不是纪律，是事实。
- **不把 TTS 引擎搬进 ComfyUI**（§1.1）。
- **不新增第二条 speech 规则**（不做 `sft`：声音到声音，不做 `ref-2-sph`：音色克隆）。引擎有 `/v1/audio/speech-to-speech`，
  但**本轮不碰** —— 与 v2「不新增第三条规则」同一条纪律。
- **不做 `speech` 的作业模型**（§2.6）。
- **不做多引擎并行播报**：`abilities` 的形状允许多条，但本轮只配一台（手写表不预留）。
- **不把引擎地址或令牌播报进文档**（§1.4 方案 2 的前提）。
- **不动 `spec` / `/chp` 路径 / `PLUGIN_ID` / `HAMDRAW_*` 既有名字**（v2 §1.9 的既有定稿）。
- **不动 hamdraw happ 本身**：它是画图工具，不需要朗读。
- **不打发布包**，不改网站下载位（§3.3）。

---

## 6 阶段与验收判据

| 阶段 | 内容 | 判据（可执行） |
|---|---|---|
| **S0** | 规范：`chp-spec.md` 加 `speech` 一节 | 全文含 §2.2/§2.3/§2.4/§2.5/§2.6/§2.7 的全部条文；`endpoints` 写成八键；「speech 文本永不翻译」一句在 |
| **S1** | 插件：`speech.py` + `settings.speech()` + `document(speech=…)` + `ENDPOINTS` | `grep` 得到 `HAMDRAW_SPEECH_URL`；`settings.speech()` 对空 url 返回 `{"available": False}` 且不抛 |
| **S2** | 插件：`/chp/speech` 路由（流式 + 整包两种） | 离线用例：`stream:true` 的响应是 `audio/pcm` 分块；`stream:false` 是 `audio/wav`；坏音色 `400 unsupported_voice`；错密码 `401` |
| **S3** | 插件：离线测试与变异 | 见下表；**每条新断言都被至少一次变异按名字抓住** |
| **S4** | A1X 真机验收（转发真引擎） | §7 的七条 |
| **S5** | Chataxi：catalog + 发现 + tts 分支 + 文案 | `node tools/verify.mjs` 全绿；新增「speech 段缺失 ⇒ 报升级插件」的断言 |
| **S6** | 设备热更新 + 真机朗读 | 读回 sha256 MATCH；**朗读一句话真的出声**（需业主在卡片上自己填地址与密码，见 §7 注） |

### S3 的断言与变异（照既有 `.mutate_*.py` 手法：**按名字命中**才算抓住）

| 断言 | 变异（必须报红） |
|---|---|
| `document` 有第九个键 `speech`，且 `endpoints` 是八键 | 少一个键 |
| `speech.rules` 恰好一条、`rule == "txt-2-sph"`、`signature` 由模态拼出 | 手写一份 `signature` 覆盖 / 把 `sph` 写成 `img` |
| 每个 `ability` 至少一个音色（**装配期断言**，照 `check_frames`） | 删掉全部音色 / 留一个空 `voices` |
| 默认音色 = `voices[0]`（不是自己算的常量） | 把默认值改成写死的字符串 |
| 帧外/清单外音色 ⇒ `400 unsupported_voice` | 把成员检查放宽成「非空字符串即可」 |
| 引擎 401 / 连不上 ⇒ `no_engine`，且**响应里不含 url 与 token** | 把引擎原话透传出去 |
| 引擎地址与 token **不在文档任何位置** | 把 url 塞进 `speech.abilities[].files` |
| `speech` 的文本**不经过 `translate`**（给中文，读回的还是中文） | 让 `speak` 复用 `ensure_english` |
| `stream:false` 时 `Content-Type` 是 `audio/wav` | 两种都回 `audio/pcm` |

---

## 7 S4：A1X 真机验收（七条）

按技能 `a1x-comfy-device` 的闭环：**逐文件传、清 `__pycache__`、重启 `minimax-h3-comfy`、两侧 `sha256sum` 逐一对照**。

1. `GET http://192.168.124.31:8189/chp/info`：多出 `speech` 段；`endpoints` **八个**键；
   `spec` **仍是 `chp/2`**；`plugin.version == "3.2.0"`；`errors` 里多出三条新码。
2. `speech.abilities[0].voices` **恰好 9 条**，且顺序是设置里那份；
   `audio.sample_rate == 24000`、`streaming == true`。
3. **流式**：`POST /chp/speech`，`{text:"你好，这是一次测试。", voice:"vivian", stream:true}`，
   带 `chp_params.password`（**不带 Authorization 头**）⇒
   `Content-Type: audio/pcm`，**首字节在 1 s 内到达**（量 TTFB），总字节数与文本长度相称。
4. **整包**：同一次请求改成 `stream:false` ⇒ `Content-Type: audio/wav`，body 以 `RIFF` 开头。
5. **九个音色逐个**跑一遍，全部 2xx 且字节数非零（这是「Chataxi 能不能获得它的音色」的直接答案）。
6. **拒绝类**：`voice:"nobody"` ⇒ `400 unsupported_voice`；密码写错 ⇒ `401`；
   把 `speech.url` 指到一个空端口 ⇒ `409 no_engine`，**且响应体与文档里都找不到那个地址**。
7. **没有旁效**：`/chp/info` 的 `rules` / `abilities` 与图片侧**逐项与升级前一致**（加法不许碰旧的那两表）。

> **注（必读）**：真机上要让 Chataxi 出声，需要**业主自己在朗读槽配一张 CHP 卡并保存密码**。
> 那张卡是他的数据；按既有规矩（`AGENTS.md`：密钥只在用户明确保存后写入），
> **不代填、不把 CHP 密码或引擎令牌写进 happ 数据区**。
> 验收时用**只存在内存的探针卡片**（`discover(..., {persist:false})`）证明链路通，再由他保存。

---

## 8 版本与落地顺序

| 物 | 现在 | 改成 | 理由 |
|---|---|---|---|
| `spec` | `chp/2` | **`chp/2`（不动）** | 图片侧契约没变；加一节是加法 |
| 插件 | `3.1.1` | **`3.2.0`** | 加法、向后兼容，走第二段 |
| hamdraw 仓 | 当前值 | 升第三段（四处同步照旧） | 插件源码在 hamdraw 仓里 ⇒ 这个仓有源码改动 |
| chataxi 仓 | 当前值 | 升第三段（同上） | 改了 `catalog.js` / `model-services.js` / `tts.js` / i18n |
| PoseGi | 不动 | **不动** | 与语音无关 |

```
S0 → S1 → S2 → S3 → S4（A1X 真机）→ S5 → S6（推设备）
```

**S4 通过之前不碰设备**，避免在设备上反复试错（v2 的同一条纪律）。
正式发布（GitHub release + 网站安装包 + 下载位）是 S6 之后的**独立动作**，本计划不含。

---

## 9 风险与回滚

| 风险 | 处置 |
|---|---|
| 流式转发在 ComfyUI 的 aiohttp 里首字节被拖慢 | S4 第 3 条**量 TTFB**；若明显劣于直连，退到 §1.4 方案 1（文档播报地址、happ 直连）——**退路是设计好的，不是临时的** |
| ComfyUI 重启会带走语音（多了一个耦合） | 已知并接受；与 `translate` 今天的处境完全一样 |
| 引擎忙 / 显存被图片任务占住 | 引擎在**另一个容器**里，不与 ComfyUI 抢显存；`timeout` 兜底 |
| happ 里存着旧卡（没有 speech 那节） | 报「插件没有语音能力，请升级插件」，**不是静默不出声** |
| 推理器把 `speech` 段读成空数组却不报错 | S5 加一档断言：`speech` 缺失 / `voices` 为空两条分支各一条用例 |
| 插件回滚 | 宿主 `.bak-<日期>/` 拷回 + 重启容器 |
| happ 回滚 | 热更新前的版本仍在设备上，直接回推 |

---

## 10 两处要业主定的（其余按本文执行）

1. **`/chp/speech` 的 body 字段名**：本文定 `text`（理由 §2.5）。
   若你更希望「任何懂 OpenAI `/v1/audio/speech` 的东西拿来就能用」，改成 `input` 也行 ——
   差别只在客户端那一行，但会失去「字段名与模态 `txt` 同字」这条内在一致。
2. **方案 2 vs 方案 1**（§1.4）：本文推荐**转发**，理由是密钥边界与「只有一处知道引擎在哪」。
   若你认为「插件不该转发大字节流」，方案 1 也自洽，代价是 happ 要拿两个地址、两份密钥。
