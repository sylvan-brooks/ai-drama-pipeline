# ai-drama-pipeline：AI 短剧从剧本到成片的流程骨架

一套把 AI 短剧从"对标拆片"一路做到"发布版成片"的脚本和模板：拆对标作品的节奏、填分镜表、调生成接口（带账本，防重复扣费）、放大并按镜头插帧到 60fps、加字幕配音混音。

A skeleton pipeline for AI short dramas: reference analysis, shot lists, a provider-agnostic async generation client with a cost ledger, per-shot upscaling + frame interpolation to 60fps, and subtitle / voice-over / loudness finishing.

## 为什么做这个

AI 短剧每一步都在花钱，而且最容易浪费钱的地方不在生成本身：

- 同一个任务手滑提交两次，钱扣两份；
- 生成成功了，下载那一步网断了，结果找不到，只能重新生成；
- 到了视频阶段才发现人物长得不对，前面的图和打样全白费；
- 放大插帧的时候跨着硬切插，切点上生出两个镜头叠在一起的糊帧。

这套流程就是冲着这几件事做的：越往后越贵，所以每道关卡都卡在前一步还便宜的时候。

```mermaid
flowchart LR
  A[对标拆片] --> B[剧本分段] --> C[分镜表] --> D[定妆图 / 场景图]
  D -->|并排比过对标| E[低清打样] -->|动作顺序人物都对| F[定稿生成]
  F --> G[放大 + 插帧] --> H[字幕 + 配音 + 混音] --> I[成片检查]
```

## 目录

```
analyze/
  grid.py            接触表: 每隔几秒抽一帧拼网格, 看节奏和镜头切换
  strips.py          动作条: 一个动作 / 运镜均匀抽几帧摊开看
  crops.py           原画局部: 某一刻裁一块原分辨率, 看皮肤布景字体
  motion.py          运动量: 逐帧变化量和整体平移, 尖峰 ≈ 硬切
pipeline/
  gen.py             生图 / 生视频 / 配音的异步任务客户端: 提交 → 轮询 → 先记账再下载
  providers.example.json   接口地址、模型名、单价、返回字段 (复制成 providers.json 改)
  upscale60.py       Real-ESRGAN 放大 + 按硬切分镜头用 RIFE 插帧到 60fps
  finish.py          字幕 (两层投影, 淡入淡出) + 画外音 + 原声自动压低 + 响度归一
templates/
  shotlist.md        分镜表 + 出片前自查
  seg.example.json   finish.py 的段落配置示例
docs/workflow.md     每一步怎么做、卡什么关
```

## 快速开始

需要 Python 3.9+、Pillow、NumPy、ffmpeg。

```bash
# 拆一部对标作品
python analyze/grid.py ref.mp4 out/ref_grid 0 60 1
python analyze/motion.py ref.mp4 out/ref_motion.npz 30

# 生成 (先写 providers.json, key 走环境变量)
export GEN_API_KEY=...
python pipeline/gen.py img a_front "角色正面定妆, ..." --root work
python pipeline/gen.py video seg01 prompts/seg01.txt --ref a_front --res 480p --root work

# 放大插帧 (要 realesrgan-ncnn-vulkan 和 rife-ncnn-vulkan)
export REALESRGAN=/path/to/realesrgan-ncnn-vulkan
export RIFE=/path/to/rife-ncnn-vulkan
python pipeline/upscale60.py work/gen/video/seg01.mp4 work/gen/video/seg01_60fps.mp4 --cuts 3.5,7.2

# 字幕 + 配音 + 混音
python pipeline/finish.py templates/seg01.json --still 2.0
python pipeline/finish.py templates/seg01.json
```

完整步骤和每道关卡卡什么，见 [docs/workflow.md](docs/workflow.md)。

## 依赖的外部工具

不随仓库附带，自己从官方发布页下载：

- [Real-ESRGAN ncnn Vulkan](https://github.com/xinntao/Real-ESRGAN)（BSD-3）：放大。
- [rife-ncnn-vulkan](https://github.com/nihui/rife-ncnn-vulkan)（MIT）：插帧，默认用 `rife-v4.6` 模型。
- [FFmpeg](https://ffmpeg.org/)。

生成接口用哪家都行，只要是"提交任务拿 taskId，再按 taskId 查结果"这一类。地址、模型名、单价、返回字段都在 `providers.json` 里改，代码里不写死任何一家。用之前确认你选的模型生成的内容能不能商用。

## 局限

- 这是骨架：剧本怎么写、提示词怎么写、选哪个模型，都要按你自己的题材和对标去定。仓库里没有现成的提示词，也没有"调好的参数"。
- `gen.py` 的请求体字段是按常见写法给的，不同服务商字段名可能不一样，对不上就改 `build_body()`。
- 放大插帧很慢。先用 `--frames` 跑几十帧，看效果，也估一下整段要多久。
- 放大能让边缘更清楚，但会有涂抹感，补不回生成时就没有的细节。

## 给 AI 用

仓库根目录有 `SKILL.md`，放进 Claude Code 的 `~/.claude/skills/ai-drama-pipeline/` 或 Codex 的 skills 目录，说「按这个流程做一段 AI 短剧」就会照着做，在每道花钱的关卡前停下来问你。这个 Skill 给 AI 用效果会更好，直接丢给 AI 就可以了。

## 许可

MIT
