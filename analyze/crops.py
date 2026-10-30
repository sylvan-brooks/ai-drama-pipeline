# 原画局部: 在某一刻按比例坐标裁一块, 原分辨率输出 (最宽 1600), 看皮肤、布景、字体这些细节.
# python crops.py <video> <outdir> "t,x0,y0,x1,y1;..."   (x0..y1 是 0-1 的比例)
import sys, subprocess, os
from PIL import Image
v,od=sys.argv[1],sys.argv[2]; os.makedirs(od,exist_ok=True)
for spec in sys.argv[3].split(';'):
    t,x0,y0,x1,y1=map(float,spec.split(','))
    p=f'{od}/f_{t:.1f}.png'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss',f'{t:.2f}','-i',v,'-frames:v','1',p],check=True)
    im=Image.open(p); W,H=im.size; c=im.crop((int(x0*W),int(y0*H),int(x1*W),int(y1*H)))
    if c.width>1600: c=c.resize((1600,int(c.height*1600/c.width)),Image.LANCZOS)
    c.save(f'{od}/crop_{t:.1f}.png'); os.remove(p); print(f'crop_{t:.1f}.png',c.size)
