import os,json
import redis
from fastapi import APIRouter,Depends,HTTPException,Response
from sqlalchemy.exc import IntegrityError
from src.config.database import db
from src.models.entities import User,Sample,Run,Review,Audit,Plan,PlanSlot
from src.schemas.business import Login,SampleInput,RunInput,ReviewInput,PlanInput,PlanReschedule
from src.middlewares.auth import current,editor,admin
from src.utils.security import verify,token
from src.services.business import audit,dump
from src.services.schedule import ScheduleError,Infeasible
from src.services import plans as plan_service
from src.controllers.business import ensure_run,ensure_plan
router=APIRouter()
def plan_error(e):
 if isinstance(e,Infeasible):return HTTPException(422,'无可行排机方案：'+str(e))
 if isinstance(e,ScheduleError):return HTTPException(422,str(e))
 if isinstance(e,LookupError):return HTTPException(404,str(e))
 return HTTPException(409,str(e))
@router.post('/auth/login')
def login(data:Login,s=Depends(db)):
 u=s.query(User).filter_by(email=data.email).first()
 if not u or not verify(data.password,u.password):raise HTTPException(401,'账号或密码错误')
 return {'token':token(u),'user':dump(u)}
@router.get('/me')
def me(u=Depends(current)):return dump(u)
@router.get('/samples')
def samples(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Sample).order_by(Sample.hour).all()]
@router.post('/samples')
def create(data:SampleInput,u=Depends(editor),s=Depends(db)):
 r=Sample(**data.model_dump());s.add(r)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'该小时已存在，请使用修订功能')
 audit(s,u,'录入小时 '+r.hour);return dump(r)
@router.put('/samples/{i}')
def edit(i:int,data:SampleInput,u=Depends(editor),s=Depends(db)):
 r=s.get(Sample,i)
 if not r:raise HTTPException(404,'小时样本不存在')
 for k,v in data.model_dump().items():setattr(r,k,v)
 try:s.commit()
 except IntegrityError:s.rollback();raise HTTPException(409,'小时重复')
 audit(s,u,'修订样本 '+str(i));return dump(r)
@router.get('/runs')
def runs(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Run).order_by(Run.id.desc()).all()]
@router.post('/runs')
def train(data:RunInput,u=Depends(editor),s=Depends(db)):
 rows=[dump(r) for r in s.query(Sample).order_by(Sample.hour).all()];r=Run(**data.model_dump(),result={'snapshot':rows});s.add(r);s.commit()
 try:redis.Redis.from_url(os.environ['REDIS_URL']).rpush('airpower:runs',r.id)
 except redis.RedisError:r.state='failed';r.error='队列暂不可用，请稍后重试';s.commit();raise HTTPException(503,r.error)
 audit(s,u,'提交模型 '+str(r.id));return dump(r)
@router.get('/runs/{i}')
def detail(i:int,u=Depends(current),s=Depends(db)):return dump(ensure_run(s,i))
@router.get('/runs/{i}/export')
def export(i:int,u=Depends(current),s=Depends(db)):
 r=ensure_run(s,i)
 if r.state!='done':raise HTTPException(409,'仅成功版本可导出')
 return Response(json.dumps(dump(r),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="airpower-select-{i}.json"'})
@router.get('/reviews')
def reviews(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Review).order_by(Review.id.desc()).all()]
@router.post('/reviews')
def review(data:ReviewInput,u=Depends(editor),s=Depends(db)):
 if ensure_run(s,data.run_id).state!='done':raise HTTPException(409,'模型计算完成后才能起草评议')
 r=Review(**data.model_dump());s.add(r);s.commit();audit(s,u,'起草节能评议 '+str(r.id));return dump(r)
@router.put('/reviews/{i}')
def edit_review(i:int,data:ReviewInput,u=Depends(editor),s=Depends(db)):
 r=s.get(Review,i)
 if not r:raise HTTPException(404,'评议不存在')
 if r.status!='draft':raise HTTPException(409,'已签核评议冻结，请新建')
 if ensure_run(s,data.run_id).state!='done':raise HTTPException(409,'需要已成功模型')
 for k,v in data.model_dump().items():setattr(r,k,v)
 s.commit();audit(s,u,'修订评议 '+str(i));return dump(r)
@router.post('/reviews/{i}/approve')
def approve(i:int,u=Depends(admin),s=Depends(db)):
 r=s.get(Review,i)
 if not r:raise HTTPException(404,'评议不存在')
 if r.status!='draft':raise HTTPException(409,'已签核评议不能重复签核')
 r.status='approved';s.commit();audit(s,u,'签核节能评议 '+str(i));return dump(r)
@router.get('/reviews/{i}/export')
def export_review(i:int,u=Depends(current),s=Depends(db)):
 r=s.get(Review,i)
 if not r:raise HTTPException(404,'评议不存在')
 return Response(json.dumps(dump(r),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="airpower-review-{i}.json"'})
@router.get('/audits')
def audits(u=Depends(admin),s=Depends(db)):return [dump(r) for r in s.query(Audit).order_by(Audit.id.desc()).limit(100)]

def plan_base(s,p):
 d=plan_service.plan_payload(p)
 hours=[h['hour'] for h in p.input['hours']]
 owner={}
 if hours:
  for hour,plan_id in s.query(PlanSlot.hour,PlanSlot.plan_id).filter(PlanSlot.hour.in_(hours)).all():owner[hour]=plan_id
 d['conflicts']=sorted({i for i in owner.values() if i!=p.id})
 d.pop('result',None);d.pop('input',None)
 d['summary']=(p.result or {}).get('summary')
 return d,owner
def plan_out(s,p,full=False):
 d,owner=plan_base(s,p)
 d['occupied_hours']=sorted(r[0] for r in s.query(PlanSlot.hour).filter(PlanSlot.plan_id==p.id).all())
 if not full:
  d.pop('params',None)
  d['input']={'hours_count':len(p.input.get('hours',[]))}
  d['result']={'summary':(p.result or {}).get('summary'),'model':(p.result or {}).get('model'),'greedy':(p.result or {}).get('greedy'),'method':(p.result or {}).get('method')}
 else:
  d['params']=p.params
  d['input']=p.input
  d['result']=p.result or {}
  d['slot_owner']=owner
 return d
@router.get('/plans')
def list_plans(u=Depends(current),s=Depends(db)):
 return [plan_out(s,p) for p in s.query(Plan).order_by(Plan.id.desc()).all()]
@router.get('/plans/{i}')
def plan_detail(i:int,u=Depends(current),s=Depends(db)):return plan_out(s,ensure_plan(s,i),full=True)
@router.post('/plans/preview')
def preview(data:PlanInput,u=Depends(editor),s=Depends(db)):
 run=ensure_run(s,data.model_run_id)
 try:p=plan_service.create_preview(s,data.name,data.model_run_id,data.rows,data.params.model_dump(),u)
 except (ScheduleError,Infeasible) as e:raise plan_error(e)
 except ValueError as e:raise plan_error(e)
 audit(s,u,'预览排机计划 '+str(p.id));return plan_out(s,p,full=True)
@router.post('/plans/{i}/reschedule')
def reschedule(i:int,data:PlanReschedule,u=Depends(editor),s=Depends(db)):
 parent=ensure_plan(s,i)
 if parent.state!='confirmed' or parent.superseded_by:raise HTTPException(409,'仅当前有效的已确认计划可以改排')
 try:p=plan_service.create_preview(s,data.name or ('改排自 #'+str(parent.id)),parent.model_run_id,data.rows,(data.params.model_dump() if data.params else None),u,kind='reschedule',parent=parent)
 except (ScheduleError,Infeasible) as e:raise plan_error(e)
 except ValueError as e:raise plan_error(e)
 audit(s,u,'改排排机计划 '+str(parent.id)+' → 预览 '+str(p.id));return plan_out(s,p,full=True)
@router.put('/plans/{i}')
def revise(i:int,data:PlanReschedule,u=Depends(editor),s=Depends(db)):
 ensure_plan(s,i)
 try:p=plan_service.revise_preview(s,i,data.rows,(data.params.model_dump() if data.params else None),u)
 except (ScheduleError,Infeasible) as e:raise plan_error(e)
 except (ValueError,LookupError) as e:raise plan_error(e)
 audit(s,u,'重算排机预览 '+str(i));return plan_out(s,p,full=True)
@router.post('/plans/{i}/confirm')
def confirm(i:int,u=Depends(editor),s=Depends(db)):
 try:p,changed=plan_service.confirm(s,i,u)
 except (ScheduleError,Infeasible) as e:raise plan_error(e)
 except (ValueError,LookupError) as e:raise plan_error(e)
 if changed:audit(s,u,'确认排机计划 '+str(i))
 return {**plan_out(s,p,full=True),'idempotent':not changed}
@router.post('/plans/{i}/cancel')
def cancel(i:int,u=Depends(editor),s=Depends(db)):
 try:p,changed=plan_service.cancel(s,i,u)
 except (ScheduleError,Infeasible) as e:raise plan_error(e)
 except (ValueError,LookupError) as e:raise plan_error(e)
 if changed:audit(s,u,'取消排机计划 '+str(i))
 return {**plan_out(s,p,full=True),'idempotent':not changed}
@router.get('/plans/{i}/export')
def export_plan(i:int,u=Depends(current),s=Depends(db)):
 p=ensure_plan(s,i)
 return Response(json.dumps(plan_out(s,p,full=True),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="airpower-plan-{i}.json"'})
