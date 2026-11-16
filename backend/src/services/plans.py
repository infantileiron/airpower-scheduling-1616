from datetime import datetime,timezone,timedelta
from sqlalchemy.exc import IntegrityError,OperationalError
from src.models.entities import Plan,PlanSlot,Run
from src.services.schedule import ScheduleError,Infeasible,aggregate,digest,local_hour
from src.services.schedule import snapshot_model,build_result
def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def revalidate_hours(hours):
 if not isinstance(hours,list) or not hours:raise ScheduleError('冻结时段为空')
 out=[];prev=None
 for i,h in enumerate(hours):
  try:
   hour=local_hour(h['hour']);pressure=float(h['pressure']);temperature=float(h['temperature']);available=float(h['available_machines']);demand=float(h['demand']);workshops=list(h['workshops'])
  except Exception:raise ScheduleError('冻结时段第'+str(i+1)+'项结构不完整')
  if not available.is_integer() or not 0<=available<=50:raise ScheduleError('冻结时段第'+str(i+1)+'项可用台数不合法')
  if not 0<=pressure<=20 or not -30<=temperature<=100 or demand<0:raise ScheduleError('冻结时段第'+str(i+1)+'项数值越界')
  if prev is not None and datetime.fromisoformat(hour)-datetime.fromisoformat(prev)!=timedelta(hours=1):raise ScheduleError('冻结时段不连续：'+prev+' → '+hour)
  out.append({'hour':hour,'pressure':pressure,'temperature':temperature,'available_machines':int(available),'demand':demand,'workshops':[{'workshop':str(w['workshop']),'demand':float(w['demand'])} for w in workshops]})
  prev=hour
 return out
def plan_payload(p):
 return {'id':p.id,'name':p.name,'state':p.state,'kind':p.kind,'model_run_id':p.model_run_id,'parent_plan_id':p.parent_plan_id,'params':p.params,'input':p.input,'result':p.result,'error':p.error or '','checksum':p.checksum,'created_by':p.created_by,'created':p.created,'confirmed_by':p.confirmed_by,'confirmed':p.confirmed,'cancelled_by':p.cancelled_by,'cancelled':p.cancelled,'superseded_by':p.superseded_by,'superseded':p.superseded}
def create_preview(s,name,model_run_id,rows,params,user,kind='direct',parent=None):
 hours=aggregate(rows) if rows is not None else revalidate_hours(parent.input['hours'])
 if parent is not None:
  frozen_model=parent.result['model'] if parent.result else None
  if not frozen_model:raise ScheduleError('原计划缺少冻结模型快照，无法改排')
  model=frozen_model
  params=dict(parent.params if params is None else params)
 else:
  run=s.get(Run,model_run_id)
  if not run:raise ScheduleError('模型版本不存在')
  model=snapshot_model(run,run.result)
  params=dict(params)
 input_checksum=digest({'hours':hours})
 result=build_result(hours,params,model,input_checksum)
 checksum=digest({'params':params,'hours':hours,'model_run_id':model['run_id']})
 p=Plan(name=name or ('改排自 #'+str(parent.id)),state='preview',kind=kind,model_run_id=model['run_id'],parent_plan_id=parent.id if parent else None,params=params,input={'hours':hours},result=result,error='',checksum=checksum,created_by=user.email,created=now())
 s.add(p);s.commit()
 return p
def confirm(s,plan_id,user):
 p=s.query(Plan).filter(Plan.id==plan_id).with_for_update().first()
 if not p:raise LookupError('排机计划不存在')
 if p.state=='confirmed':return p,False
 if p.state=='cancelled':raise ValueError('计划已取消，不能确认')
 if p.state=='superseded':raise ValueError('计划已被改排替代，不能确认')
 if p.state!='preview':raise ValueError('当前状态不能确认')
 hours=[h['hour'] for h in p.input['hours']]
 parent=None
 try:
  if p.kind=='reschedule':
   parent=s.query(Plan).filter(Plan.id==p.parent_plan_id).with_for_update().first()
   if not parent or parent.state!='confirmed' or parent.superseded_by:raise ValueError('原计划已取消或已被其他改排替代，本次改排不能确认')
   s.query(PlanSlot).filter(PlanSlot.plan_id==parent.id).delete(synchronize_session=False)
  for h in hours:s.add(PlanSlot(plan_id=p.id,hour=h))
  s.flush()
  p.state='confirmed';p.confirmed_by=user.email;p.confirmed=now();p.error=''
  if parent is not None:
   parent.state='superseded';parent.superseded_by=p.id;parent.superseded=now()
  s.commit()
  return p,True
 except IntegrityError:
  s.rollback();raise ValueError('时段已被其他已确认计划占用，确认失败；原计划与占用保持不变')
 except OperationalError:
  s.rollback();raise ValueError('时段占用发生并发冲突，确认失败；原计划与占用保持不变，请刷新后重试')
 except Exception:
  s.rollback();raise
def cancel(s,plan_id,user):
 p=s.query(Plan).filter(Plan.id==plan_id).with_for_update().first()
 if not p:raise LookupError('排机计划不存在')
 if p.state=='cancelled':return p,False
 if p.state=='superseded':raise ValueError('计划已被改排替代，占用已由新计划接管')
 if p.state not in ('preview','confirmed'):raise ValueError('当前状态不能取消')
 s.query(PlanSlot).filter(PlanSlot.plan_id==p.id).delete(synchronize_session=False)
 p.state='cancelled';p.cancelled_by=user.email;p.cancelled=now();s.commit()
 return p,True
def revise_preview(s,plan_id,rows,params,user):
 p=s.query(Plan).filter(Plan.id==plan_id).with_for_update().first()
 if not p:raise LookupError('排机计划不存在')
 if p.state!='preview':raise ValueError('已确认计划的输入和参数已冻结，不能修改；请另建改排预览')
 frozen=p.result.get('model') if p.result else None
 if not frozen:raise ScheduleError('预览缺少模型快照，请重新导入')
 hours=aggregate(rows) if rows is not None else p.input['hours']
 new_params={**p.params,**(params or {})}
 result=build_result(hours,new_params,frozen,digest({'hours':hours}))
 p.input={'hours':hours};p.params=new_params;p.result=result
 p.checksum=digest({'params':new_params,'hours':hours,'model_run_id':p.model_run_id})
 s.commit();return p
