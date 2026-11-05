import tifffile, glob, csv, math, sys
from PIL import Image, ImageDraw, ImageFont
D=sys.argv[1]; MAP=sys.argv[2]
def utm_inv(x,y,zone=34):
    a=6378137.0; f=1/298.257223563; e2=f*(2-f); k0=0.9996; ep2=e2/(1-e2)
    x-=500000.0; M=y/k0; mu=M/(a*(1-e2/4-3*e2**2/64-5*e2**3/256))
    e1=(1-math.sqrt(1-e2))/(1+math.sqrt(1-e2))
    p1=mu+(3*e1/2-27*e1**3/32)*math.sin(2*mu)+(21*e1**2/16-55*e1**4/32)*math.sin(4*mu)+(151*e1**3/96)*math.sin(6*mu)
    N1=a/math.sqrt(1-e2*math.sin(p1)**2); T1=math.tan(p1)**2; C1=ep2*math.cos(p1)**2
    R1=a*(1-e2)/(1-e2*math.sin(p1)**2)**1.5; Dd=x/(N1*k0)
    lat=p1-(N1*math.tan(p1)/R1)*(Dd**2/2-(5+3*T1+10*C1-4*C1**2-9*ep2)*Dd**4/24+(61+90*T1+298*C1+45*T1**2-252*ep2-3*C1**2)*Dd**6/720)
    lon=(Dd-(1+2*T1+C1)*Dd**3/6+(5-2*C1+28*T1-3*C1**2+8*ep2+24*T1**2)*Dd**5/120)/math.cos(p1)
    return math.degrees(lon)+(zone-1)*6-180+3, math.degrees(lat)
rows=list(csv.DictReader(open(MAP,encoding='utf-8-sig'),delimiter=';'))
# check projection on station points
for r in rows[:2]:
    print('check',r['station_label'],utm_inv(float(r['gpkg_x']),float(r['gpkg_y'])),r['gpkg_lon_wgs84'],r['gpkg_lat_wgs84'])
by={}
for r in rows: by.setdefault(int(r['station_id']),[]).append(r)
for s in by: by[s].sort(key=lambda r:(int(r['link_no']),int(r['from_node_no']),int(r['to_node_no'])))
for f in sorted(glob.glob(D+'/*.tif')):
    with tifffile.TiffFile(f) as t:
        img=t.pages[0].asarray(); g=t.geotiff_metadata
    sx,sy=g['ModelPixelScale'][:2]; lon0,lat0=g['ModelTiepoint'][3:5]
    S=3
    im=Image.fromarray(img).convert('RGB').resize((img.shape[1]*S,img.shape[0]*S),Image.LANCZOS)
    dr=ImageDraw.Draw(im)
    px=lambda lon,lat:((lon-lon0)/sx*S,(lat0-lat)/sy*S)
    for s,rs in by.items():
        lon,lat=float(rs[0]['gpkg_lon_wgs84']),float(rs[0]['gpkg_lat_wgs84'])
        X,Y=px(lon,lat)
        if not(-50<X<im.width+50 and -50<Y<im.height+50): continue
        for side,(r,col) in enumerate(zip(rs,((220,0,0),(0,0,230)))):
            # direction of the directed edge at the station: from_node->to_node along WKT, else heading
            w=r['geometry_wkt']
            if w.startswith('LINESTRING'):
                pts=[tuple(map(float,p.split())) for p in w[w.index('(')+1:-1].split(',')]
                (x1,y1),(x2,y2)=pts[0],pts[-1]
                a,b=utm_inv(x1,y1),utm_inv(x2,y2)
                dx,dy=b[0]-a[0],b[1]-a[1]
            else:
                dx=dy=0
            L=math.hypot(dx*math.cos(math.radians(lat)),dy) or 1
            ux,uy=dx*math.cos(math.radians(lat))/L,-dy/L
            off=8*(1 if side==0 else -1)
            nx,ny=-uy*off,ux*off
            x0,y0=X+nx-ux*35,Y+ny-uy*35; x1_,y1_=X+nx+ux*35,Y+ny+uy*35
            dr.line([x0,y0,x1_,y1_],fill=col,width=4)
            hx,hy=x1_,y1_; dr.polygon([(hx+ux*10,hy+uy*10),(hx-uy*7,hy+ux*7),(hx+uy*7,hy-ux*7)],fill=col)
            dr.text((x1_+ux*14+3,y1_+uy*14),('A' if side==0 else 'B')+':'+r['link_no'],fill=col)
        dr.ellipse([X-4,Y-4,X+4,Y+4],outline=(0,160,0),width=2); dr.text((X+6,Y-18),'SDP%d'%s,fill=(0,120,0))
    out=f.replace('.tif','_overlay.png'); im.save(out); print(out, im.size)
# crops per station
for f in sorted(glob.glob(D+'/*_overlay.png')):
    pass
