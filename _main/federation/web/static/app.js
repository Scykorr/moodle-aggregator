'use strict';
const $ = selector => document.querySelector(selector);
let rows = [], revision = 0, dirty = false, working = false, authorized = false, polling = false;
let token = ''; // Kept in memory only, never in localStorage or URLs.
const labels = {idle:'Не проверен', queued:'В очереди', checking:'Проверяем…', moodle:'Площадка найдена', unknown:'Площадка не подтверждена', restricted:'Доступ ограничен', unreachable:'Нет соединения', invalid:'Ошибка адреса', http_error:'Ошибка ответа сервера'};
function notify(text, error=false) { $('#notice').textContent=text; $('#notice').classList.toggle('error',error); }
function setDirty(value) {dirty=value; $('#save-state').textContent=value?'Есть несохранённые изменения':'Все изменения сохранены'; $('#save-state').classList.toggle('dirty',value);}
function newId() { return globalThis.crypto?.randomUUID?.() || 'row-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2); }
async function api(path, method='GET', body) {
  const headers={'X-Aggregator-Request':'1'};
  if(token) headers.Authorization='Bearer '+token;
  if(body!==undefined) headers['Content-Type']='application/json';
  const response=await fetch(path,{method,headers,body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
  const data=await response.json();
  if(response.status===401) {authorized=false; $('#login').hidden=false; $('#workspace').hidden=true;}
  if(!response.ok) throw new Error(data.error || 'Ошибка соединения с агрегатором.');
  return data;
}
function metrics() {
  $('#total').textContent=rows.filter(r=>r.address.trim()).length;
  $('#found').textContent=rows.filter(r=>r.kind==='moodle').length;
  $('#attention').textContent=rows.filter(r=>['unknown','restricted','unreachable','invalid','http_error'].includes(r.kind)).length;
}
function updateResult(row, element) {
  const kind=row.kind || 'idle';
  element.querySelector('.badge').className='badge '+kind;
  element.querySelector('.badge').textContent=labels[kind] || 'Не проверен';
  element.querySelector('.result-detail').textContent=kind==='idle'?'':row.message || '';
  element.querySelector('.final-url').textContent=row.url && !['idle','queued','checking'].includes(kind)?row.url+' · '+row.elapsed_ms+' мс':'';
  element.querySelector('.check').disabled=working || ['queued','checking'].includes(kind);
}
function render() {
  const container=$('#servers'); container.replaceChildren();
  $('#empty').hidden=rows.length>0;
  rows.forEach((row,index)=>{
    const element=$('#row-template').content.firstElementChild.cloneNode(true);
    element.dataset.id=row.id;
    element.querySelector('.row-number').textContent=String(index+1).padStart(2,'0');
    const input=element.querySelector('.address'); input.value=row.address;
    input.disabled=working;
    element.querySelector('.remove').disabled=working;
    input.setAttribute('aria-label','Адрес сервера '+(index+1));
    input.addEventListener('input',()=>{row.address=input.value; row.kind='idle'; row.message=''; row.url=''; setDirty(true); updateResult(row,element);metrics();});
    input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();runCheck([row.id]);}});
    element.querySelector('.check').addEventListener('click',()=>runCheck([row.id]));
    element.querySelector('.remove').addEventListener('click',()=>{rows=rows.filter(item=>item.id!==row.id);setDirty(true);render();});
    updateResult(row,element);container.append(element);
  });metrics();
}
function apply(data) {revision=data.revision;rows=data.servers;setDirty(false);render();}
function controls(disabled) {
  working=disabled;
  document.querySelectorAll('#workspace button,#workspace input').forEach(element=>element.disabled=disabled);
  if(!disabled) document.querySelectorAll('.server-row').forEach(element=>{const row=rows.find(item=>item.id===element.dataset.id); if(row) updateResult(row,element);});
}
async function save() {
  const data=await api('/api/servers','PUT',{revision,servers:rows.map(({id,address})=>({id,address}))});
  apply(data);return data;
}
async function action(fn) {if(working)return; controls(true);notify('');try{await fn();}catch(error){notify(error.message,true);}finally{controls(false);}}
async function runCheck(ids) { await action(async()=>{await save(); const data=await api('/api/check','POST',{ids});apply(data);notify('Проверки запущены. Результаты обновляются автоматически.');});}
$('#add').addEventListener('click',()=>{rows.push({id:newId(),address:'',kind:'idle'});setDirty(true);render();$('#servers').lastElementChild.querySelector('input').focus();});
$('#save').addEventListener('click',()=>action(async()=>{await save();notify('Список сохранён.');}));
$('#check-all').addEventListener('click',()=>runCheck(rows.filter(row=>row.address.trim()).map(row=>row.id)));
async function load() {const data=await api('/api/servers');authorized=true;$('#login').hidden=true;$('#workspace').hidden=false;apply(data);notify('');}
$('#login-form').addEventListener('submit',async event=>{event.preventDefault();token=$('#password').value;try{await load();$('#password').value='';}catch(error){notify(error.message,true);}});
async function poll() {
  if(!authorized || working || polling)return;
  polling=true;
  try {
    const data=await api('/api/servers');
    if(data.revision<revision)return;
    if(!working){
      if(!dirty && data.revision!==revision)apply(data);
      else {
        const results=new Map(data.servers.map(row=>[row.id,row]));
        for(const row of rows){const incoming=results.get(row.id);if(incoming && incoming.address===row.address)Object.assign(row,incoming);}
        document.querySelectorAll('.server-row').forEach(element=>{const row=rows.find(item=>item.id===element.dataset.id);if(row)updateResult(row,element);});metrics();
      }
    }
  }catch(error){notify(error.message,true);}finally{polling=false;}
}
load().catch(error=>notify(error.message,true));
setInterval(poll,1200);
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
