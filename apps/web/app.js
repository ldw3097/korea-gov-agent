const $ = id => document.getElementById(id);
const state = { me:null, config:null, threads:[], projects:[], files:[], project:null, thread:null, snapshot:null, attachments:[], artifact:null, view:'chat', projectEdit:null, picker:'attach', busy:false, generation:0, messagesKey:'', artifactIDs:new Set(), submission:null };
const ACTIVE = ['queued','running','waiting_input'];
const labels = {queued:'작업 대기 중', running:'업무를 처리하고 있습니다', waiting_input:'답변을 기다리고 있습니다', completed:'작업 완료', failed:'작업이 중단됐습니다', cancelled:'작업을 중지했습니다'};
const statusLabels = {pending:'승인 대기',approved:'승인됨',rejected:'거절됨',suspended:'정지됨'};
function el(tag, value='', cls='') { const n=document.createElement(tag); n.textContent=value; if(cls)n.className=cls; return n; }
function notice(message='') { $('status').textContent=state.view==='chat'?message:''; $('toast').textContent=state.view!=='chat'?message:''; }
function reset() {
  state.me=null; state.thread=null; state.project=null; state.snapshot=null; state.attachments=[]; state.artifact=null; state.submission=null; state.generation++;
  $('workspace').hidden=true; $('auth-screen').hidden=false; $('auth-title').textContent='업무에 집중하는 공간';
  $('auth-description').textContent='Google로 로그인한 뒤 관리자의 사용 승인을 받으면 시작할 수 있습니다.';
  $('refresh-approval').hidden=true; $('auth-logout').hidden=true; $('artifact-panel').hidden=true; $('prompt').value=''; $('password').value='';
  for(const id of ['messages','stream-message','artifact-content','project-list','thread-list','file-list','user-list','audit-list']) $(id).replaceChildren();
}
async function api(path, options={}) {
  const response=await fetch('/api'+path,{credentials:'same-origin',...options});
  if(!response.ok) {
    const data=await response.json().catch(()=>({}));
    if(response.status===401) reset();
    if(response.status===403 && data.detail==='관리자 사용 승인이 필요합니다.') await enter();
    throw new Error(typeof data.detail==='string'?data.detail:`요청을 완료하지 못했습니다 (${response.status})`);
  }
  return response.status===204?null:response.json();
}
const json=(method,body)=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
function action(fn) {return async event=>{
  event?.preventDefault(); if(state.busy)return; state.busy=true; notice();
  try { await fn(event); } catch(error) {notice(error.message); $('auth-error').textContent=error.message; if($('file-dialog').open)$('file-dialog-error').textContent=error.message;}
  finally {state.busy=false; updateComposer();}
};}
function button(label,fn,cls='') {const n=el('button',label,cls);n.type='button';n.onclick=action(fn);return n;}
function inline(parent,value) {
  const re=/\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
  let start=0,match;
  while((match=re.exec(value))) {
    parent.append(document.createTextNode(value.slice(start,match.index)));
    const n=el(match[1]?'strong':match[2]?'code':'a',match[1]||match[2]||match[3]);
    if(match[4]) {try {const url=new URL(match[4]); if(['http:','https:'].includes(url.protocol)){n.href=url.href;n.target='_blank';n.rel='noopener noreferrer';n.referrerPolicy='no-referrer';}}catch{}}
    parent.append(n);start=re.lastIndex;
  }
  parent.append(document.createTextNode(value.slice(start)));
}
function markdown(value) {
  const root=el('div','','markdown'), lines=value.split('\n'); let i=0;
  const cells=s=>s.trim().replace(/^\||\|$/g,'').split('|').map(v=>v.trim());
  while(i<lines.length) {
    const line=lines[i];
    if(!line.trim()){i++;continue;}
    if(line.startsWith('```')){const content=[];i++;while(i<lines.length&&!lines[i].startsWith('```'))content.push(lines[i++]);i++;const pre=el('pre');pre.append(el('code',content.join('\n')));root.append(pre);continue;}
    const heading=/^(#{1,3})\s+(.+)$/.exec(line);
    if(heading){const n=el('h'+heading[1].length);inline(n,heading[2]);root.append(n);i++;continue;}
    if(line.includes('|')&&i+1<lines.length&&/^\s*\|?\s*:?-+/.test(lines[i+1])){
      const wrap=el('div','','table-wrap'),table=el('table'),head=el('thead'),tr=el('tr');
      for(const c of cells(line)){const th=el('th');inline(th,c);tr.append(th);}head.append(tr);table.append(head);i+=2;const body=el('tbody');
      while(i<lines.length&&lines[i].includes('|')&&lines[i].trim()){const row=el('tr');for(const c of cells(lines[i++])){const td=el('td');inline(td,c);row.append(td);}body.append(row);}
      table.append(body);wrap.append(table);root.append(wrap);continue;
    }
    const list=/^\s*(?:[-*]|\d+\.)\s+/.exec(line);
    if(list){const ordered=/^\s*\d/.test(line),n=el(ordered?'ol':'ul');while(i<lines.length&&/^\s*(?:[-*]|\d+\.)\s+/.test(lines[i])){const li=el('li');inline(li,lines[i++].replace(/^\s*(?:[-*]|\d+\.)\s+/,''));n.append(li);}root.append(n);continue;}
    if(/^>\s?/.test(line)){const n=el('blockquote');inline(n,line.replace(/^>\s?/,''));root.append(n);i++;continue;}
    const p=el('p');inline(p,line);root.append(p);i++;
  }
  return root;
}
function setView(view) {
  state.view=view; $('chat-view').hidden=view!=='chat';$('files-view').hidden=view!=='files';$('admin-view').hidden=view!=='admin';
  $('artifact-panel').hidden=view!=='chat'||!state.artifact;
  $('workspace').classList.remove('nav-open');
  updateHeader();
}
function activeRun() {return state.snapshot?.runs.find(r=>ACTIVE.includes(r.status))||null;}
function updateHeader() {
  $('breadcrumb').textContent=state.view==='files'?'내 파일':state.view==='admin'?'사용 승인 관리':state.project?.name||'내 작업 공간';
  $('project-settings').hidden=state.view!=='chat'||!state.project;
  $('project-files').hidden=state.view!=='chat'||!state.project;
  $('thread-options').hidden=state.view!=='chat'||!state.thread;
  const count=state.snapshot?.artifacts.length||0;
  $('show-artifacts').hidden=state.view!=='chat'||!count;$('artifact-count').textContent=count;
  $('mode-badge').textContent=$('mode').value==='work'?'Work':'대화';
  $('welcome-title').textContent=state.project?state.project.name:'어떤 일을 함께 할까요?';
  $('welcome-description').textContent=state.project?'이 프로젝트의 자료와 맥락을 이어서 작업하세요.':'자료를 첨부하거나, 완성하고 싶은 업무를 알려주세요.';
  $('project-context').hidden=!state.project;
  $('project-context').textContent=state.project?`▱ ${state.project.name} · 프로젝트 자료 ${state.project.files?.length||0}개와 작업 지침을 함께 사용합니다`:'';
}
function updateComposer() {
  const run=activeRun(), ready=state.config?.agent_available;
  $('send').disabled=state.busy||!ready;
  $('stop').hidden=!run; $('stop').disabled=state.busy;
  $('mode').disabled=!!run;
  $('attach').disabled=!!run||state.busy;
  $('input-hint').textContent=run?'추가 요청으로 방향을 바꿀 수 있어요':'문서 작성 · 자료 분석';
  $('prompt').placeholder=run?.status==='waiting_input'?'질문에 답하면 작업을 이어갑니다.':run?'추가로 반영할 내용을 알려주세요.':'업무를 맡겨보세요. 파일을 첨부할 수도 있어요.';
}
function renderNav() {
  const query=$('search').value.trim().toLowerCase();
  $('project-list').replaceChildren(...state.projects.map(p=>button(p.name,()=>chooseProject(p.id),p.id===state.project?.id?'selected':'')));
  if(!state.projects.length)$('project-list').append(el('div','관련 업무를 묶어보세요','empty-nav'));
  const items=state.threads.filter(t=>(!state.project||t.project_id===state.project.id)&&t.title.toLowerCase().includes(query));
  $('thread-list').replaceChildren(...items.map(t=>button(t.title,()=>openThread(t.id),t.id===state.thread?'selected':'')));
  if(!items.length)$('thread-list').append(el('div',query?'검색 결과가 없습니다.':'새로운 일을 시작해 보세요.','empty-nav'));
  $('recent-label').textContent=state.project?'프로젝트 대화':'최근 대화';
}
async function loadNavigation() {const [threads,projects]=await Promise.all([api('/threads'),api('/projects')]);state.threads=threads;state.projects=projects;renderNav();}
function navigateURL() {const url=new URL(location.href);url.search='';if(state.thread)url.searchParams.set('thread',state.thread);else if(state.project)url.searchParams.set('project',state.project.id);history.replaceState(null,'',url);}
function clearChat() {
  state.thread=null;state.snapshot=null;state.artifact=null;state.messagesKey='';state.artifactIDs=new Set();state.attachments=[];state.submission=null;state.generation++;
  $('messages').replaceChildren();$('stream-message').replaceChildren();$('thread-artifacts').replaceChildren();$('run-card').hidden=true;$('stream-message').hidden=true;$('artifact-panel').hidden=true;
  $('welcome').hidden=false;$('conversation').hidden=true;renderAttachments();updateHeader();updateComposer();
}
async function newChat() {state.project=null;clearChat();setView('chat');renderNav();navigateURL();$('prompt').focus();}
async function chooseProject(id) {state.project=await api('/projects/'+id);clearChat();setView('chat');renderNav();navigateURL();}
async function openThread(id) {
  const generation=++state.generation;
  const data=await api(`/threads/${id}/workspace`);if(generation!==state.generation)return;
  state.thread=id;state.artifact=null;state.messagesKey='';state.artifactIDs=new Set(data.artifacts.map(a=>a.id));state.attachments=[];state.submission=null;
  state.project=data.project_id?await api('/projects/'+data.project_id):null;
  if(generation!==state.generation)return;
  setView('chat');applySnapshot(data);renderNav();renderAttachments();navigateURL();
  if(data.artifacts.length)await openArtifact(data.artifacts[0].id);
  $('chat-scroll').scrollTop=$('chat-scroll').scrollHeight;
}
function errorText(error) {return ({MODEL_AUTH:'모델 연결 인증을 확인해야 합니다.',MODEL_RATE_LIMIT:'요청이 몰렸습니다. 잠시 후 다시 시도해 주세요.',MODEL_UNAVAILABLE:'모델 연결이 일시적으로 불안정합니다.',MODEL_OUTPUT_LIMIT:'결과가 너무 길어 중단됐습니다. 범위를 나눠 요청해 주세요.',CONTEXT_LIMIT:'대화와 자료가 너무 깁니다. 새 대화에서 자료를 나눠 요청해 주세요.',SERVER_RESTARTED:'서버 재시작으로 중단됐습니다. 다시 요청해 주세요.',ACCESS_REVOKED:'사용 권한이 변경돼 작업이 중단됐습니다.',TIMEOUT:'처리 시간이 초과됐습니다. 범위를 나눠 다시 요청해 주세요.',STEP_LIMIT:'한 번의 작업 범위를 넘었습니다. 이어서 요청해 주세요.'})[error]||'작업을 완료하지 못했습니다. 다시 요청해 주세요.';}
function renderRun(run) {
  const card=$('run-card'),expanded=card.querySelector('details')?.open;card.replaceChildren();card.hidden=!run;
  if(!run)return;
  const title=el('div','','run-title');if(['queued','running'].includes(run.status))title.append(el('span','','spinner'));title.append(el('span',labels[run.status]||run.status));card.append(title);
  const details=el('details'),summary=el('summary',`${run.events.length}개의 작업 기록`),list=el('ol');
  details.open=!!expanded;
  run.events.forEach(e=>list.append(el('li',e.label)));details.append(summary,list);card.append(details);
  if(run.error)card.append(el('p',errorText(run.error),'run-error'));
  if(run.status==='failed'||run.status==='cancelled') {
    const area=el('div','','run-actions');area.append(button('이어서 다시 요청',()=>{$('prompt').value='앞선 요청을 이어서 완료해 줘.';$('prompt').focus();}));card.append(area);
  }
}
function applySnapshot(data) {
  if(state.thread!==data.id)return;
  const scroll=$('chat-scroll'),stick=scroll.scrollHeight-scroll.scrollTop-scroll.clientHeight<24;
  state.snapshot=data; $('welcome').hidden=true;$('conversation').hidden=false;
  const key=JSON.stringify(data.messages);
  if(key!==state.messagesKey) {
    state.messagesKey=key;
    $('messages').replaceChildren(...data.messages.map(m=>{
      if(m.role==='user')return el('div',m.content,'user-message');
      const n=el('div','','assistant-message'),label=el('div','','assistant-label');label.append(el('span','✳'),el('strong','K-gov-agent'));n.append(label,markdown(m.content));return n;
    }));
  }
  const run=activeRun()||data.runs[0];renderRun(run);
  const partial=activeRun()?.partial||'';$('stream-message').hidden=!partial;
  if(partial)$('stream-message').replaceChildren(markdown(partial));
  const latest=new Map();for(const artifact of data.artifacts)if(!latest.has(artifact.filename))latest.set(artifact.filename,artifact);
  $('thread-artifacts').replaceChildren(...[...latest.values()].map(a=>{const b=button('',()=>openArtifact(a.id),'artifact-card'),info=el('div');info.append(el('strong',a.title),el('small',`${a.filename} · 버전 ${a.version}`));b.append(el('span','▧'),info);return b;}));
  const added=data.artifacts.find(a=>!state.artifactIDs.has(a.id));data.artifacts.forEach(a=>state.artifactIDs.add(a.id));
  if(added)openArtifact(added.id).catch(e=>notice(e.message));
  updateHeader();updateComposer();
  if(stick)scroll.scrollTop=scroll.scrollHeight;
}
async function refreshSelected() {
  if(!state.me||!state.thread||state.view!=='chat')return;
  const tid=state.thread,generation=state.generation;
  const data=await api(`/threads/${tid}/workspace`);
  if(tid===state.thread&&generation===state.generation)applySnapshot(data);
}
async function openArtifact(id) {
  const generation=state.generation,document=await api('/artifacts/'+id);
  if(generation!==state.generation||document.thread_id!==state.thread)return;
  state.artifact=document;$('artifact-panel').hidden=false;$('artifact-title').textContent=document.title;
  $('artifact-content').replaceChildren(markdown(document.content));
  const versions=(state.snapshot?.artifacts||[]).filter(a=>a.filename===document.filename).sort((a,b)=>b.version-a.version);
  $('artifact-version').replaceChildren(...versions.map(a=>{const option=el('option','버전 '+a.version);option.value=a.id;return option;}));
  $('artifact-version').value=id;$('artifact-download').href=`/api/artifacts/${id}/download`;
}
function renderAttachments() {
  $('attachments').replaceChildren(...state.attachments.map(file=>{const chip=el('div','','attachment-chip');chip.append(el('span','▤ '+file.name),button('×',()=>{state.attachments=state.attachments.filter(f=>f.id!==file.id);renderAttachments();}));return chip;}));
}
async function send() {
  const content=$('prompt').value.trim();if(!content)return;
  if(!state.config?.agent_available)throw new Error('AI 모델 연결을 준비하고 있습니다.');
  if(!state.thread) {
    const thread=await api('/threads',json('POST',{title:content.replace(/\s+/g,' ').slice(0,65),project_id:state.project?.id||null}));
    state.thread=thread.id;state.generation++;state.snapshot=null;state.messagesKey='';state.artifactIDs=new Set();navigateURL();
  }
  const run=activeRun(),fingerprint=JSON.stringify([state.thread,run?.id,content,state.attachments.map(f=>f.id),$('mode').value]);
  if(!state.submission||state.submission.fingerprint!==fingerprint)state.submission={fingerprint,id:crypto.randomUUID()};
  if(run)await api(`/runs/${run.id}/input`,json('POST',{request_id:state.submission.id,content}));
  else await api(`/threads/${state.thread}/runs`,json('POST',{request_id:state.submission.id,content,mode:$('mode').value,file_ids:state.attachments.map(f=>f.id)}));
  state.submission=null;$('prompt').value='';state.attachments=[];renderAttachments();await loadNavigation();await refreshSelected();
  $('chat-scroll').scrollTop=$('chat-scroll').scrollHeight;
}
async function filesList() {state.files=await api('/files');return state.files;}
async function showFiles() {
  setView('files');await filesList();
  $('file-list').replaceChildren(...state.files.map(file=>{
    const row=el('div','','file-row'),info=el('div');info.append(el('strong','▤ '+file.name),el('small',`${(file.size/1024).toFixed(1)} KB · 본인만 접근`));
    const download=el('a','다운로드','subtle');download.href=`/api/files/${file.id}/download`;
    row.append(info,button('대화에 첨부',()=>{if(activeRun())throw new Error('새 대화에서 첨부하거나 진행 중인 작업을 먼저 마쳐 주세요.');if(!state.attachments.some(f=>f.id===file.id))state.attachments.push(file);renderAttachments();setView('chat');}),download,button('삭제',async()=>{if(!confirm('이 파일을 삭제할까요?'))return;await api('/files/'+file.id,{method:'DELETE'});state.attachments=state.attachments.filter(f=>f.id!==file.id);await showFiles();}));return row;
  }));
  if(!state.files.length)$('file-list').append(el('p','아직 등록한 자료가 없습니다. 첫 자료를 추가해 보세요.','empty-nav'));
}
async function filePicker(mode='attach') {
  state.picker=mode;await filesList();if(mode==='project')state.project=await api('/projects/'+state.project.id);
  $('file-dialog-title').textContent=mode==='project'?'프로젝트 참고 자료':'참고 자료 연결';
  $('file-dialog-description').textContent=mode==='project'?'선택한 자료는 이 프로젝트의 새 작업에 자동으로 포함됩니다.':'이 요청에 사용할 파일을 선택하세요. 프로젝트 자료와 합쳐 최대 5개입니다.';
  $('file-dialog-error').textContent='';renderPicker();$('file-dialog').showModal();
}
function renderPicker() {
  const selected=new Set((state.picker==='project'?state.project.files:state.attachments).map(f=>f.id));
  $('file-picker').replaceChildren(...state.files.map(file=>{
    const label=el('label'),input=document.createElement('input');input.type='checkbox';input.checked=selected.has(file.id);label.append(input,el('span',file.name));
    input.onchange=async()=>{input.disabled=true;try {
      if(state.picker==='project') {
        await api(`/projects/${state.project.id}/files/${file.id}`,{method:input.checked?'PUT':'DELETE'});
        state.project=await api('/projects/'+state.project.id);updateHeader();
      } else {
        if(input.checked&&!state.attachments.some(f=>f.id===file.id)) {if(state.attachments.length>=5)throw new Error('최대 5개까지 첨부할 수 있습니다.');state.attachments.push(file);}
        if(!input.checked)state.attachments=state.attachments.filter(f=>f.id!==file.id);
        renderAttachments();
      }
    }catch(e){input.checked=!input.checked;$('file-dialog-error').textContent=e.message;}finally{input.disabled=false;}};
    return label;
  }));
  if(!state.files.length)$('file-picker').append(el('p','등록한 파일이 없습니다. 새 파일을 등록해 주세요.'));
}
function pickUpload(mode) {state.picker=mode;$('file-input').value='';$('file-input').click();}
async function uploadFiles() {
  for(const file of $('file-input').files) {
    if(file.size>2*1024*1024)throw new Error('파일당 최대 2 MiB까지 등록할 수 있습니다.');
    if(!/\.(txt|md|csv|tsv|json)$/i.test(file.name))throw new Error('현재는 TXT·MD·CSV·TSV·JSON 파일을 분석할 수 있습니다.');
    const row=await api('/files?'+new URLSearchParams({name:file.name}),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});
    if(state.picker==='project')await api(`/projects/${state.project.id}/files/${row.id}`,{method:'PUT'});
    else if(state.picker==='attach'&&state.attachments.length<5)state.attachments.push(row);
  }
  if(state.project)state.project=await api('/projects/'+state.project.id);
  await filesList();renderAttachments();updateHeader();
  if($('file-dialog').open)renderPicker();
  if(state.view==='files')await showFiles();
}
function projectDialog(edit=false) {
  state.projectEdit=edit?state.project.id:null;
  $('project-dialog-title').textContent=edit?'프로젝트 설정':'새 프로젝트';
  $('project-name').value=edit?state.project.name:'';$('project-instructions').value=edit?state.project.instructions:'';
  $('project-dialog').showModal();
}
async function admin() {
  setView('admin');const [users,events]=await Promise.all([api('/admin/users'),api('/admin/audit')]);
  $('user-list').replaceChildren(...users.map(user=>{
    const row=el('div','','user-row'),info=el('div');info.append(el('strong',user.display_name),el('small',user.username));row.append(info,el('span',statusLabels[user.approval_status]||user.approval_status,'status-chip'));
    if(user.id!==state.me.id) {
      if(['cloudflare','google'].includes(state.config.auth_mode)) {
        const change=async status=>{await api(`/admin/users/${user.id}/approval`,json('PATCH',{status}));await admin();};
        if(user.approval_status!=='approved')row.append(button('승인',()=>change('approved'),'solid'));
        if(user.approval_status!=='rejected')row.append(button(user.approval_status==='approved'?'승인 취소':'거절',()=>change('rejected')));
      }else row.append(button(user.active?'비활성화':'활성화',async()=>{await api('/admin/users/'+user.id,json('PATCH',{active:!user.active}));await admin();}));
    }return row;
  }));
  $('audit-list').replaceChildren(...events.slice(0,50).map(e=>el('div',`${new Date(e.created_at*1000).toLocaleString('ko-KR')} · ${e.action}`)));
}
async function enter() {
  state.me=await api('/me');const user=state.me;
  $('identity').textContent=user.display_name;$('avatar').textContent=user.display_name.slice(0,1);$('auth-error').textContent='';
  if(user.approval_status!=='approved') {
    $('workspace').hidden=true;$('auth-screen').hidden=false;$('google-login').hidden=true;$('login-form').hidden=true;
    $('auth-title').textContent=user.approval_status==='pending'?'사용 승인 대기':'사용이 제한된 계정입니다';
    $('auth-description').textContent=user.approval_status==='pending'?'Google 로그인은 완료됐습니다. 관리자가 승인하면 사용할 수 있습니다.':'관리자에게 계정 상태를 문의해 주세요.';
    $('refresh-approval').hidden=false;$('auth-logout').hidden=false;return;
  }
  $('auth-screen').hidden=true;$('workspace').hidden=false;$('admin-nav').hidden=user.role!=='admin';
  $('model-status').textContent=state.config.agent_available?'✳ AI 연결됨 · Work PoC':'AI 연결을 준비하고 있습니다';
  await loadNavigation();const url=new URL(location.href),tid=url.searchParams.get('thread'),pid=url.searchParams.get('project');
  if(tid)await openThread(tid);else if(pid)await chooseProject(pid);else await newChat();updateComposer();
}
async function logout() {reset();if(state.config.logout_url){location.assign(state.config.logout_url);return;}await api('/auth/logout',{method:'POST'});}
$('login-form').onsubmit=action(async()=>{const password=$('password').value;$('password').value='';await api('/auth/login',json('POST',{username:$('username').value,password}));await enter();});
$('refresh-approval').onclick=action(enter);$('logout').onclick=action(logout);$('auth-logout').onclick=action(logout);
$('new-chat').onclick=action(newChat);$('new-project').onclick=()=>projectDialog();$('project-settings').onclick=()=>projectDialog(true);
$('project-form').onsubmit=action(async()=>{
  const data={name:$('project-name').value,instructions:$('project-instructions').value};
  const project=await api(state.projectEdit?'/projects/'+state.projectEdit:'/projects',json(state.projectEdit?'PATCH':'POST',data));
  $('project-dialog').close();await loadNavigation();await chooseProject(project.id);
});
$('project-files').onclick=action(()=>filePicker('project'));$('attach').onclick=action(()=>filePicker());
$('upload-library').onclick=()=>pickUpload('library');$('upload-picker').onclick=()=>pickUpload(state.picker);$('file-input').onchange=action(uploadFiles);
$('files-nav').onclick=action(showFiles);$('admin-nav').onclick=action(admin);$('search').oninput=renderNav;
$('composer').onsubmit=action(send);$('prompt').onkeydown=event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();if(!state.busy&&state.config?.agent_available)$('composer').requestSubmit();}};
$('mode').onchange=()=>{updateHeader();updateComposer();};
$('stop').onclick=action(async()=>{const run=activeRun();if(run){await api(`/runs/${run.id}/cancel`,{method:'POST'});await refreshSelected();}});
$('close-artifact').onclick=()=>{state.artifact=null;$('artifact-panel').hidden=true;};
$('show-artifacts').onclick=action(()=>{const a=state.snapshot?.artifacts[0];if(a)return openArtifact(a.id);});
$('artifact-version').onchange=action(()=>openArtifact($('artifact-version').value));
$('revise-artifact').onclick=()=>{$('prompt').value=`수정할 문서: ${state.artifact.filename}\n수정 요청: `;$('prompt').focus();};
$('thread-options').onclick=action(async()=>{if(!confirm('이 대화와 생성한 결과물을 삭제할까요?'))return;await api('/threads/'+state.thread,{method:'DELETE'});clearChat();navigateURL();await loadNavigation();});
$('menu').onclick=()=>$('workspace').classList.toggle('nav-open');
$('chat-view').onclick=event=>{if(event.target===$('chat-scroll'))$('workspace').classList.remove('nav-open');};
for(const b of document.querySelectorAll('[data-prompt]'))b.onclick=()=>{$('prompt').value=b.dataset.prompt;$('prompt').focus();};
for(const b of document.querySelectorAll('[data-close]'))b.onclick=()=>$(b.dataset.close).close();
let polling=false;
setInterval(async()=>{if(polling||state.busy||!state.me||!state.thread)return;polling=true;try{await refreshSelected();}catch(e){notice(e.message);}finally{polling=false;}},1000);
async function boot() {
  state.config=await api('/config');$('google-login').hidden=state.config.auth_mode!=='google';$('login-form').hidden=state.config.auth_mode!=='local';
  if(state.config.auth_mode==='cloudflare')$('auth-description').textContent='Google 로그인 상태를 확인하고 있습니다.';
  try{await enter();}catch(error){if(state.config.auth_mode==='cloudflare')$('auth-error').textContent=error.message+' 새로고침해 로그인 상태를 확인해 주세요.';}
}
boot().catch(error=>$('auth-error').textContent=error.message);
document.addEventListener('keydown',event=>{const tag=document.activeElement?.tagName;if(event.key==='n'&&!event.ctrlKey&&!event.metaKey&&!event.altKey&&!['INPUT','TEXTAREA','SELECT'].includes(tag)&&!document.querySelector('dialog[open]')&&state.me&&state.me.approval_status==='approved'){event.preventDefault();action(newChat)();}});
$('workspace').addEventListener('click',event=>{if(window.innerWidth<=640&&!$('sidebar').contains(event.target)&&!$('menu').contains(event.target))$('workspace').classList.remove('nav-open');});
