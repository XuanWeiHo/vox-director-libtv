---
name: vox-director-libtv
description: 使用 LibTV CLI 制作 Vox 风格纸张拼贴解说视频或广告，支持主题、照片主体、口播视频和数字主持人，包含分镜、图片、动态、配音、音乐、字幕和 ffmpeg 成片。用于完整视频制作，而非普通单张生图。
---

# Vox Director · LibTV

使用 LibTV CLI 生成图片、视频、配音和音乐；本地 faster-whisper 转写、rembg 抠图、ffmpeg 剪辑合成。无需 Atlas Cloud API key。保留上游叙事库和拼贴提示词设计。

## 制作前

1. 读取 [references/beat-layer.md](references/beat-layer.md) 选择适合主题的叙事结构，读取 [references/prompt-guide.md](references/prompt-guide.md) 设计拼贴风格。
2. 以一个 `out/<project>/beats.json` 管理一个作品。媒体路径使用绝对路径；JSON 使用 UTF-8。不要把用户素材路径当作已上传资源。
3. 检查 `libtv --version`、登录状态、`ffmpeg`、`ffprobe` 与 `requirements.txt` 依赖。现有脚本验证于 LibTV CLI 1.1.3。用 `.venv` Python 执行脚本；详见 README。
4. 从 `examples/libtv-broll.beats.json` 建立分镜，保留用户指定主题、时长、比例和素材。分镜列出旁白、每镜画面、镜头运动、元素运动。展示分镜并确认视觉方向；已有明确指令或已批准分镜可直接继续。
5. `libtv.project_id` 必须绑定精确画布。模型按实时 `libtv model search -t <image|video|audio>` 和 `libtv model "展示名"` 发现。`pipeline.py preflight` 会只读检查画布、模型和参数。

## 统一执行

```powershell
python scripts/pipeline.py init out/my-film --spec examples/libtv-broll.beats.json
python scripts/pipeline.py preflight out/my-film
python scripts/pipeline.py run out/my-film --execute
```

`init` 默认创建画布；已有画布传 `--project-id <UUID>`。`run` 不带 `--execute` 只展示计划，不生成。模型生成会消耗当前 LibTV 账户额度；遵循用户已经授权的制作范围，不额外生成变体。

**视频测试必须先确认。** `--execute` 不是测试视频授权。适配层在创建或运行视频节点前输出 `video-plan-<hash>.json` 并停止；展示其中的模型、时长、提示词、素材和数量，取得明确同意后用 `pipeline.py approve-video <目录> --request-hash <hash> --confirmation "用户原确认"` 记录，再续跑。改参数会产生新计划，需要新确认。已完成结果只读恢复无需重复生成授权。不得将“继续”解释为视频生成同意。

风格需要比较时，用 `style_bakeoff.py <project_dir> 风格1,风格2` 生成明确数量的候选。选定后设置 `theme`。关键帧须先检查是否具有纸张层次、撕边、拼贴元素和正确主体，尤其是图中文字；确定方向后再批量执行。批量管线适用于视觉方向已确定的作品。

## 四种输入

| 输入 | 配置 / 路由 |
|---|---|
| 主题 B-roll | 默认模式：audio → keyframes → clips → assemble |
| 人物 / 产品照片 C-roll | `mode: croll`、`anchor_photo`、`croll_subject`，使用 croll_keyframes，再进入同一成片流程 |
| 现有口播视频 A-roll | 先 `asr_beats.py <目录> <视频> --language zh`，审阅时间戳和识别文字、补充 theme，然后绑定 `libtv.project_id`；aroll_clips → aroll_assemble |
| 数字主持人 Host | `host.avatar` 指向头像或已生成图片；该 beat 只有一个 `kind: host` 镜头；audio → host_plates → host_clips，再与其余镜头合成 |

C-roll 保留照片主体、服装或产品标签约束。Host 使用人物绿幕和独立背景两套素材，保留人物生成视频自身音轨，不对主持人镜头变速。两者均需视觉与口型验收，提示词约束不等于逐像素保证。

A-roll 从原始口播截取精确时间范围，视频编辑遵循源时长和比例，合成时使用原始音轨。时长不符时报错，不悄悄裁短或拼出缺镜头成片。生成模型仍可能改变面部运动，应对照原片验收。

## 音频与本地动画

- 配音音色、声音参考、音乐或导入音频，读取 [references/voices.md](references/voices.md)。`audio_source` 可指定每个 beat 的现成配音，`music.source` 可导入 BGM，`music: false` 禁用 BGM。
- ASR 默认本地 `small` 模型；首次运行下载模型。可用 `--asr-model <本地模型目录>` 离线运行。生成的时间戳来自真实识别，文字需校对。
- 元素级动画读取 [references/local-engine.md](references/local-engine.md)，`extract_elements.py` 使用本地 rembg 输出透明 PNG，`motion.py` 渲染元素关键帧。
- 主持人的参数、位置和验收流程读取 [references/host-mode.md](references/host-mode.md)。

## 任务恢复与交付

- 每个项目 `.libtv/vox/` 保存请求、节点、上传指纹和回执。`--run` 阻塞到终态，不再套旧轮询或超时重投。
- 结果未知时重运行原阶段仅恢复原节点；无结果会停止，不重新扣费。不要删除日志来“修复”未知任务。诊断流程见 [references/models-and-gotchas.md](references/models-and-gotchas.md)。
- 有意重新生成时先确认旧任务已终止，再修改具体提示词或 `libtv.generation_revision`，并清除对应镜头旧输出字段。更改 revision 会允许新付费任务。
- CLI 官方下载路径负责平台水印规则；脚本不绕过水印。`watermark` 只控制本地额外片尾标记。
- `pipeline.py verify` 检查文件、音视频流、完整解码并输出抽帧、SHA-256 和 `verification.json`。实际查看抽帧、试听音量、检查字幕和口型后再交付。仅 task 成功不等于成片完成。
- 任意镜头失败应修复并续跑；禁止交付漏镜头或静默丢失原音的作品。
