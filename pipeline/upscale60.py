"""成片放大 + 插帧到 60fps: Real-ESRGAN 放大 → lanczos 铺满目标画幅 → 按硬切分镜头各自用 RIFE 插帧 (不跨镜头糊帧) → x264.
python upscale60.py <in.mp4> <out.mp4> [--size 2160x3840] [--cuts 4.42,6.75] [--model realesrgan-x4plus] [--frames N] [--crf 16]
  --size   目标画幅; 不给就按横竖屏选 3840×2160 或 2160×3840
  --cuts   硬切时间点 (秒); 不给就用 ffmpeg scdet 自动找
  --frames 只处理前 N 帧, 先测速度和效果
环境变量: REALESRGAN (realesrgan-ncnn-vulkan 可执行文件路径) · RIFE (rife-ncnn-vulkan 可执行文件路径). 都不在 PATH 里就必须设.
中间帧放在输出文件旁边的 _tmp_<名字>/ 里, 跑完自己删. 音轨原样带过去.
退出码: 0 成功 / 1 参数或环境问题 / 2 外部程序失败."""
import sys, os, re, json, shutil, subprocess, argparse, time


def tool(env, name):
    path = os.environ.get(env) or shutil.which(name)
    if not path or not os.path.isfile(path):
        print(f'找不到 {name}: 设环境变量 {env} 指到可执行文件', file=sys.stderr); sys.exit(1)
    return path


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', **kw)
    if r.returncode:
        print(f'失败: {os.path.basename(cmd[0])}\n{r.stderr[-1500:]}', file=sys.stderr); sys.exit(2)
    return r


def probe(path):
    r = run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_entries',
             'stream=width,height,r_frame_rate,nb_read_frames', '-of', 'json', path])
    s = json.loads(r.stdout)['streams'][0]
    a, b = s['r_frame_rate'].split('/')
    return s['width'], s['height'], float(a) / float(b), int(s['nb_read_frames'])


def scene_cuts(path, thr=0.3):
    r = subprocess.run(['ffmpeg', '-hide_banner', '-i', path, '-vf', f'scdet=threshold={thr * 100}:sc_pass=1', '-an', '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return [float(m) for m in re.findall(r'lavfi\.scd\.time:\s*([\d.]+)', r.stderr)]


def main():
    ap = argparse.ArgumentParser(description='放大 + 按镜头插帧到 60fps')
    ap.add_argument('src'); ap.add_argument('out')
    ap.add_argument('--size'); ap.add_argument('--cuts'); ap.add_argument('--model', default='realesrgan-x4plus')
    ap.add_argument('--rife-model', default='rife-v4.6'); ap.add_argument('--scale', type=int, default=4)
    ap.add_argument('--frames', type=int); ap.add_argument('--crf', type=int, default=16)
    ap.add_argument('--scd', type=float, default=0.3, help='自动找硬切的灵敏度 (0-1, 越小越容易判成硬切)')
    a = ap.parse_args()
    esr, rife = tool('REALESRGAN', 'realesrgan-ncnn-vulkan'), tool('RIFE', 'rife-ncnn-vulkan')
    w, h, fps, n = probe(a.src)
    if a.size:
        W, H = (int(x) for x in a.size.lower().split('x'))
    else:
        W, H = (2160, 3840) if h > w else (3840, 2160)
    cuts = [float(x) for x in a.cuts.split(',')] if a.cuts else scene_cuts(a.src, a.scd)
    print(f'源 {w}x{h} {fps:.3f}fps {n} 帧 → {W}x{H}@60 · 硬切 {cuts}', flush=True)
    if not a.cuts and not cuts:
        print('  没自动找到硬切. 片子里有硬切的话用 --cuts 手给, 或调低 --scd (默认 0.3), 不然切点上会插出两个镜头叠在一起的帧', flush=True)
    out = os.path.abspath(a.out)
    tmp = os.path.join(os.path.dirname(out), '_tmp_' + os.path.splitext(os.path.basename(out))[0])
    if os.path.exists(tmp):
        print(f'临时目录已存在, 先确认没有别的任务在用再删: {tmp}', file=sys.stderr); sys.exit(1)
    src_d, up_d, fit_d = (os.path.join(tmp, x) for x in ('src', 'up', 'fit'))
    for d in (src_d, up_d, fit_d):
        os.makedirs(d)
    vf = [] if not a.frames else ['-frames:v', str(a.frames)]
    run(['ffmpeg', '-v', 'error', '-i', a.src, *vf, '-start_number', '0', os.path.join(src_d, '%05d.png')])
    n = len(os.listdir(src_d))

    t = time.time()   # 1) 放大 (整目录一次)
    run([esr, '-i', src_d, '-o', up_d, '-n', a.model, '-s', str(a.scale), '-f', 'png'], cwd=os.path.dirname(esr))
    print(f'放大 {n} 帧 {time.time() - t:.0f}s', flush=True)

    t = time.time()   # 2) 缩放到目标画幅: 等比铺满再居中裁 (lanczos)
    run(['ffmpeg', '-v', 'error', '-start_number', '0', '-i', os.path.join(up_d, '%05d.png'),
         '-vf', f'scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H}',
         '-start_number', '0', os.path.join(fit_d, '%05d.png')])
    shutil.rmtree(up_d)
    print(f'缩放裁切 {time.time() - t:.0f}s', flush=True)

    # 3) 按镜头插帧: 每个镜头 k 帧 → round(k*60/fps) 帧. 跨硬切插帧会在切点生出两个镜头叠在一起的糊帧
    bounds = [0] + [min(n, round(c * fps)) for c in cuts if 0 < round(c * fps) < n] + [n]
    seg_files = []
    t = time.time()
    for i, (s, e) in enumerate(zip(bounds, bounds[1:])):
        if e <= s:
            continue
        si, so = os.path.join(tmp, f's{i}_in'), os.path.join(tmp, f's{i}_out')
        os.makedirs(si); os.makedirs(so)
        for j, f in enumerate(sorted(os.listdir(fit_d))[:e - s]):
            shutil.move(os.path.join(fit_d, f), os.path.join(si, f'{j:05d}.png'))
        target = max(2, round((e - s) * 60 / fps))
        if e - s >= 2:
            run([rife, '-i', si, '-o', so, '-m', a.rife_model, '-n', str(target), '-f', '%05d.png'], cwd=os.path.dirname(rife))
        else:
            shutil.copy(os.path.join(si, '00000.png'), os.path.join(so, '00001.png'))
        seg_files += [os.path.join(so, f) for f in sorted(os.listdir(so))]
        shutil.rmtree(si)
        print(f'  镜头{i + 1}: {e - s} → {len(os.listdir(so))} 帧', flush=True)
    print(f'插帧 {time.time() - t:.0f}s', flush=True)

    lst = os.path.join(tmp, 'list.txt')
    with open(lst, 'w', encoding='utf-8') as f:
        for p in seg_files:
            f.write(f"file '{p.replace(chr(92), '/')}'\nduration {1 / 60:.6f}\n")
        # concat 不认最后一条的 duration, 不重复写一次最后一帧会少一两帧
        f.write(f"file '{seg_files[-1].replace(chr(92), '/')}'\n")
    t = time.time()   # 4) 编码 H.264 High 60fps, 原音轨. 时长按帧数算死; 用 -shortest 会在结尾少切掉一两帧
    run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-i', a.src,
         '-map', '0:v', '-map', '1:a?', '-r', '60', '-c:v', 'libx264', '-preset', 'slow', '-crf', str(a.crf),
         '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-c:a', 'copy', '-t', f'{len(seg_files) / 60:.6f}', '-movflags', '+faststart', out])
    print(f'编码 {time.time() - t:.0f}s → {out}', flush=True)
    shutil.rmtree(tmp)


if __name__ == '__main__':
    main()
