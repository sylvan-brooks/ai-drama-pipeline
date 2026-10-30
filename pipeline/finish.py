"""成片收尾: 画面 + 字幕 + 画外音 + 原声 → 发布版. 一段一份 json 配置:
{"video": "seg01_60fps.mp4", "out": "seg01_final.mp4",
 "subs": [{"text": "第一句字幕", "start": 1.9, "end": 5.6}, ...],
 "vo":   [{"file": "vo01.wav", "start": 2.0, "gain_db": 0}, ...],      (可空)
 "duck_db": -6, "lufs": -16, "limit": 0.8,
 "style": {"font": "字体文件路径", "size": 0.045, "y": 0.78, "color": [255,255,255], "shadow": [0,0,0], "track": 0.04}}
python finish.py <seg.json> [--still 3.0]   (--still 只出一帧带字幕的 png 看样式, 不编码)
路径相对 json 所在目录. 字体不给就找系统中文字体.
字幕: 每条一张整帧透明 png, 两层投影 (贴身压暗 + 大半径柔光), 淡入淡出 0.12s.
声音: 画外音期间原声按 duck_db 压低, 0.2s 斜坡进 / 0.3s 斜坡出; 再按"加增益 → 限幅 → 重测"循环对到目标响度.
退出码: 0 成功 / 1 参数或配置问题 / 2 ffmpeg 失败."""
import sys, os, json, shutil, subprocess, argparse, tempfile
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FALLBACK_FONTS = ['C:/Windows/Fonts/msyh.ttc', '/System/Library/Fonts/PingFang.ttc',
                  '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc']


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        print(f'失败: {" ".join(cmd[:6])}...\n{r.stderr[-1500:]}', file=sys.stderr); sys.exit(2)
    return r


def size(path):
    r = run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', path])
    return tuple(int(x) for x in r.stdout.strip().split(',')[:2])


def has_audio(path):
    r = run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0', path])
    return bool(r.stdout.strip())


def font_path(style):
    for p in [style.get('font')] + FALLBACK_FONTS:
        if p and os.path.isfile(p):
            return p
    print('找不到中文字体, 在 style.font 里指一个', file=sys.stderr); sys.exit(1)


def render_sub(text, W, H, out, style):
    """整帧大小的透明 png: 字 + 两层投影."""
    fs = round(W * style.get('size', 0.045)); track = round(fs * style.get('track', 0.04))
    font = ImageFont.truetype(font_path(style), fs)
    ink, shadow = tuple(style.get('color', [255, 255, 255])), tuple(style.get('shadow', [0, 0, 0]))
    widths = [font.getlength(c) for c in text]
    tw = sum(widths) + track * (len(text) - 1)
    x0, y0 = (W - tw) / 2, H * style.get('y', 0.78) - fs / 2
    def draw(fill, img, dx=0, dy=0):
        d = ImageDraw.Draw(img); x = x0
        for c, w in zip(text, widths):
            d.text((x + dx, y0 + dy), c, font=font, fill=fill); x += w + track
    base = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    soft = Image.new('RGBA', (W, H), (0, 0, 0, 0)); draw(shadow + (150,), soft); soft = soft.filter(ImageFilter.GaussianBlur(fs * 0.22))
    near = Image.new('RGBA', (W, H), (0, 0, 0, 0)); draw(shadow + (190,), near, 0, fs * 0.03); near = near.filter(ImageFilter.GaussianBlur(fs * 0.05))
    base = Image.alpha_composite(base, soft); base = Image.alpha_composite(base, near)
    draw(ink + (255,), base)
    base.save(out)


def lufs(p):
    r = subprocess.run(['ffmpeg', '-hide_banner', '-i', p, '-af', 'ebur128', '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace').stderr
    try:
        return float(r.split('Integrated loudness:')[1].split('I:')[1].split('LUFS')[0])
    except (IndexError, ValueError):
        return float('-inf')


def main():
    ap = argparse.ArgumentParser(description='字幕 + 画外音 + 原声 → 发布版'); ap.add_argument('cfg'); ap.add_argument('--still', type=float)
    a = ap.parse_args()
    c = json.load(open(a.cfg, encoding='utf-8'))
    here = os.path.dirname(os.path.abspath(a.cfg))
    rel = lambda p: p if os.path.isabs(p) else os.path.join(here, p)
    video, out, style = rel(c['video']), rel(c['out']), c.get('style', {})
    if style.get('font'):
        style['font'] = rel(style['font'])
    W, H = size(video)
    fps = c.get('fps', 60)
    tmp = tempfile.mkdtemp(prefix='finish_', dir=here)
    try:
        pngs = []
        for i, s in enumerate(c.get('subs', [])):
            p = os.path.join(tmp, f'sub{i}.png'); render_sub(s['text'], W, H, p, style); pngs.append(p)

        if a.still is not None:   # 样式预览: 取那一刻的帧, 叠上当时该出的字幕
            fr = os.path.join(tmp, 'frame.png')
            run(['ffmpeg', '-v', 'error', '-y', '-ss', str(a.still), '-i', video, '-frames:v', '1', fr])
            im = Image.open(fr).convert('RGBA')
            for s, p in zip(c.get('subs', []), pngs):
                if s['start'] <= a.still < s['end']:
                    im = Image.alpha_composite(im, Image.open(p))
            still = os.path.splitext(out)[0] + f'_still{a.still}.png'
            im.convert('RGB').save(still); print(still); return

        # 画面: 每条字幕 0.12s 淡入淡出
        inputs = ['-i', video]
        vf, last = [], '0:v'
        for i, (s, p) in enumerate(zip(c.get('subs', []), pngs)):
            d = s['end'] - s['start']
            inputs += ['-loop', '1', '-framerate', str(fps), '-t', f'{d:.3f}', '-i', p]
            vf.append(f'[{i + 1}:v]format=rgba,fade=in:st=0:d=0.12:alpha=1,fade=out:st={max(0, d - 0.12):.3f}:d=0.12:alpha=1,'
                      f'setpts=PTS-STARTPTS+{s["start"]}/TB[s{i}]')
            vf.append(f'[{last}][s{i}]overlay=0:0:eof_action=pass[v{i}]'); last = f'v{i}'
        # 声音: 原声 (画外音期间压低 duck_db) + 画外音
        vo = c.get('vo', []); k = 1 + len(pngs); af = []
        for v in vo:
            inputs += ['-i', rel(v['file'])]
        duck = c.get('duck_db', -6)
        spans = []
        for v in vo:
            dur = float(run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', rel(v['file'])]).stdout)
            spans.append((v['start'] - 0.15, v['start'] + dur + 0.25))
        if has_audio(video):
            amb = '[0:a]aformat=sample_rates=48000:channel_layouts=stereo'
        else:   # 原片没声音 (有些生成模型低分辨率档不出声): 垫一段静音
            dur = float(run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', video]).stdout)
            amb = f'anullsrc=r=48000:cl=stereo,atrim=0:{dur:.3f}'
        if spans:   # 压低带 0.2s 斜坡进、0.3s 斜坡出, 不硬跳
            r = [f'clip(min((t-{s:.2f})/0.2,({e:.2f}-t)/0.3),0,1)' for s, e in spans]
            expr = r[0]
            for x in r[1:]:
                expr = f'max({expr},{x})'
            amb += f",volume='1-{1 - 10 ** (duck / 20):.4f}*{expr}':eval=frame"
        af.append(amb + '[amb]')
        mix = ['[amb]']
        for j, v in enumerate(vo):
            af.append(f'[{k + j}:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={round(v["start"] * 1000)}:all=1,'
                      f'volume={v.get("gain_db", 0)}dB[vo{j}]'); mix.append(f'[vo{j}]')
        af.append(f'{"".join(mix)}amix=inputs={len(mix)}:normalize=0:duration=first[mixed]')
        pre = os.path.join(tmp, 'pre.wav')   # 只跑声音图; 画面图的输出没 map 会报 unconnected output
        run(['ffmpeg', '-v', 'error', '-y', *inputs, '-filter_complex', ';'.join(af), '-map', '[mixed]', pre])
        # 限幅会把尖的瞬态压下去, 整体响度跟着掉, 所以加增益 → 限幅 → 重测, 最多 4 轮
        target = c.get('lufs', -16); limit = c.get('limit', 0.8); I0 = lufs(pre); final_a = os.path.join(tmp, 'final.wav')
        if I0 == float('-inf'):
            shutil.copy(pre, final_a); gain, I = 0.0, I0   # 全是静音, 不做响度
        else:
            gain = target - I0
            for _ in range(4):
                run(['ffmpeg', '-v', 'error', '-y', '-i', pre, '-af', f'volume={gain:.2f}dB,alimiter=limit={limit}:level=false', final_a])
                I = lufs(final_a)
                if abs(I - target) < 0.3:
                    break
                gain += target - I
        run(['ffmpeg', '-v', 'error', '-y', *inputs[:2 + 8 * len(pngs)], '-i', final_a,
             *(['-filter_complex', ';'.join(vf), '-map', f'[{last}]'] if vf else ['-map', '0:v']),
             '-map', f'{1 + len(pngs)}:a', '-c:v', 'libx264', '-preset', 'slow', '-crf', str(c.get('crf', 16)), '-pix_fmt', 'yuv420p',
             '-profile:v', 'high', '-r', str(fps), '-c:a', 'aac', '-b:a', '256k', '-movflags', '+faststart', out])
        print(f'{out}  原混音 {I0:.1f} LUFS → 增益 {gain:+.1f} dB → {I:.1f} LUFS')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()
