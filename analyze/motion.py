# 运动量: 逐帧算画面变化 (相邻帧平均差) 和整体平移 (相位相关), 存成 npz. 差值尖峰 ≈ 硬切, 平移 ≈ 推拉摇移.
# python motion.py <video> <out.npz> [fps]
# 读: d = np.load(out.npz); d['d'] 每帧变化量, d['s'] 每帧 (dx, dy, 置信度), d['fps']
import sys, subprocess, numpy as np
v,out=sys.argv[1],sys.argv[2]; fps=float(sys.argv[3]) if len(sys.argv)>3 else 30
W,H=192,108
p=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-i',v,'-vf',f'fps={fps},scale={W}:{H},format=gray','-f','rawvideo','-'],stdout=subprocess.PIPE)
prev=None; diffs=[]; shifts=[]; win=np.outer(np.hanning(H),np.hanning(W))
while True:
    b=p.stdout.read(W*H)
    if len(b)<W*H: break
    f=np.frombuffer(b,np.uint8).astype(np.float32)
    f=f.reshape(H,W)
    if prev is not None:
        diffs.append(np.abs(f-prev).mean())
        A=np.fft.fft2((prev-prev.mean())*win); B=np.fft.fft2((f-f.mean())*win)
        R=A*np.conj(B); R/=np.abs(R)+1e-6; r=np.fft.ifft2(R).real
        iy,ix=np.unravel_index(np.argmax(r),r.shape)
        if iy>H//2: iy-=H
        if ix>W//2: ix-=W
        shifts.append((ix,iy,r.max()))
    prev=f
np.savez(out,d=np.array(diffs),s=np.array(shifts),fps=fps)
print(len(diffs))
