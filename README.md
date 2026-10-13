# CHP 插件（CHPCP）— Haminn 综合入口程序的 ComfyUI 后端

CHP 是 **Consolidated Haminn Portal**（中文「Haminn 综合入口程序」）；这个目录是它的**参考实现**，装在 ComfyUI 里，名字叫 `hamdraw_chp`（这一半自称 **CHP 插件**，简称 **CHPCP**）。

任何客户端（HamDraw 本体、其他开发者的工具、只会发 curl 的脚本）只要认下面这一个 HTTP 契约，就能用你已经装好的 ComfyUI 出图，**不需要自己导出工作流 JSON** —— 五个场景的图都内置在插件里。

3.2.0 起这个契约多了一条**语音**：同一台机器上已经装好的 TTS 引擎也照同样的形状播报出来，一个请求直接回音频字节。`spec` 仍是 `chp/2`（图片侧一个字没变），新的一段在第九个顶层键 `speech` 里，见「语音（TTS）」一节。

- 规范标识：`chp/2`（响应体里的 `spec`）
- 接口根路径：`/chp`（**路径不版本化**；地址一律从文档的 `endpoints` 里读，客户端不要自己拼）
- 契约文本：[`plans/chp-spec.md`](../plans/chp-spec.md)；落地计划：[`plans/chp-v2-plan.md`](../plans/chp-v2-plan.md)
- 目录：把 `hamdraw_chp/` 整个放进 ComfyUI 的 `custom_nodes/`

**新客户端第一步先调信息接口**（**要钥匙** —— 前提是配了至少一把；一把都没配的部署是公开的，见「安装」第 4 步）：它一次给出这台机器上**有哪些场景、每个场景收什么请求体、背后是哪几个模型文件、每个场景能出哪些画幅、这条场景的编码器认不认中文、有没有语音能力（有哪些音色）**，以及**这把钥匙能用到的部分** —— 没带或带错就是 `401`，不再靠 `auth.authorized` 那一句「你带的密码不对」。

## 安装

1. 拷贝目录：

   ```bash
   cp -r hamdraw_chp  <你的 ComfyUI>/custom_nodes/hamdraw_chp
   ```

   容器部署时把这个目录挂进去即可（宿主路径 → 容器 `custom_nodes/hamdraw_chp`），改完重启 ComfyUI。

2. **没有额外依赖**，只用 ComfyUI 自带的 `aiohttp` / `folder_paths` / `execution`；也不用改 `requirements.txt`。

3. 重启后在 ComfyUI 节点菜单里搜 **HamDraw**，会看到三个节点：

   | 节点 | 用途 |
   |---|---|
   | **HamDraw 配置 (Config)** | **用户唯一需要操作的节点**：设密码 + 选三套 checkpoint + 参考图重绘/纯文生图那两路的三个槽位与各自的加速 LoRA + 翻译后端地址 |
   | HamDraw 输入 / 输出 | 输入那个是给人看的观察窗口；输出那个是内置图引用的节点类。插件**不接受**用户自备的自定义工作流 |

4. 想确认装好了：

   ```bash
   curl -s http://127.0.0.1:8188/chp/info
   ```

   返回 JSON，且 `spec` 为 `chp/2`、`plugin.version` 是你期望的那一版（当前 **3.2.0**）、每个能力的 `ready` 为 `true`，即成功。

   信息端点**也要钥匙**（前提是配了至少一把）。没带或带错 ⇒ `401`，而那个响应体里多一个 `spec` —— 它自证“这里是 CHP，只是钥匙不对”，客户端因此不必靠猜 URL 去分辨“地址填错了”和“钥匙不对”。这两种情况给用户的下一步动作完全不同。

   **一把钥匙都没配时（配置节点的密码为空、且没有 key 表）服务是公开的**，`/chp/info` 照旧 `200` 并给出全部能力 —— 这是既有行为，老用户零改动。

   **插件版本只有一个出处**：`hamdraw_chp/version.py` 的 `__version__`。发布包名由 `tools/package-plugin.py` 从它派生（`release/hamdraw-comfyui-plugin-v<ver>.zip`），`/chp/info` 上报的 `plugin.version` 也是它 —— 两个数字同源。**happ 里不再有内嵌副本**（2026-10-13 起 CHP 从三个 happ 里彻底分离，插件只从官网取），所以这条版本线从此只属于本仓。

## 配置（HamDraw 配置节点）

| 字段 | 说明 |
|---|---|
| `password` | **访问密码**，也是**默认钥匙**：填了就只有带对它的请求能用；**留空 = 不校验**（前提是也没有 key 表 —— 见下）。它的权限是全部场景。 |
| `fast_checkpoint` | 快速生图用的模型，默认 `DreamShaper8_LCM.safetensors` |
| `inpaint_checkpoint` | 局部重绘用的模型，可填 `(same as fast)` 复用上一个 |
| `upscale_checkpoint` | 图像放大用的模型，同样支持 `(same as fast)` |
| `qwen_unet` / `qwen_text_encoder` / `qwen_vae` | `render` 与 `generate` 两路共用的**三个槽位**（diffusion model / 文本编码器 / VAE），与上面的 checkpoint 互不影响 |
| `render_lora` / `render_lora_strength` / `render_sigmas` | `render` 那一路的**加速档案**（见下节），出厂留空 = 不加速 |
| `generate_lora` / `generate_lora_strength` / `generate_sigmas` | `generate` 那一路的加速档案，同样出厂留空 |
| `translate_prompts` / `translator_url` | 是否启用自动翻译，以及翻译后端地址 |

**三套 checkpoint 其实是同一个槽位加两次覆盖**：`inpaint` / `upscale` 留空就回落到 `fast` 那个，所以只填一次也能跑那三个场景；填了就用自己那个。`render` / `generate` 那两路要三个文件都填齐才算 `ready`，只填一半时信息接口会把它们标成 `ready: false` 并在 `abilities[].missing` 里点名缺哪个槽位。

### 加速档案：省时间的那条路（部署调参，出厂留空）

默认的 `render` / `generate` 走满步数（30 步左右），单张约 6.5 秒固定开销 + 每步 1.16 秒。给某一路配一份**加速档案**就换成"少步数 + 显式 sigma 表"：

```json
"accelerators": {
  "render":   {"lora": "acc_pdd_4step_comfy.safetensors", "strength": 1.0,
               "sigmas": "1.0, 0.9169867038726807, 0.7861579060554504, 0.5494909882545471, 0.0"},
  "generate": {"lora": "acc_viggle_6step.safetensors",    "strength": 1.0,
               "sigmas": "1.0, 0.9375, 0.875, 0.75, 0.5, 0.25, 0.0"}
}
```

三条规矩：

- **`sigmas` 的长度必须等于步数 + 1**，对不上整条档案不生效（那一档步数下的 sigma 表是模型训练时就定下的，凑不出来）。步数由长度反推，客户端一个 step 都不用发。
- **只有配对的那个 LoRA 真的在 `models/loras` 里，档案才生效**。配了却没装不会报错，只在日志里留一行，然后**安静地退回满步数** —— 一台机器换硬盘不该让出图直接失败。
- 加速只在**那一档步数**上成立，所以档案是按类别分的：`render` 可用 4 步 PDD，也可用 6 步 Viggle；`generate` 可用 6 步 Viggle。实际采用哪套由各类别自己的加速档案决定。

档案**只在部署侧写**：一个"4 步蒸馏 LoRA"的文件名只对装了它的那台机器成立（同 `translate.url` 与 `cache_dtype`）。

配置写在 `custom_nodes/hamdraw_chp/hamdraw_settings.json`（原子写、可手工编辑）；也可以直接用环境变量 `HAMDRAW_PASSWORD` 覆盖密码（适合容器/CI）。

**部署调参（手工编辑设置文件）**：`families.qwen_image_21` 下三项。`cache_device` / `cache_dtype` 控制 Qwen 的 KV 缓存（默认 `auto` / `default`，即模型作者的建议值）；**显存吃紧的机器**改成 `cache_dtype: "int8"`。`reference_edge` 是**参考图的编码预算**（原生引擎管它叫 `reference_resolution`）：参考图先按**面积**缩到“约 edge² 像素”再进编码器（`ImageScaleToTotalPixels`，**保持原图自己的比例**, 对齐到 32），默认 `1024`（核心节点自己的默认值），想省算力可以写小；**它不影响出图画幅**。参考图的**比例永远保留**：画幅由采样 latent 决定，参考图只说“长什么样” —— 按硬目标框去缩会把定妆照拉变形。插件不会替某台机器做这些假设 —— 环境变量 `HAMDRAW_TRANSLATE_URL` / `HAMDRAW_TRANSLATE_MODEL` / `HAMDRAW_TRANSLATE_DISABLED` 同理。

`HAMDRAW_*` 环境变量、`hamdraw_settings.json`、`hamdraw-comfy-settings/v1` 这些**盘上数据的格式标识故意没跟着协议改名** —— 它们是格式标识，不是产品名，改名只会让每台机器都要重新配一遍。

**钥匙不对会怎样**：请求在**入队之前**就被拦下，返回 `401 unauthorized`，**不会生图**。客户端拿到的是一句可读的中文提示，而不是一张画错的图。

**钥匙不够会怎样**：如果这台机器配了**按场景授权**的 key（`chp_keys.json`），而请求的 `category` 不在这把 key 的授权集里，返回 `403 forbidden_capability`。这道判定在**执行层**、每次提交都做一遍 —— 信息文档里少列几项只是为了让界面不出现点不动的选项，**它不是权限**：知道 `category` 名字的人可以直接 POST。

## 五个场景（`category`）

`category` 就是请求体字段名，取值只有这五个，**没有别名**：`fast` / `inpaint` / `upscale` / `render` / `generate`。

| `category` | 规则 | 参考图 | 画幅（帧表，首项即默认） | 步数枚举与默认 | 参考权重默认 | 提示词语言 | 说明 |
|---|---|---|---|---|---|---|---|
| `fast` | `txt-ref-2-img` | 要 | 1:1 `512x512`；4:3 `576x384`；3:4 `384x576` | 2 / 4 / 6 / **8** | 0.55 | **只认英文** | 把画布当参考图重绘一张速写稿 |
| `inpaint` | `txt-msk-ref-2-img` | 要（+蒙版） | 同 `fast`（蒙版必须与画布同尺寸） | 4 / **6** / 8 / 12 | 0.30 | **只认英文** | **只重画白色蒙版区域**，其余原样保留 |
| `upscale` | `txt-ref-2-img` | 要 | 1:1 `1024x1024`、`2048x2048` | 4 / **8** / 12 / 16 / 20 | 0.75 | **只认英文** | 参考图按**原分辨率**（上限 1024）直接编码；只有目标大于上限时才 latent 放大。**不要退回“先缩到 512 再放大”**——那等于在采样器看到参考图之前先模糊它一轮，渲染出来会发软、像被重新演绎过。 |
| `render` | `txt-ref-2-img` | **要** | 9:16：`768x1344`（中，默认）/ `512x896`（低）/ `896x1568`（高） | 4 / 6 / 8 / 12 / **20** | 0.95 | **英文更佳**（中文也吃） | **给定一张图重新生成**：给张图（定妆照、姿势骨架、随手一张照片）加一句描述，重画成一张成品图 —— 构图由参考图带来。模型是 Qwen-Image 2.1（官方 INT8）的 unet + clip + vae 三件套。 |
| `generate` | `txt-2-img` | **不收** | 9:16：`768x1344`（中，默认）/ `512x896`（低）/ `896x1568`（高） | 6 / 8 / 12 / **20** | — | **英文更佳** | **纯文字生成**：只给一句描述，从零画一张成品图，一个字节的输入图都不带。**没有定妆照时走这一条**（Chataxi 就是这么用的）。 |

**步数只管"没配加速档案"的那条路**：客户端不发 `ext_params.step` 时，配了加速档案的场景走**档案自己那一档**（本机 `render` 配 Viggle 时为 6 步），没配的走上表里的默认值（20）。枚举里留着 4 与 6 就是为了让 PDD / Viggle 加速档案的步数合法（见「加速档案」一节）。

**`render` 与 `generate` 是两条规则、两个类别，不是同一条规则的两个用法**（2026-10-01 分开）。理由是"有没有参考图"决定的是**图怎么搭**：一条走参考条件生成，一条从空 latent 起步，两者连节点都不一样。把它做成"同一条规则，带不带图随你"会让客户端只能靠**试探**去发现这件事 —— 分开之后，客户端从规则名本身就看得出来（`txt-ref-2-img` 里有 `ref`，`txt-2-img` 里没有），而服务端也会**明确拒收**：给 `generate` 发 `image_base64` 回 `400 bad_image`，文案就是"这个场景不收参考图"。

**就绪状态与画幅各归各的场景**：两条场景可以落在同一个模型文件组上（本实现里就是同一组 Qwen 三件套），也可以落在两组上；`abilities[].frames` 按 `category` 分开列，客户端按需读。

**画幅就是这张表，没有第二条路。** 每个场景的 `frames` 是手写的，顺序是规范的一部分：第一档就是**省略 `resolution` 时的默认**。请求里的 `resolution` 是一个**字符串**（`"768x1344"`），只能逐项命中那张表，否则 `400 unsupported_size`。没有“域”，没有“这个比例合法但不在清单里”，也**没有需要客户端自己算的东西** —— 先把 `ratio` 列给用户选，再列该比例下的 `resolution`，两步零算术。

`"9:16"` 是**标签不是算出来的比例**：`768 × 1344` 的精确比是 4:7，叫它 9:16 是作者定的类目名（和相机的画幅档位一个道理）。客户端**只显示、不反推**。

**`render` / `generate` 的三档是按 Qwen-Image 2.1 自己的竖幅档位定的**（2026-10-01，业主：「分辨率改用 Qwen 2.1 推荐的 9:16 的档位」「只是 happ 要迁就 qwen2.1，不是相反」）。Qwen 2.1 公布的两档竖幅是 `768×1344`（1K）与 `1536×2688`（2K），两条边的比是 4:7；2K 那条的高是 2688，远超 16 GB 卡能舒服跑的上限，所以三档**按同一个 4:7 几何**取：中就是官方 1K 原样、低 `512x896`、高 `896x1568`（业主定的上限 1600 之内、下限 500 之上）。三条边都是 16 的倍数（Qwen 的 VAE 压缩倍率）。默认是第 0 条 ⇒ **中档**；**加档一律往该档的数组末尾追加**，往前面插一条会让每个客户端的默认画幅一起换掉。其余比例整条删掉：两个客户端要的都是竖幅，而"菜单越短、越不容易选错"。

**推荐模型**：DreamShaper8 LCM 系列（512 分辨率通常 1 秒左右出图）。`fast` / `inpaint` 建议就用它，不必换；`upscale` 用能接受 512 参考图、输出 1024/2048 的模型即可。`render` / `generate` 走 Qwen-Image 那一族，与前三套的 checkpoint 完全独立。

### 语言：谁认中文，由场景自己报

`fast` / `inpaint` / `upscale` 是 **SD1.5 + CLIP-L** 结构，文本编码器只吃英文；`render` 的编码器是 **Qwen3-VL**，中文是它的母语。这不是猜的，是两条独立证据：

- 官方口径：Qwen-Image 系支持中英双语提示词，SD1.5 / SDXL 那套 CLIP-L 不支持。
- 真机实测：固定 seed 与参考图，只换提示词跑四单 `render`，比较逐像素平均差。**中文 vs 它的英文译文 12.38，中文 vs 无关提示词 21.40，中文 vs 空提示词 27.73**——中文把画面带到了它英文译文去的地方，噪声做不到这件事。

于是每个场景的 `prompt.language` 是 `"en"` 或 `"any"`，客户端**不要自己写死**。

**但界面上一律建议写英文**，这正是 HamDraw 两个提示词输入框里的那句 `英文可以获得更佳效果`：`"en"` 的场景不过翻译这一道，就没有译错的余地；`"any"` 的场景写英文也照样走通，只是那并不是唯一走法。

### 翻译：推荐流程，不是规则

`prompt.language` 为 `"en"` 的场景，如果提示词**含非 ASCII 可打印字符**（中文、俄语、希腊语、阿拉伯语、泰语都算），插件在**提交时自己翻**：

```
提交 → 需要翻? ─否→ 用原文建图
              └是→ 查翻译记忆库 ─命中→ 用译文
                              └未命中→ 调翻译后端 → 成功则存库并用译文
                                                    └失败→ 用原文建图(任务不失败)
```

- 客户端**可以**先调翻译接口把译文显示给用户，也可以什么都不做 —— 什么都不做也不会把中文喂进只认英文的编码器。
- **判据是“是不是全 ASCII”**，不是“有没有中文”：CLIP-L 对西里尔/希腊字母一样两眼一抹黑，只看中日韩会让它们原样过去变成噪声。
- 记忆库落盘在插件目录的 `hamdraw_translations.json`，重装、重启都不丢。**键 = 原文 + 目标语言**：一条翻译是语言事实，与哪个引擎翻的无关；引擎与提示词版本作为旁注记下来（将来换更好的引擎重刷时按它筛），不进键。
- 后端只要求 **OpenAI 兼容的 `POST {url}/v1/chat/completions`**（llama.cpp / vLLM / Ollama / 各家云 API 都行）。**默认地址是空的，也就是关闭** —— 插件不替任何部署写死一个地址。

### `ref_strength` 是唯一的权重入口

它是“**参考图权重**”：越高越贴近你画的原稿，越低越放手重画，值域 **0.05–0.95**（越界会被夹到边界并在 `job.ref_strength` 回显，不报错）。至于实现怎么做到，是各家族自己的事：

- 图生图家族（`checkpoint`）把它换算成去噪强度：`denoise = clamp(1 - ref_strength, 0.05, 1.0)`；
- 参考条件生成家族（`qwen_image_21`）没有可保留的初始 latent，改成**把参考图本身柔化**：越高越原样交给编码器，越低肢体轮廓越发散。

两种机制都满足“越大越贴近”，所以都合规，客户端滑杆逻辑完全一样。

## HTTP 契约

`endpoints` 是**规则不是建议**：把用户填的地址原样当信息接口请求一次；若它不是 CHP 文档、且地址里没有路径，再试一次推荐的 `/chp/info`；两次都不成就是“这个地址不是 CHP 服务”。拿到文档之后，**其余地址全部从 `endpoints` 里读**，不要自己拼。

| 键 | 值 | 鉴权 | 说明 |
|---|---|---|---|
| `info` | `GET /chp/info` | **钥匙**（前提见上） | 信息文档：规则表 + 能力表 + 两份请求 schema + 翻译可用性 + 错误码。**只播报这把钥匙能用的那部分**；无钥匙/错钥匙 ⇒ `401`（响应体带 `spec`）。一把都没配时公开 |
| `jobs` | `POST /chp/jobs` | 见下 | 提交作业 → **202** `{"job": {…}}`。**执行层再校验 `category`**，不在钥匙授权集里 ⇒ `403 forbidden_capability` |
| `job` | `GET /chp/jobs/{job_id}` | Bearer | 状态 + 提示词 + `outputs`（较重，完成后再调） |
| `progress` | `GET /chp/jobs/{job_id}/progress` | Bearer | **高频轮询用**：只回 `{id, state, queue_position, progress}`，不解析结果 |
| `output` | `GET /chp/jobs/{job_id}/output/{index}` | Bearer | 取成图（直接返回 PNG） |
| `cancel` | `POST /chp/jobs/{job_id}/cancel` | Bearer | 取消排队中的作业 |
| `translate` | `POST /chp/translate` | 见下 | 提前翻译（可选，用于把译文显示给用户） |
| `speech` | `POST /chp/speech` | 见下 | 语音：**一次请求直接回音频字节**（`stream` 决定 `audio/pcm` 还是 `audio/wav`），**不套作业模型**。`category` 同样在**执行层**校验 ⇒ 不在钥匙授权集里就 `403 forbidden_capability` |

**`progress` 允许为 `null`，而且经常就是 `null`。** 编一个假百分比比给 `null` 更糟；`queue_position`（前面还有几个作业，自己在跑时为 0）是任何实现都算得出来的可靠数字，客户端用不确定态 + 队列位置就够了。

**这张表就是全部端点。** 管理面（控制台）**故意不在里面** —— 见下面「控制台」一节：客户端只从文档读地址，所以不在文档里的东西对它不存在。

### 钥匙放在哪：一个请求只用一种载体

| 请求 | 载体 |
|---|---|
| **带 body 的 `POST`**（提交任务、翻译） | `chp_params.password` |
| `GET` 与**无 body 的 `POST`**（轮询、取状态、取图、取消） | `Authorization: Bearer <key>` —— **唯一例外，理由是钥匙不进 URL 也不进日志** |

参考实现**继续也接受** `Basic` 与 `X-HamDraw-Password`（今天三个都认），所以这条规矩是“新写的按字段、拿不到 body 时才用头”，不是把老路堵死。一把钥匙都没配时不需要。

### 两种钥匙

| 钥匙 | 从哪来 | 权限 |
|---|---|---|
| **默认钥匙** | 配置节点里的 `password`，或环境变量 `HAMDRAW_PASSWORD`。老客户端手里就是这个。 | 全部场景 |
| **key 表** | 包目录里的 `chp_keys.json`，也就是 `custom_nodes/hamdraw_chp/chp_keys.json`（与 `keys.py` 同级，**不在版本库里**；里面是凭据，建议 `0600`）。每把 key 写它自己的 `categories`，`["*"]` 表示全部 | 就是它写的那些 |

```json
{ "schema": "chp-keys/v1",
  "keys": [ { "id": "k_…", "label": "A1X 上的 Chataxi", "key": "…",
              "categories": ["fast", "inpaint"], "created": "2026-10-13T00:00:00+08:00" } ] }
```

改完**下一个请求就生效**（每次请求重读），不用重启。`categories` 写成空数组是一把**什么都看不见、也什么都做不了**的钥匙 —— 那正是"撤权但先不删"的写法，而不是"全部"。

**密码和 key 只认英文大小写字母、数字、`-` 和 `_`**（业主 2026-10-13 定，**中文不必支持**）。这条规矩卡在**收进来那一刻**，两个收口：控制台建 key、配置节点那格密码（Queue 那一次会被挡下来并说清原因）。不在比对时替非 ASCII 绕路 —— `hmac.compare_digest` 遇到非 ASCII 的 `str` 会直接抛，所以那种"支持"以前是拿一条 500 换来的。**送上来的**那一串不受这条规矩管：不匹配就是一句 `401`（比对照旧按字节走，所以一个中文的尝试不会变成 500）。`chp_admin.json` 是运维自己写的文件、**读它的时候不拦**（拦了就是把自己锁在门外）。

## 提交作业（`jobs`）

### 两个扩展通道

| | `ext_params` | `chp_params` |
|---|---|---|
| 层 | **模型层**（这次画什么） | **CHP 层**（这次怎么连、怎么算账） |
| 住户 | **规范一个都不定义** | CHP 定义：目前只有 `password` |
| 谁校验 | 没有人。**原样携带、原样回显** | 参考实现拿它当**默认钥匙**比对。另一份是包目录里的 `chp_keys.json`（key 表），**不走这个通道、也不走 URL** —— 两者只要有一个对上就放行 |

**`ext_params` 里没有官方字段表**：放什么进来都由你自己的客户端自己读，插件不筛不校验，`job.ext_params` 原样带回你发的那个对象（含嵌套结构）。

**本实现自己认识两个键**（这是它的行为，不是协议条文，所以写在这里而不是规范里）：

- `ext_params.step` —— 步数。**枚举**，取值就是上表里那个枚举，越界 → `400 unsupported_steps`；省略取该场景自己的那一档（配了加速档案就是档案的步数，否则是上表的默认值）。小数会被拒（`20.5` 不是 `20`）。
- `ext_params.negative_prompt` —— 反向提示词。`render` / `generate` 按 cfg 1 采样，它没有作用面，但插件照收。

### 提交体（每个类别共用一份基础 schema）

| 字段 | 类别 | 说明 |
|---|---|---|
| `category` | 规则参数，必填 | `fast` / `inpaint` / `upscale` / `render` / `generate` |
| `resolution` | 规则参数，**必填** | `"768x1344"` 这样的**字符串**，必须逐项命中该 `category` 的帧表；少了 → `400 unsupported_size`，表外 → 同一个码 |
| `prompt` | 规则参数 | 是否需要先译成英文由 `rules[].prompt.language` 决定 |
| `seed` | 规则参数，**必填** | **留在顶层**：少了它前端就无法锁定重复生成（少发 → `400 bad_request`）。`0` = 每次不同 |
| `ref_strength` | 规则参数 | 0.05–0.95，越界**夹到边界**并在 `job` 回显。只跟参考图一起发 —— 它是"要多像这张参考图"，没有图的时候没有意义 |
| `image_base64` / `mask_base64` | 规则参数 | 参考图 / 蒙版（**白 = 要重画**）。图片可直接给 data URL，插件自己解码；请求体上限 32 MB。**规则签名里没有 `ref` 的类别（`generate`）收到 `image_base64` 会被拒**（`400 bad_image`）—— 这是"想画一张没有参考图的图"走错场景时唯一的当场信号 |
| `ext_params` | 扩展通道 | 任意 JSON 对象 |
| `chp_params` | 扩展通道 | 目前只有 `password`（也就是**默认钥匙**） |
| `request_id` | 提交身份，可省 | 你自己这次提交的编号。**重发同一次提交就沿用同一个值**，服务端还你原来那个作业、不会再排一个；内容变了就换一个值。见下节 |

**其余顶层字段一律忽略，并把名字回显到 `job.ignored`。** 这条回执不是可选项：没有它，一次参数改名对客户端就是**静默失效**。`capability` / `task` / `size` / `steps` / `negative_prompt` 这五个 v1 的顶层字段现在都不认了 —— 客户端漏改时会当场在 `ignored` 里看到自己发错的那个名字（甚至没带 `category` 时那份 `400` 的 `detail` 里也带着这份名单）。

```json
{
  "category": "fast",
  "resolution": "512x512",
  "prompt": "a red fox",
  "seed": 12345,
  "ref_strength": 0.55,
  "image_base64": "data:image/png;base64,...",
  "ext_params": { "step": 8, "negative_prompt": "" },
  "chp_params": { "password": "<password>" },
  "request_id": "0f9c1e2a-…"
}
```

### `request_id`：一次提交只出一个作业

**要解决的问题是真的**：一次提交在服务端跑了 20 秒、回程却断了（客户端等超时、换了网络、App 被杀），这时**图已经生成好了**，而客户端手里没有作业号 —— 它只能再提交一次，于是队列里多出一个作业，第一张图谁也没来取。

`request_id` 就是给这次提交一个身份，规则四条：

| 情形 | 服务端 |
|---|---|
| 键没见过 | 正常提交，`202` + `"replayed": false`，键记住 |
| 同一个键 + **同样的内容** | **不排队、不写图**，直接答**原来那个作业的此刻状态**，`202` + `"replayed": true` |
| 同一个键 + 换过的内容 | `409 duplicate_request` —— 一个键只装一次提交，改内容就换个键 |
| 同一个键、上一次**还在处理中** | `409 duplicate_request` —— 稍后用同一个键再问一次即可 |

**内容**指的是除 `chp_params`（那是密码）和 `request_id` 自己以外的整个请求体；字段顺序不影响判定。**提交失败（`no_model` / `bad_image` / 校验不过…）会把键还回来**，所以一次失败不会挡住你自己的重试。整个字段是可选的：`request_id` 一个都不发的旧客户端照常工作。

完成后的 `outputs[n].url` 就是文档里公布的模板拼出来的那条 `/chp/jobs/...`，**客户端直接拼服务器地址去下就行，不要再拼一层**。

`job` 对象里三个字段回答“提示词到底发生了什么”：`prompt_source` 是客户端给的原文、`prompt` 是实际送进模型的那份、`translated` 表示两者是否不同。

错误码：`unauthorized(401)` / `bad_request` / `unsupported_category` / `unsupported_size` / `unsupported_steps` / `bad_image` / `bad_mask` / `stretched_reference` / `invalid_workflow` / `unsupported_voice(400)` / `forbidden_capability(403)` / `no_model(409)` / `no_upstream(409)` / `no_engine(409)` / `speech_failed(502)` / `busy(429)` / `duplicate_request(409)` / `not_found(404)` / `internal(500)`，全部带可读中文文案。`/chp/info` 的 `errors` 就是这份清单，所以客户端不必自己抄一遍。**其中只有 `unauthorized` 的响应体多一个 `spec`**（客户端靠它把「是 CHP、只是钥匙不对」和「那里没有插件」分开），其余错误码的形状一个字节都没变。

`no_upstream` 只在**服务模式**（`python -m hamdraw_chp serve`，见下）里回：那种模式自己不跑模型，所以"上游那台 ComfyUI 连不上"是一件真会发生的事。它与 `no_model` 分得很清楚，因为两件事要人做的是**两件不同的事**：一个是去那台机器上看它为何没在跑，另一个是回到配置节点上挑模型。

### `/cvp` 与 `/hamdraw/v1` 都不存在了

插件 2.3.0 之前叫 CVP，主根是 `/cvp`；改名成 CHP 之后主根是 `/chp`，`/cvp` 曾作为过渡别名保留。**`chp/2` 起别名整条删掉**：客户端被告知从 `endpoints` 里读地址，于是“同一个 API 的两种拼法”成了一个这一版故意不再做的承诺。`/hamdraw/v1` 那套旧投影面更早以前就整块删除了。

## 语音（TTS）

**一条规则、一个地址、不套作业模型。** 图片侧是"提交 → 轮询 → 取件"，因为一张 9:16 成品图要 20~45 秒；一句话只要一两秒，**而且慢的正是首字节** —— 排队位次、进度百分比、取消、分件取回，为 1.5 秒的音频付这些是抄形状不抄理由。所以语音只有 `POST /chp/speech` 一个地址：**一次请求，边合成边回字节**。

### `speech` 段（信息文档的第九个顶层键）

`GET /chp/info` 多了一节 `speech`，形状与图片侧那两张表一样，只是都装在这一个键里：

```json
"speech": {
  "rules": [
    { "category": "speak", "rule": "txt-2-sph", "signature": "txt-2-sph",
      "input": "txt-2-sph/v1",
      "label": { "zh": "朗读", "en": "Speak" },
      "needs": { "text": true }, "typical_seconds": 1.2 }
  ],
  "abilities": [
    { "name": "qwen3-tts-0.6b", "ready": true, "missing": [],
      "files": { "engine": "qwen3-tts-12hz-0.6b-customvoice-q8_0.gguf" },
      "audio": { "sample_rate": 24000, "channels": 1,
                 "formats": ["pcm", "wav"], "streaming": true },
      "voices": [ { "id": "vivian", "label": "Vivian", "languages": ["zh", "en"] }, "…" ] }
  ],
  "input_schemas": { "txt-2-sph/v1": { "…": "…" } }
}
```

- **规则签名沿用同一套文法**：模态词表加一个字 `sph`（speech），`txt-2-sph` 就是"文本 → 语音"。将来真有音乐/音效再加 `aud`，两者不混。按 `signature` 匹配能力槽的客户端因此**不必为语音写第二套协议**，只是多一条规则。
- **那条规则里没有 `prompt`，也没有 `defaults`**，这是有意的：`prompt.language` 是翻译的开关，`defaults` 装的是参考权重这类图片侧的东西 —— 少一个字段就少一条会走错的路。它声明的输入只有一个 `text`（`needs: {"text": true}`）。
- **`audio` 是这份能力自己的输出规格**（采样率 / 声道 / 容器 / 支不支持流式），客户端**读它、不猜它**。今天引擎固定 24 kHz 单声道。
- **`files.engine` 用的就是引擎自己的模型文件名**，与图片侧 `files.checkpoint` 同一个位置、同一个道理：这台机器上跑的是哪个模型，是可播报的事实。
- **音色菜单的取值与顺序来自部署**（`speech.voices`，见下），标签与语言来自插件里手写的那张表；**第一个就是默认音色**。客户端**只选不算**，服务端**成员校验**。有些引擎的 `/v1/voices` 是空的 ⇒ 这张表只能由实现手写并播报。
- **语音那份请求 schema 住在 `speech.input_schemas` 里**（键 `txt-2-sph/v1`，与规则条目的 `input` 同名）。顶层那个 `input_schemas` **仍然只有图片侧那三份** —— "同一规则共用一份 schema"的规矩没变，只是语音那一份与它自己的两张表放在一起。

### 请求体：`POST /chp/speech`

| 字段 | 类别 | 说明 |
|---|---|---|
| `text` | 规则参数，必填 | **要念出来的字**。**永不翻译**，见下。超过 2000 字会被**截断**（上限是本实现的一道闸，不是协议条文 —— 不设的话一段粘贴进来的长文会占着引擎算很久，而客户端等的是一句话） |
| `voice` | 规则参数 | 该能力 `voices[]` 里的 `id`。schema 里它是必填（客户端应当总是发它），服务端对**省略**却是宽容的：**省略即菜单第一项** —— 与 `ext_params.step` 省略时取该类别自己那一档同一条规矩，默认值是**表里的一个成员**，不是一个自己算的常量（写死一个名字的话，运维把菜单换成另一台引擎的音色之后，省略 `voice` 的客户端就会拿到一个不存在的名字）。未知音色 ⇒ `400 unsupported_voice` |
| `language` | 规则参数，可省 | `zh` / `en` / …；省略由引擎取默认 |
| `response_format` | 规则参数，可省 | `pcm` / `wav`；**省略时与 `stream` 配对**（流式默认裸 `pcm`、整包默认 `wav`）。一个请求只该选"怎么听"，不该顺带要求客户端知道"容器"是第三个旋钮 |
| `stream` | 规则参数，可省 | 省略 = `true` |
| `speed` | 规则参数，可省 | 语速倍率；给了就转给引擎（引擎不认就忽略） |
| `chp_params` | 扩展通道 | 有 body 的 POST ⇒ 密码放这里（无新规矩） |

**`text` 不叫 `prompt`，这是承重的命名。** `prompt` 在 CHP 里**带副作用**：`rules[].prompt.language` 为 `"en"` 会让服务端在**提交路径上自动翻译**。语音的输入是"要原样念出来的话"，接上那条规则就会把中文念成英文。所以这条规则里没有 `prompt`，`text` 也**永不翻译** —— 这一句是规则不是建议。实现里这条规矩是有形状的：`validate()` 故意写成**同步**函数，想在这里插一次翻译就得先有一个不存在的 `await`。`text` 还与模态名 `txt` 同字，符合既有构词法（`category` ← 规则的 `category`，`resolution` ← 帧表的 `resolution`，`text` ← 模态的 `txt`）。

```json
{ "text": "你好，这是一次测试。", "voice": "vivian", "stream": true,
  "chp_params": { "password": "<password>" } }
```

### 传输：一条路由，`stream` 决定内容类型

| | `stream: true`（默认） | `stream: false` |
|---|---|---|
| `Content-Type` | `audio/pcm` | `audio/wav` |
| 响应头 | `X-Sample-Rate: 24000`、`X-Channels: 1` | 同左 |
| body | 裸 s16le 分块，按 4 KiB 一片转发 | 整个文件 |

`X-Sample-Rate` **两种形态都给**：裸 PCM 不给这个头就播不了，而整包那份也带着它，客户端读一个值就不必为两种形态写两条路。**错误一律是 JSON**，而且在开始写 body **之前**就用状态码定好了 —— 客户端的判据是"先看状态码，非 2xx 就按 JSON 解析"。首字节之后才出的错没法再变成状态码，那种情况只能断开连接并在日志里留一行。

### 拒绝：三条新错误码

| 码 | HTTP | 什么时候 |
|---|---|---|
| `unsupported_voice` | 400 | 这个音色不在 `speech.abilities[].voices` 里（`detail` 把那份菜单带回来） |
| `no_engine` | 409 | 没配 `speech.url`、连不上、或引擎回 `401`/`403`（令牌不对） |
| `speech_failed` | 502 | 引擎在跑，但没正常应答（回 `500` 之类） |

`401`/`403` 收敛成 `no_engine` 而不是一个新码：对客户端来说"引擎要令牌而这台机器没配对"与"引擎没在跑"是同一件事 —— 都要运维去改那台机器，而它自己能做的动作一模一样。

**且执行层那道授权照旧先做**：`speak` 不在钥匙的授权集里 ⇒ `403 forbidden_capability`（在必填字段检查**之前**判），与 `jobs` 同一条规矩。

**引擎地址与令牌永不进文档、永不进响应。** 不论连不上、令牌错还是引擎 500，一律收敛成上面三条，明细**只进那台机器的日志**（`translate.py` 已在遵守的同一条规矩）。实现上这条规矩是有形状的：判定函数只收一个**状态码**，引擎说的话没有任何入口。

### 部署参数（HTTP 上永远看不见）

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

写在 `custom_nodes/hamdraw_chp/hamdraw_settings.json` 里（与 `families.*` 那些部署旋钮同一个文件）；容器/CI 用两个环境变量覆盖：`HAMDRAW_SPEECH_URL`、`HAMDRAW_SPEECH_TOKEN`。

| 键 | 不给会怎样 |
|---|---|
| `url` | 给不出 `no_engine`；`speech.abilities` 播报 `ready: false`、`missing: ["url"]` |
| `token` | 引擎回 `401` ⇒ 同样收敛成 `no_engine` |
| `voices` / `sample_rate` / `timeout` | 用出厂值照跑。`voices` 是**这台机器上引擎支持的那几个名字**，换引擎才要改；写成空数组 ⇒ `ready: false`、`missing: ["voices"]`（配了引擎却一个音色都没有，一样是答不了，而"缺的是哪一档"要说出来） |
| `engine` | 只用于播报（`files.engine`），不影响跑 |

**`token` 与 CHP 自己的密码是两把不同的钥匙**：密码是「客户端 ↔ CHP」，令牌是「CHP ↔ 引擎」。两者都在 `hamdraw_settings.json` 里、同一个信任级别。

**引擎要的是 OpenAI 那套 `POST {url}/v1/audio/speech`**（地址给到根、给到 `/v1`、给到 `/v1/audio` 都行，插件自己补齐），body 是 `{input, voice, response_format, stream}`（客户端给了 `language` / `speed` 就一起带上），带 `Authorization: Bearer <token>`。**不传 `model`**：这台机器上加载的是哪个模型是引擎自己的事，`speech.engine` 只播报、不外发。

**ComfyUI 重启会带走语音** —— 多了一个耦合，与 `translate` 今天的处境完全一样；`timeout` 兜底。

## 控制台（管理面）

同一个服务、同一个端口上的一个网页：**管 key 与 key 的授权**。地址是 `/chp/admin/`。

**它不在 `endpoints` 里**（§0-3 那条"地址一律从文档里读"的反面用法）：客户端只从信息文档取地址，所以它**永远不知道控制台存在**，契约保持干净 —— 控制台不是协议的一部分。

打开它，浏览器会自己弹一个登录框（那个 401 带 `WWW-Authenticate`，所以**页面上没有、也不需要任何登录表单**）：

| | |
|---|---|
| 用户名 / 密码 | `chp_admin.json` 里的 `user` / `password`；**文件不存在时用代码里的默认值 `hamster` / `imahamster`** |
| 改它 | 只能在**本机**改那个文件（SSH / 编辑器），**改完要重启**才生效 |
| 能做什么 | 看**已注册的能力**（只读）、建 key、改 key 的标签与授权、换一把、删掉 |
| 不能做什么 | **不能新增能力、不能改模型配置、不能改凭据** —— 页面上没有那样的入口 |

**为什么"不能改凭据"不是靠自觉**：三条线用了三个文件，控制台**根本没有那把钥匙**：

| 钥匙 | 谁对谁 | 存哪 |
|---|---|---|
| **数据面 key** | 客户端 ↔ CHP | `chp_keys.json`（+ 配置节点里的密码 / `HAMDRAW_PASSWORD` 作为**默认钥匙**，权限全部） |
| **控制台凭据** | 管理员 ↔ 控制台 | `chp_admin.json`（**只能本机改，改完重启**） |
| **引擎令牌** | CHP ↔ 语音引擎 | `hamdraw_settings.json` 的 `speech.token`（**永不进文档、永不进响应**） |

这三把**不许共用同一个值**：数据面 key 泄漏 = 白用模型；它若能进控制台，就是"能改授权、能给自己造 key" = 接管。实现上有一道闸专门管这件事的两半：

- 控制台**只认 `Basic`**（`Bearer` 进不来）—— 数据面那把钥匙不能当控制台凭据使；
- 往表里写一把**与控制台凭据同值**的 key 会被**拒收** —— 因为数据面也认 `Basic`（把 `:` 之后那段当 key），同值就等于控制台密码顺带成了一把数据面钥匙。

**授权只能从已注册的清单里选。** 那份清单**就是代码里的 `category` 表**（`fast` / `inpaint` / `upscale` / `render` / `generate`，外加语音的 `speak`），页面上列的就是它、`GET /chp/admin/capabilities` 回的也是它，**每个场景的 `ready` / `missing` 与 `/chp/info` 同源**（两边说法不一致会让管理员去找一个并不存在的配置问题）。提交一个清单外的 `category` 一律拒收 —— 与数据面的 `unsupported_category` 同一条纪律。**"添加一个模型"这个动作在控制台里不存在**：能力是代码，授权是数据；前者改代码、重启，后者点控制台、**下一个请求就生效**。

`categories` 写 `["*"]` 是"全部"，写空数组是"什么都看不见、也什么都做不了"（撤权但先不删的写法）。**key 明文存储**、表按 `0600` 原子写：它就是一把可以抄出来交给别人的钥匙，而管理员需要能把它复制走。

**key 与密码只认英文大小写字母、数字、`-` 和 `_`**（不支持中文）—— 这条规矩卡在**收进来的那一刻**：控制台拒收别的写法，配置节点（默认钥匙）也一样，Queue 那一次会被挡下来并说清原因。`chp_admin.json` 的控制台凭据是运维自己写的文件，读它的时候不拦（拦了就是把自己锁在门外）；**送上来的**那一串更不受限制，只是不匹配就照旧一句 `401`（凭据比对按字节走，所以一个中文的尝试不会变成 500）。

三个配置文件都**不在版本库里**（`.gitignore`），也都**不会进发布 zip**（`tools/package-plugin.py` 按名字排除，且发现它们在树里会打一行警告）：发布包该装到谁的机器上，谁的机器上就还没有这些凭据。

## 服务模式（`python -m hamdraw_chp serve`）

**一个包，两个入口**：`import hamdraw_chp` 是**插件**（进程内后端，跑在 ComfyUI 自己的端口上）；`python -m hamdraw_chp serve` 是**服务**（HTTP 后端，自己起一个端口）。**模式由「谁启动的」决定，不自动检测。**

上面写的每一个接口、每一个错误码、`/chp/info` 的每一个字段，两种模式下**完全一样** —— 客户端无从分辨，也不需要分辨。

```bash
python -m hamdraw_chp serve          # 默认 127.0.0.1:8889
```

`hamdraw_settings.json` 的 `serve` 块（**插件模式忽略这一档**：绑定由 ComfyUI 决定）：

| 键 | 默认 | 说明 |
|---|---|---|
| `serve.host` | `127.0.0.1` | 绑定地址 |
| `serve.port` | `8889` | 自己的端口；**换它不用改客户端、不用改文档** |
| `serve.upstream` | `http://127.0.0.1:8188` | 上游 ComfyUI 的地址；**只在部署侧配，永不来自请求体** |

服务模式怎么拿到上游的东西：**模型清单**来自上游 `object_info` 的枚举，读的是一份**快照**（所以 `/chp/info` 永远不等上游、上游慢也不拖它）；**作业号**由本服务自己发，`我们的号 ↔ 上游 prompt_id` 的映射在内存里（进程重启前提交的作业只能回 `not_found`，与「从来不存在的号」同一个答案）；**参考图**先落本机暂存目录，提交时上传、并按**上游答的那个名字**改写图里那一格；**产物**反向取回再交给 `FileResponse`。**不假设与上游共享文件系统** —— 假设共享是那种「本机测得通、换台机器就废」的设计。

**上游不在时**：`/chp/info` 仍返回 **200**，`abilities` 全部 `ready: false`、`errors` 里写 `no_upstream`（409）。「后端缺席 ≠ 服务缺席」；把它说成 `no_model` 会把人指到错的配置文件上。

验收就三条，一条比一条硬：

1. 同一个 key 下 `/chp/info` 与插件模式**逐字节相同**（`endpoints` 存的是相对路径，所以连地址都不必例外）；
2. 上游不在时 `/chp/info` 仍 200 且 `errors` 里有说明；
3. 改 `serve.port` 后客户端**一行不改**仍可用。

## 自测

```bash
# 0. 离线自检（不需要 ComfyUI、不需要网络、不需要 aiohttp）
python3 tests/test_spec.py
python3 tests/test_mask_graph.py

# 1. 信息接口：有哪些场景、各自收什么、画幅有哪些、谁只认英文、模型就绪没
curl -s http://<host>:8188/chp/info

# 2. 提交 + 轮询 + 取图（密码在 body 里）
curl -s -X POST http://<host>:8188/chp/jobs -H 'Content-Type: application/json' \
  -d '{"category":"fast","resolution":"512x512","prompt":"a red fox","seed":1,
       "image_base64":"data:image/png;base64,...",
       "chp_params":{"password":"<password>"}}'

# 其余接口没有 body，密码走头
curl -s -H 'Authorization: Bearer <password>' http://<host>:8188/chp/jobs/<id>/progress
curl -s -H 'Authorization: Bearer <password>' -o out.png http://<host>:8188/chp/jobs/<id>/output/0

# 3. 中文提示词（fast 只认英文，插件会自动译英，响应里 translated: true）
curl -s -X POST http://<host>:8188/chp/jobs -H 'Content-Type: application/json' \
  -d '{"category":"inpaint","prompt":"一只红色的狐狸","image_base64":"data:image/png;base64,...",
       "mask_base64":"data:image/png;base64,...","chp_params":{"password":"<password>"}}'

# 4. 语音：流式（默认）—— 裸 PCM 分块，听的时候首字节最先到
curl -s -D- -X POST http://<host>:8188/chp/speech -H 'Content-Type: application/json' \
  -d '{"text":"你好，这是一次测试。","voice":"vivian",
       "chp_params":{"password":"<password>"}}' -o speech.pcm

# 5. 语音：整包 —— 换 stream:false，拿到一个能直接播的 wav
curl -s -D- -X POST http://<host>:8188/chp/speech -H 'Content-Type: application/json' \
  -d '{"text":"你好，这是一次测试。","voice":"vivian","stream":false,
       "chp_params":{"password":"<password>"}}' -o speech.wav

# 6. 控制台（管理面）：默认凭据是 hamster / imahamster，没写 chp_admin.json 时就用它
curl -s -u hamster:imahamster http://<host>:8188/chp/admin/capabilities
curl -s -u hamster:imahamster http://<host>:8188/chp/admin/keys
```

用 `python3 -m json.tool` 过一遍第 1 步的返回，重点确认六件事：`spec` 是 `chp/2`、`rules` 有你预期的五条、`abilities` 的 `ready` 为 `true`、每个 `category` 至少命中一帧、`input_schemas` 恰好三份（三条规则各一份）、`speech` 段里有 `txt-2-sph` 那条规则与那份音色菜单（引擎没配时它是 `ready: false`，不是缺失）。

第 4 / 5 步看响应头：`Content-Type` 分别是 `audio/pcm` 与 `audio/wav`，两者都带 `X-Sample-Rate`。播第 5 步那个文件最简单（`afplay speech.wav` / 双击）；第 4 步那份是裸 PCM，播放器要知道参数：`24000 Hz`、单声道、`s16le`。

- **第一次请求会慢**（模型加载，约十几秒），之后同模型重跑约 1 秒；别用首单判断“模型太慢”。
- 在 HamDraw App 里对接：设置 → 模型配置 → 接口模式选「CHP 插件（CHPCP）」，服务器地址填 `http://<host>:<port>`，访问密码填节点里设的那个。
