# Vox Director LibTV

默认用中文交流，代码和技术术语保留英文。先读 `SKILL.md`。

这是基于 Alisa0808/vox-director 的 LibTV CLI 分支。保持原 MIT 版权声明。
生成操作经 `scripts/libtv_provider.py` 调用 CLI，不引入 Atlas API 或凭据。
画布 ID 从作品 `beats.json` 的 `libtv.project_id` 读取，不写死私人账户或节点。
CLI 模型和参数需根据实时 schema 验证；测试 fixture 只用于回归测试。

修改生成 / 恢复逻辑后运行 `python -m unittest discover -s tests -v`。
媒体验证用 `pipeline.py verify`；网络集成测试会生成收费素材，必须符合当前任务授权。
测试时创建或运行任何视频节点，必须先展示具体计划并取得用户明确确认；“继续”不等于视频生成授权。不得关闭 require_video_approval 来绕过确认。
构建 `.skill` 时排除 `.git`、`.venv`、`out`、任务日志、缓存和凭据。
