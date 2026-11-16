import {state} from '../stores/session.js';
import {esc} from '../utils/html.js';
import {field} from '../components/common/fields.js';
import {api,post} from '../api/client.js';
import {PLAN_STATE_TEXT as stateText} from '../constants/enums.js';
import {parseBatch,toCSV} from '../utils/batch.js';

const DEFAULTS={capacity_per_machine:6,startup_kwh:18,initial_machines:2,max_starts:12};
const draft={text:'',hours:[],error:'',note:'',mode:null,form:null};
let deps={render(){},run:async fn=>fn(),feedback(){}};
export function configure(d){deps=d}

const SAMPLE=`hour,workshop,demand,pressure,temperature,available_machines
2026-11-11T00:00,冲压车间,8.4,6.7,22,4
2026-11-11T00:00,焊装车间,6.1,6.7,22,4
2026-11-11T01:00,冲压车间,8.9,6.7,21.6,4
2026-11-11T01:00,焊装车间,6.4,6.7,21.6,4
2026-11-11T02:00,冲压车间,5.2,6.8,21.4,4
2026-11-11T02:00,焊装车间,3.8,6.8,21.4,4
2026-11-11T03:00,冲压车间,9.6,6.8,21.2,5
2026-11-11T03:00,焊装车间,7.2,6.8,21.2,5`;

const money=x=>Number(x??0).toLocaleString('zh-CN',{maximumFractionDigits:2,minimumFractionDigits:2});
const stateClass={preview:'st-preview',confirmed:'st-confirmed',cancelled:'st-cancelled',superseded:'st-superseded'};
function tag(p){return `<span class="tag ${stateClass[p.state]||''}">${esc(stateText[p.state]||p.state)}</span>`}
function pname(id){const run=state.runs.find(r=>r.id===id);return run?run.name:'#'+id}
function hoursRows(hours){
 return hours.flatMap(h=>h.workshops.map(w=>({hour:h.hour,workshop:w.workshop,demand:w.demand,pressure:h.pressure,temperature:h.temperature,available_machines:h.available_machines})));
}
function parseDraft(){
 try{
  const parsed=parseBatch(draft.text);
  draft.hours=parsed.hours;draft.error='';draft.note=`已解析 ${parsed.hours.length} 个整点小时 / ${parsed.rows.length} 行车间需气`;
 }catch(e){draft.hours=[];draft.error=e.message;draft.note=''}
}
function importPanel(){
 const hours=draft.hours;
 const mode=draft.mode||{};
 const params={...DEFAULTS,...(mode.params||{}),...(draft.form||{})};
 const nameValue=draft.form?.name||(mode.parentId?('改排自 #'+mode.parentId):mode.reviseId?('预览 #'+mode.reviseId):'ZX-A01排机计划');
 const modelOptions=state.runs.filter(r=>r.state==='done').map(r=>`<option value="${r.id}">#${r.id} ${esc(r.name)}</option>`).join('')||'<option value="">暂无成功模型</option>';
 const title=mode.parentId?`改排 #${mode.parentId}`:mode.reviseId?`编辑预览 #${mode.reviseId}`:'导入车间需气批次';
 return `<aside class="side"><h2>${title}</h2>
 <p class="hint">CSV含表头或JSON行数组，字段 hour/workshop/demand/pressure/temperature/available_machines。同一小时的压力、温度、可用台数必须一致，小时必须连续；任一行不合法或缺口即整批拒绝。</p>
 <label>批次文本<textarea id="plan-text" rows="9" spellcheck="false" placeholder="hour,workshop,demand,pressure,temperature,available_machines">${esc(draft.text)}</textarea></label>
 <div class="row"><button id="plan-parse" type="button">解析批次</button><button id="plan-sample" type="button">填入示例</button><button id="plan-clear" type="button">清空</button></div>
 <label>或选取 CSV / JSON 文件<input id="plan-file" type="file" accept=".csv,.json,text/csv,application/json"></label>
 <p class="note ${draft.error?'bad':''}">${esc(draft.error||draft.note||'尚未解析批次。')}</p>
 ${hours.length?`<div class="scroll compact"><table><thead><tr><th>小时</th><th>车间</th><th>需气</th></tr></thead><tbody>${hours.flatMap(h=>h.workshops.map(w=>`<tr><td>${esc(h.hour)}</td><td>${esc(w.workshop)}</td><td>${money(w.demand)}</td></tr>`)).join('')}</tbody></table></div>`:''}
 <h3>排机参数</h3>
 ${mode.parentId?`<p class="note">改排沿用原计划冻结的模型系数快照。原计划与占用在新计划确认成功前保持不变。</p>`:mode.reviseId?`<p class="note">仅未确认的预览可修改；确认后输入与参数冻结。</p>`:''} <form id="plan-form">
  ${mode.parentId||mode.reviseId?'':`<label>成功模型（须包含开机台数特征）<select name="model_run_id">${modelOptions}</select></label>`}
  ${field('计划名称','name','text','required value="'+esc(nameValue)+'"')}
  ${field('单台供气上限 / m³·min⁻¹','capacity_per_machine','number',`required min=0.001 step=0.001 value="${esc(params.capacity_per_machine)}"`)}
  ${field('每增开一台启动耗电 / kWh','startup_kwh','number',`required min=0 step=0.001 value="${esc(params.startup_kwh)}"`)}
  ${field('给定初始台数','initial_machines','number',`required min=0 max=50 step=1 value="${esc(params.initial_machines)}"`)}
  ${field('总增开台次上限','max_starts','number',`required min=0 max=500 step=1 value="${esc(params.max_starts)}"`)}
  <button class="primary" id="plan-submit" ${hours.length?'':'disabled'}>${mode.parentId?'计算改排预览（不占用）':mode.reviseId?'重算预览':'计算预览（不占用时段）'}</button>
  ${mode.parentId||mode.reviseId?'<button id="plan-exit-mode" type="button">退出当前编辑</button>':''}
 </form>
 </aside>`;
}
function planRow(p){
 const s=p.summary||{};
 const current=draft.mode?.parentId===p.id||draft.mode?.reviseId===p.id;
 return `<article class="plan ${state.lastPlanId===p.id?'chosen':''} ${current?'editing':''}">
  <div class="plan-head"><h3>#${p.id} ${esc(p.name)} ${tag(p)}</h3><span class="eyebrow">${p.kind==='reschedule'?'改排 · 原计划 #'+p.parent_plan_id:'直接排机'}</span></div>
  <p class="note">模型 #${p.model_run_id} ${esc(p.result?.model?.name||pname(p.model_run_id))} · ${s.hours||0} 小时 · ${esc(s.start_hour||'')} → ${esc(s.end_hour||'')}</p>
  ${s.total_kwh!==undefined?`<div class="plan-metrics"><div><strong>${money(s.total_kwh)}</strong>总耗电 kWh</div><div><strong>${money(s.operation_kwh)}</strong>运行耗电</div><div><strong>${money(s.startup_kwh)}</strong>启动耗电</div><div><strong>${s.total_starts}</strong>增开台次</div></div>`:''}
  <p class="note">${
    p.state==='confirmed'?`占用 ${p.occupied_hours?.length||0} 小时${p.superseded_by?'，已由 #'+p.superseded_by+' 接管':''}`
    :p.state==='preview'?(p.conflicts?.length?`预览不占用时段；与已确认计划 #${p.conflicts.join('、#')} 整点重叠，确认将被拒绝`:'预览不占用任何时段，可确认')
    :p.state==='cancelled'?'已取消，相关时段已释放':'已被新改排替代，旧占用已释放'}</p>
  <div class="row">
   <button data-plan-detail="${p.id}">核对小时明细</button>
   ${p.state==='preview'?`<button class="primary" data-plan-confirm="${p.id}">确认占用</button><button data-plan-revise="${p.id}">编辑预览</button>`:''}
   ${p.state==='confirmed'?`<button data-plan-reschedule="${p.id}">改排</button>`:''}
   ${p.state==='preview'||p.state==='confirmed'?`<button data-plan-cancel="${p.id}">取消计划</button>`:''}
   <button data-plan-export="${p.id}">导出</button>
  </div>
 </article>`;
}
function detailPanel(){
 const p=state.selectedPlan;
 if(!p)return '<section class="panel"><h2>排机计划与小时明细</h2><p class="note">从下方计划记录选择“核对小时明细”，逐小时核对开机台数、运行与启动耗电。</p></section>';
 const r=p.result||{};
 const hourly=r.hourly||p.hourly||[];
 const summary=r.summary||p.summary||{};
 const owner=p.slot_owner||{};
 return `<section class="panel"><div class="result-head"><h2>#${p.id} ${esc(p.name)} ${tag(p)}</h2><span class="eyebrow">${esc(p.created_by)} · ${esc(p.created)}</span></div>
 ${p.error?`<p class="note bad">${esc(p.error)}</p>`:''}
 <div class="metrics"><div><strong>${money(summary.total_kwh)}</strong>整段总耗电 / kWh</div><div><strong>${money(summary.operation_kwh)}</strong>运行耗电 / kWh</div><div><strong>${money(summary.startup_kwh)}</strong>启动耗电 / kWh</div><div><strong>${summary.total_starts??0}</strong>增开台次 / ${summary.max_starts??'—'}</div></div>
 <p class="note">给定初始台数 ${summary.initial_machines??'—'}，单台供气上限 ${summary.capacity_per_machine??'—'} m³/min，单台启动 ${summary.startup_kwh_per_machine??'—'} kWh。输入、参数与模型原单位系数快照在创建预览时固化，确认只占用时段、不重算；确认后的计划不可再改输入或参数，只能改排或取消。校验 ${esc((p.checksum||'').slice(0,16))}…</p>
 ${r.greedy?`<p class="notice">贪心对照（每小时只开满足需气的最低台数）：${money(r.greedy.total_kwh)} kWh、${r.greedy.total_starts} 次增开${r.greedy.within_limit?'':'（超出增开上限，不可行）'}；整段最优 ${money(summary.total_kwh)} kWh，${r.greedy.diff_kwh>0?'贪心多耗 '+money(r.greedy.diff_kwh)+' kWh':'两者恰好相同'}。</p>`:''}
 <h3>逐小时明细</h3>
 <div class="scroll"><table><thead><tr><th>本地小时</th><th>需求车间 / 需气</th><th>合计需气</th><th>压力</th><th>温度</th><th>可用</th><th>最低台数</th><th>开机台数</th><th>增开</th><th>负载率</th><th>运行 kWh</th><th>启动 kWh</th><th>合计 kWh</th><th>时段占用</th></tr></thead><tbody>${hourly.map(h=>`<tr><td>${esc(h.hour)}</td><td class="wrap-cell">${esc(h.workshops.map(w=>w.workshop+' '+money(w.demand)).join(' / '))}</td><td>${money(h.demand)}</td><td>${h.pressure}</td><td>${h.temperature}</td><td>${h.available_machines}</td><td>${h.required_machines}</td><td>${h.machines}</td><td>${h.started}</td><td>${(h.load_ratio*100).toFixed(1)}%</td><td>${money(h.operation_kwh)}</td><td>${money(h.startup_kwh)}</td><td>${money(h.total_kwh)}</td><td>${owner[h.hour]?('#'+owner[h.hour]+(owner[h.hour]===p.id?' 本计划':' 其他计划')):'未占用'}</td></tr>`).join('')||'<tr><td colspan="14">无明细</td></tr>'}</tbody></table></div>
 <p class="note">${esc(r.method||'')}</p>
 </section>`;
}
export function render(){
 return `<div class="split"><section class="panel"><div class="result-head"><h2>排机计划：整点聚合 → 逐小时选台 → 确认占用</h2><button id="plan-refresh">刷新状态</button></div>
 <p class="notice">预览只计算、不占用；确认成功才以整点唯一约束占用时段，并发确认重叠计划仅一份成功。改排先出预览，新计划确认成功后才接管原占用；改排失败或取消不会改变原计划。确认后输入、参数与模型系数快照冻结。</p>
 ${detailPanel()}
 <h3>计划记录</h3>
 ${state.plans.map(planRow).join('')||'<p>暂无排机计划。请先在右侧导入车间批次并计算预览。</p>'}
 </section>${importPanel()}</div>`;
}
async function refreshPlans(){
 state.plans=await api('/plans');
 if(state.selectedPlan){
  try{state.selectedPlan=await api('/plans/'+state.selectedPlan.id)}catch(e){state.selectedPlan=null}
 }
}
async function loadDetail(id){
 state.selectedPlan=await api('/plans/'+id);
 state.lastPlanId=Number(id);
 deps.render();
}
const fieldEl=(form,key)=>form.elements.namedItem(key);
function formParams(form){
 return {
  capacity_per_machine:Number(fieldEl(form,'capacity_per_machine').value),
  startup_kwh:Number(fieldEl(form,'startup_kwh').value),
  initial_machines:Number(fieldEl(form,'initial_machines').value),
  max_starts:Number(fieldEl(form,'max_starts').value),
 };
}
function captureForm(){
 const f=document.querySelector('#plan-form');
 if(!f)return;
 draft.form={name:fieldEl(f,'name').value,capacity_per_machine:fieldEl(f,'capacity_per_machine').value,startup_kwh:fieldEl(f,'startup_kwh').value,initial_machines:fieldEl(f,'initial_machines').value,max_starts:fieldEl(f,'max_starts').value};
}
function loadForEdit(p,kind){
 draft.form=null;
 draft.mode=kind==='reschedule'?{parentId:p.id,params:p.params}:{reviseId:p.id,params:p.params};
 draft.text=toCSV(p.input.hours);
 parseDraft();
 draft.note=`已载入 #${p.id} 的冻结批次与参数，修改后计算${kind==='reschedule'?'改排预览':'预览重算'}。`;
 deps.render();
}
export function bind(){
 const text=document.querySelector('#plan-text');
 if(text)text.oninput=()=>{draft.text=text.value;draft.hours=[];draft.note='';draft.error=''};
 document.querySelector('#plan-parse')?.addEventListener('click',()=>{captureForm();parseDraft();deps.render()});
 document.querySelector('#plan-sample')?.addEventListener('click',()=>{captureForm();draft.mode=null;draft.text=SAMPLE;parseDraft();deps.render()});
 document.querySelector('#plan-clear')?.addEventListener('click',()=>{draft.text='';draft.hours=[];draft.error='';draft.note='';deps.render()});
 const file=document.querySelector('#plan-file');
 if(file)file.onchange=()=>deps.run(async()=>{
  const f=file.files[0];if(!f)return;
  captureForm();draft.text=await f.text();parseDraft();deps.render();
 });
 document.querySelector('#plan-exit-mode')?.addEventListener('click',()=>{draft.mode=null;draft.form=null;draft.text='';draft.hours=[];draft.note='';draft.error='';deps.render()});
 const form=document.querySelector('#plan-form');
 if(form)form.onsubmit=e=>{e.preventDefault();deps.run(async()=>{
  if(!draft.hours.length)parseDraft();
  if(draft.error||!draft.hours.length)throw Error(draft.error||'请先解析批次');
  const body={name:fieldEl(form,'name').value,rows:hoursRows(draft.hours),params:formParams(form)};
  let saved;
  if(draft.mode?.parentId)saved=await post('/plans/'+draft.mode.parentId+'/reschedule',body);
  else if(draft.mode?.reviseId)saved=await api('/plans/'+draft.mode.reviseId,{method:'PUT',body:JSON.stringify({rows:body.rows,params:body.params})});
  else{
   const modelField=fieldEl(form,'model_run_id');
   if(!modelField||!modelField.value)throw Error('没有可用的成功模型，请先在“特征方案”提交并等待计算完成');
   saved=await post('/plans/preview',{...body,model_run_id:Number(modelField.value)});
  }
  draft.mode=null;draft.form=null;draft.text='';draft.hours=[];draft.note='';draft.error='';
  state.selectedPlan=saved;state.lastPlanId=saved.id;
  await refreshPlans();deps.render();
 })};
 document.querySelector('#plan-refresh')?.addEventListener('click',()=>deps.run(async()=>{await refreshPlans();deps.render()}));
 document.querySelectorAll('[data-plan-detail]').forEach(b=>b.onclick=()=>deps.run(()=>loadDetail(b.dataset.planDetail)));
 document.querySelectorAll('[data-plan-confirm]').forEach(b=>b.onclick=()=>deps.run(async()=>{
  const out=await post('/plans/'+b.dataset.planConfirm+'/confirm',{});
  state.selectedPlan=out;state.lastPlanId=out.id;await refreshPlans();deps.render();
  if(out.idempotent)deps.feedback('该计划此前已确认，本次未重复占用。');
 }));
 document.querySelectorAll('[data-plan-cancel]').forEach(b=>b.onclick=()=>deps.run(async()=>{
  const out=await post('/plans/'+b.dataset.planCancel+'/cancel',{});
  state.selectedPlan=out;state.lastPlanId=out.id;await refreshPlans();deps.render();
  if(out.idempotent)deps.feedback('该计划此前已取消，时段未被重复释放。');
 }));
 document.querySelectorAll('[data-plan-reschedule]').forEach(b=>b.onclick=()=>deps.run(async()=>loadForEdit(await api('/plans/'+b.dataset.planReschedule),'reschedule')));
 document.querySelectorAll('[data-plan-revise]').forEach(b=>b.onclick=()=>deps.run(async()=>loadForEdit(await api('/plans/'+b.dataset.planRevise),'revise')));
 document.querySelectorAll('[data-plan-export]').forEach(b=>b.onclick=()=>deps.run(async()=>{
  const d=await api('/plans/'+b.dataset.planExport);
  const u=URL.createObjectURL(new Blob([JSON.stringify(d,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=u;a.download='airpower-plan-'+b.dataset.planExport+'.json';a.click();URL.revokeObjectURL(u);
 }));
}
