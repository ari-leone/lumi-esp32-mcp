'use strict';
const $ = id => document.getElementById(id);
const state = {view:'pending', query:'', items:[], next:null, editor:null, kind:'task', request:null, loading:0, deleting:null};
const views = {
  pending:{title:'Tus pendientes',description:'Paso a paso, lo importante encuentra su lugar.',label:'Tu lista de tareas',empty:'Haz espacio para lo que viene',hint:'Añade tu primera tarea y empieza por un pequeño paso.'},
  completed:{title:'Lo que ya has hecho',description:'Cada pequeño paso cuenta. Aquí están los tuyos.',label:'Tareas completadas',empty:'Aquí irán tus pequeños logros',hint:'Cuando completes una tarea, la encontrarás aquí.'},
  notes:{title:'Tus ideas, a salvo',description:'Un lugar para todo lo que no quieres olvidar.',label:'Tus notas',empty:'Una idea merece su lugar',hint:'Guarda una nota y vuelve a ella cuando la necesites.'},
  trash:{title:'Tu papelera',description:'A veces cambias de idea. Puedes recuperarlo todo.',label:'Elementos en papelera',empty:'Todo está en su sitio',hint:'Las notas y tareas que retires aparecerán aquí.'}
};
let toastTimer, searchTimer;
const dateFormatter = new Intl.DateTimeFormat('es-ES',{timeZone:'Europe/Madrid',day:'numeric',month:'short',year:'numeric'});
const timeFormatter = new Intl.DateTimeFormat('es-ES',{timeZone:'Europe/Madrid',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
function localDay(){return new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Madrid',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());}
function dueLabel(value){return dateFormatter.format(new Date(value+'T12:00:00Z'));}
function node(tag,className,text){const el=document.createElement(tag);if(className)el.className=className;if(text!==undefined)el.textContent=text;return el;}
function toast(message,error=false){clearTimeout(toastTimer);$('toast').textContent=message;$('toast').className='toast'+(error?' error':'');$('toast').hidden=false;toastTimer=setTimeout(()=>$('toast').hidden=true,5000);}
async function api(path,body){
  let response;
  try{response=await fetch(path,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json','X-Lumi-Client':'local'},body:JSON.stringify(body)});}
  catch{const error=new Error('No se puede conectar con Lumi. Conserva tu borrador y vuelve a intentarlo.');error.code='network';throw error;}
  const result=await response.json();
  if(!response.ok){const error=new Error(result.message||'No se pudo completar la operación.');error.code=result.error;throw error;}
  return result;
}
async function refresh(append=false){
  const ticket=++state.loading;
  const offset=append?state.next||0:0;
  try{
    const [list,counts]=await Promise.all([api(`/api/items?view=${state.view}&q=${encodeURIComponent(state.query)}&offset=${offset}&limit=50`),api('/api/counts')]);
    if(ticket!==state.loading)return;
    state.items=append?[...state.items,...list.items]:list.items;state.next=list.next_offset;
    $('load-error').hidden=true;$('connection').lastChild.textContent='Espacio local';
    for(const key of ['pending','completed','notes','trash'])$('count-'+key).textContent=counts[key];
    for(const key of ['pending','completed','notes'])$('summary-'+key).textContent=counts[key];
    $('list-total').textContent=list.total;
    $('footer-count').textContent=`${list.total} ${state.view==='notes'?'notas':state.view==='trash'?'elementos':'tareas'} en esta lista`;
    render();
  }catch(error){if(ticket!==state.loading)return;$('error-message').textContent=error.message;$('load-error').hidden=false;$('connection').lastChild.textContent='Sin conexión';}
}
function render(){
  const info=views[state.view];$('items').replaceChildren();
  for(const item of state.items){
    const row=node('article','item'+(item.status==='completed'&&item.kind==='task'?' completed':''));
    if(item.kind==='task'&&state.view!=='trash'){
      const check=node('button','check-button'+(item.status==='completed'?' checked':''),item.status==='completed'?'✓':'');
      check.setAttribute('aria-label',(item.status==='completed'?'Reabrir ':'Completar ')+item.title);
      check.onclick=()=>operate(item,item.status==='completed'?'reopen':'complete',check);row.append(check);
    }else row.append(node('span','note-icon',item.kind==='note'?'▤':'✓'));
    const content=node('div','item-main'),title=node('button','item-title',item.title);
    title.onclick=()=>openEditor(item);content.append(title);
    if(item.text)content.append(node('p','item-preview',item.text));
    const details=node('div','item-details');
    if(item.due_date){const overdue=item.due_date<localDay()&&item.status==='pending';details.append(node('span','date-badge'+(overdue?' overdue':''),(overdue?'Vencida · ':'◷ ')+dueLabel(item.due_date)));}
    if(item.deleted_at)details.append(node('span','',`Retirada ${timeFormatter.format(new Date(item.deleted_at))}`));
    else if(item.completed_at&&item.kind==='task')details.append(node('span','',`Completada ${timeFormatter.format(new Date(item.completed_at))}`));
    else details.append(node('span','',`Actualizada ${timeFormatter.format(new Date(item.updated_at))}`));
    content.append(details);row.append(content);
    const actions=node('div','item-actions');
    if(state.view==='trash'){
      const restore=node('button','restore','Restaurar');restore.onclick=()=>operate(item,'restore',restore);actions.append(restore);
    }else{
      const edit=node('button','icon-button','✎');edit.setAttribute('aria-label','Editar '+item.title);edit.title='Editar';edit.onclick=()=>openEditor(item);
      const remove=node('button','icon-button','×');remove.setAttribute('aria-label','Mover a la papelera '+item.title);remove.title='Mover a la papelera';remove.onclick=()=>{state.deleting=item;$('confirm-text').textContent=`«${item.title}» se moverá a la papelera.`;$('confirm-dialog').showModal();};actions.append(edit,remove);
    }
    row.append(actions);$('items').append(row);
  }
  $('empty').hidden=state.items.length>0;$('load-more').hidden=state.next===null;
  const searching=Boolean(state.query);$('empty-title').textContent=searching?'No encontramos coincidencias':info.empty;
  $('empty-description').textContent=searching?'Prueba con otro título o una palabra del contenido.':info.hint;
  $('empty-create').hidden=searching||!['pending','notes'].includes(state.view);
  $('empty-create').textContent=state.view==='notes'?'＋ Crear mi primera nota':'＋ Crear mi primera tarea';
}
function changeView(view){
  state.view=view;state.query='';state.items=[];state.next=null;$('search').value='';
  document.querySelectorAll('[data-view]').forEach(el=>{el.classList.toggle('active',el.dataset.view===view);el.setAttribute('aria-current',el.dataset.view===view?'page':'false');});
  const info=views[view];$('view-title').replaceChildren(document.createTextNode(info.title),node('span','','.'));
  $('view-description').textContent=info.description;$('list-label').replaceChildren(document.createTextNode(info.label+' '),$('list-total'));
  $('new-button').hidden=view==='trash';$('new-button').replaceChildren(node('span','','＋'),document.createTextNode(view==='notes'?' Nueva nota':' Nueva tarea'));
  $('search').placeholder=view==='notes'?'Buscar en tus notas…':'Buscar en esta lista…';refresh();
}
async function openEditor(item=null){
  state.editor=item;state.kind=item?.kind||(state.view==='notes'?'note':'task');state.request=null;
  const isNote=state.kind==='note',trashed=Boolean(item?.deleted_at);
  $('editor-title').textContent=(trashed?'Ver ':item?'Editar ':'Nueva ')+(isNote?'nota':'tarea');
  $('editor-eyebrow').textContent=isNote?'UNA IDEA QUE SE QUEDA':'UN PEQUEÑO PASO';
  $('title').value=item?.title||'';$('text').value=item?.text||'';$('due-date').value=item?.due_date||'';
  $('date-field').hidden=isNote;$('text-label').replaceChildren(document.createTextNode(isNote?'Contenido ':'Descripción '),node('span','','opcional'));
  $('save-button').textContent='Guardar '+(isNote?'nota':'tarea');$('save-button').hidden=trashed;
  for(const id of ['title','text','due-date'])$(id).readOnly=trashed;
  $('editor-error').hidden=true;$('reload-item').hidden=true;
  $('editor-meta').textContent=item?`Guardado en tu PC · Actualizado ${timeFormatter.format(new Date(item.updated_at))} · Versión ${item.version}`:'Se guardará en tu PC. Puedes volver a editarlo cuando quieras.';
  if(!$('editor').open)$('editor').showModal();
  $('title').focus();
}
function closeEditor(){
  const item=state.editor;
  const changed=$('title').value!==(item?.title||'')||$('text').value!==(item?.text||'')||$('due-date').value!==(item?.due_date||'');
  if(changed&&!item?.deleted_at&&!window.confirm('Tienes cambios sin guardar. ¿Quieres descartarlos?'))return;
  $('editor').close();state.request=null;
}
async function save(event){
  event.preventDefault();const button=$('save-button');button.disabled=true;
  const item=state.editor;
  const body={kind:state.kind,title:$('title').value,text:$('text').value,due_date:state.kind==='task'?$('due-date').value||null:null};
  if(item)body.expected_version=item.version;
  // Reuse the same request after uncertain network failures; editing changes the key.
  const signature=JSON.stringify(body);
  if(!state.request||state.request.signature!==signature)state.request={signature,id:crypto.randomUUID()};
  body.request_id=state.request.id;
  try{await api(item?`/api/items/${item.id}/update`:'/api/items',body);$('editor').close();toast(item?'Cambios guardados.':state.kind==='note'?'Tu idea ya está guardada.':'Tarea guardada. Un pequeño paso más.');state.request=null;await refresh();}
  catch(error){$('editor-error').textContent=error.message;$('editor-error').hidden=false;$('reload-item').hidden=error.code!=='conflict';}
  finally{button.disabled=false;}
}
async function operate(item,action,button){
  button.disabled=true;
  try{await api(`/api/items/${item.id}/${action}`,{expected_version:item.version,request_id:crypto.randomUUID()});toast({complete:'Un pendiente menos. Bien hecho.',reopen:'Tarea de nuevo en pendientes.',delete:'Movido a la papelera. Puedes recuperarlo.',restore:'Elemento restaurado.'}[action]);await refresh();}
  catch(error){toast(error.message,true);await refresh();}finally{button.disabled=false;}
}
$('today').textContent=new Intl.DateTimeFormat('es-ES',{timeZone:'Europe/Madrid',weekday:'long',day:'numeric',month:'long'}).format(new Date());
document.querySelectorAll('[data-view]').forEach(el=>el.onclick=()=>changeView(el.dataset.view));
$('new-button').onclick=()=>openEditor();$('empty-create').onclick=()=>openEditor();
$('close-editor').onclick=closeEditor;$('cancel-editor').onclick=closeEditor;
$('editor').addEventListener('cancel',event=>{event.preventDefault();closeEditor();});
$('editor-form').onsubmit=save;
$('reload-item').onclick=async()=>{
  if(!window.confirm('Recargar reemplaza el borrador con los datos actuales. Puedes copiar tu texto antes de continuar.'))return;
  try{await openEditor(await api('/api/items/'+state.editor.id));}catch(error){toast(error.message,true);}
};
$('search').oninput=()=>{clearTimeout(searchTimer);state.query=$('search').value;searchTimer=setTimeout(()=>refresh(),220);};
$('retry-button').onclick=()=>refresh();$('load-more').onclick=()=>refresh(true);
$('cancel-delete').onclick=()=>$('confirm-dialog').close();
$('confirm-delete').onclick=async()=>{await operate(state.deleting,'delete',$('confirm-delete'));$('confirm-dialog').close();};
$('export-button').onclick=async()=>{
  try{const data=await api('/api/export');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=node('a');a.href=url;a.download=`lumi-${localDay()}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Exportación preparada.');}catch(error){toast(error.message,true);}
};
$('import-button').onclick=()=>$('import-file').click();
$('import-file').onchange=async event=>{
  const file=event.target.files[0];if(!file)return;
  const button=$('import-button');button.disabled=true;
  try{if(file.size>10_000_000)throw new Error('El archivo supera el límite de 10 MB.');const data=JSON.parse(await file.text());if(!window.confirm('¿Importar esta exportación de Lumi? Los elementos existentes no se sobrescribirán.'))return;const result=await api('/api/import',data);toast(`${result.imported} importados · ${result.skipped} ya existentes.`);await refresh();}
  catch(error){toast(error.message,true);}finally{event.target.value='';button.disabled=false;}
};
$('backup-button').onclick=async()=>{const button=$('backup-button');button.disabled=true;try{await api('/api/backup',{});toast('Copia de seguridad creada y verificada.');}catch(error){toast(error.message,true);}finally{button.disabled=false;}};
window.addEventListener('beforeunload',event=>{if($('editor').open&&!state.editor?.deleted_at&&($('title').value!==(state.editor?.title||'')||$('text').value!==(state.editor?.text||'')||$('due-date').value!==(state.editor?.due_date||''))){event.preventDefault();event.returnValue='';}});
setInterval(()=>{if(document.visibilityState==='visible'&&!$('editor').open&&!$('confirm-dialog').open&&state.next===null&&state.items.length<=50)refresh();},15000);
changeView('pending');
