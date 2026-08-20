const $ = (selector) => document.querySelector(selector);
const state = { items: [], filter: 'current', busy: false };
const labels = { active:'Attivo', completed:'Completato', suspended:'Sospeso', abandoned:'Abbandonato', waiting:'In attesa', unplanned:'Non pianificato', commitment:'Impegno', routine:'Routine', introduction:'Reintroduzione', possibility:'Possibilità' };

async function api(path, options = {}) {
  const response = await fetch(path, { headers:{'Content-Type':'application/json'}, ...options });
  if (!response.ok) { const body = await response.json().catch(()=>({})); throw new Error(body.detail || `Errore ${response.status}`); }
  if (response.status === 204) return null;
  return response.json();
}

function escapeHtml(value='') { const node=document.createElement('div'); node.textContent=value; return node.innerHTML; }
function displayDate(value) { return value ? new Intl.DateTimeFormat('it-IT',{day:'numeric',month:'short',year:'numeric'}).format(new Date(value)) : ''; }
function showToast(text) { const el=$('#toast'); el.textContent=text; el.classList.add('show'); setTimeout(()=>el.classList.remove('show'),2400); }

function addMessage(role, content, pending=false) {
  const node=document.createElement('article'); node.className=`message ${role}${pending?' pending':''}`;
  node.innerHTML=pending?'<span>Sto mettendo insieme il contesto…</span>':escapeHtml(content);
  $('#messages').append(node); window.scrollTo({top:document.body.scrollHeight,behavior:'smooth'}); return node;
}

async function loadMessages() {
  const messages=await api('/api/messages');
  $('#messages').innerHTML=''; messages.forEach(msg=>addMessage(msg.role,msg.content));
  if(messages.length) $('#intro').hidden=true;
}

async function loadItems() {
  state.items=await api('/api/items');
  $('#activeCount').textContent=state.items.filter(item=>['active','waiting','unplanned'].includes(item.status)).length;
  renderItems();
}

function renderItems() {
  const visible=state.filter==='all'?state.items:state.items.filter(item=>['active','waiting','unplanned','suspended'].includes(item.status));
  const list=$('#itemList');
  if(!visible.length){ list.innerHTML='<div class="empty">Non c’è ancora nulla qui.<br>Parlami di qualcosa che vuoi tenere a mente.</div>'; return; }
  list.innerHTML=visible.map(item=>`<article class="item-card" data-id="${item.id}"><h3>${escapeHtml(item.title)}</h3><div class="item-meta"><span class="tag">${labels[item.status]||item.status}</span><span class="tag">${labels[item.kind]||item.kind}</span>${item.due_at?`<span class="tag">entro ${displayDate(item.due_at)}</span>`:''}${item.progress_value!=null?`<span class="tag">${item.progress_value}${item.progress_total?`/${item.progress_total}`:''}</span>`:''}</div></article>`).join('');
  list.querySelectorAll('.item-card').forEach(card=>card.addEventListener('click',()=>openEdit(card.dataset.id)));
}

async function loadCheckins() {
  const checkins=await api('/api/checkins'); const stack=$('#checkins');
  stack.innerHTML=checkins.map(checkin=>`<article class="checkin" data-id="${checkin.id}"><small>Forse vale la pena parlarne</small>${escapeHtml(checkin.message)}<br><button>Parliamone</button></article>`).join('');
  stack.querySelectorAll('button').forEach(button=>button.addEventListener('click',async()=>{
    const card=button.closest('.checkin'); $('#messageInput').value=card.childNodes[2]?.textContent?.trim()||'Parliamone.';
    await api(`/api/checkins/${card.dataset.id}/deliver`,{method:'POST'}); card.remove(); $('#messageInput').focus();
  }));
}

async function loadUsage() {
  const usage=await api('/api/usage');
  $('#usageCost').textContent=`$${Number(usage.estimated_cost_usd).toFixed(4)} / $${Number(usage.monthly_budget_usd).toFixed(2)}`;
  $('#usageDetail').textContent=`${usage.request_count} richieste · ${usage.total_tokens} token`;
  const percent=usage.monthly_budget_usd?Math.min(100,usage.estimated_cost_usd/usage.monthly_budget_usd*100):100;
  $('#usageBar').style.width=`${Math.max(percent,percent>0?1:0)}%`;
}

async function sendMessage(message) {
  if(state.busy) return; state.busy=true; $('#intro').hidden=true; addMessage('user',message); const pending=addMessage('assistant','',true);
  $('#messageInput').value=''; resizeComposer(); $('.send').disabled=true;
  try { const result=await api('/api/chat',{method:'POST',body:JSON.stringify({message})}); pending.remove(); addMessage('assistant',result.reply); await Promise.all([loadItems(),loadUsage()]); }
  catch(error){ pending.remove(); addMessage('assistant',`Non sono riuscito a elaborare il messaggio: ${error.message}`); }
  finally { state.busy=false; $('.send').disabled=false; $('#messageInput').focus(); }
}

function openPanel(){ $('#statePanel').classList.add('open'); $('#statePanel').setAttribute('aria-hidden','false'); $('#stateToggle').setAttribute('aria-expanded','true'); $('#scrim').hidden=false; }
function closePanel(){ $('#statePanel').classList.remove('open'); $('#statePanel').setAttribute('aria-hidden','true'); $('#stateToggle').setAttribute('aria-expanded','false'); $('#scrim').hidden=true; }

function openEdit(id){ const item=state.items.find(entry=>entry.id===id); if(!item)return; $('#editId').value=id; $('#editTitle').value=item.title; $('#editStatus').value=item.status; $('#editDue').value=item.due_at?.slice(0,10)||''; $('#editMotivation').value=item.motivation||''; $('#editDialog').showModal(); }

function resizeComposer(){ const input=$('#messageInput'); input.style.height='auto'; input.style.height=`${Math.min(input.scrollHeight,160)}px`; }

$('#chatForm').addEventListener('submit',event=>{ event.preventDefault(); const value=$('#messageInput').value.trim(); if(value)sendMessage(value); });
$('#messageInput').addEventListener('input',resizeComposer);
$('#messageInput').addEventListener('keydown',event=>{ if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();$('#chatForm').requestSubmit();} });
document.querySelectorAll('[data-prompt]').forEach(button=>button.addEventListener('click',()=>sendMessage(button.dataset.prompt)));
$('#stateToggle').addEventListener('click',openPanel); $('#stateClose').addEventListener('click',closePanel); $('#scrim').addEventListener('click',closePanel);
$('#filters').addEventListener('click',event=>{ if(!event.target.dataset.filter)return; state.filter=event.target.dataset.filter; document.querySelectorAll('#filters button').forEach(btn=>btn.classList.toggle('active',btn===event.target)); renderItems(); });
$('#editForm').addEventListener('submit',async event=>{ event.preventDefault(); const id=$('#editId').value; const due=$('#editDue').value; await api(`/api/items/${id}`,{method:'PATCH',body:JSON.stringify({title:$('#editTitle').value,status:$('#editStatus').value,due_at:due?`${due}T23:59:00Z`:null,motivation:$('#editMotivation').value||null})}); $('#editDialog').close(); await loadItems(); showToast('Memoria aggiornata'); });
$('#deleteItem').addEventListener('click',async()=>{ if(!confirm('Eliminare definitivamente questo elemento? Il log di audit conserverà la traccia della modifica.'))return; await api(`/api/items/${$('#editId').value}`,{method:'DELETE'}); $('#editDialog').close(); await loadItems(); showToast('Elemento eliminato'); });
document.addEventListener('keydown',event=>{if(event.key==='Escape')closePanel();});

Promise.all([loadMessages(),loadItems(),loadCheckins(),loadUsage()]).catch(error=>showToast(error.message));
if('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js');
