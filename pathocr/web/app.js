'use strict';
history.replaceState(null,'',location.pathname);
const $ = id => document.getElementById(id);
let state = {jobs:[],settings:{},runtime:{}}, selected = null, activeTab = 'render', page = 1, text = '', lastRevision = '', uploading = false;
const labels = {queued:'Queued',running:'Processing',completed:'Saved',error:'Failed',cancelled:'Cancelled',interrupted:'Interrupted'};
function toast(message) { $('toast').textContent=message; $('toast').hidden=false; clearTimeout(toast.timer); toast.timer=setTimeout(()=>$('toast').hidden=true,4500); }
async function api(url, options={}) { const r=await fetch(url,options); if(!r.ok) { let message='Request failed'; try {message=(await r.json()).detail||message;} catch{} throw Error(typeof message==='string'?message:JSON.stringify(message)); } return r.json(); }
function el(tag, cls, content) { const e=document.createElement(tag); if(cls)e.className=cls; if(content!==undefined)e.textContent=content; return e; }
async function action(url) {try {await api(url,{method:'POST'}); await refresh();}catch(e){toast(e.message);} }
function drawJobs() {
  $('count').textContent=state.jobs.length;
  $('empty').hidden=!!state.jobs.length;
  const frag=document.createDocumentFragment();
  for(const job of state.jobs) {
    const row=el('div','job'+(selected===job.id?' selected':'')); row.tabIndex=0; row.setAttribute('role','button'); row.setAttribute('aria-label',job.name);
    const top=el('div','job-top'); top.append(el('span','file-icon','PDF'),el('span','job-name',job.name),el('span','badge '+job.status,labels[job.status]||job.status)); row.append(top);
    const meta=el('div','job-meta'); meta.append(el('span','',`${job.done} / ${job.pages} pages`));
    if(['queued','running'].includes(job.status)) {const b=el('button','text-button','Cancel'); b.onclick=e=>{e.stopPropagation();action(`/api/jobs/${job.id}/cancel`);};meta.append(b);}
    if(['error','cancelled','interrupted'].includes(job.status)) {const b=el('button','text-button','Resume ↻'); b.onclick=e=>{e.stopPropagation();action(`/api/jobs/${job.id}/retry`);};meta.append(b);}
    row.append(meta);
    if(job.status==='running'){const p=el('progress');p.max=job.pages;p.value=job.done;row.append(p);}
    if(job.error){row.append(el('p','job-error',job.error));}
    const pick=()=>{selected=job.id;page=1;lastRevision='';drawJobs();updatePreview();}; row.onclick=pick;row.onkeydown=e=>{if(e.key==='Enter')pick();};frag.append(row);
  }
  $('jobs').replaceChildren(frag);
}
async function refresh() {
  try {
    state=await api('/api/state'); drawJobs();
    const r=state.runtime;
    $('engine-light').className='light '+r.status;
    $('engine-message').textContent=r.message;
    $('engine-message').title=r.fallback_reason||r.message;
    $('engine-title').textContent=r.status==='ready'?`Local OCR · ${r.backend==='cpu'?'CPU':`GPU / ${(r.backend||'').toUpperCase()}`}`:'OCR engine';
    $('setup-button').hidden=r.status==='ready';
    $('setup-button').disabled=['installing','loading'].includes(r.status);
    $('setup-button').textContent=r.installed?'Start OCR engine':'Install engine and models';
    $('setup-progress').hidden=r.status!=='installing'||!r.total;
    $('setup-progress').max=r.total||1; $('setup-progress').value=r.received||0;
    $('output-path').textContent='Auto-save to '+state.settings.output_dir;
    if(!selected && state.jobs.length){selected=state.jobs[0].id;drawJobs();}
    await updatePreview();
  } catch(e){$('engine-message').textContent=e.message;}
}
async function updatePreview() {
  const job=state.jobs.find(j=>j.id===selected);if(!job)return;
  $('preview-title').textContent=job.name;
  $('download').hidden=job.status!=='completed';$('download').href=`/api/jobs/${job.id}/download`;
  $('preview-meta').textContent=job.status==='completed'?`Saved automatically · ${job.output}`:`${labels[job.status]} · Processed ${job.done} / ${job.pages} pages`;
  $('original').href=`/api/jobs/${job.id}/pdf`;
  const rev=`${job.id}-${job.done}-${job.status}`;
  if(lastRevision!==rev){
    const id=job.id;
    try{
      const result=await api(`/api/jobs/${id}/markdown`);if(selected!==id)return;
      text=result.text;$('source').textContent=text||'Waiting for results…';
      if(text && window.marked && window.DOMPurify){
        $('render').innerHTML=DOMPurify.sanitize(marked.parse(text),{FORBID_TAGS:['img','style','iframe','form','input','video','audio'],FORBID_ATTR:['style']});
        $('render').querySelectorAll('a').forEach(a=>{a.target='_blank';a.rel='noopener noreferrer';});
      }else{$('render').replaceChildren(el('div',text?'':'empty',text||'Completed pages will appear here'));}
      lastRevision=rev;
    }catch(e){toast(e.message);}
  }
  $('page-label').textContent=`${page} / ${job.pages}`;
  $('prev-page').disabled=page<=1;$('next-page').disabled=page>=job.pages;
  const url=`/api/jobs/${job.id}/page/${page}`;if($('pdf-page').getAttribute('src')!==url && activeTab==='pdf')$('pdf-page').src=url;
}
function switchTab(tab) {activeTab=tab;for(const name of ['render','source','pdf'])$(name).hidden=tab!==name;document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('selected',b.dataset.tab===tab));updatePreview();}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>switchTab(b.dataset.tab));
$('prev-page').onclick=()=>{if(page>1)page--;updatePreview();};$('next-page').onclick=()=>{const j=state.jobs.find(j=>j.id===selected);if(j&&page<j.pages)page++;updatePreview();};
$('copy').onclick=async()=>{try{await navigator.clipboard.writeText(text);toast('Markdown copied');}catch{toast('Clipboard access was denied. Copy manually from Source text.');}};
$('setup-button').onclick=()=>action('/api/setup');
$('open-folder').onclick=()=>action('/api/open-output');
$('choose-folder').onclick=async()=>{try{const r=await api('/api/choose-output',{method:'POST'});if(r.path)$('settings-form').elements.output_dir.value=r.path;}catch(e){$('settings-error').textContent=e.message;}};
$('quit').onclick=async()=>{try{await api('/api/shutdown',{method:'POST'});toast('The app is closing. Resume unfinished tasks next time.');}catch(e){toast(e.message);}};
$('cancel-all').onclick=async()=>{for(const j of state.jobs.filter(j=>['queued','running'].includes(j.status)))await action(`/api/jobs/${j.id}/cancel`);};
$('settings-button').onclick=()=>{for(const [k,v] of Object.entries(state.settings)){if($('settings-form').elements[k])$('settings-form').elements[k].value=v;}$('settings-error').textContent='';$('settings').showModal();};
$('close-settings').onclick=()=>$('settings').close();
$('settings-form').onsubmit=async e=>{e.preventDefault();const value=Object.fromEntries(new FormData(e.target));for(const k of ['dpi','max_tokens','gpu_layers'])value[k]=Number(value[k]);try{await api('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});$('settings').close();toast('Settings saved');refresh();}catch(e){$('settings-error').textContent=e.message;}};
function uploadOne(file,index,total) {return new Promise((resolve,reject)=>{const data=new FormData();data.append('file',file);const xhr=new XMLHttpRequest();xhr.open('POST','/api/jobs');xhr.upload.onprogress=e=>{$('upload-status').textContent=`Adding ${index}/${total} · ${file.name} · ${e.lengthComputable?Math.round(e.loaded/e.total*100)+'%':''}`;};xhr.onload=()=>{if(xhr.status>=200&&xhr.status<300)resolve(JSON.parse(xhr.responseText));else{try{reject(Error(JSON.parse(xhr.responseText).detail));}catch{reject(Error('Upload failed'));}}};xhr.onerror=()=>reject(Error('Connection interrupted'));xhr.send(data);});}
async function addFiles(files) {
  if(uploading){toast('Files are being added. Please wait before dropping more.');return;}
  const list=Array.from(files);if(!list.length)return;
  uploading=true;$('choose-files').disabled=true;let added=0,failed=0;
  for(let i=0;i<list.length;i++){
    const file=list[i];if(!file.name.toLowerCase().endsWith('.pdf')){failed++;continue;}
    try{const result=await uploadOne(file,i+1,list.length);added++;if(!selected)selected=result.id;await refresh();}catch(e){failed++;toast(`${file.name}: ${e.message}`);}
  }
  $('upload-status').textContent=`Added ${added} PDFs${failed?` · ${failed} files could not be added`:''}`;uploading=false;$('choose-files').disabled=false;$('file-input').value='';
}
$('choose-files').onclick=e=>{e.stopPropagation();$('file-input').click();};
$('dropzone').onclick=e=>{if(e.target!==$('file-input'))$('file-input').click();};
$('dropzone').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();$('file-input').click();}};
$('file-input').onchange=e=>addFiles(e.target.files);
let dragDepth=0;document.addEventListener('dragover',e=>e.preventDefault());document.addEventListener('drop',e=>e.preventDefault());
$('dropzone').ondragenter=e=>{e.preventDefault();dragDepth++;$('dropzone').classList.add('drag');};
$('dropzone').ondragleave=()=>{if(--dragDepth<=0){dragDepth=0;$('dropzone').classList.remove('drag');}};
$('dropzone').ondrop=e=>{e.preventDefault();dragDepth=0;$('dropzone').classList.remove('drag');addFiles(e.dataTransfer.files);};
async function poll(){await refresh();setTimeout(poll,1500);}poll();
