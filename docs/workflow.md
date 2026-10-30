# 从剧本到成片

AI 短剧每一步都在花钱：生图按张、生视频按秒、配音按字。这套流程的思路是**越往后越贵，所以每道关卡都在前一步便宜的时候卡住**。

```mermaid
flowchart LR
  A[对标拆片] --> B[剧本分段]
  B --> C[分镜表]
  C --> D[定妆图 / 场景图]
  D -->|并排比过对标| E[低清打样]
  E -->|动作顺序人物都对| F[定稿生成]
  F --> G[放大 + 插帧]
  G --> H[字幕 + 配音 + 混音]
  H --> I[成片检查]
```

## 0. 对标拆片（免费）

先找一两部你想做到的那种水平的作品，把它拆开看：

```bash
python analyze/grid.py ref.mp4 out/ref_grid 0 120 1 6 8 320      # 每秒一帧的接触表, 看节奏和镜头切换
python analyze/motion.py ref.mp4 out/ref_motion.npz 30            # 逐帧变化量: 尖峰 ≈ 硬切, 平移 ≈ 运镜
python analyze/strips.py ref.mp4 out/ref_strips.png 6 240 "12.0:14.5,30.2:33.0"   # 把一个动作 / 运镜摊开看
python analyze/crops.py ref.mp4 out/ref_crops "15.2,0.2,0.1,0.8,0.6"              # 原画局部: 皮肤、布景、字体
```

数一下：平均几秒一个镜头？开头几秒交代了什么？特写和全景的比例？这些数会直接用在下面的分镜表里。

## 1. 剧本分段 → 2. 分镜表（免费）

按 [templates/shotlist.md](../templates/shotlist.md) 填。每段的长度按视频模型一次能生成的上限来，每个镜头写清楚秒段、景别、画面里发生什么、对应哪句台词。硬切点顺手记下来，后面插帧要用。

## 3. 定妆图 / 场景图（便宜）

每个角色、每个场景先出图。**出完和对标作品的帧并排放在一起比**，逐条写差在哪，改提示词再出，比到满意为止。

这一步省不得。视频模型会把定妆图里的问题原样放大到每一帧，到了视频阶段再发现人物不对，前面的钱全白花。

## 4. 低清打样 → 5. 定稿（贵）

先用最低分辨率出一版，只看三件事：动作对不对、镜头顺序对不对、人物还是不是那个人。都对了再出定稿分辨率。

```bash
python pipeline/gen.py video seg01_draft prompts/seg01.txt --ref a_front --ref scene_x --res 480p --root work
python pipeline/gen.py video seg01_final prompts/seg01.txt --ref a_front --ref scene_x --res 768p --root work
```

`--ref` 写之前生成过的 name，会从账本里取它的结果地址，不用重新上传。

## 6. 放大 + 插帧（本地，免费，慢）

```bash
python pipeline/upscale60.py work/gen/video/seg01_final.mp4 work/gen/video/seg01_60fps.mp4 --cuts 3.5,7.2 --frames 30   # 先跑 30 帧看效果和速度
python pipeline/upscale60.py work/gen/video/seg01_final.mp4 work/gen/video/seg01_60fps.mp4 --cuts 3.5,7.2
```

插帧一定要按镜头分开插。跨着硬切插，切点上会生出一两帧两个镜头叠在一起的糊帧，放慢看很明显。`--cuts` 不给会自动找，但淡入淡出、闪白这类切换可能找不到，最好手给。

## 7. 字幕 + 配音 + 混音 → 8. 检查

```bash
python pipeline/gen.py tts seg01_vo01 "这一句画外音" --voice <音色ID> --root work
python pipeline/finish.py templates/seg01.json --still 2.0     # 先出一帧看字幕样式
python pipeline/finish.py templates/seg01.json
```

画外音出来的时候，原片的环境声会自动压低再恢复，带斜坡，不会一跳一跳的。最后统一对到目标响度。

技术检查（字幕对不对、响度、帧率）过了，再把整段从头看一遍。

## 花钱这件事

- `gen.py` 每次提交前按 `providers.json` 里的单价报预估花费和余额。单价是你自己填的，以服务商后台扣费为准。
- 同一个 name 生成成功过就不会再提交，要重来换个 name。
- 提交成功后先把结果地址记进 `ledger.jsonl` 再下载。下载失败用 `gen.py fetch <name>` 重下，不会重复扣费。
- `gen.py ledger` 看每个模型提交了几次、估算花了多少。
