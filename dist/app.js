"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const escape = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const safeUrl = (value) => { try { const u = new URL(value); return u.protocol === "https:" ? escape(u.href) : "#"; } catch { return "#"; } };
  const url = new URL(location.href);
  const allowedViews = ["all", "saved", "human-ai-education", "human-ai-creativity", "bci-psychology", "human-ai-behavior"];
  const requestedView = url.searchParams.get("topic");
  const state = {
    view: allowedViews.includes(requestedView) ? requestedView : "all",
    days: ["7", "30", "90", "all"].includes(url.searchParams.get("days")) ? url.searchParams.get("days") : "30",
    q: url.searchParams.get("q") || "", type: "all", source: "all", sort: "published", limit: 15,
  };
  const today = new Intl.DateTimeFormat("en-CA", {timeZone:"Asia/Shanghai", year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
  let data, filtered = [], saved = new Set(), toastTimer;
  try { const items = JSON.parse(localStorage.getItem("human-ai-brief-saved-v1") || "[]"); if (Array.isArray(items)) saved = new Set(items.filter(x => typeof x === "string")); } catch { /* Storage is optional. */ }
  function toast(message) { $("toast").textContent = message; $("toast").hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $("toast").hidden = true; }, 3000); }
  function withinDays(p, days) {
    if (days === "all") return true;
    if (!p.published || p.published > today) return false;
    const lower = new Date(today + "T00:00:00Z"); lower.setUTCDate(lower.getUTCDate() - Number(days) + 1);
    return p.published >= lower.toISOString().slice(0, 10);
  }
  const topicMap = {}, venueLabel = {};
  function searchable(p) {
    return [p.title,p.authors,p.journal,p.doi,p.abstract,...(p.keywords || []),...p.topics.map(t => topicMap[t]?.name || t),...(p.venue_groups || []).map(g => venueLabel[g] || g)].join(" ").toLocaleLowerCase();
  }
  function typeMatch(p, type) {
    if (type === "all") return true;
    if (type === "preprint") return p.is_preprint;
    if (type === "review") return p.is_review;
    if (type === "conference") return p.venue_type === "conference" && !p.is_review && !p.is_preprint;
    if (type === "journal") return !p.is_preprint && !p.is_review && p.venue_type !== "conference";
    return true;
  }
  function filterPapers() {
    const terms = state.q.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    return data.papers.filter(p =>
      (state.view === "all" || (state.view === "saved" ? saved.has(p.id) : p.topics.includes(state.view))) &&
      withinDays(p, state.days) &&
      typeMatch(p, state.type) &&
      (state.source === "all" || (p.venue_groups || []).includes(state.source)) &&
      (!terms.length || terms.every(term => searchable(p).includes(term)))
    ).sort((a,b) => {
      const key = state.sort === "added" ? "first_seen" : "published";
      return (b[key] || "").localeCompare(a[key] || "") || a.title.localeCompare(b.title);
    });
  }
  function card(p) {
    const stamp = p.published ? `<span class="day">${escape(p.published.slice(5).replace("-", "."))}</span><span class="year">${escape(p.published.slice(0,4))}</span>` : '<span class="year">日期未提供</span>';
    const topicTags = p.topics.map(t => `<span class="tag ${escape(t)}">${escape(topicMap[t]?.short_name || t)}</span>`).join("");
    const sourceTags = (p.venue_groups || []).map(g => `<span class="tag source">${escape(venueLabel[g] || g)}</span>`).join("");
    const matched = [...new Set(Object.values(p.evidence || {}).flat())];
    const abstract = p.abstract || "来源尚未提供摘要，暂无法生成中文概览，请点击题目阅读原文。";
    const overview = p.summary_zh ? `<div class="summary-zh"><span>AI 中文概览</span><p>${escape(p.summary_zh)}</p></div>` : `<p class="abstract-preview">${escape(abstract)}</p>`;
    const kind = p.is_preprint ? "预印本" : (p.venue_type === "conference" ? "会议论文" : "期刊文章");
    return `<article class="paper"><div class="paper-date" aria-label="发表日期 ${escape(p.published || '未提供')}">${stamp}</div><div class="paper-body"><div class="paper-meta"><span class="journal">${escape(p.journal)}</span><span class="type-badge ${p.is_preprint ? 'preprint' : ''}">${kind}</span>${p.is_review ? '<span class="type-badge">综述</span>' : ''}</div><h3><a href="${safeUrl(p.url)}" target="_blank" rel="noopener">${escape(p.title)}</a></h3><div class="authors" title="${escape(p.authors)}">${escape(p.authors || '来源未提供作者')}</div>${overview}<div class="paper-tags">${topicTags}${sourceTags}</div><details><summary>原始摘要与收录依据</summary><div class="detail-content"><p class="full-abstract">${escape(abstract)}</p><p class="evidence">检索命中：${escape(matched.join(' · ') || '匹配本方向检索式，详见原始数据')}。<br>本站首次收录：${escape(p.first_seen?.slice(0,10) || '—')}；来源收录：${escape(p.indexed || '未提供')}。</p><div class="detail-links"><a href="${safeUrl(p.url)}" target="_blank" rel="noopener">前往原文 ↗</a><a href="${safeUrl(p.source_url)}" target="_blank" rel="noopener">OpenAlex 记录 ↗</a></div><p class="doi-line">${p.doi ? 'DOI: ' + escape(p.doi) : 'OpenAlex 编号: ' + escape(p.source_id)}</p></div></details></div><button class="bookmark" data-id="${escape(p.id)}" aria-pressed="${saved.has(p.id)}" aria-label="${saved.has(p.id) ? '取消收藏' : '收藏'}：${escape(p.title)}" title="${saved.has(p.id) ? '取消本机收藏' : '保存到本机收藏'}">${saved.has(p.id) ? '◆' : '◇'}</button></article>`;
  }
  function syncUrl() {
    const u = new URL(location.href);
    for (const [key, value, defaultValue] of [["topic",state.view,"all"],["days",state.days,"30"],["q",state.q,""]]) {
      if (value === defaultValue) u.searchParams.delete(key); else u.searchParams.set(key,value);
    }
    u.searchParams.delete("summary");
    try { history.replaceState(null,"",u); } catch { /* Some browsers restrict history on local HTML files. */ }
  }
  function render() {
    if (!data) return;
    filtered = filterPapers();
    $("papers").setAttribute("aria-busy", "false");
    $("result-count").textContent = `${filtered.length} 篇`;
    $("list-title").firstChild.textContent = state.view === "saved" ? "本机收藏 " : "最新文献 ";
    const current = topicMap[state.view];
    $("page-title").innerHTML = `${escape(current?.short_name || (state.view === 'saved' ? '我的阅读清单' : '文献观察'))}<span class="title-dot">.</span>`;
    $("page-description").textContent = current?.description || (state.view === "saved" ? "留住值得再读的研究。收藏仅保存在当前浏览器。" : "人智协同与脑机接口的前沿研究，每天自动更新");
    document.querySelectorAll("[data-view]").forEach(b => { const active = b.dataset.view === state.view; b.classList.toggle("active", active); b.setAttribute("aria-pressed", active); });
    document.querySelectorAll("[data-days]").forEach(b => { const active = b.dataset.days === state.days; b.classList.toggle("selected", active); b.setAttribute("aria-pressed", active); });
    $("count-saved").textContent = data.papers.filter(p=>saved.has(p.id)).length;
    $("export-button").disabled = filtered.length === 0;
    if (filtered.length) {
      $("papers").innerHTML = filtered.slice(0,state.limit).map(card).join("");
    } else {
      const emptySaved = state.view === "saved" && !data.papers.some(p=>saved.has(p.id));
      $("papers").innerHTML = `<div class="empty"><strong>${emptySaved ? '给下一次阅读留个位置。' : '暂时没有匹配的文献。'}</strong><p>${emptySaved ? '点击论文右侧的 ◇，把它加入当前浏览器的收藏。' : '可以扩大时间范围，或减少关键词和来源筛选。'}</p><button id="reset-filters">${emptySaved ? '浏览全部文献' : '清除筛选'}</button></div>`;
      $("reset-filters").addEventListener("click", () => { if (emptySaved) state.view = "all"; state.days = "all"; state.q = ""; state.type = "all"; state.source = "all"; state.limit = 15; $("search").value = ""; $("type").value = "all"; $("source").value = "all"; render(); });
    }
    $("load-more").hidden = filtered.length <= state.limit;
    $("load-more").innerHTML = `继续阅读 · 还有 ${Math.max(0,filtered.length-state.limit)} 篇 <span>↓</span>`;
    syncUrl();
  }
  function saveBookmark(button) {
    const id = button.dataset.id;
    if (saved.has(id)) saved.delete(id); else saved.add(id);
    let persisted = true;
    try { localStorage.setItem("human-ai-brief-saved-v1", JSON.stringify([...saved])); } catch { persisted = false; }
    if (state.view === "saved") render();
    else { button.setAttribute("aria-pressed", saved.has(id)); button.textContent = saved.has(id) ? "◆" : "◇"; button.title = saved.has(id) ? "取消本机收藏" : "保存到本机收藏"; const paper = data.papers.find(p=>p.id===id); button.setAttribute("aria-label", `${saved.has(id) ? '取消收藏' : '收藏'}：${paper?.title || ''}`); $("count-saved").textContent = data.papers.filter(p=>saved.has(p.id)).length; }
    toast(persisted ? (saved.has(id) ? "已保存到本机收藏" : "已移出收藏") : "浏览器禁止保存；收藏仅在本次打开时有效");
  }
  function exportRis() {
    const clean = (s) => String(s || "").replace(/[\r\n]+/g," ");
    const records = filtered.map(p => ["TY  - " + (p.is_preprint ? "UNPB" : (p.venue_type === "conference" ? "CPAPER" : "JOUR")),"TI  - " + clean(p.title),...p.authors.split(/,\s*/).filter(Boolean).map(a=>"AU  - " + clean(a)),"JO  - " + clean(p.journal),...(p.published ? ["PY  - " + p.published.slice(0,4),"DA  - " + p.published.replaceAll("-","/")] : []),...(p.doi ? ["DO  - " + clean(p.doi)] : []),"UR  - " + clean(p.url),...(p.abstract ? ["AB  - " + clean(p.abstract)] : []),...p.topics.map(t=>"KW  - " + topicMap[t].name),"ER  - ",""].join("\r\n")).join("\r\n");
    const blob = new Blob([records],{type:"application/x-research-info-systems;charset=utf-8"});
    const objectUrl = URL.createObjectURL(blob); const a = document.createElement("a"); a.href=objectUrl; a.download=`human-ai-brief-${today}-${filtered.length}.ris`; document.body.append(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(objectUrl),30000); toast(`已导出 ${filtered.length} 篇，可导入 Zotero`);
  }
  document.querySelectorAll("[data-view]").forEach(b=>b.addEventListener("click",()=>{state.view=b.dataset.view;state.limit=15;render();}));
  document.querySelectorAll("[data-days]").forEach(b=>b.addEventListener("click",()=>{state.days=b.dataset.days;state.limit=15;render();}));
  $("search").value=state.q;
  $("search").addEventListener("input",e=>{state.q=e.target.value;state.limit=15;render();});
  for (const key of ["type","source","sort"]) $(key).addEventListener("change",e=>{state[key]=e.target.value;state.limit=15;render();});
  $("papers").addEventListener("click",e=>{const b=e.target.closest(".bookmark");if(b)saveBookmark(b);});
  $("load-more").addEventListener("click",()=>{state.limit+=15;render();});
  $("export-button").addEventListener("click",exportRis);
  $("about-button").addEventListener("click",()=>$("about-dialog").showModal());
  $("close-about").addEventListener("click",()=>$("about-dialog").close());
  $("about-dialog").addEventListener("click",e=>{if(e.target===$("about-dialog"))$("about-dialog").close();});
  const aboutFooter = document.createElement("button"); aboutFooter.textContent="数据来源与收录说明 ↗"; aboutFooter.className="footer-about"; aboutFooter.addEventListener("click",()=>$("about-dialog").showModal()); document.querySelector("footer p").append(aboutFooter);
  document.addEventListener("keydown",e=>{if(e.key==="/"&&!/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)&&!$("about-dialog").open){e.preventDefault();$("search").focus();}});
  const embedded = document.getElementById("snapshot-data");
  async function loadDataset() {
    if ("DecompressionStream" in window) {
      const response = await fetch("./data.json.gz", {cache:"no-cache"});
      if (response.ok) return new Response(response.body.pipeThrough(new DecompressionStream("gzip"))).json();
      if (response.status !== 404) throw new Error(`HTTP ${response.status}`);
    }
    const response = await fetch("./data.json", {cache:"no-cache"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }
  const dataPromise = embedded ? Promise.resolve().then(()=>JSON.parse(embedded.textContent)) : loadDataset();
  dataPromise.then(d=>{
    if(d.schema_version!==1||!Array.isArray(d.papers))throw new Error("Invalid dataset");
    data=d;data.topics.forEach(t=>topicMap[t.id]=t);
    Object.assign(venueLabel, d.venue_group_labels || {});
    if (embedded) {
      $("about-update").textContent="这是可直接打开的离线快照，不会自行更新。请打开在线网站查看每日更新。";
      const dataLink=document.querySelector('.data-link');
      dataLink.href=URL.createObjectURL(new Blob([embedded.textContent],{type:'application/json'}));
      dataLink.download='human-ai-brief-data.json';dataLink.textContent='下载当前文献数据 ↗';
      document.querySelector('.brand').href=location.pathname;
    }
    const groups = d.venue_group_labels || {};
    const venues = d.monitored_venues || [];
    $("venue-guide-title").textContent=`关注来源如何选择？查看 ${venues.length} 个来源`;
    $("venue-list").innerHTML=Object.entries(groups).map(([id,label])=>`<div><h3>${label}</h3><p>${venues.filter(v=>v.group===id).map(v=>escape(v.name)).join(" · ")}</p></div>`).join("");
    $("count-all").textContent=data.papers.length;$("stat-total").textContent=data.papers.length;
    $("stat-week").textContent=data.papers.filter(p=>withinDays(p,"7")).length;
    for(const t of data.topics)$("count-"+t.id).textContent=data.papers.filter(p=>p.topics.includes(t.id)).length;
    const stamp=new Date(data.updated_at);
    $("stat-updated").textContent=new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",month:"2-digit",day:"2-digit"}).format(stamp)+" 已更新";
    $("stat-updated").title=`最近成功采集：${stamp.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})}（北京时间）`;
    $("update-mode").textContent=`本日收录文献 ${data.update_summary?.new_papers ?? 0} 篇`;
    $("update-mode").title="按北京时间统计该更新日首次进入本站的去重文献；包含延迟收录的文章，不等于当天发表数量。";
    $("about-meta").textContent=`首次回溯起点：${data.initial_coverage_start}。最近成功采集：${stamp.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})}（北京时间）。`;
    if(data.update_mode==="github-actions"&&!embedded){ $("about-update").textContent="由 GitHub Actions 每天北京时间 08:17 自动采集并部署，电脑关机也会运行；调度和来源收录可能延迟。每日新收录数按北京时间统计去重后的首次收录记录，同一天重复运行不重复计数。“已更新”表示采集成功，并不表示出版方今天发表的文章已经全部入库。"; }
    const age=(Date.now()-stamp.getTime())/86400000;
    if(age>2){$("notice").hidden=false;$("notice").textContent=`文献库已超过 ${Math.floor(age)} 天未成功更新。当前显示已保存的数据，请检查更新任务。`;}
    render();
  }).catch(error=>{
    $("papers").setAttribute("aria-busy","false");$("export-button").disabled=true;
    $("papers").innerHTML='<div class="empty"><strong>文献数据暂时无法读取。</strong><p>请检查网络后重新载入。若在本机运行，请使用 HTTP 预览服务打开网页。</p><button id="retry">重新载入</button></div>';
    $("retry").addEventListener("click",()=>location.reload());console.error("Dataset load failed:",error);
  });
})();
