# LibTV 模型与执行细节

## 模型发现

`libtv model search -t image` / `video` / `audio` 查询目录，`libtv model "展示名"` 查询 schema。
默认图片为 General image V2，视频为 Seedance 2.5，配音为 Minimax-speech-2.8-hd，音乐为 Eleven Music V3。可在 beats.json 覆盖，模型不可用时明确报错，不静默换模型。

模型参数按 schema 验证。图片的 resolution 映射为 quality（如 1K）；视频 duration 的范围由实时 schema 决定。音乐的 duration 可能以毫秒计。视频编辑使用源视频的自适应比例与时长，不把普通生成参数当作编辑参数。

## CLI 1.1.3 的真实返回

- 无引用创建返回 nodeKey；创建并连线返回 newNodeKey 和 reactFlowNode。
- `--run` 会等待结束，输出可能包含多段 JSON 和进度日志；使用最终节点 taskInfo 和媒体 url 验证。
- `download` 成功通常输出文件路径，不是 JSON；验证实际下载文件，并按目标格式转换。
- `-s quality=1K` 可自动分配到 settings。不要使用 `-s settings.quality=1K`，当前版本把它视为非法字段。
- 音频节点要显式指定 schema 的 scene，例如 Text-to-Speech 或 Music。
- 引用使用真实项目节点和 `--left`，不能直接写 audioList/imageList 等派生字段。
- `{{Node <nodeKey>}}` 是 CLI 的正式提示词引用语法。旧模板中的 @image1 等须映射到对应节点。
- schema 存在某模式不保证 CLI 连线规则允许该模式；Seed Audio 的音频→音频引用在当前 CLI 中会被拒绝，见 voices.md。

## 恢复

请求以参数、引用、镜头标签和 generation_revision 的 SHA-256 标识；先写本地 journal，再创建节点并运行。进程锁阻止同一项目被两个脚本同时写入。

若 CLI 退出或连接中断：保留日志，重新执行原阶段，回读原节点。节点已完成则恢复输出；仍在运行或结果未知则报错并停止。不得因为超时再次 `--run`。

创建 / 上传回执丢失可按日志中的确定名称查找原节点。只有确认没有生成被接受后才能人为修复 prepared 状态。不要删除 journal 强制重投。

模型明确拒绝或参数错误时修改具体条件，再重新生成。不要无条件切换模型或对内容拒绝进行绕过。

## Windows 与成片

JSON 和源码使用 UTF-8；从 PowerShell 写含中文的文件时使用 UTF-8，不用默认 ASCII 管道。执行 Python 用脚本文件或参数；若确需管道先设置 `$OutputEncoding = [System.Text.UTF8Encoding]::new($false)`。

concat 清单使用正斜杠路径并转义单引号。中文字体缺失会明确报错，可设 VOX_FONT。下载后的 MP3 真实转码，不只是改扩展名。

ASR 通过 ffmpeg 解码为 16kHz float32，再送 faster-whisper，避免 PyAV 版本 API 差异。所有时间戳取自实际音频。A-roll 不允许缺片段或明显时长不匹配。
