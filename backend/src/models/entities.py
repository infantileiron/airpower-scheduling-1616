from sqlalchemy import Column,Integer,String,Float,JSON,Text,ForeignKey,UniqueConstraint
from src.config.database import Base
class User(Base):
 __tablename__='users'
 id=Column(Integer,primary_key=True);email=Column(String(100),unique=True);password=Column(String(200));role=Column(String(20))
class Sample(Base):
 __tablename__='samples'
 id=Column(Integer,primary_key=True);hour=Column(String(30),unique=True,nullable=False);pressure=Column(Float);flow=Column(Float);temperature=Column(Float);machines=Column(Integer);sensor_noise=Column(Float);kwh=Column(Float);note=Column(Text,default='')
class Run(Base):
 __tablename__='runs'
 id=Column(Integer,primary_key=True);name=Column(String(100));features=Column(JSON);alphas=Column(JSON);state=Column(String(20),default='queued');result=Column(JSON);error=Column(Text,default='')
class Review(Base):
 __tablename__='reviews'
 id=Column(Integer,primary_key=True);run_id=Column(Integer,ForeignKey('runs.id'));title=Column(String(100));finding=Column(Text);action=Column(Text);status=Column(String(20),default='draft')
class Audit(Base):
 __tablename__='audits'
 id=Column(Integer,primary_key=True);actor=Column(String(100));action=Column(String(200));created=Column(String(40))
class Plan(Base):
 __tablename__='plans'
 id=Column(Integer,primary_key=True)
 name=Column(String(120),nullable=False)
 state=Column(String(20),default='preview',nullable=False)
 kind=Column(String(20),default='direct',nullable=False)
 model_run_id=Column(Integer,ForeignKey('runs.id'),nullable=False)
 parent_plan_id=Column(Integer,ForeignKey('plans.id'))
 params=Column(JSON,nullable=False)
 input=Column(JSON,nullable=False)
 result=Column(JSON)
 error=Column(Text,default='')
 checksum=Column(String(64),default='')
 created_by=Column(String(100));created=Column(String(40));confirmed_by=Column(String(100));confirmed=Column(String(40));cancelled_by=Column(String(100));cancelled=Column(String(40));superseded_by=Column(Integer);superseded=Column(String(40))
class PlanSlot(Base):
 __tablename__='plan_slots'
 id=Column(Integer,primary_key=True)
 plan_id=Column(Integer,ForeignKey('plans.id'),nullable=False)
 hour=Column(String(30),nullable=False)
 __table_args__=(UniqueConstraint('hour',name='uq_plan_slot_hour'),UniqueConstraint('plan_id','hour',name='uq_plan_slot_plan_hour'))
