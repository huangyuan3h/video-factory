# video-use 经验吸收（Video Factory）

来源：[browser-use/video-use](https://github.com/browser-use/video-use)（MIT），`SKILL.md` 的 Hard Rules + Self-eval，`helpers/render.py`。
分支：`feat/video-use-qa`（基于 `release/vf-2026-10-03`，未合并、未上传）。日期 2026-10-06。

## 1. 硬渲染规则 —— 差距表

| 规则 (video-use) | 现状（改前） | 位置 | 本次处理 | 工作量 |
|---|---|---|---|---|
| 字幕最后叠加（最上层） | **已有**：`all_clips = video_clips + subtitle_clips` | `compose_service.py` `_compose_video_sync`（改后 L845） | 加注释 + 测试锁定（`test_subtitles_are_the_last_layer`）；render QA 在每个切点 ±1.5s、字幕生效时检查底部字幕带有字 | XS |
| 逐段抽取 + `-c copy` 无损拼接（避免二次编码） | **不适用/未采纳**：MoviePy 单次合成、单次编码，本来就没有二次编码；段间 crossfade 跨段，逐段编码会破坏转场 | `_create_video_track` | 不改主渲染。仅自动修复路径（音频重混）用 `-c:v copy`，视频码流逐字节不变 | — |
| 每个拼接点 ~30ms afade in/out 防爆音 | **缺失**：旁白段 `AudioFileClip(...).with_start(seg_start)` 直接拼 | `_create_audio_track`（改前 L316-320） | `_join_fade()`：每段旁白 `AudioFadeIn(0.03)+AudioFadeOut(0.03)`（改后 L386）；QA 检测每个旁白起止点的二阶差分尖峰 | S |
| 叠加层 `setpts=PTS-STARTPTS+T/TB` 对齐 | **不适用**：叠加由 MoviePy `with_start` 定位，不走 ffmpeg overlay | — | 无 | — |
| SRT 时间戳在输出时间轴上 | **部分**：字幕 TextClip 用 `start_offset`（封面停留）平移，正确；但 `subtitles.ass` / `task.log` 是旁白时间轴，且 task.log 只保留 0.1s | `video_service.py`、`compose_service.py` L835 | 渲染时写 `timeline.json`（每段旁白在**输出时间轴**上的精确起点/时长，含封面停留）；QA / 重混优先读它，旧任务回退 task.log | S |
| 字体加载断言（失败要响，不静默回退） | **缺失**：`_find_font_path` 找不到中文字体就退到 DejaVu（无 CJK，出豆腐块）；单条字幕或整条字幕轨失败只 warning 继续 → 成片可能无字幕 | `_find_font_path` 改前 L30；L663 / L669 | `SUBTITLE_STRICT=True`：`_require_font_path` 校验字体能加载且覆盖所有字幕字形，否则 `SubtitleFontError`；字幕失败改为抛错停渲染。FONT_PATHS 在 DejaVu 前加 Linux Noto CJK（macOS 仍优先 STHeiti，渲染不变） | S |

## 2. 发布前自动 QA —— 差距表

| 检查 | 现状（改前） | 位置 | 本次处理 | 工作量 |
|---|---|---|---|---|
| ebur128 响度 + true peak | **部分**：只看 `bgm.json` 里的计划值；`bgm.check_bgm_loudness` 写了但没接到成片上；没有成片 TP | `bgm.py` L525 | `render_qa.py`：成片 I（-24±2.5，即现行 `NARRATION_REF_LUFS`）、TP ≤ -1 dBTP；旁白 stem -24±2.5；BGM bed 按 bgm.json 实际片段+增益量 = -42±（`TARGET_BED_LUFS`，Yuan 选定）且低于旁白 ≥15dB；封面 1-3s 非静音坑（-42±3）。**目标值未改** | M |
| ffprobe 时长 vs 计划 | **缺失**（人工） | — | format 与 video stream 各自对比计划（±0.25s），防止视频流短于音频被 format 掩盖 | S |
| 切点 ±1.5s 抽帧：跳帧/黑帧/字幕遮挡 | **缺失**（agent 人工截图） | — | 每个段切点 ±1.5s 抽 10fps 灰度帧：黑帧、单帧闪；字幕生效时底部带“墨量”≥0.2% | M |
| 拼接爆音 | **缺失** | — | 每个旁白起止点 ±15ms 二阶差分峰 / 全段 P99 > 8 且绝对值 > 0.02 判爆音 | S |
| 封面/首帧集数 OCR（系列） | **缺失**（ep39 曾出现 24 vs 39 错卡） | — | tesseract（eng）在 t=1.5s、0.1s：标题行裁剪的**第一个数字**必须是 N（eng 会把「集」读成一位杂数字，如 41→`415`，故接受 N+1 位），全图需含 N；无 tesseract 时记录 skipped | S |
| 最多 3 轮自动修复，之后交人 | **缺失** | — | `fix_loop`：只有音频问题（TP/bed/爆音）有确定性修复 = 从 stem 重混（30ms 淡入淡出，`-c:v copy`，保留 `output.pre_fix.mp4`）；视觉/OCR/时长 → 直接 `needs_human` | S |

入口：
- `apps/worker/scripts/render_qa.py TASK_DIR [--episode N] [--fix] [--json]` → 写 `render_qa.json`，退出码 0/1。
- `vf qa --dir TASK_DIR --render`（可选开关，默认行为不变）：在原 script QA 基础上加 `render_qa` 段，无 output.mp4 直接 FAIL。

## 3. 可选：LLM 输出 JSON 编辑表 + 确定性渲染
VF 已是“脚本 JSON（script.json/段落）→ 确定性渲染”，`vf render --approved-script` 即确定性重渲；没有 ReelBatch 那种自然语言改稿需求，**本次未新增 EDL**。ReelBatch 侧已实现（`pipeline_real/edl.py`）。

## 4. 未采纳及原因
- 逐段 `-c copy` 拼接：MoviePy 单编码 + 跨段 crossfade，改成逐段会改变画面且收益小。
- 统一 loudnorm 到 -14 LUFS：VF 现行标准是旁白 -24 / bed -42，无理由不改目标。
- 词级 ASR 对齐切点、多 take 选择、调色预设、动画：与 VF 指标讲解形态无关或已有对应工具（subtitle_sync_report / indicator_qa）。
- 视觉问题自动修复：没有确定性修法，按规则 3 轮内只修音频，其余交人。

## 5. 验收（见分支提交说明 / 最终报告）
- 新增 `tests/test_video_use_render_qa.py`；改动 3 个旧测试（版式测试显式 `SUBTITLE_STRICT=False`，并新增 strict 抛错版本）。
- ep41 成片（release 渲染）离线跑 render QA：全部 PASS；把封面集数改成 24 → OCR FAIL；重混修复后响度不变、视频码流逐字节一致。
