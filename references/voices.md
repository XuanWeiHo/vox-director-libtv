# 配音、声音参考与音乐

## 普通配音

```json
"voice": {"model": "Minimax-speech-2.8-hd", "language": "zh", "speed": 1.0}
```

未指定音色时使用实时 schema 中的默认 voiceCard。指定 voice_id 时必须是该 LibTV 模型可用的音色 ID，不能复制上游 xAI 的 leo 等 ID。每个 beat 单独生成，保持同一音色配置。

## 声音参考

当前 CLI 1.1.3 禁止音频资源连向音频生成节点，即使 Seed Audio schema 显示 audio2audio。因此本适配使用 **Seedance 2.5 的 audio2video 入口生成带参考音色的语音，再由 ffmpeg 提取音轨**。

```json
"voice": {
  "clone_ref": "C:/media/reference.mp3",
  "model": "Seedance 2.5",
  "language": "zh",
  "clone_duration": 8
}
```

参考音频需符合模型时长限制，内容须可用于声音复现。clone_duration 是每段生成视频时长；未指定时按旁白长度估算并受实时模型范围约束。此路线按视频模型计费，比普通 TTS 成本高，且音色和逐字准确性需要试听与转写校验；不要宣称与原专用语音模型完全等价。脚本保留生成视频节点及任务回执。

如果已有旁白，给 beat 设置 `audio_source` 即可复用，不执行生成。空旁白生成本地静音片段。

## 音乐

`music` 可为提示词字符串，或：

```json
"music": {"model": "Eleven Music V3", "prompt": "轻快的纪录片配乐", "duration": 30}
```

duration 以秒配置，按模型 schema 换算。纯器乐约束写入提示词。也可设 `music: {"source": "C:/media/bgm.mp3"}` 导入本地音乐，或 `music: false` 关闭。成片 BGM 循环覆盖全长，旁白出现时压低 BGM。

`mix.music` 和 `mix.voice` 控制音量，默认 0.6 与 1.25。
