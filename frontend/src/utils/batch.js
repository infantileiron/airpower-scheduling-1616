// 批量需气行解析：CSV（含表头）或 JSON 数组；任一行不合法即整批拒绝。
const COLUMNS=['hour','workshop','demand','pressure','temperature','available_machines'];
export function parseCSV(text){
  const rows=[];let row=[],cell='',quoted=false;
  for(let i=0;i<text.length;i++){
    const ch=text[i];
    if(quoted){
      if(ch==='"'){if(text[i+1]==='"'){cell+='"';i++}else quoted=false}else cell+=ch;
    }else if(ch==='"'){quoted=true}
    else if(ch===','){row.push(cell);cell=''}
    else if(ch==='\n'){row.push(cell);rows.push(row);row=[];cell=''}
    else if(ch==='\r'){}
    else cell+=ch;
  }
  if(cell!==''||row.length){row.push(cell);rows.push(row)}
  return rows.filter(r=>r.some(c=>c.trim()!==''));
}
export function parseBatch(text){
  if(!text||!text.trim())throw Error('批次为空：请粘贴CSV或选择JSON/CSV文件');
  const trimmed=text.trim();
  let raw;
  if(trimmed.startsWith('[')||trimmed.startsWith('{')){
    let data;
    try{data=JSON.parse(trimmed)}catch(e){throw Error('JSON解析失败：'+e.message)}
    if(!Array.isArray(data))throw Error('JSON批次必须是行数组');
    raw=data;
  }else{
    const table=parseCSV(trimmed);
    if(table.length<2)throw Error('CSV需要表头行和至少一行数据');
    const header=table[0].map(h=>h.trim());
    const missing=COLUMNS.filter(c=>!header.includes(c));
    if(missing.length)throw Error('CSV缺少列：'+missing.join('、')+'（需要 '+COLUMNS.join(',')+'）');
    raw=table.slice(1).map((cells,i)=>{
      const obj={};
      header.forEach((h,j)=>{obj[h]=(cells[j]??'').trim()});
      obj.__line=i+2;
      return obj;
    });
  }
  if(!raw.length)throw Error('批次为空：至少需要一行车间小时需气');
  const rows=raw.map((r,i)=>{
    const line=r.__line??i+1;
    const item={};
    for(const c of COLUMNS){
      if(r[c]===undefined||r[c]===null||String(r[c]).trim()==='')throw Error(`第${line}行缺少 ${c}`);
      item[c]=c==='hour'||c==='workshop'?String(r[c]).trim():Number(String(r[c]).trim());
      if(c!=='hour'&&c!=='workshop'&&!Number.isFinite(item[c]))throw Error(`第${line}行 ${c} 不是数值`);
    }
    return item;
  });
  return aggregateRows(rows);
}
export function aggregateRows(rows){
  const seen=new Set(),byHour=new Map();
  rows.forEach((r,i)=>{
    const line=i+1;
    if(!/^\d{4}-\d{2}-\d{2}T\d{2}:00$/.test(r.hour))throw Error(`第${line}行小时须为本地整点，如2026-11-01T08:00`);
    if(!r.workshop)throw Error(`第${line}行车间为空`);
    const key=r.hour+'|'+r.workshop;
    if(seen.has(key))throw Error(`第${line}行重复：${r.workshop} 在 ${r.hour} 已出现，整批拒绝`);
    seen.add(key);
    if(r.demand<0)throw Error(`第${line}行需气不能为负`);
    if(r.pressure<0||r.pressure>20)throw Error(`第${line}行压力须在0到20bar之间`);
    if(r.temperature<-30||r.temperature>100)throw Error(`第${line}行温度须在-30到100℃之间`);
    if(!Number.isInteger(r.available_machines)||r.available_machines<0||r.available_machines>50)throw Error(`第${line}行可用台数须为0到50的整数`);
    const slot=byHour.get(r.hour);
    if(slot){
      if(Math.abs(slot.pressure-r.pressure)>1e-9)throw Error(`第${line}行与 ${r.hour} 的压力不一致，整批拒绝`);
      if(Math.abs(slot.temperature-r.temperature)>1e-9)throw Error(`第${line}行与 ${r.hour} 的温度不一致，整批拒绝`);
      if(slot.available_machines!==r.available_machines)throw Error(`第${line}行与 ${r.hour} 的可用台数不一致，整批拒绝`);
      slot.workshops.push({workshop:r.workshop,demand:r.demand});
    }else byHour.set(r.hour,{hour:r.hour,pressure:r.pressure,temperature:r.temperature,available_machines:r.available_machines,workshops:[{workshop:r.workshop,demand:r.demand}]});
  });
  const hours=[...byHour.values()].sort((a,b)=>a.hour<b.hour?-1:1);
  for(let i=1;i<hours.length;i++){
    const prev=new Date(hours[i-1].hour).getTime(),cur=new Date(hours[i].hour).getTime();
    if(cur-prev!==3600000)throw Error(`小时不连续：${hours[i-1].hour} 与 ${hours[i].hour} 之间缺小时，整批拒绝`);
  }
  for(const h of hours){
    h.workshops.sort((a,b)=>a.workshop<b.workshop?-1:1);
    h.demand=h.workshops.reduce((s,w)=>s+w.demand,0);
  }
  return {rows,hours};
}
export function toCSV(hours){
  const lines=['hour,workshop,demand,pressure,temperature,available_machines'];
  for(const h of hours)for(const w of h.workshops)lines.push([h.hour,w.workshop,w.demand,h.pressure,h.temperature,h.available_machines].join(','));
  return lines.join('\n');
}
