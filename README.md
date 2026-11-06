# Vox Director · LibTV CLI

将主题、照片、口播视频或数字主持人制作成 Vox 风格纸张拼贴视频。
图片、视频、配音、音乐通过 **LibTV CLI** 生成，转写和抠图在本地运行，`ffmpeg` 完成字幕、混音和剪辑。

本项目改编自 [Alisa0808/vox-director](https://github.com/Alisa0808/vox-director)，保留其 MIT 许可证、创作参考和叙事 / 视觉设计。不需要 Atlas Cloud API key。

首次使用请阅读 [完整中文操作手册](references/user-guide.zh.md)：包含对话指令模板、PowerShell 全流程、四种模式、视频确认、修改恢复与成片验收。

## 安装

需要 Python 3.10+、LibTV CLI、ffmpeg / ffprobe 和中文字体。CLI 接口依据官方 [1.1.3 文档包](https://liblibai-web-static.liblib.cloud/cli/1.1.3/libtv-cli-skill.zip)，不是同名的 Liblib OpenAPI 第三方 CLI。

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
libtv login web --open
```

macOS / Linux 使用 `.venv/bin/python`。可用 `LIBTV_CLI` 指定可执行文件路径，`VOX_FONT` 指定支持中文的字体。Windows 默认使用微软雅黑，macOS 使用 PingFang，Linux 使用 Noto Sans CJK。

## 制作一个作品

编辑 `examples/libtv-broll.beats.json` 的主题、旁白和分镜，或由 agent 根据你的需求编写。

```powershell
.venv/Scripts/python scripts/pipeline.py init out/my-film --spec examples/libtv-broll.beats.json
.venv/Scripts/python scripts/pipeline.py preflight out/my-film
.venv/Scripts/python scripts/pipeline.py run out/my-film --execute
```

已有画布，在 `init` 后加 `--project-id <UUID>`。`preflight` 只读检查，`run --execute` 执行完整生成计划并消耗 LibTV 额度。作品、素材和 `final.mp4` 均在 `out/my-film/`。

四种模式的配置见 [SKILL.md](SKILL.md)。模式覆盖主题 B-roll、照片 C-roll、视频编辑 A-roll 和双层数字主持人 Host。声音参考的 CLI 兼容路线见 [voices.md](references/voices.md)。

迁移已有上游分镜：先保存到 `out/my-film/beats.json`，再运行：

```powershell
.venv/Scripts/python scripts/pipeline.py migrate out/my-film
```

原配置保存为 `beats.before-libtv.json`；媒体原件保留，旧生成指针清理，模型改为 LibTV 默认。然后在配置中填入 `libtv.project_id`。模型替换需要重新验收视觉效果，原平台音色 ID 不通用。

## 恢复、验证与测试

重复运行原命令会复用已完成请求，未知任务不会自动重投。`.libtv/vox/` 是恢复记录，不应清空。修改 prompt 或 generation_revision 表示新的付费请求。

```powershell
.venv/Scripts/python -m unittest discover -s tests -v
.venv/Scripts/python scripts/pipeline.py verify out/my-film
```

`verify` 输出 SHA-256、解码验证和三张抽帧。它不代替旁白准确性、画面和口型检查。

视频节点默认要求逐项确认：首次运行到视频阶段会保存 `video-plan-<hash>.json` 并停止。确认模型、时长、提示词和参考素材后，用 `pipeline.py approve-video <目录> --request-hash <hash> --confirmation "具体确认内容"` 记录同意，再续跑。`--execute` 或普通“继续”不会跳过此门槛。

本地 ASR / rembg 首次运行会下载开源模型；之后可以使用缓存或本地模型目录。`voice.clone_ref` 对当前 CLI 的适配方式、限制和收费差异见 [声音说明](references/voices.md)。

MIT © 2026 Alisa Qian；LibTV 适配修改见 Git diff。
