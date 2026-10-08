"use strict";
const state={report:null,board:null,inventory:null,archive:[],feedback:{},token:"",filter:"home",ranking:"personal",query:"",repository:"",limit:10,saved:[],workspaceId:null,bootstrap:null,hub:null,hotSort:"useful"};
const $=selector=>document.querySelector(selector);
const escapeHTML=value=>String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
function safeURL(value){try{const u=new URL(value);return u.protocol==="https:"&&!u.username&&!u.password&&["x.com","twitter.com","github.com","learn.chatgpt.com","developers.openai.com","agentskills.io","api-docs.deepseek.com"].includes(u.hostname)?u.href:"";}catch{return "";}}
function sourceLink(url,label="查看原文 ↗"){const safe=safeURL(url);return safe?`<a class="source-link" href="${escapeHTML(safe)}" target="_blank" rel="noopener noreferrer">${escapeHTML(label)}</a>`:"";}
async function getJSON(url){const res=await fetch(url,{headers:state.workspaceId?{"X-Workspace-Id":state.workspaceId}:{}});if(!res.ok)throw new Error(`读取失败 (${res.status})`);return res.json();}
function toast(text){$("#toast").textContent=text;$("#toast").classList.add("visible");clearTimeout(toast.timer);toast.timer=setTimeout(()=>$("#toast").classList.remove("visible"),2600);}
function dateTime(value){try{return new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"}).format(new Date(value));}catch{return "待核对";}}
function dateLong(value){try{return new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",year:"numeric",month:"long",day:"numeric"}).format(new Date(value));}catch{return "长期 Skills 目录";}}
const relations={new:"新增能力",improvement:"专门流程改进",covered:"已有能力覆盖",uncertain:"增量待核对"};
const compat={documented:"文档显示可用",adaptation:"需要适配",blocked:"依赖暂不满足",unknown:"兼容性待核对"};
const difficulty={beginner:"容易开始",intermediate:"需要一些准备",advanced:"需要较多准备"};
const views={home:"首页精选",hot:"热门 Skills",growth:"近期增长",news:"AI / Agent 动态",tibo:"tibo监视",personal:"可选个人推荐",all:"我的变化记录",saved:"我的收藏"};
function matches(row){return (!state.query||[row.name,row.description,row.summary,row.repository,row.reason,row.general_reason,row.use_case,row.title,...(row.tags||[])].join(" ").toLowerCase().includes(state.query))&&(!state.repository||state.filter!=="leaderboard"||row.repository===state.repository);}
function feedbackButtons(row){const action=state.feedback[row.id]?.action;return `<div class="feedback" data-id="${escapeHTML(row.id)}">${[["interested","感兴趣"],["already_have","已有类似"],["not_relevant","与我无关"]].map(([key,label])=>`<button data-action="${key}" aria-pressed="${action===key}" class="${action===key?"selected":""}">${label}</button>`).join("")}${action?'<button data-action="reset">撤销</button>':""}</div>`;}
function skill(row,index,section){
 const reviewed=["ai_reviewed","inventory_matched"].includes(row.analysis_status),classic=section==="classic",rank=section==="personal"?row.personal_rank:classic?row.classic_rank:index+1;
 const action=state.feedback[row.id]?.action;
 const label=action==="already_have"?"你已标记有类似能力":reviewed?(relations[row.relation]||"待核对"):"个人增量待核对";
 const stars=Number(row.stars||0).toLocaleString("en-US");
 const matched=row.matched_existing||row.matched_skills||[];
 const scoreLabel=classic?`经典精选 ${row.classic_score}/100`:reviewed?`个人匹配 ${row.score}/100`:"尚未评分";
 const priority=!classic&&reviewed&&row.score>=80&&["new","improvement"].includes(row.relation)&&(!row.source_status||row.source_status==="current");
 return `<article class="article"><div class="article-number">${String(rank).padStart(2,"0")}</div><div><div class="article-top"><span class="tag ${priority?"recommend":""}">${escapeHTML(label)}</span>${priority?'<span class="tag recommend">优先试用</span>':""}<span>${escapeHTML(row.repository)}</span><span>仓库 ★ ${stars}</span><span>${escapeHTML(scoreLabel)}</span></div><h3>${escapeHTML(row.name)}</h3><p class="summary">${escapeHTML(row.summary||row.description)}</p><div class="article-detail">${classic?`<p><strong>长期价值</strong> ${escapeHTML(row.general_reason||"通用价值仍在核对。")}</p>`:""}<p><strong>对你的价值</strong> ${escapeHTML(row.reason||"尚未完成与现有能力的比较。")}</p>${row.use_case?`<p><strong>可以这样试</strong> ${escapeHTML(row.use_case)}</p>`:""}${matched.length?`<p><strong>已有能力对照</strong> ${escapeHTML(matched.join("、"))}</p>`:""}<p><strong>${escapeHTML(compat[row.compatibility_status]||"兼容性待核对")}</strong> ${escapeHTML(row.compatibility_notes||"请先核对宿主、账户与依赖。")}</p>${row.difficulty?`<p><strong>试用准备</strong> ${escapeHTML(difficulty[row.difficulty])}</p>`:""}${row.change_summary?`<p><strong>变化</strong> ${escapeHTML(row.change_summary)}</p>`:""}<p><strong>采集证据</strong> ${escapeHTML((row.evidence_paths||[row.path]).join("、"))} · ${escapeHTML(dateTime(row.collected_at))}</p>${row.source_status&&row.source_status!=="current"?'<p><strong>原文待刷新</strong> 此条保留为历史参考，请再次核对当前依赖。</p>':""}</div><div class="article-footer">${sourceLink(row.url)}${feedbackButtons(row)}</div></div></article>`;
}
function heading(title,count,subtitle){return `<div class="section-heading"><span>${String(count).padStart(2,"0")}</span><h2>${title}</h2><small>${subtitle}</small></div>`;}
function section(title,subtitle,rows,key){const filtered=rows.filter(matches);return `<section class="section">${heading(title,filtered.length,subtitle)}${filtered.length?filtered.map((row,index)=>skill(row,index,key)).join(""):`<div class="empty"><strong>${state.query?"没有匹配的条目":"本期暂无条目"}</strong>${key==="recommendations"?"本期变化不会重复刊登已经推荐过的 Skills，可从长期榜继续阅读。":"已采集内容会随核对逐步补充。"}</div>`}</section>`;}
function newsSection(rows){const filtered=rows.filter(matches);return `<section class="section">${heading("官方动态",filtered.length,"已核实的使用变化")}${filtered.length?filtered.map(row=>`<article class="news-row"><div class="news-date">${escapeHTML(row.date_label||"日期待核对")}<span>${escapeHTML(row.source)}</span></div><div><h3>${escapeHTML(row.title)}</h3><p>${escapeHTML(row.summary)}</p><p>${escapeHTML(row.impact)}</p>${sourceLink(row.url)}</div></article>`).join(""):'<div class="empty">本期没有需要刊登的官方变化。</div>'}</section>`;}
function repositories(){const rows=state.board.repositories;return `<details class="repository-list"><summary>技能库热度榜 · ${rows.length} 个来源</summary><p class="repository-description">这里比较技能库的仓库 Stars。单个 Skill 的用途与价值见上方具体条目。</p><div class="repository-grid header"><span>技能库</span><span>仓库 Stars</span><span>已读 / 已发现</span></div>${rows.map(row=>`<div class="repository-grid"><span>${sourceLink(row.url,row.name)}<small>${dateTime(row.checked_at)} 检查</small></span><span class="repository-stars">${Number(row.stars).toLocaleString("en-US")}</span><span>${row.read_count} / ${row.skill_count}<small>${row.reviewed_count} 个已核对</small></span></div>`).join("")}</details>`;}
function leaderboard(){
 const b=state.board;
 if(!b)return '<div class="empty"><strong>长期榜正在建立</strong>历史技能的原文与用途核对完成后，会在这里持续保留。</div>';
 const personal=state.ranking==="personal";
 let rows=personal?b.personal:b.classics;
 if(personal)rows=rows.filter(row=>!["not_relevant","already_have"].includes(state.feedback[row.id]?.action));
 rows=rows.filter(matches);
 const visible=rows.slice(0,state.limit);
 return `<section class="section">${heading(personal?"适合我的能力增量":"知名技能库的经典精选",rows.length,personal?"持续保留 · 按个人价值排序":"持续保留 · 含已有类似能力")}${visible.length?visible.map((row,index)=>skill(row,index,personal?"personal":"classic")).join(""):`<div class="empty"><strong>${state.query||state.repository?"没有匹配的条目":"候选正在核对"}</strong>${personal?"切换知名经典榜，也可以认识你已有类似能力的高价值 Skills。":"未变化的历史条目完成核对后也会入榜。"}</div>`}<div class="rank-load"><span>已显示 ${visible.length} / ${rows.length} 项</span>${visible.length<rows.length?'<button id="load-more">继续看后面的排名</button>':""}</div></section>${repositories()}`;
}
function motion(){if(!window.gsap||!window.ScrollTrigger||matchMedia("(prefers-reduced-motion: reduce)").matches)return;gsap.registerPlugin(ScrollTrigger);ScrollTrigger.getAll().forEach(x=>x.kill());gsap.set("#progress",{scaleX:0});gsap.to("#progress",{scaleX:1,ease:"none",scrollTrigger:{trigger:"#paper",start:"top top",end:"bottom bottom",scrub:true}});gsap.from(".source-row",{opacity:0,y:6,duration:.35,stagger:.025,ease:"power2.out",scrollTrigger:{trigger:".coverage",start:"top 90%",once:true}});ScrollTrigger.refresh();}
function render(){
 if(["home","hot","growth","news","tibo"].includes(state.filter)){renderPublic();return;}
 const r=state.report,b=state.board,isBoard=state.filter==="personal";
 $("#editor-note").hidden=false;$("#stats").hidden=false;$("#personal-sidebar").hidden=false;
 if(!r&&!b)return;
 $("#view-title").textContent=views[state.filter];$("#rank-controls").hidden=!isBoard;$("#rank-explanation").hidden=!isBoard;
 $("#rank-explanation").textContent=state.ranking==="personal"?"按能补充或改善你现有能力的价值排序，60–79 分为按需了解，80 分起为优先试用。历史 Skills 会持续保留，不要求今天更新。":"从高星技能库中认识通用、成熟的实用流程。已有同类能力也保留介绍；Stars 属于仓库，精选分不是单个 Skill 的真实口碑或采用量。";
 $("#issue-date").textContent=isBoard?dateLong(b?.generated_at):r?.date||"每日晨报";$("#edition-label").textContent=isBoard?"长期 Skills 推荐榜":r?.edition_label||"每日版";
 $("#lead").textContent=isBoard?b?b.needs_scan?"经典目录已经可读。检查自己的 Skills 并填写业务目标后，这里会生成属于当前工作区的推荐。":`当前工作区「${b.workspace_name||"个人"}」有 ${b.reviewed_count} 个 Skill 完成个人比较。先看业务增量，也可以切换到知名经典。`:"正在补齐历史上值得使用的 Skills。":r?.lead||"这个工作区的晨报将在生成推荐后建立。";
 const stats=isBoard&&b?[[b.personal.length,"个人增量"],[b.classics.length,"经典精选"],[b.reviewed_count,"已核对技能"],[b.pending_review,"待核对技能"]]:[[r?.recommendations.length||0,"本期新推荐"],[r?.candidate_count||0,"已采集候选"],[r?.inventory_count||0,"本地能力"],[r?.pending_review||0,"待编辑核对"]];
 $("#stats").innerHTML=stats.map(([n,label])=>`<div class="stat"><b>${Number(n)||0}</b><span>${label}</span></div>`).join("");
 $("#health").hidden=isBoard?!b?.pending_review&&!b?.needs_scan&&!b?.needs_goals:!r?.degraded;
 $("#health").textContent=isBoard?b?.needs_scan?"请先检查当前工具的 Skills，或导入能力清单。":b?.needs_goals?"请在业务与模型中填写当前任务，推荐会围绕这个目标生成。":`仍有 ${b?.pending_review||0} 个候选等待个人比较，可继续生成推荐补齐。`:r?.inventory_stale?"个人能力清单需要刷新，增量推荐暂缓。":"部分来源或编辑尚未完成，进度已保留。";
 let html="";
 if(isBoard)html=leaderboard();
 else if(state.filter==="all"&&r){html=section("本期新增推荐","每日变化",r.recommendations,"recommendations");if(r.updates.length)html+=section("已报道能力的变化","每日变化",r.updates,"updates");html+=section("每日观察","新发现与待核对",r.observations,"observations")+newsSection(r.news);}
 else if(state.filter==="observations"&&r)html=section("每日观察","新发现与待核对",r.observations,"observations");
 else if(state.filter==="saved")html=section("收藏清单","跨期保存",state.saved.filter(row=>state.feedback[row.id]?.action==="interested"),"saved");
 $("#content").innerHTML=html;
 const labels={ok:"已检查",snapshot:"采集快照",partial:"部分完成",failed:"待补查",filtered:"未达门槛",disabled:"编辑暂停"};
 const sources=isBoard&&b?b.repositories.map(row=>({source:row.name,status:"snapshot",detail:`${row.read_count} 个原文已读，${row.reviewed_count} 个已核对；目录 ${row.skill_count} 个；${dateTime(row.checked_at)} 检查`})):r?.sources||[];
 $("#coverage-count").textContent=isBoard&&b?`已读 ${b.items.length} / 已发现 ${b.discovered_count} 个`:`${sources.length} 项检查`;
 $("#sources").innerHTML=sources.map(row=>`<div class="source-row"><span class="source-name">${escapeHTML(row.source)}</span><span class="source-status ${escapeHTML(row.status)}">${escapeHTML(labels[row.status]||row.status)}</span><span class="source-detail">${escapeHTML(row.detail)}</span></div>`).join("");
 $("#notes").textContent=(isBoard?b?.notes:r?.notes)?.join(" ")||"";$("#generated").textContent=`${isBoard?"榜单核对":"本期生成"}时间 ${dateTime(isBoard?b?.generated_at:r?.generated_at)} · Asia/Shanghai`;
 motion();
}
function renderInventory(){const query=$("#inventory-search").value.trim().toLowerCase();const rows=[...(state.inventory?.native_capabilities||[]),...(state.inventory?.skills||[])].filter(x=>[x.name,x.description,...(x.tags||[])].join(" ").toLowerCase().includes(query));const scopes={user:"用户级",project:"当前业务项目",plugin_cache:"插件缓存",custom:"自选目录",imported:"导入清单"};$("#inventory-list").innerHTML=rows.map(row=>`<div class="inventory-row"><h3>${escapeHTML(row.name)}</h3><p>${escapeHTML(row.description||"当前工具的原生能力")}</p><small>${escapeHTML(scopes[row.scope]||"原生能力")} · ${row.enabled===false?"已禁用":row.source==="user_import"?"用户提供 · 调用待确认":row.availability==="available"?"原生可用":"已读取定义 · 依赖待确认"}</small></div>`).join("")||'<div class="empty">没有匹配的能力。</div>';}
function setReading(value){if(!["standard","large","extra"].includes(value))value="large";document.documentElement.dataset.reading=value;document.querySelectorAll(".font-control button").forEach(button=>{const selected=button.dataset.reading===value;button.classList.toggle("selected",selected);button.setAttribute("aria-pressed",String(selected));});try{localStorage.setItem("agent-reader-font",value);}catch{}if(window.ScrollTrigger)ScrollTrigger.refresh();}
$("#content").addEventListener("click",async event=>{
 if(event.target.closest("#load-more")){state.limit+=10;render();return;}
 const button=event.target.closest("button[data-action]");if(!button)return;const container=button.closest("[data-id]");button.disabled=true;
 if(!state.workspaceId){toast("建立自己的工作区后，就可以保存收藏和反馈");button.disabled=false;return;}
 try{const response=await fetch("/api/feedback",{method:"POST",headers:{"Content-Type":"application/json","X-Morningpaper-Token":state.token,"X-Workspace-Id":state.workspaceId},body:JSON.stringify({id:container.dataset.id,action:button.dataset.action})});if(!response.ok)throw new Error();state.feedback=(await response.json()).feedback;render();toast(button.dataset.action==="reset"?"反馈已撤销":"反馈已保存，下次核对会参考");}catch{toast("保存失败，请确认本地服务仍在运行");button.disabled=false;}
});
document.querySelectorAll(".nav").forEach(button=>button.addEventListener("click",()=>navigate(button.dataset.filter)));
document.querySelectorAll("[data-ranking]").forEach(button=>button.addEventListener("click",()=>{state.ranking=button.dataset.ranking;state.limit=10;document.querySelectorAll("[data-ranking]").forEach(x=>{x.classList.toggle("selected",x===button);x.setAttribute("aria-pressed",String(x===button));});render();}));
document.querySelectorAll(".font-control button").forEach(button=>button.addEventListener("click",()=>setReading(button.dataset.reading)));
$("#repo-filter").addEventListener("change",event=>{state.repository=event.target.value;state.limit=10;render();});
$("#search").addEventListener("input",event=>{state.query=event.target.value.trim().toLowerCase();state.limit=10;render();});
$("#inventory-open").addEventListener("click",()=>{renderInventory();$("#inventory-dialog").showModal();});$("#inventory-close").addEventListener("click",()=>$("#inventory-dialog").close());$("#inventory-search").addEventListener("input",renderInventory);
$("#archive").addEventListener("change",async event=>{try{state.report=await getJSON("/api/report/"+encodeURIComponent(event.target.value));state.filter="all";document.querySelectorAll(".nav").forEach(x=>{const active=x.dataset.filter==="all";x.classList.toggle("active",active);x.setAttribute("aria-pressed",String(active));});render();}catch{toast("期刊读取失败");}});
async function loadWorkspace(workspaceId){
 state.workspaceId=workspaceId;state.report=null;state.board=null;state.inventory=null;state.archive=[];state.feedback={};state.saved=[];state.limit=10;
 if(!workspaceId){state.board=null;render();return;}
 const results=await Promise.allSettled([getJSON("/data/latest.json"),getJSON("/data/archive.json"),getJSON("/data/inventory.json"),getJSON("/api/feedback"),getJSON("/data/leaderboard.json")]);
 if(results[0].status==="fulfilled")state.report=results[0].value;
 if(results[1].status==="fulfilled")state.archive=results[1].value;
 $("#archive").innerHTML=state.archive.length?state.archive.map(row=>`<option value="${escapeHTML(row.id)}">${escapeHTML(row.date||dateLong(row.generated_at))} · ${escapeHTML(dateTime(row.generated_at))}</option>`).join(""):'<option>这个工作区还没有晨报</option>';
 if(results[2].status==="fulfilled")state.inventory=results[2].value;
 if(results[3].status==="fulfilled")state.feedback=results[3].value;
 if(results[4].status==="fulfilled"){state.board=results[4].value;$("#repo-filter").innerHTML='<option value="">全部技能库</option>'+state.board.repositories.map(row=>`<option value="${escapeHTML(row.name)}">${escapeHTML(row.name)}</option>`).join("");}
 render();document.dispatchEvent(new CustomEvent("skill-shelf-workspace",{detail:workspaceId}));
}
function publicMatch(row){return !state.query||[row.name,row.description,row.summary,row.repository,row.title,row.source,row.scope,row.mechanism_label].join(' ').toLowerCase().includes(state.query);}
function publicCard(row){return `<article class="skill-card"><div class="card-source">${escapeHTML(row.repository)}</div><h3>${escapeHTML(row.name)}</h3><p class="card-summary">${escapeHTML((row.summary||row.description||'').slice(0,150))}</p><div class="card-meta"><b>仓库 ★ ${Number(row.stars||0).toLocaleString('en-US')}</b>${sourceLink(row.url,'看原文 ↗')}</div><details><summary>了解用途与适配</summary><p>${escapeHTML(row.general_reason||row.description)}</p><p>${escapeHTML(row.host_notes||'可先查看原文中的宿主和依赖说明。')}</p><small>原文核对 ${escapeHTML(dateTime(row.collected_at))}</small></details></article>`;}
function publicHeading(title,view){return `<div class="home-section-head"><h2>${title}</h2>${view?`<button data-view="${view}">查看全部 ↗</button>`:''}</div>`;}
function growthHTML(rows){return rows.length?`<div class="growth-table">${rows.map(row=>`<div class="growth-row"><span>${sourceLink(row.url,row.repository)}<small>仓库 ★ ${Number(row.stars).toLocaleString('en-US')}</small></span><b>${row.delta>=0?'+':''}${Number(row.delta).toLocaleString('en-US')}</b><span>采样 ${row.hours} 小时<small>${row.percent>=0?'+':''}${row.percent}% ${row.fast_growth?'· 快速增长':''}</small></span></div>`).join('')}</div>`:'<div class="empty">增长记录正在积累，可以先看热门高星技能。</div>';}
function publicNewsHTML(rows){return `<div class="home-news">${rows.map(row=>`<article class="public-news-row"><div class="news-time">${escapeHTML(row.published_at?row.published_at.slice(0,10):'官方页面更新')}<br><small>${escapeHTML(row.source)}</small></div><div><h3>${escapeHTML(row.title)}</h3><p>${escapeHTML(row.summary||'官方原文已收录，摘要正在整理。')}</p>${sourceLink(row.url,'查看来源 ↗')}</div></article>`).join('')||'<div class="empty">正在补充经过核对的官方动态。</div>'}</div>`;}
function tiboItemHTML(row){const conflicts=row.verification==='conflicting';const states={announced:'已宣布，待执行',in_progress:'原文描述补发中',completed:'原文称已完成',unclear:'执行状态待确认',documented:'历史方式说明',not_announced:'本条未宣布重置',proposal:'提问或提议，未宣布',mixed:'多项安排，需看原文'};const day=row.published_at?row.published_at.slice(0,10):'原文没有发布日期';const publication=row.date_precision==='second'?dateTime(row.published_at)+'（上海时间）':day+'（原文仅提供日期）';return `<article class="tibo-entry"><div class="tibo-entry-top"><span>${escapeHTML(row.mechanism_label||'额度重置')}</span><span class="tibo-state">${escapeHTML(conflicts?'来源表述冲突，待确认':states[row.event_status]||'已核对来源')}</span></div><h3>${escapeHTML(row.title)}</h3><p>${escapeHTML(row.summary)}</p><dl class="tibo-fields"><div><dt>重置时间</dt><dd>${escapeHTML(conflicts?'来源互相矛盾，暂不确认':row.reset_time_text||'原文未明确')}</dd></div><div><dt>适用范围</dt><dd>${escapeHTML(row.scope||'原文未明确')}</dd></div><div><dt>消息发布</dt><dd>${escapeHTML(publication)}</dd></div><div><dt>首次采集</dt><dd>${escapeHTML(dateTime(row.collected_at))}（上海时间）</dd></div></dl>${sourceLink(row.url,'查看原帖 / 官方说明 ↗')}<details><summary>核对依据与待确认项</summary><p>来源：${escapeHTML(row.source)}。最近核对 ${escapeHTML(dateTime(row.last_verified_at))}。</p>${row.excerpt?`<blockquote>${escapeHTML(row.excerpt)}</blockquote>`:''}${(row.uncertainties||[]).map(text=>`<p>${escapeHTML(text)}</p>`).join('')}</details></article>`;}
function tiboHTML(value,preview=false){const t=value||{items:[],references:[],sources:[],status:'not_checked'};const rows=(t.items||[]).filter(publicMatch);const label={ok:'本轮来源核对完成',partial:'覆盖范围有限',unavailable:'来源暂不可核实',not_checked:'尚未执行本专栏监测'}[t.status]||'覆盖范围待核对';const listing=rows.length?rows.slice(0,preview?2:20).map(tiboItemHTML).join(''):'<div class="empty">暂无新的已确认重置消息。来源不可读时，不据此断言今天没有重置。</div>';return `<p class="tibo-intro">只跟踪 ChatGPT / Codex 额度刷新、补发与可储存重置。</p><p class="tibo-health">${escapeHTML(label)} · 核对截至 ${escapeHTML(dateTime(t.updated_at))} · 每天 08:30 / 20:30</p>${listing}${preview?'':`<details class="tibo-coverage"><summary>官方重置说明与本轮覆盖范围</summary><p>${escapeHTML(t.coverage)}</p>${(t.references||[]).map(row=>`<p><b>${escapeHTML(row.title)}</b><br>${escapeHTML(row.summary)} ${sourceLink(row.url,'官方说明 ↗')}</p>`).join('')}${(t.sources||[]).map(row=>`<p>${escapeHTML(row.source)}：${escapeHTML(row.detail)}</p>`).join('')}</details>`}`;}
function renderPublic(){
 const h=state.hub;if(!h)return;
 $('#editor-note').hidden=true;$('#stats').hidden=true;$('#rank-controls').hidden=true;$('#rank-explanation').hidden=true;$('#health').hidden=true;$('#personal-sidebar').hidden=true;$('#welcome-panel').hidden=true;$('#workspace-panel').hidden=true;$('#session-needed').hidden=true;
 $('#issue-date').textContent=`核对截至 ${dateTime(h.updated_at)}`;$('#edition-label').textContent=`${h.skill_count} 个 Skill · ${h.repository_count} 个技能库`;$('#view-title').textContent=views[state.filter];
 const skills=(state.filter==='home'&&!state.query?h.featured:h.skills).filter(publicMatch);
 const growth=h.growth.filter(row=>publicMatch({repository:row.repository}));const news=h.news.filter(publicMatch);
 let html='';
 if(state.filter==='home'){html=`<section class="home-section">${publicHeading(state.query?'技能搜索结果':'精选热门 Skills','hot')}<div class="skill-grid">${skills.slice(0,6).map(publicCard).join('')||'<div class="empty">没有匹配的技能。</div>'}</div></section><section class="home-section">${publicHeading('近期增长观察','growth')}${growthHTML(growth.slice(0,3))}</section><section class="home-section">${publicHeading('AI / Agent 动态','news')}${publicNewsHTML(news.slice(0,3))}</section><section class="home-section">${publicHeading('tibo监视','tibo')}${tiboHTML(h.tibo,true)}</section>`;}
 if(state.filter==='tibo')html=tiboHTML(h.tibo);
 if(state.filter==='hot'){const sorted=state.hotSort==='stars'?[...skills].sort((a,b)=>b.stars-a.stars):skills;const shown=sorted.slice(0,state.limit);html=`<p class="nav-hint">历史上好用的技能持续保留，直接查看用途和原文。</p><div class="rank-controls"><div class="rank-modes"><button data-hot-sort="useful" class="${state.hotSort==='useful'?'selected':''}">精选实用</button><button data-hot-sort="stars" class="${state.hotSort==='stars'?'selected':''}">仓库 Stars</button></div></div><div class="skill-grid">${shown.map(publicCard).join('')}</div><div class="rank-load"><span>已显示 ${shown.length} / ${sorted.length} 项</span>${shown.length<sorted.length?'<button id="public-load-more">继续浏览</button>':''}</div>`;}
 if(state.filter==='growth')html=`${publicHeading('近期增长')}<p class="growth-note">${escapeHTML(h.growth_note)}</p>${growthHTML(growth)}`;
 if(state.filter==='news')html=`${publicHeading('AI / Agent 动态')}<p class="nav-hint">保留正式发布日期。没有日期的页面更新单独标注。</p>${publicNewsHTML(news)}`;
 $('#content').innerHTML=html;$('#coverage-count').textContent=`${h.skill_count} 个已收录 Skill`;
 $('#sources').innerHTML=h.repositories.map(row=>`<div class="source-row"><span>${escapeHTML(row.name)}</span><span>${row.read_count} 已读</span><span class="source-detail">目录 ${row.skill_count} 项 · ${escapeHTML(dateTime(row.checked_at))} 核对</span></div>`).join('');
 $('#notes').textContent='热度来自 GitHub 仓库，实用价值依据具体 Skill 原文。';$('#generated').textContent='资讯阅读无需能力检查；个人推荐可选。';motion();
}
async function ensurePrivate(){if(state.bootstrap)return true;try{state.bootstrap=await getJSON('/api/bootstrap');state.token=state.bootstrap.token;state.workspaceId=state.bootstrap.active_workspace;document.dispatchEvent(new CustomEvent('skill-shelf-bootstrap'));return true;}catch{return false;}}
async function navigate(view){
 state.filter=view;state.limit=10;document.querySelectorAll('.nav[data-filter]').forEach(button=>{const active=button.dataset.filter===view;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});
 if(['home','hot','growth','news','tibo'].includes(view)){renderPublic();document.dispatchEvent(new CustomEvent('skill-shelf-view'));return;}
 if(!await ensurePrivate()){$('#session-needed').hidden=false;$('#welcome-panel').hidden=true;$('#workspace-panel').hidden=true;$('#rank-controls').hidden=true;$('#content').innerHTML='<div class="empty">个人记录需要本机会话。可以随时返回首页继续浏览资讯。</div>';return;}
 if(view==='saved'){state.saved=state.workspaceId?await getJSON('/api/saved'):[];render();}
 else{await loadWorkspace(state.workspaceId);if(!state.workspaceId){$('#welcome-panel').hidden=false;$('#content').innerHTML='<div class="empty">检查现有能力后，可在这里看个人增量。也可以先看公开热门榜。</div>';}}
 document.dispatchEvent(new CustomEvent('skill-shelf-view'));
}
$('#content').addEventListener('click',event=>{const target=event.target.closest('[data-view]');if(target){navigate(target.dataset.view);return;}const sort=event.target.closest('[data-hot-sort]');if(sort){state.hotSort=sort.dataset.hotSort;renderPublic();return;}if(event.target.closest('#public-load-more')){state.limit+=10;renderPublic();}});
document.querySelectorAll('.return-home').forEach(button=>button.addEventListener('click',()=>navigate('home')));
async function init(){
 let reading='large';try{reading=localStorage.getItem('agent-reader-font')||'large';}catch{}setReading(reading);
 try{state.hub=await getJSON('/api/public/home');renderPublic();}catch{$('#content').innerHTML='<div class="empty">资讯暂未载入，请刷新重试。</div>';}
 const launch=new URLSearchParams(location.hash.slice(1)).get('session');
 if(launch){try{const response=await fetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({launch_token:launch})});if(response.ok)history.replaceState(null,'',location.pathname+location.search);}catch{}}
}
init();

setInterval(async()=>{try{const value=await getJSON('/api/public/tibo');if(state.hub)state.hub.tibo=value;if(['home','tibo'].includes(state.filter))renderPublic();}catch{}},60000);
