# 动作条: 每一行是一个事件 (一段时间), 在里面均匀抽 cols 帧, 看一个动作 / 运镜是怎么展开的.
# python strips.py <video> <out.png> <cols> <tw> "start:end,start:end,..."
import sys, subprocess
from PIL import Image, ImageDraw, ImageFont
def load_font(size):
    for p in ('C:/Windows/Fonts/msyh.ttc', '/System/Library/Fonts/PingFang.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'):
        try: return ImageFont.truetype(p, size)
        except OSError: pass
    return ImageFont.load_default()
v,out,cols,tw=sys.argv[1],sys.argv[2],int(sys.argv[3]),int(sys.argv[4]); th=tw*9//16
rows=[tuple(map(float,r.split(':'))) for r in sys.argv[5].split(',')]
font=load_font(max(12,tw//14))
sheet=Image.new('RGB',(cols*(tw+3)+3,len(rows)*(th+3)+3),(20,20,20)); d=ImageDraw.Draw(sheet)
for r,(a,b) in enumerate(rows):
    for c in range(cols):
        t=a+(b-a)*c/(cols-1)
        x=subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-ss',f'{t:.3f}','-i',v,'-frames:v','1','-vf',f'scale={tw}:{th}','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True).stdout
        if len(x)<tw*th*3: continue
        X,Y=3+c*(tw+3),3+r*(th+3); sheet.paste(Image.frombytes('RGB',(tw,th),x[:tw*th*3]),(X,Y))
        lab=f'{int(t//60)}:{t%60:05.2f}'; d.rectangle([X,Y,X+tw*0.42,Y+tw//12],fill=(0,0,0)); d.text((X+2,Y-1),lab,fill=(255,220,0),font=font)
sheet.save(out); print(out,sheet.size)
