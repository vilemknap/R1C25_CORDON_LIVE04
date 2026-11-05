import math
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
