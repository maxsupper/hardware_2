/* 硬件审查台 — 前端主逻辑（原生 JS，无构建；轮询 run.log/run.state + 门禁/人工） */
(() => {
  const PH = ["PH-0","PH-1","PH-2","PH-3","PH-4","PH-5","PH-6"];
  const PH_NAME = {"PH-0":"输入准备","PH-1":"手册检索","PH-2":"网表解析",
                   "PH-3":"深度分析","PH-4":"报告合成","PH-5":"审计复核","PH-6":"闭环交付"};
  let product = (localStorage.getItem('hw.product')||'');
  let cursor = 0, follow = true;
  const agentState = {};   // agent -> {started, done, err, tasks}

  const $ = id => document.getElementById(id);
  const logEl = $('log');

  function logLine(ev){
    const t=(new Date(ev.ts||'').toTimeString().slice(0,8));
    const ty=ev.type||'';
    const cls = ty==='error'?'t-err'
      : ty.startsWith('gate_fail')?'t-gate_fail'
      : ty.startsWith('gate_pass')?'t-gate_pass'
      : (ty==='human_block'||ty==='batch_pause')?'t-human'
      : ty.includes('warn')?'t-warn' : ty.includes('ok')?'t-ok':'t-info';
    const el=document.createElement('div'); el.className=cls;
    const brief=ev.err||ev.brief||ev.note||ev.out||ev.msg||'';
    el.textContent=`${t} [${ev.phase||'-'}] ${ty}${brief?' · '+String(brief).slice(0,140):''}`;
    logEl.appendChild(el);
    if(follow) logEl.scrollTop=logEl.scrollHeight;
    // 简单 agent 聚合
    if(ty==='icon_ok'||ty==='icon_err'){ const a=ty==='icon_ok'?'hw_analyze':'hw_search';
      agentState[a]=agentState[a]||{started:0,done:0,err:0};
      ty==='icon_ok'?agentState[a].done++:agentState[a].err++; }
    if(ty==='task_completed'){ const a=ev.agent||'agent'; agentState[a]=agentState[a]||{done:0}; agentState[a].done++; }
  }

  async function poll(){
    if(product){ try{ await refresh(); }catch(e){ $('conn').textContent='ERR'; } }
    setTimeout(poll,1500);
  }

  async function refresh(){
    const [st,gates,logs] = await Promise.all([
      fetch(`/api/state/${product}`).then(r=>r.json()),
      fetch(`/api/gates/${product}`).then(r=>r.json()),
      fetch(`/api/logs/${product}?after=${cursor}`).then(r=>r.json())]);
    logs.events.forEach(logLine); cursor=logs.next;
    renderRail(st); renderGates(gates); renderAgents(st);
    $('conn').textContent = st.current||'IDLE';
    $('todo').classList.toggle('hidden', !st.paused);
    if(st.paused) maybeModal(st);
  }

  function renderRail(st){
    PH.forEach((ph,i)=>{
      let node=$('ph-'+ph);
      const stt=(st.phases||{})[ph]||'PENDING';
      if(!node){ node=document.createElement('div'); node.id='ph-'+ph;
        node.innerHTML=`<span class="st"></span><span class="nm"></span>`;
        $('rail').appendChild(node); }
      node.className='phase '+(stt==='DONE'?'done':(st.current===ph?'current':''))+(stt==='FAIL'?' fail':'');
      node.querySelector('.nm').textContent=ph+' '+PH_NAME[ph];
    });
  }
  function renderGates(gates){
    Object.entries(gates).forEach(([g,v])=>{
      let node=$('gt-'+g);
      if(!node){ node=document.createElement('span'); node.id='gt-'+g; node.className='gate-tag'; $('rail').appendChild(node); }
      node.textContent=`${g}:${v.status||'?'}`;
      node.className='gate-tag '+((v.status||''));
    });
  }
  function renderAgents(st){
    const box=$('agents');
    box.innerHTML='';                       // 清空后重建，避免每次轮询重复追加标题（重复打印 bug）
    const cur=st.current||'';
    const t=document.createElement('div'); t.className='rail-title';
    t.textContent='③ 当前环节 '+cur+' · agent 活动';
    box.appendChild(t);
    for(const [a,v] of Object.entries(agentState)){
      const d=document.createElement('div'); d.className='agent-card '+(v.err?'fail':(v.done?'done':'running'));
      d.innerHTML=`<span class="dot"></span>${a} <span class="dim">d=${v.done||0} e=${v.err||0}</span>`;
      box.appendChild(d);
    }
  }

  function maybeModal(st){
    const box=$('modal'), body=$('m-body'), act=$('m-actions');
    if(box.classList.contains('hidden')===false) return;
    $('m-title').textContent='【待你处理】 '+(st.pause_reason||'批次边界');
    body.textContent='当前环节：'+(st.current||'')+'。请选择';
    act.innerHTML='';
    [['继续审查','continue'],['停止','stop']].forEach(([txt,ans])=>{
      const b=document.createElement('button'); b.className='btn primary'; b.textContent=txt;
      b.onclick=()=>{ POST('/api/human/confirm',{product,kind:'batch',answer:ans}); box.classList.add('hidden'); };
      act.appendChild(b); });
    box.classList.remove('hidden');
  }

  function POST(url,data){ return fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}); }

  $('product').value=product;
  $('product').addEventListener('change',()=>{ product=$('product').value.trim(); localStorage.setItem('hw.product',product); $('btn-start').disabled=!product; });
  $('files').addEventListener('change',()=>{ const ul=$('filelist'); ul.innerHTML='';
    [...$('files').files].forEach(f=>{const li=document.createElement('li'); li.textContent=f.name+' ('+f.size+'B)'; ul.appendChild(li);}); });
  $('btn-upload').onclick=async ()=>{
    const name=($('product').value||'').trim(); if(!name){alert('先填产品名');return;}
    const fd=new FormData(); fd.append('product',name); [...$('files').files].forEach(f=>fd.append('files',f));
    const r=await fetch('/api/upload',{method:'POST',body:fd}).then(x=>x.json());
    alert('已上传: '+r.saved.join(', ')); product=name; $('btn-start').disabled=false;
  };
  $('btn-start').onclick=()=>{
    const fd=new FormData(); fd.append('product',product); fd.append('auto_pass',$('autopass').checked?'true':'false');
    fetch('/api/start',{method:'POST',body:fd}).then(r=>r.json()).then(r=>{ $('conn').textContent='RUN '+r.run_id; cursor=0; });
  };
  $('btn-follow').onclick=()=>{ follow=!follow; $('btn-follow').textContent=follow?'跟随':'暂停'; };
  $('btn-clear').onclick=()=>{ logEl.innerHTML=''; };
  $('btn-dl').onclick=()=>{ const b=new Blob([logEl.textContent],{type:'text/plain'});
    const a=document.createElement('a'); a.href=URL.createObjectURL(b); a.download='run.log.txt'; a.click(); };

  poll();
})();
