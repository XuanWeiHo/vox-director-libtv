# Vox Director LibTV 完整操作手册

适用版本：当前 LibTV 迁移分支；实际联调使用 LibTV CLI 1.1.3。本文命令面向 Windows PowerShell，均在仓库根目录执行。文中的示例命令不会因为阅读本文而自动运行。

仓库：https://github.com/XuanWeiHo/vox-director-libtv

## 1. 先理解它做什么

这是供 AI agent 使用的一套视频制作技能和 Python 脚本，没有独立的图形化编辑器。你可以直接在对话中描述需求，让 agent 写脚本、分镜并操作；也可以自己编辑 `beats.json`，逐阶段执行。

完整流程是：需求 → 文案与分镜 → 配音和图片 → 审看关键帧 → 确认视频请求 → LibTV 生成视频 → 本地字幕、混音与合成 → 审片。

图片、配音、音乐和视频的模型生成走当前登录的 LibTV 账户，可能消耗额度。本地转写、抠图、剪辑不调用 Atlas Cloud；首次使用 ASR / rembg 会下载模型。本技能不需要 Atlas Cloud API key，也不要求把 LibTV 凭据填进项目 `.env`。

| 模式 | 你提供什么 | 主要用途 | 视频生成量，不含返工 |
|---|---|---|---|
| B-roll | 主题或文案 | 科普、知识解说、故事 | 通常每个 shot 一段 |
| C-roll | 人物或产品照片，加文案 | 产品广告、照片主体拼贴 | 通常每个 shot 一段 |
| A-roll | 带声音的口播视频 | 保留原声、改造背景和视觉风格 | 每个 beat 一段编辑视频，可能另有素材上传节点 |
| Host | 主持人头像，加文案或配音 | 数字主持人讲解 | 每个 Host 镜头两段：人物层和背景层 |

`beat` 是一段叙事和旁白，`shot` 是这一段中的一个画面。一个 beat 可以有多个普通 shot；每个 Host beat 必须只有一个 Host shot。

## 2. 最方便的用法：在对话中交给 agent 执行

当前电脑已经安装 `vox-director-libtv`。不必重新安装依赖，也不用手动输入下面所有命令。直接发送以下模板，并替换主题或素材路径。

### 主题解说 B-roll

> 使用 $vox-director-libtv，制作一条约 30 秒的中文解说视频，主题是“纸飞机为什么能飞”，16:9 横屏，swiss-modern 纸张拼贴风格，中文字幕，Seedance 2.5，720p。新建名为 paper-flight-30s 的 LibTV 画布。先给我完整旁白、分镜、图片/音频/视频节点数量和模型计划；确认后制作配音与关键帧，关键帧让我审看。所有视频生成节点必须先向我确认，不要额外生成候选，不要自动重试。最后交付 final.mp4 和验收结果。

### 产品照片 C-roll

> 使用 $vox-director-libtv，把 C:/media/product.jpg 做成约 15 秒、9:16 的中文产品介绍，newsprint-editorial 拼贴风格。保留产品形状、配色和标签，配中文字幕。先写文案和分镜并展示生成计划；图片确认后，再向我确认视频节点。不要擅自增加候选。

### 口播改造 A-roll

> 使用 $vox-director-libtv，把 C:/media/talking.mp4 转成 Vox 风格拼贴口播。先本地转写并给我校对，保留原始声音和语句时间，背景加入与文案有关的纸张图形。不要承诺面部运动逐帧不变。素材上传节点和视频编辑节点分别列明，生成前向我确认。最后给我成片和与原视频对照的验收结果。

### 数字主持人 Host

> 使用 $vox-director-libtv，以 C:/media/presenter.png 为主持人，制作约 20 秒的中文科普视频，主题是“空气怎样托起机翼”，16:9，主持人在左，信息图在右。先给完整文案和分镜，再制作配音、人物绿幕图和背景图供我审看。逐镜列出人物层、背景层两个视频节点的模型和时长，得到我的确认后再生成。

这些话是制作指令，不是让 agent 立即无条件生成全部视频。“继续”只表示继续当前工作；视频请求仍要有具体范围的确认。你也可以指定已有 LibTV 画布 ID，避免创建新画布。

## 3. 准备环境与进入目录

当前已配置的电脑：打开项目目录里的 PowerShell，直接进入第 4 节。其他电脑先克隆并安装 Python 依赖：

```powershell
git clone https://github.com/XuanWeiHo/vox-director-libtv.git
Set-Location vox-director-libtv
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

另外需要已安装官方 LibTV CLI、ffmpeg / ffprobe 和中文字体。CLI 安装以其官方发布说明为准，不要误装同名的第三方 Liblib OpenAPI 工具。接口参考：[官方 CLI 1.1.3 文档包](https://liblibai-web-static.liblib.cloud/cli/1.1.3/libtv-cli-skill.zip)。

检查命令：

```powershell
libtv --version
ffmpeg -version
ffprobe -version
.venv/Scripts/python --version
```

尚未登录时执行：

```powershell
libtv login web --open
```

如果 `libtv` 不在 PATH，可设置真实安装位置，例如：

```powershell
$env:LIBTV_CLI = "D:/libtv/libtv.exe"
& $env:LIBTV_CLI --version
```

这个变量供 Python 适配层使用；它不会创建一个名为 `libtv` 的 PowerShell 命令。后续直接查询 CLI 时可用 `& $env:LIBTV_CLI` 代替 `libtv`。

所有 JSON 保存为 UTF-8。素材路径建议使用绝对路径和正斜杠，例如 `C:/media/product.jpg`。若通过 PowerShell 管道传递中文到 Python，先设置：

```powershell
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
```

## 4. 一次完整的 B-roll 操作

下面以纸飞机解说为例。每个作品用一个独立目录，不复用别的作品的任务记录。

### 4.1 建立作品与画布

```powershell
.venv/Scripts/python -X utf8 scripts/pipeline.py init out/paper-flight --spec examples/libtv-broll.beats.json
```

这一步复制模板并创建 LibTV 画布，不生成图片、音频或视频。模板中的 `project` 是画布名称；希望更换名称，可先复制模板到自定义 spec，改好 `project` 再 init。

如果已有画布，改为以下命令；两条 init 命令只选一条：

```powershell
.venv/Scripts/python -X utf8 scripts/pipeline.py init out/paper-flight --spec examples/libtv-broll.beats.json --project-id "实际画布UUID"
```

画布 ID 可从 LibTV 画布网址的 `projectId` 参数读取。init 会写入 `out/paper-flight/beats.json` 的 `libtv.project_id`。同一目录已有 beats.json 时，不要再次 init。

### 4.2 编辑分镜

打开 `out/paper-flight/beats.json`。模板是一段旁白配两个 5 秒镜头，并不是自动写出 30 秒剧本的按钮。需要更长视频时，先增加经过审阅的 beats / shots。

| 字段 | 含义 / 示例 |
|---|---|
| `topic` | 主题，例如“纸飞机为什么能飞” |
| `language` | 语言，例如 `zh` |
| `aspect` | 横屏 `16:9`，竖屏 `9:16` |
| `style` | 当前拼贴流程使用 `collage` |
| `theme` | 如 `swiss-modern`、`newsprint-editorial`、`american-retro`、`punk-zine`、`chinese-ink` |
| `image_model` / `image_resolution` | 默认 `General image V2`；模板图片质量 `1k` |
| `video_model` / `video_resolution` | 默认 `Seedance 2.5` / `720p`；以账户实时 schema 为准 |
| `captions` | `true` 开启字幕，`false` 关闭，默认开启 |
| `caption_style` | `white` 或 `paper` |
| `output_size` | 可选，如 `[1920, 1080]`；只控制本地输出尺寸，不会提升模型原生细节 |
| `music` | 音乐配置；`false` 关闭 |
| `mix` | 普通合成音量，如 `{"music": 0.35, "voice": 1.1}` |
| `libtv.require_video_approval` | 保持 `true` |

一个 beat 的主要结构：

```json
{
  "id": 1,
  "title_cn": "",
  "title_en": "PAPER FLIGHT",
  "narration": "一张纸，折出飞行的秘密。空气托起机翼，重力让它滑翔。",
  "bg": "teal blue",
  "feel": "curious, playful",
  "shots": [
    {
      "id": "a",
      "dur": 5,
      "title": true,
      "scene": "a white folded paper airplane on layered blue paper sky, orange wind arrows",
      "camera_move": "push_in",
      "element_motion": "the airplane glides slowly right; the clouds drift gently without changing shape"
    },
    {
      "id": "b",
      "dur": 5,
      "title": false,
      "scene": "close-up of the folded wing with paper airflow arrows",
      "camera_move": "static",
      "element_motion": "the arrows slide around the rigid wing"
    }
  ]
}
```

这是 beat 片段，放在完整配置的 `beats` 数组里，不要拿它覆盖整个文件。beat ID 与 shot ID 的组合必须唯一，例如 `1a`、`1b`。

`scene` 描述静态画面，`camera_move` 描述镜头移动，`element_motion` 描述物件怎样运动。常用镜头词有 `static`、`push_in`、`pull_out`、`pan`、`parallax`。避免把同一镜头写成多个冲突的运镜。

时长注意：`dur` 是单个模型视频的请求时长。普通 B-roll / C-roll 合成会在旁白过长时延长最后一个镜头，可能放慢画面；成片时长不一定等于填写的秒数总和。要求严格时长时，应先试听旁白、调整文案与镜头时长，再生成视频。Host 和 A-roll 不用这种放慢方式补时长。

### 4.3 只读预检查

```powershell
.venv/Scripts/python -X utf8 scripts/pipeline.py preflight out/paper-flight
```

它会访问 LibTV 查询画布和模型 schema，并检查部分配置、路径、字体及工具；不生成媒体，但会保存本地检查结果。成功不代表所有图片、语音和视频质量已经通过验收。

下面的命令也是预检查，不执行生成：

```powershell
.venv/Scripts/python -X utf8 scripts/pipeline.py run out/paper-flight
```

### 4.4 制作并审看音频、关键帧

文案和生成范围确定后，执行：

```powershell
.venv/Scripts/python -X utf8 scripts/audio.py out/paper-flight
.venv/Scripts/python -X utf8 scripts/keyframes.py out/paper-flight
```

这两步可能消耗音频和图片生成额度。查看 `audio/`、`keyframes/`，试听是否漏字、错读，审看主体、拼贴风格、图中文字和构图。确认以后再进行视频步骤。

默认字幕是一整个 beat 的文案，在该 beat 期间显示，不是逐字高亮字幕。需要更细的字幕变化，应在写分镜时拆成更短的 beats。AI 图片中的标题与本地字幕是两回事；图片中的错字不能靠修改字幕解决。

### 4.5 生成视频计划并确认

```powershell
.venv/Scripts/python -X utf8 scripts/clips.py out/paper-flight
```

未授权时会停在 `VIDEO_APPROVAL_REQUIRED`，给出 `.libtv/vox/video-plan-<hash>.json` 路径。这是正常的确认门槛，不是生成失败。尚未授权的视频节点不会在此创建或运行。

按第 5 节阅读并记录确认，然后重新运行同一条 clips 命令。多个镜头可能逐个停下来请求确认；当前脚本不保证首次就列出全片所有精确 hash，也不会自动批准后面的镜头。

### 4.6 合成与验收

全部镜头完成后：

```powershell
.venv/Scripts/python -X utf8 scripts/assemble.py out/paper-flight
.venv/Scripts/python -X utf8 scripts/pipeline.py verify out/paper-flight
Invoke-Item out/paper-flight/final.mp4
```

得到 `final.mp4`、`verification.json` 和 `verify-0.jpg` 到 `verify-2.jpg`。verify 检查音视频流、完整解码、抽帧和 SHA-256；仍要完整播放确认旁白、字幕、音量与画面。

视觉方向已经确定时，可以用统一入口替代分阶段执行：

```powershell
.venv/Scripts/python -X utf8 scripts/pipeline.py run out/paper-flight --execute
```

这会顺序执行该模式的各阶段并最终 verify，仍受视频确认门槛约束。它不会自动在图片生成结束后停下来等你审图，因此需要审图时用上面的分阶段方式。

## 5. 视频确认的具体操作

首先打开错误信息指定的那个计划文件；不要用“最新一个文件”的猜测代替核对：

```powershell
Get-Content -LiteralPath "out/paper-flight/.libtv/vox/video-plan-完整hash.json" -Encoding UTF8
```

核对 `request` 的画布、模型、分辨率、时长、prompt 和 refs。视频编辑通常使用源片段时长，参数可能显示 `duration_auto: 0`，这不代表生成零秒；应同时核对源片段实际时长。价格以当前 LibTV 账户为准，脚本不提供可靠报价。

确认这个具体请求后，将完整 hash 和自己的实际确认内容填入：

```powershell
.venv/Scripts/python -X utf8 scripts/pipeline.py approve-video out/paper-flight --request-hash "实际64位hash" --confirmation "我确认此请求：Seedance 2.5、720p、5秒、镜头1a，使用计划中的参考图，不增加候选"
.venv/Scripts/python -X utf8 scripts/clips.py out/paper-flight
```

`approve-video` 只保存同意记录，不立即生成。文字必须反映真实同意；命令本身不会弹出第二次人工确认。由 agent 操作时，应先让用户确认，再记录。

一个 hash 对应一个精确请求；修改提示词、参考素材或参数会形成新请求，需要新确认。`--execute`、Host 的 `--yes` 和普通“继续”都不能代替这个记录。不要为了省步骤关闭 `require_video_approval`。

A-roll 的 `video_resource_upload` 计划表示上传源片段，不是模型生成任务。上传确认与后续编辑生成确认是两个不同请求，不能混为一次视频生成。声音参考兼容路线也会触发视频确认，见第 8 节。

## 6. C-roll：使用照片中的人物或产品

```powershell
.venv/Scripts/python -X utf8 scripts/pipeline.py init out/product-film --spec examples/libtv-croll.beats.json
```

编辑 `out/product-film/beats.json`：

- `anchor_photo`：真实照片绝对路径。
- `croll_subject`：产品用 `product`，人物用 `portrait`。
- `subject_desc`：产品的外形、配色或标签描述；人物服装可用 `subject_wardrobe`，默认沿用照片服装。
- `narration`、`scene`、`element_motion`：替换成你的内容。

按顺序运行：

```powershell
.venv/Scripts/python -X utf8 scripts/pipeline.py preflight out/product-film
.venv/Scripts/python -X utf8 scripts/audio.py out/product-film
.venv/Scripts/python -X utf8 scripts/croll_keyframes.py out/product-film
```

审看关键帧，尤其检查产品标签和人物形象。再执行 `clips.py out/product-film`，按第 5 节确认视频，完成后执行 `assemble.py` 和 `pipeline.py verify`。C-roll 的保留主体提示词是约束，不保证产品标识逐像素不变。

## 7. A-roll：用已有口播视频

### 7.1 转写到一个独立草稿目录

```powershell
.venv/Scripts/python -X utf8 scripts/asr_beats.py out/talking-transcript "C:/media/talking.mp4" --language zh --asr-model small --max-beat-dur 9.5
```

这是本地转写，不生成 LibTV 视频。首次可能需要下载 ASR 模型。草稿目录不能已有 beats.json；该保护防止覆盖你校对过的内容。

### 7.2 校对草稿

编辑 `out/talking-transcript/beats.json`：

- 校正每段 `text`，特别是专有名词。
- 检查 `start`、`end`，保证 `dur = end - start`，并检查片段是否从完整语句开始和结束。
- 转写分段按识别到的词生成，可能省略开头、结尾或段间静音；需要保留时手工调整时间范围。
- 将 `theme` 从 `null` 改为 `newsprint-editorial` 等具体主题。
- 为每个 beat 填写 `content_beats`，说明背景要出现什么纸张元素。
- 确认 `source_video` 指向实际视频，保留合理的 `aspect`；视频编辑本身跟随源片段时长和比例。

当前默认最多按约 9.5 秒分段是脚本的分段策略，不是所有模型的通用时长上限。特别短或特殊格式的片段仍可能被模型拒绝，应在提交前检查实时要求。

### 7.3 从校对稿建立正式作品

```powershell
.venv/Scripts/python -X utf8 scripts/pipeline.py init out/talking-film --spec out/talking-transcript/beats.json
.venv/Scripts/python -X utf8 scripts/pipeline.py preflight out/talking-film
.venv/Scripts/python -X utf8 scripts/aroll_clips.py out/talking-film
```

这里使用新的正式作品目录，避免 init 与转写生成的 beats.json 冲突。已有画布仍可给 init 加 `--project-id`。

首次通常先遇到视频素材上传确认；确认并续跑后，再遇到编辑生成确认。每次都按第 5 节核对具体计划。无需运行普通 `audio.py` 或 `keyframes.py`。

### 7.4 保留原声并合成

```powershell
.venv/Scripts/python -X utf8 scripts/aroll_assemble.py out/talking-film
.venv/Scripts/python -X utf8 scripts/pipeline.py verify out/talking-film
```

A-roll 合成使用源视频对应时间段的原始音轨；生成的视频画面仍可能改变面部运动。明显时长不符会停止，不能以放慢、截短来掩盖问题。应与原片对照审看，不把“保留原声”理解成“口型绝对不变”。

## 8. Host：数字主持人流程

```powershell
.venv/Scripts/python -X utf8 scripts/pipeline.py init out/host-film --spec examples/libtv-host.beats.json
```

配置 `host.avatar` 为头像路径。横屏 `host.position` 可用 `left`、`center`、`right`；竖屏用 `lower`。`host.size` 是头部高度占画面高度的比例，不是人物整个身体的比例。每段仅保留一个 `kind: host` 镜头。

```powershell
.venv/Scripts/python -X utf8 scripts/pipeline.py preflight out/host-film
.venv/Scripts/python -X utf8 scripts/audio.py out/host-film
.venv/Scripts/python -X utf8 scripts/host_plates.py out/host-film
```

先试听旁白，再检查人物绿幕图和背景图：人物位置是否正确，绿幕是否均匀，背景是否给人物留出了空区。

查看本地视频时长计划：

```powershell
.venv/Scripts/python -X utf8 scripts/host_clips.py out/host-film
```

该调用默认只展示需要生成的层和时长，不提交生成。实际时长由旁白长度加余量推导，不是简单照抄 shot.dur。单段过长应拆 beat。

进入精确请求确认流程：

```powershell
.venv/Scripts/python -X utf8 scripts/host_clips.py out/host-film --yes
```

没有 hash 确认时仍会停止。每镜人物层、背景层分别确认；`--yes` 只允许脚本进入执行阶段。两层完成后脚本本地抠绿合成，随后执行：

```powershell
.venv/Scripts/python -X utf8 scripts/assemble.py out/host-film
.venv/Scripts/python -X utf8 scripts/pipeline.py verify out/host-film
```

Host 使用人物生成视频自己的音轨，以配合其生成表演；原始配音保存为参考。务必试听人物最终是否说对文字，并检查口型、绿边和背景遮挡。本轮集成测试使用插画人物，真人效果仍需单独审看。

## 9. 配音、音乐和已有素材复用

### 普通 TTS

```json
"voice": {"model": "Minimax-speech-2.8-hd", "language": "zh", "speed": 1.0}
```

不指定 `voice_id` 时用实时 schema 默认音色；自选 ID 必须来自当前 LibTV 模型。不要使用原 Atlas / xAI 的音色 ID。

### 使用已有旁白

把这一项放到对应 beat 中：

```json
"audio_source": "C:/media/narration-01.mp3"
```

每个 beat 对应自己的音频，不要无意间给所有 beats 指向同一整段录音。保留与录音匹配的 `narration`，本地字幕使用它。音频时长会以实际文件探测结果为准。

### 音乐

关闭音乐：`"music": false`。

使用现成音乐：`"music": {"source": "C:/media/bgm.mp3"}`。

生成音乐：`"music": {"model": "Eleven Music V3", "prompt": "轻快的纪录片配乐", "duration": 30}`。

音乐与音量配置主要用于 B-roll / C-roll / Host 的普通合成。当前 A-roll 合成直接保留源音轨，不会自动套用普通管线的 BGM 混音设置。

### 声音参考

```json
"voice": {
  "clone_ref": "C:/media/reference.mp3",
  "model": "Seedance 2.5",
  "language": "zh",
  "clone_duration": 8
}
```

当前 CLI 的兼容实现是 audio2video 生成带声音的视频，再本地提取音轨。因此它会产生额外视频请求、触发视频确认并按视频模型计费；不是低成本普通 TTS，也不等同于专用声音克隆。没有声音复现需求时使用普通 TTS 或现成音频即可。详见 [voices.md](voices.md)。

## 10. 修改、返工与中断恢复

| 需求 | 操作原则 |
|---|---|
| 只改字幕显示文字、样式、音量、输出尺寸 | 修改相关配置，只运行本地 assemble 和 verify；A-roll 用 aroll_assemble |
| 换一句实际旁白 | 需要重新处理声音；Host 人物视频也受影响，应重新确认对应生成计划 |
| 换画面或风格 | 新 prompt 可能生成新请求；检查并清理对应旧输出指针后再生成，不要假定改 theme 就会覆盖缓存 |
| 网络断开或 CLI 状态未知 | 保留 `.libtv/vox/`，检查原画布节点，续跑原阶段恢复；不要重新 run 远端节点 |
| 原任务明确失败，需要重做 | 先确认原任务终止，再制定具体新请求，视频重新确认 |
| 复制作品 | 用干净 spec 新建，不把旧节点 ID、clip_path 和任务日志误当新作品输入 |

普通模式修改 `narration` 后只运行 assemble 会改变字幕，但不会改变已经录制的声音；不要把字幕和实际声音改成不一致的内容。

有意重做时，`libtv.generation_revision` 可以产生新请求，但它是项目级设置，会影响多个请求。不要把递增 revision 当作普通恢复手段。已有 `keyframe_url` 等字段可能让阶段直接跳过；应只处理目标镜头，保留其余结果和日志。精确返工可以交给 agent，说明“只改哪一镜，哪些素材必须复用”。

中断后优先重跑原阶段，例如 `clips.py out/paper-flight`。已完成且请求未变的节点会复用；仍在运行或结果未知时停止，不自动重新扣费。如果阶段中前面的镜头已完成、后面遇到确认门槛，也可通过同样方式恢复。

重新运行统一入口适用于配置未改变的情况；它会重新走各阶段并可能重新下载、合成。只修改本地字幕、音量时，无需运行整条管线。

## 11. 文件位置与成片交付

```text
out/作品名/
  beats.json             分镜、设置及生成结果指针
  audio/                 配音、音乐与 Host 音轨
  keyframes/             普通关键帧或 Host 两层图片
  segments/              A-roll 源视频切片（该模式使用）
  clips/                 视频素材和 Host 合成镜头
  .libtv/                画布绑定、请求记录、确认记录与缓存
  _seg/                  本地合成中间文件
  final.mp4              最终成片
  verification.json      解码、时长、文件指纹等验证结果
  verify-0.jpg           开头抽帧
  verify-1.jpg           中间抽帧
  verify-2.jpg           结尾抽帧
```

不同模式不会生成每一个目录。需要交片时交付 final.mp4；需要未来可恢复编辑时，保存整个作品目录、源素材、代码版本和依赖环境。

`out/`、`.libtv/`、`.venv/` 和凭据不进入 Git 提交。LibTV 画布上的原始节点与本地 `final.mp4` 不是同一产物：当前管线在本地合成，不会自动把最终成片上传回画布。

最终审片至少检查：开头结尾完整、旁白不缺字、字幕匹配、音乐不盖人声、主体与标签稳定、Host 绿幕边缘及口型、A-roll 与原片的表演一致程度。平台下载水印遵循官方 CLI 行为；配置里的 `watermark` 只控制普通本地合成额外叠加的标记。

## 12. 常见问题

| 情况 | 处理 |
|---|---|
| `libtv not found` | 检查 PATH，或设置 `LIBTV_CLI` 指向真实可执行文件 |
| 没有画布 ID / 找不到画布 | 检查登录账户与 `libtv.project_id`，不要用画布名字替代 UUID |
| `VIDEO_APPROVAL_REQUIRED` | 读取指定计划，确认后记录 hash，再续跑原阶段 |
| `Project already exists` | 已有项目直接编辑和续跑；新作品换目录 |
| ASR 提示 beats.json 已存在 | 保留校对稿，重新转写用新草稿目录 |
| 模型或参数被拒绝 | 查询 `libtv model search -t video` 和 `libtv model "Seedance 2.5"` 等实时 schema，不静默换模型 |
| 缺字体或中文变方块 | 检查微软雅黑等中文字体，可设置 `VOX_FONT` 为实际字体文件路径 |
| 中文变成问号 | 检查原 JSON 编码和 PowerShell 的 UTF-8 管道设置，不对损坏文本继续生成 |
| `Another process is operating this project` | 同一作品已有进程操作；先核对原进程，避免并发运行同目录 |
| 任务结果未知 | 检查原节点和 journal，不能清空日志后重投 |
| A-roll 时长不符 | 对照原片段与生成结果，修复明确问题；新的生成需重新确认 |
| 成片看起来不够清晰 | `output_size` 只是本地尺寸；更高原生视频质量需要新模型请求及确认 |

## 13. 可选：比较风格与本地元素动画

已有分镜、确实需要比较两种画风时，可以执行：

```powershell
.venv/Scripts/python -X utf8 scripts/style_bakeoff.py out/paper-flight swiss-modern,newsprint-editorial
```

这会调用图片模型制作候选，消耗图片生成额度，不是免费预览。先确定候选数量；选中后修改 `theme`，再制作正式关键帧。不要在已经确认的成片中无意间新增候选。

需要精确控制单个纸片的位置、旋转和透明度时，可用本地 rembg 抠图和 ffmpeg 元素动画流程，详见 [local-engine.md](local-engine.md)。它需要额外的元素配置，不会因运行普通 pipeline 自动启用，也不等同于 LibTV 图生视频。

## 14. 日常最短流程

对话使用：说明主题、时长、比例、素材路径、风格和画布 → 审文案分镜 → 审图试听 → 确认具体视频请求 → 看成片。

自己执行：init → 编辑 beats.json → preflight → audio → keyframes / croll_keyframes / host_plates → 审图试听 → clips / host_clips / aroll_clips 的逐项确认 → assemble / aroll_assemble → verify → 完整播放。

视频确认前，准备工作可以继续；视频提交必须落在实际批准的范围内。
