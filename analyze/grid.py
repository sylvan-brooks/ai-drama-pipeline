# 接触表: 从 start 到 end 每隔 step 秒抽一帧, 带时间码拼成网格, 看节奏和镜头切换. 一张放 cols×rows 帧, 多了自动分页.
# python grid.py <video> <outprefix> <start> <end> <step> [cols] [rows] [tw]
import sys, subprocess, os
from PIL import Image, ImageDraw, ImageFont
def load_font(size):
    for p in ('C:/Windows/Fonts/msyh.ttc', '/System/Library/Fonts/PingFang.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'):
        try: return ImageFont.truetype(p, size)
        except OSError: pass
    return ImageFont.load_default()
v,pre=sys.argv[1],sys.argv[2]; a,b,st=map(float,sys.argv[3:6])
cols=int(sys.argv[6]) if len(sys.argv)>6 else 6; rows=int(sys.argv[7]) if len(sys.argv)>7 else 8; tw=int(sys.argv[8]) if len(sys.argv)>8 else 320
th=tw*9//16; n=int((b-a)/st+1e-6)+1; times=[a+i*st for i in range(n)]
font=load_font(max(12,tw//16))
per=cols*rows
for k in range(0,len(times),per):
    ts=times[k:k+per]; sheet=Image.new('RGB',(cols*(tw+4)+4,((len(ts)+cols-1)//cols)*(th+4)+4),(20,20,20))
    for i,t in enumerate(ts):
        r=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-ss',f'{t:.3f}','-i',v,'-frames:v','1','-vf',f'scale={tw}:{th}','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True)
        if len(r.stdout)<tw*th*3: continue
        im=Image.frombytes('RGB',(tw,th),r.stdout[:tw*th*3]); x=4+(i%cols)*(tw+4); y=4+(i//cols)*(th+4); sheet.paste(im,(x,y))
        d=ImageDraw.Draw(sheet); lab=f'{int(t//60)}:{t%60:05.2f}'; d.rectangle([x,y,x+len(lab)*tw//28+6,y+tw//14],fill=(0,0,0)); d.text((x+3,y),lab,fill=(255,220,0),font=font)
    out=f'{pre}_{k//per}.png'; sheet.save(out); print(out,len(ts))
