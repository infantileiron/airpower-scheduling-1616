import hashlib,json,math
from datetime import datetime,timedelta
import numpy as np
FEATURES=('pressure','flow','temperature','machines','sensor_noise')
MAX_HOURS=24*14
MAX_ROWS=5000
class ScheduleError(ValueError):
 pass
class Infeasible(ScheduleError):
 pass
def canonical(obj):return json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def digest(obj):return hashlib.sha256(canonical(obj).encode()).hexdigest()
def local_hour(v):
 try:d=datetime.fromisoformat(str(v))
 except Exception:raise ScheduleError('小时必须是ISO本地整点，如2026-11-01T08:00')
 if d.tzinfo or d.minute or d.second or d.microsecond:raise ScheduleError('小时必须使用工厂本地整点，不带时区、分秒')
 return d.strftime('%Y-%m-%dT%H:00')
def aggregate(rows):
 if not isinstance(rows,list) or not rows:raise ScheduleError('批次为空，至少需要一行车间小时需气')
 if len(rows)>MAX_ROWS:raise ScheduleError('批次超过 '+str(MAX_ROWS)+' 行')
 by_hour={};seen=set()
 for i,raw in enumerate(rows):
  row=dict(raw);hour=local_hour(row.get('hour'));workshop=str(row.get('workshop') or '').strip()
  if not workshop:raise ScheduleError('第'+str(i+1)+'行车间为空')
  key=(hour,workshop)
  if key in seen:raise ScheduleError('第'+str(i+1)+'行重复：车间 '+workshop+' 在 '+hour+' 已出现')
  seen.add(key)
  try:
   demand=float(row['demand']);pressure=float(row['pressure']);temperature=float(row['temperature']);avail_raw=float(row['available_machines'])
  except (KeyError,TypeError,ValueError):raise ScheduleError('第'+str(i+1)+'行字段不全或不是数值：hour/workshop/demand/pressure/temperature/available_machines')
  if not all(math.isfinite(v) for v in (demand,pressure,temperature,avail_raw)):raise ScheduleError('第'+str(i+1)+'行含非有限数值')
  if not avail_raw.is_integer():raise ScheduleError('第'+str(i+1)+'行可用台数必须是整数')
  available=int(avail_raw)
  if demand<0:raise ScheduleError('第'+str(i+1)+'行需气不能为负')
  if not 0<=pressure<=20:raise ScheduleError('第'+str(i+1)+'行压力须在0到20bar之间')
  if not -30<=temperature<=100:raise ScheduleError('第'+str(i+1)+'行温度须在-30到100℃之间')
  if not 0<=available<=50:raise ScheduleError('第'+str(i+1)+'行可用台数须在0到50之间')
  slot=by_hour.setdefault(hour,{'hour':hour,'pressure':pressure,'temperature':temperature,'available_machines':available,'rows':[]})
  if abs(slot['pressure']-pressure)>1e-9:raise ScheduleError('第'+str(i+1)+'行与 '+hour+' 的压力不一致，整批拒绝')
  if abs(slot['temperature']-temperature)>1e-9:raise ScheduleError('第'+str(i+1)+'行与 '+hour+' 的温度不一致，整批拒绝')
  if slot['available_machines']!=available:raise ScheduleError('第'+str(i+1)+'行与 '+hour+' 的可用台数不一致，整批拒绝')
  slot['rows'].append((workshop,demand))
 hours=sorted(by_hour.values(),key=lambda h:h['hour'])
 if len(hours)>MAX_HOURS:raise ScheduleError('排机时段超过 '+str(MAX_HOURS)+' 小时')
 stamps=[datetime.fromisoformat(h['hour']) for h in hours]
 for a,b in zip(stamps,stamps[1:]):
  if b-a!=timedelta(hours=1):raise ScheduleError('小时不连续：'+a.strftime('%Y-%m-%dT%H:00')+' 与 '+b.strftime('%Y-%m-%dT%H:00')+' 之间缺小时，整批拒绝')
 out=[]
 for h in hours:
  workshops=sorted(h['rows'])
  demand=math.fsum(v for _,v in workshops)
  out.append({'hour':h['hour'],'pressure':h['pressure'],'temperature':h['temperature'],'available_machines':h['available_machines'],'demand':demand,'workshops':[{'workshop':w,'demand':d} for w,d in workshops]})
 return out
def snapshot_model(run,result):
 if run.state!='done':raise ScheduleError('仅计算成功的模型可用于排机估算')
 res=result or {}
 feats=list(res.get('features') or []);coefs=list(res.get('coefficients') or [])
 if not feats or len(coefs)!=len(feats):raise ScheduleError('模型结果缺少特征或系数，请重新计算')
 if len(set(feats))!=len(feats) or not set(feats)<=set(FEATURES):raise ScheduleError('模型特征不合法，无法用于排机')
 if 'machines' not in feats:raise ScheduleError('所选模型未包含开机台数特征，无法估算各开机台数耗电；请用含machines的方案重算')
 coef={}
 for c in coefs:
  f=c.get('feature');v=float(c.get('original_unit'))
  if f not in feats or not math.isfinite(v):raise ScheduleError('模型系数不完整，请重新计算')
  coef[f]=v
 intercept=float(res.get('intercept_original'))
 if not math.isfinite(intercept):raise ScheduleError('模型截距不完整，请重新计算')
 return {'run_id':run.id,'name':run.name,'selected_alpha':res.get('selected_alpha'),'features':feats,'coefficients':coef,'intercept_original':intercept,'training_checksum':res.get('checksum','')}
def predict(model,hour,m):
 if m==0:return 0.0,0.0
 vals={'pressure':hour['pressure'],'flow':hour['demand'],'temperature':hour['temperature'],'machines':float(m),'sensor_noise':0.0}
 raw=model['intercept_original']+sum(model['coefficients'][f]*vals[f] for f in model['features'])
 if not math.isfinite(raw):raise ScheduleError('模型估算出非有限耗电，请检查模型或输入')
 return max(0.0,raw),raw
def solve(hours,params,model):
 try:capacity=float(params['capacity_per_machine']);startup=float(params['startup_kwh']);initial=int(params['initial_machines']);max_starts=int(params['max_starts'])
 except Exception:raise ScheduleError('排机参数不完整')
 if not math.isfinite(capacity) or capacity<=0:raise ScheduleError('单台供气上限必须为正数')
 if not math.isfinite(startup) or startup<0:raise ScheduleError('启动耗电不能为负')
 if initial<0 or max_starts<0:raise ScheduleError('初始台数与增开上限不能为负')
 H=len(hours);avail=[int(h['available_machines']) for h in hours];max_avail=max(avail);M=max_avail+1;P=max(initial,max_avail)+1
 required_preview=[max(0,math.ceil(float(h['demand'])/capacity-1e-9)) for h in hours]
 achievable=0;lower_prev=initial
 for t,h in enumerate(hours):
  achievable+=max(0,avail[t]-lower_prev);lower_prev=required_preview[t]
 S=min(max_starts,achievable)+1
 energy=np.full((H,M),np.inf);raws=np.zeros((H,M));required=[]
 for t,h in enumerate(hours):
  need=max(0,math.ceil(float(h['demand'])/capacity-1e-9))
  if need>avail[t]:raise Infeasible(h['hour']+' 需气 '+format(h['demand'],'.6g')+' m³/min，按单台上限 '+format(capacity,'.6g')+' 需 '+str(need)+' 台，但该小时仅可用 '+str(avail[t])+' 台')
  required.append(need)
  for m in range(need,avail[t]+1):
   energy[t,m],raws[t,m]=predict(model,h,m)
 future_c=np.zeros((P,S));future_s=np.zeros((P,S),dtype=np.int64);choices=np.zeros((H,P,S),dtype=np.int16)
 s_idx=np.arange(S,dtype=np.int64)[None,:];prev_idx=np.arange(P,dtype=np.int64)[:,None]
 for t in range(H-1,-1,-1):
  best_c=np.full((P,S),np.inf);best_s=np.zeros((P,S),dtype=np.int64);best_m=np.zeros((P,S),dtype=np.int16)
  for m in range(required[t],avail[t]+1):
   k=np.maximum(0,m-prev_idx);valid=k<=s_idx;src=np.clip(s_idx-k,0,S-1);fc=future_c[m][src];fs=future_s[m][src]
   cand_c=np.where(valid,energy[t,m]+k*startup+fc,np.inf)
   feasible=valid&np.isfinite(fc)
   cand_s=np.where(feasible,k+fs,np.iinfo(np.int64).max)
   better=(cand_c<best_c)|((cand_c==best_c)&(cand_s<best_s)&np.isfinite(cand_c))
   best_c=np.where(better,cand_c,best_c);best_s=np.where(better,cand_s,best_s);best_m=np.where(better,np.int16(m),best_m)
  choices[t]=best_m;future_c,future_s=best_c,best_s
 cap=S-1
 if not np.isfinite(future_c[initial,cap]):
  minimal=sum(max(0,a-b) for a,b in zip([initial]+required[:-1],required))
  raise Infeasible('在总增开台次上限 '+str(max_starts)+' 内无可行排机方案'+(('；仅按最低台数轮换至少需 '+str(minimal)+' 次增开') if minimal>max_starts else ''))
 prev=initial;sleft=cap;sequence=[]
 for t in range(H):
  m=int(choices[t,prev,sleft]);sequence.append(m);sleft-=max(0,m-prev);prev=m
 if sleft<0:raise Infeasible('排机回溯失败')
 total_op=0.0;total_start=0.0;total_starts=0;hourly=[];prev=initial
 for t,(h,m) in enumerate(zip(hours,sequence)):
  started=max(0,m-prev);op=float(energy[t,m]);st=started*startup
  total_op+=op;total_start+=st;total_starts+=started
  hourly.append({'hour':h['hour'],'demand':h['demand'],'workshops':h['workshops'],'pressure':h['pressure'],'temperature':h['temperature'],'available_machines':h['available_machines'],'required_machines':required[t],'machines':m,'started':started,'supply_capacity':m*capacity,'load_ratio':(h['demand']/(m*capacity) if m*capacity>0 else 0.0),'operation_kwh':op,'startup_kwh':st,'total_kwh':op+st,'model_kwh_raw':float(raws[t,m])})
  prev=m
 summary={'total_kwh':total_op+total_start,'operation_kwh':total_op,'startup_kwh':total_start,'total_starts':total_starts,'hours':H,'start_hour':hours[0]['hour'],'end_hour':hours[-1]['hour'],'peak_demand':max(h['demand'] for h in hours),'initial_machines':initial,'max_starts':max_starts,'capacity_per_machine':capacity,'startup_kwh_per_machine':startup}
 greedy=greedy_baseline(hours,energy,required,initial,startup,max_starts)
 greedy['diff_kwh']=round(greedy['total_kwh']-summary['total_kwh'],6)
 return {'summary':summary,'hourly':hourly,'greedy':greedy}
def greedy_baseline(hours,energy,required,initial,startup,max_starts):
 '贪心对照：每小时只开满足需气的最低台数。用于暴露少开一台省运行电却多付启动电的局部最优失误。'
 prev=initial;starts=0;total=0.0
 for t in range(len(hours)):
  m=int(required[t]);started=max(0,m-prev);starts+=started;prev=m
  total+=float(energy[t,m])+started*startup
 return {'total_kwh':total,'total_starts':starts,'within_limit':starts<=max_starts}
def build_result(hours,params,model,input_checksum):
 solved=solve(hours,params,model)
 return {**solved,'model':model,'input_checksum':input_checksum,'method':'按小时连续性校验后，以成功Ridge模型的原单位系数估算该小时不同开机台数的运行耗电（模型若含sensor_noise按0代入；m=0耗电记0，负预测截为0）。动态规划状态为(上一小时台数,已用增开台次)，转移代价=该小时运行耗电+增开台数×单台启动耗电，覆盖整段求最低总耗电；同耗电同增开台次时优先较少台数。预览不占用任何小时，确认时才以小时唯一约束占用。'}
