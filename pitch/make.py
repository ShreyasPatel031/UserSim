import random, math, os, subprocess, shutil
from PIL import Image, ImageDraw, ImageFont, ImageFilter
W,H=1280,720; FPS=12
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),"frames")
shutil.rmtree(OUT,ignore_errors=True); os.makedirs(OUT)
B="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"; S="/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
F=lambda s,p=B: ImageFont.truetype(p,s)
INK=(30,30,40); RED=(226,74,51); BLUE=(52,104,192); YEL=(244,190,60); GRN=(70,160,110); CREAM=(250,244,228)
random.seed(1)
papers=[]
for k in range(3):
    p=Image.new("RGB",(W,H),(236,226,204)); px=p.load()
    n=Image.effect_noise((W//4,H//4),18).resize((W,H)).convert("L")
    p=Image.blend(p,Image.merge("RGB",(n,n,n)),0.08); papers.append(p)

def layer(w,h,fn):
    L=Image.new("RGBA",(w,h),(0,0,0,0)); fn(ImageDraw.Draw(L),w,h); return L
def place(img,L,cx,cy,rng,rot=2.5,j=3,shadow=True):
    a=rng.uniform(-rot,rot); L=L.rotate(a,expand=True,resample=Image.BICUBIC)
    x=int(cx-L.width/2+rng.uniform(-j,j)); y=int(cy-L.height/2+rng.uniform(-j,j))
    if shadow:
        sh=Image.new("RGBA",L.size,(0,0,0,0)); sh.putalpha(L.split()[3].point(lambda v:v*0.35))
        sh=sh.filter(ImageFilter.GaussianBlur(4)); img.alpha_composite(sh,(x+6,y+7))
    img.alpha_composite(L,(x,y))
def card(text,size=44,bg=CREAM,fg=INK,pad=26,font=B):
    f=F(size,font); bb=f.getbbox(text); w=bb[2]-bb[0]+pad*2; h=bb[3]-bb[1]+pad*2
    def d(dr,w,h):
        dr.rounded_rectangle((0,0,w-1,h-1),14,fill=bg+(255,)); dr.text((pad-bb[0],pad-bb[1]),text,font=f,fill=fg)
    return layer(w,h,d)
def robot(s,body=BLUE,sweat=False):
    def d(dr,w,h):
        u=s/10
        dr.line((5*u,0.6*u,5*u,2*u),fill=INK,width=int(u*.5)); dr.ellipse((4.3*u,0,5.7*u,1.4*u),fill=RED)
        dr.rounded_rectangle((1.5*u,2*u,8.5*u,6*u),int(u),fill=body)
        for ex in (3.4,6.6): dr.ellipse(((ex-.8)*u,3.2*u,(ex+.8)*u,4.8*u),fill=CREAM); dr.ellipse(((ex-.35)*u,3.7*u,(ex+.35)*u,4.4*u),fill=INK)
        dr.rounded_rectangle((2.5*u,6.4*u,7.5*u,10*u),int(u*.6),fill=body)
        dr.rectangle((4*u,7.4*u,6*u,8.4*u),fill=YEL)
        if sweat: dr.ellipse((8.6*u,2*u,9.6*u,3.2*u),fill=(120,190,240))
    return layer(int(s),int(s),d)
def rack():
    def d(dr,w,h):
        dr.rectangle((0,0,w-1,h-1),fill=INK)
        for i in range(5):
            y=8+i*22; dr.rectangle((8,y,w-9,y+16),fill=(70,72,90)); dr.ellipse((w-26,y+4,w-18,y+12),fill=GRN)
    return layer(90,120,d)
def person():
    return layer(110,110,lambda dr,w,h:(dr.ellipse((35,5,75,45),fill=RED),dr.pieslice((10,50,100,150),180,360,fill=RED)))
def checks():
    def d(dr,w,h):
        for i in range(3):
            y=10+i*33; dr.rectangle((8,y,32,y+24),fill=CREAM); dr.line((12,y+12,19,y+20,30,y+3),fill=GRN,width=5)
            dr.rectangle((42,y+8,100,y+16),fill=CREAM)
    return layer(110,110,d)
def flags():
    def d(dr,w,h):
        for i,c in enumerate((RED,BLUE,GRN)):
            x=10+i*33; dr.line((x,15,x,100),fill=INK,width=4); dr.polygon([(x,15),(x+28,25),(x,38)],fill=c)
    return layer(110,110,d)
def bigcard(icon,title,bg):
    def d(dr,w,h):
        dr.rounded_rectangle((0,0,w-1,h-1),18,fill=bg+(255,))
        f=F(30); y=180
        for line in title.split("\n"):
            tw=f.getlength(line); dr.text(((w-tw)/2,y),line,font=f,fill=CREAM); y+=40
    L=layer(330,290,d); L.alpha_composite(icon,(110,40)); return L

frames=[]
def scene(n,fn):
    for i in range(n): frames.append((fn,i,n))

def s1(img,i,rng):
    place(img,card("An enterprise agent at Anthropic",46),W/2,80,rng)
    place(img,robot(300,BLUE),300,420,rng)
    k=min(12,i//2+1)
    for r in range(k):
        cx=640+(r%4)*120; cy=510-(r//4)*130
        place(img,rack(),cx,cy,rng,rot=2)
    v=int(5_000_000_000*min(1,i/30))
    place(img,card(f"${v:,} in compute",50,YEL,INK,font=S),W/2,690-25-0,rng) if i>=6 else None
def s2(img,i,rng):
    place(img,card("Your weekend coding agent",46),W/2,80,rng)
    place(img,robot(140,(150,150,165),sweat=(i//3)%2==0),W/2,380,rng,rot=6,j=5)
    if i>=8:
        coin=layer(150,150,lambda dr,w,h:(dr.ellipse((0,0,149,149),fill=YEL),dr.ellipse((14,14,135,135),outline=(200,140,30),width=6),dr.text((30,48),"$60",font=F(48),fill=INK)))
        y=min(390, 120+(i-8)*60); place(img,coin,880,y,rng,rot=12)
    if i>=14: place(img,card("$60 in credits",50,RED,CREAM,font=S),W/2,600,rng)
def s3(img,i,rng):
    place(img,card("Your agents need to know…",50),W/2,90,rng)
    items=[(person(),"Who you're\nbuilding for",BLUE),(checks(),"What their\npriorities are",GRN),(flags(),"Who else is\nin the market",RED)]
    for k,(ic,t,c) in enumerate(items):
        if i>=6+k*12:
            age=i-(6+k*12); sc=1.25 if age<2 else 1.0
            L=bigcard(ic,t,c);
            if sc!=1: L=L.resize((int(L.width*sc),int(L.height*sc)))
            place(img,L,240+k*400,400,rng,rot=4)
def s4(img,i,rng):
    word="ATELIER"; f=F(130,S)
    place(img,card("That's what",44),W/2,140,rng)
    x0=W/2-len(word)*95/2+47
    for k,ch in enumerate(word):
        if i>=2+k*2:
            age=i-(2+k*2); y=360-max(0,(2-age))*80
            L=layer(105,150,lambda dr,w,h,ch=ch,k=k:(dr.rectangle((0,0,w-1,h-1),fill=[RED,BLUE,YEL,GRN][k%4]+(255,)),dr.text((w/2,h/2),ch,font=F(100,S),fill=CREAM if k%4!=2 else INK,anchor="mm")))
            place(img,L,x0+k*95+ (k-3)*12,y,rng,rot=6)
    if i>=18: place(img,card("does.",44),W/2,520,rng)
    if i>=26: place(img,card("Make something agents want.",34,INK,CREAM),W/2,640,rng)

scene(5*FPS,s1); scene(4*FPS,s2); scene(int(7.5*FPS),s3); scene(int(5.5*FPS),s4)
for idx,(fn,i,n) in enumerate(frames):
    rng=random.Random(idx//2)   # hold each pose 2 frames = stop-motion "on twos"
    img=papers[(idx//2)%3].convert("RGBA"); fn(img,i,rng)
    img.convert("RGB").save(f"{OUT}/{idx:04d}.png")
subprocess.run(["ffmpeg","-y","-loglevel","error","-framerate",str(FPS),"-i",f"{OUT}/%04d.png","-vf","fps=24","-c:v","libx264","-pix_fmt","yuv420p","-crf","18",os.path.join(os.path.dirname(os.path.abspath(__file__)),"atelier_pitch.mp4")],check=True)
print(len(frames))
