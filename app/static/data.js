const $=selector=>document.querySelector(selector);
const labels={items:'Oggetti',relations:'Relazioni',progress_events:'Progressi',activity_records:'Attività',messages:'Messaggi',checkins:'Richiami',audit_log:'Modifiche',ai_usage:'Uso AI'};
const state={snapshot:{},table:'items',search:'',category:''};

function showToast(text){const node=$('#toast');node.textContent=text;node.classList.add('show');setTimeout(()=>node.classList.remove('show'),2200);}
function displayValue(value){
  if(value===null||value===undefined||value==='')return '—';
  if(typeof value==='object')return JSON.stringify(value);
  const text=String(value);
  if((text.startsWith('{')||text.startsWith('['))&&text.length>2){try{return JSON.stringify(JSON.parse(text),null,2);}catch{}}
  return text;
}
function categories(){return [...new Set((state.snapshot.items||[]).map(row=>row.category).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'it'));}
function categoryFor(row){
  if(state.table==='items')return row.category||'';
  const itemId=row.item_id||row.source_id||row.entity_id;
  return (state.snapshot.items||[]).find(item=>item.id===itemId)?.category||'';
}
function rows(){
  const needle=state.search.toLocaleLowerCase('it');
  return (state.snapshot[state.table]||[]).filter(row=>(!state.category||categoryFor(row)===state.category)&&(!needle||JSON.stringify(row).toLocaleLowerCase('it').includes(needle)));
}
function renderTabs(){
  $('#tabs').innerHTML=Object.keys(state.snapshot).map(name=>`<button class="${name===state.table?'active':''}" data-table="${name}">${labels[name]||name}<span>${state.snapshot[name].length}</span></button>`).join('');
}
function renderTable(){
  const visible=rows();const all=state.snapshot[state.table]||[];const columns=[...new Set(all.flatMap(row=>Object.keys(row)))];
  $('#tableTitle').textContent=labels[state.table]||state.table;$('#rowCount').textContent=`${visible.length} di ${all.length} righe`;
  $('#tableHead').innerHTML=`<tr>${columns.map(column=>`<th>${column}</th>`).join('')}</tr>`;
  $('#tableBody').innerHTML=visible.map(row=>`<tr>${columns.map(column=>`<td><pre>${escapeHtml(displayValue(row[column]))}</pre></td>`).join('')}</tr>`).join('');
  $('#empty').hidden=visible.length>0;renderTabs();
}
function escapeHtml(value){const node=document.createElement('div');node.textContent=value;return node.innerHTML;}
async function load(){
  const response=await fetch('/api/debug/raw');if(!response.ok)throw new Error(`Errore ${response.status}`);state.snapshot=await response.json();
  if(!state.snapshot[state.table])state.table=Object.keys(state.snapshot)[0];
  const current=$('#category').value;$('#category').innerHTML='<option value="">Tutte le categorie</option>'+categories().map(category=>`<option>${escapeHtml(category)}</option>`).join('');$('#category').value=current;
  $('#jsonContent').textContent=JSON.stringify(state.snapshot,null,2);renderTable();
}

$('#tabs').addEventListener('click',event=>{const button=event.target.closest('[data-table]');if(!button)return;state.table=button.dataset.table;renderTable();});
$('#search').addEventListener('input',event=>{state.search=event.target.value;renderTable();});
$('#category').addEventListener('change',event=>{state.category=event.target.value;renderTable();});
$('#refresh').addEventListener('click',()=>load().then(()=>showToast('Dati aggiornati')).catch(error=>showToast(error.message)));
$('#jsonOpen').addEventListener('click',()=>$('#jsonDialog').showModal());$('#jsonClose').addEventListener('click',()=>$('#jsonDialog').close());
$('#jsonCopy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('#jsonContent').textContent);showToast('JSON copiato');}catch{showToast('Copia non disponibile');}});
load().catch(error=>showToast(error.message));
