import random,math
from datetime import datetime,timedelta
from src.config.database import Base,engine,Session
from src.models.entities import User,Sample,Run
from src.utils.security import hash_password
def rows():
 rng=random.Random(3110);out=[]
 for i in range(240):
  hour=(datetime(2026,11,1)+timedelta(hours=i)).strftime('%Y-%m-%dT%H:00');flow=round(8+3*math.sin(i*math.pi/12)+rng.uniform(-1,1),3);pressure=round(rng.uniform(5.8,7.5),3);temp=round(22+5*math.sin(i*math.pi/12)+rng.uniform(-2,2),3);machines=2+i%4;noise=round(rng.uniform(-3,3),3);kwh=round(40+14*flow+5*machines+2*pressure+.15*temp+rng.gauss(0,2.5),3)
  out.append(dict(hour=hour,flow=flow,pressure=pressure,temperature=temp,machines=machines,sensor_noise=noise,kwh=kwh,note='ZX-A01空压站；本地整点小时；sensor_noise为无关对照特征'))
 return out
def seed():
 Base.metadata.create_all(engine)
 with Session() as s:
  for role in ('admin','analyst','viewer'):
   email=role+'@demo.local'
   if not s.query(User).filter_by(email=email).first():s.add(User(email=email,role=role,password=hash_password('Demo123!')))
  for r in rows():
   if not s.query(Sample).filter_by(hour=r['hour']).first():s.add(Sample(**r))
  s.commit()
  if not s.query(Run).count():
   from src.services.analysis import choose
   data=[dict(r) for r in rows()];snapshot=[{k:v for k,v in r.items()} for r in data]
   result=choose(data,['pressure','flow','temperature','machines'],[.01,.1,1.,10.,100.])
   s.add(Run(name='ZX-A01基准能耗模型（演示）',features=result['features'],alphas=[.01,.1,1.,10.,100.],state='done',result={**result,'snapshot':snapshot}))
   s.commit()
  print({'users':s.query(User).count(),'samples':s.query(Sample).count(),'runs':s.query(Run).count()})
if __name__=='__main__':seed()
