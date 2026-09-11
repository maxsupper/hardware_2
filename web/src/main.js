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

  let lastModalReason='';
  async function maybeModal(st){
    const box=$('modal'), body=$('m-body'), act=$('m-actions');
    if(!st.paused){ if(lastModalReason){ lastModalReason=''; box.classList.add('hidden'); } return; }
    const reason=st.pause_reason||'';
    if(!box.classList.contains('hidden') && reason===lastModalReason) return;  // 同一原因不重绘
    lastModalReason=reason;
    box.classList.add('hidden');        // 先隐藏，允许按新原因重绘
    act.innerHTML=''; body.innerHTML='';
    // 手册缺失确认（PH-1）：按“芯片型号”分组，同一型号只需提交一次（如 U4/U13/U33 均为 ETA3417S2F）
    if((st.pause_reason||'').includes('手册缺失')){
      $('m-title').textContent='【待你处理】手册缺失确认';
      const g=await fetch('/api/manual_gaps/'+encodeURIComponent(product)).then(r=>r.json()).catch(()=>({gaps:[]}));
      const byModel={};                              // 型号 -> [位号...]
      (g.gaps||[]).forEach(it=>{ (byModel[it.model]=byModel[it.model]||[]).push(it.refdes); });
      const models=Object.keys(byModel);
      const hint=document.createElement('div'); hint.className='dim';
      hint.textContent=`共 ${models.length} 个型号（${(g.gaps||[]).length} 个位号），按型号选择：上传(补充文件) / 缺省(→UNVERIFIED) / 替换(按兼容型号) / 说明(补充描述→发LLM判定)`;
      body.appendChild(hint);
      const rows=[];
      models.forEach(model=>{
        const refs=byModel[model];
        const row=document.createElement('div'); row.className='agent-card';
        const nm=document.createElement('span'); nm.innerHTML=`<b>${model}</b> <span class="dim">(${refs.join(', ')})</span> `;
        const sel=document.createElement('select');
        [['IGNORE','缺省'],['PROVIDE_FILE','上传'],['COMPATIBLE','替换'],['NOTE','说明']].forEach(([v,t])=>{
          const o=document.createElement('option'); o.value=v; o.textContent=t; sel.appendChild(o); });
        const finp=document.createElement('input'); finp.type='file'; finp.style.display='none';
        const tinp=document.createElement('input'); tinp.placeholder='兼容型号'; tinp.style.display='none';
        const ninp=document.createElement('input'); ninp.placeholder='补充说明（提交时发 LLM 判定）'; ninp.style.display='none'; ninp.size=30;
        sel.onchange=()=>{ finp.style.display=sel.value==='PROVIDE_FILE'?'inline-block':'none';
                           tinp.style.display=sel.value==='COMPATIBLE'?'inline-block':'none';
                           ninp.style.display=sel.value==='NOTE'?'inline-block':'none'; };
        row.appendChild(nm); row.appendChild(sel); row.appendChild(finp); row.appendChild(tinp); row.appendChild(ninp); body.appendChild(row);
        rows.push({refs, sel, finp, tinp, ninp});
      });
      const expand=(act)=>{ const d={}; rows.forEach(r=>r.refs.forEach(ref=>{ d[ref]=act(r); })); return d; };
      const submit=async()=>{
        const decisions={};
        for(const r of rows){
          if(r.sel.value==='COMPATIBLE'){ const v={action:'COMPATIBLE',compatible_model:r.tinp.value.trim()}; r.refs.forEach(ref=>decisions[ref]=v); }
          else if(r.sel.value==='NOTE'){ const v={action:'NOTE',note:r.ninp.value.trim()}; r.refs.forEach(ref=>decisions[ref]=v); }
          else if(r.sel.value==='PROVIDE_FILE'){
            const f=r.finp.files[0];
            if(!f){ r.refs.forEach(ref=>decisions[ref]={action:'IGNORE'}); continue; }
            const fd=new FormData(); fd.append('file',f);
            const up=await fetch('/api/manual/upload',{method:'POST',body:fd}).then(x=>x.json()).catch(()=>({}));
            const v= up.path? {action:'PROVIDE_FILE',file:up.path} : {action:'IGNORE'};
            r.refs.forEach(ref=>decisions[ref]=v);
          } else { r.refs.forEach(ref=>decisions[ref]={action:'IGNORE'}); }
        }
        POST('/api/human/confirm',{product,kind:'manual',answer:'continue',decisions}); box.classList.add('hidden');
      };
      const b1=document.createElement('button'); b1.className='btn primary'; b1.textContent='提交并继续'; b1.onclick=submit;
      const b2=document.createElement('button'); b2.className='btn'; b2.textContent='全部缺省';
      b2.onclick=()=>{ POST('/api/human/confirm',{product,kind:'manual',answer:'continue',
        decisions:expand(()=>({action:'IGNORE'}))}); box.classList.add('hidden'); };
      act.appendChild(b1); act.appendChild(b2);
      box.classList.remove('hidden');
      return;
    }
    // PH-0 输入准备确认（step_0a）：“确认并开始审查”会真正重启流程
    if((st.pause_reason||'').includes('step_0a')){
      $('m-title').textContent='【待你处理】输入准备确认（PH-0）';
      const d=document.createElement('div'); d.className='dim';
      d.textContent='确认使用默认手册库 storge/refbook 开始审查（手册缺失将在 PH-1 弹窗处理）？';
      body.appendChild(d);
      const b1=document.createElement('button'); b1.className='btn primary'; b1.textContent='确认并开始审查';
      b1.onclick=async()=>{ await POST('/api/human/confirm',{product,kind:'step0a',answer:'continue'});
        const fd=new FormData(); fd.append('product',product); fd.append('auto_pass','false');
        await fetch('/api/start',{method:'POST',body:fd});
        box.classList.add('hidden'); lastModalReason=''; };
      const b2=document.createElement('button'); b2.className='btn'; b2.textContent='稍后';
      b2.onclick=()=>box.classList.add('hidden');
      act.appendChild(b1); act.appendChild(b2);
      box.classList.remove('hidden');
      return;
    }
    // 默认：批次边界确认
    $('m-title').textContent='【待你处理】 '+(st.pause_reason||'批次边界');
    body.textContent='当前环节：'+(st.current||'')+'。请选择';
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
