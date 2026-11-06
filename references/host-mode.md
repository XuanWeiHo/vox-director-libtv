# 数字主持人

每个 Host beat 仅包含一个 kind=host 镜头。host.avatar 使用本地图片、图片 URL 或同一画布的 libtv://引用；16:9 的 host.position 支持 left/center/right，9:16 使用 lower，具体以 host.py 的布局表为准。host.size 是头部高度占画面高度的比例（0.08–0.6）。

先生成旁白，再制作人物绿幕图和无人的背景图。人工检查绿幕是否均匀、人物身份和画面空区后，生成两段视频：人物由头像和填充到精确片长的音频共同驱动；背景从拼贴关键帧生成。

默认人物和背景均使用 Seedance 2.5，可分别由 host.person_video_model / host.world_video_model 覆盖。两个模型都必须支持所需输入和时长。图像可由 image_model 覆盖。

合成时以人物视频自身音轨为准，保留原始配音到 narration_audio_reference。不要把原配音覆盖到生成后已改变节奏的嘴型上。人物镜头禁止变速。背景镜头必须覆盖人物镜头时长。

批量制作可执行 `pipeline.py run <目录> --execute`；逐步检查可用 `host_plates.py` 和 `host_clips.py <目录> --yes`。`--yes` 执行当前计划，已有用户授权无需重复确认。

成片须检查人物形状、绿幕边缘、背景是否漂入人物区、旁白是否逐字正确及口型。模型提示词并不保证这些视觉结果。
