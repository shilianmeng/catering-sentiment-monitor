// 公共脚本：登录态、接口请求、顶部导航与演示控制、角色显隐、Markdown 渲染、SVG 图表。
const favicon = document.createElement("link");
favicon.rel = "icon";
favicon.href = "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#2f6fde"/><path d="M5 23L12 15L19 19L27 7" fill="none" stroke="white" stroke-width="3"/></svg>');
document.head.appendChild(favicon);
const ROLE_NAME = { analyst: "分析师", pr: "公关", admin: "管理员" };

const Auth = {
  get token() { return localStorage.getItem("yq_token"); },
  get user() { try { return JSON.parse(localStorage.getItem("yq_user") || "null"); } catch { return null; } },
  save(d) { localStorage.setItem("yq_token", d.token); localStorage.setItem("yq_user", JSON.stringify(d)); },
  clear() { localStorage.removeItem("yq_token"); localStorage.removeItem("yq_user"); },
  role() { return (this.user || {}).role; },
  can(...roles) { return roles.includes(this.role()); },
};

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (Auth.token) headers.Authorization = "Bearer " + Auth.token;
  let body = opts.body;
  if (body && typeof body !== "string") { body = JSON.stringify(body); headers["Content-Type"] = "application/json"; }
  const res = await fetch(path, { method: opts.method || "GET", headers, body });
  if (res.status === 401 && !path.endsWith("/login")) { Auth.clear(); location.href = "/login"; throw new Error("未登录"); }
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) throw new Error((data && data.detail) || ("请求失败 " + res.status));
  return data;
}

function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function $(sel, root = document) { return root.querySelector(sel); }
function $all(sel, root = document) { return [...root.querySelectorAll(sel)]; }

function toast(msg, isErr) {
  let t = $(".toast");
  if (!t) { t = document.createElement("div"); t.className = "toast"; document.body.appendChild(t); }
  t.textContent = msg; t.classList.toggle("err", !!isErr); t.classList.add("show");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 2600);
}

function lv(level) { return `<span class="lv ${esc(level)}">${esc(level)}</span>`; }
function sentiTag(s) { const c = s === "负向" ? "neg" : s === "正向" ? "pos" : "neu"; return `<span class="tag ${c}">${esc(s)}</span>`; }
function hl(text, kw) { const t = esc(text); if (!kw) return t; const k = esc(kw).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); return t.replace(new RegExp(k, "g"), m => `<mark>${m}</mark>`); }

// 按角色显隐：data-roles="analyst,admin"
function applyRoles(root = document) {
  $all("[data-roles]", root).forEach(el => {
    const ok = el.dataset.roles.split(",").includes(Auth.role());
    el.classList.toggle("hidden", !ok);
  });
}

// ---------- 顶部导航 + 演示控制 ----------
function initPage(active) {
  if (!Auth.token) { location.href = "/login"; return false; }
  const u = Auth.user;
  const links = [["/", "态势大盘"], ["/workbench", "研判工作台"], ["/events/ev001", "事件专题"], ["/reports", "报告中心"], ["/settings", "监测配置"]];
  const bar = document.createElement("header");
  bar.className = "topbar";
  bar.innerHTML = `<span class="brand">香满园舆情监测与研判</span>
    <nav>${links.map(([h, n]) => `<a href="${h}" class="${active === h ? "active" : ""}">${n}</a>`).join("")}</nav>
    <span class="spacer"></span>
    <span class="clock" id="clock" title="虚拟时钟">虚拟时钟 -</span>
    <button id="btnAdvance" data-roles="admin" title="接入下一批模拟数据">推进时钟 ▶</button>
    <button id="btnReset" data-roles="admin" title="删库重建演示数据">重置演示</button>
    <span class="user">${esc(u.display_name)}（${ROLE_NAME[u.role]}）</span>
    <button id="btnLogout">退出</button>`;
  document.body.prepend(bar);
  $("#btnLogout").onclick = async () => { try { await api("/api/logout", { method: "POST" }); } catch {} Auth.clear(); location.href = "/login"; };
  $("#btnAdvance").onclick = async () => {
    try {
      const r = await api("/api/demo/advance", { method: "POST", body: { batches: 1 } });
      if (r.message) toast(r.message);
      else { const x = r.results[0]; toast(`已推进到 ${x.label}：接入 ${x.ingested} 条，过滤 ${x.filtered} 条，合并水军帖 ${x.merged.length} 条`); }
      refreshClock();
    } catch (e) { toast(e.message, true); }
  };
  $("#btnReset").onclick = async () => {
    try { await api("/api/demo/reset", { method: "POST" }); toast("已重置为预置演示数据（T0）"); refreshClock(); }
    catch (e) { toast(e.message, true); }
  };
  refreshClock();
  applyRoles();
  return true;
}

async function refreshClock() {
  try { const c = await api("/api/clock"); setClock(c); } catch {}
}
function setClock(c) {
  const el = $("#clock"); if (!el || !c) return;
  el.textContent = `虚拟时钟 ${c.current_label} · ${c.current_time ? c.current_time.slice(5) : "-"}${c.finished ? "（已到最后一批）" : ""}`;
}

// ---------- SSE ----------
function openStream(handlers) {
  if (!Auth.token) return null;
  const es = new EventSource("/api/stream?token=" + encodeURIComponent(Auth.token));
  for (const [ev, fn] of Object.entries(handlers)) es.addEventListener(ev, e => fn(JSON.parse(e.data || "{}")));
  es.addEventListener("batch_advanced", e => setClock(JSON.parse(e.data).clock));
  return es;
}

// ---------- 极简 Markdown 渲染（标题 / 列表 / 表格 / 粗体 / 引用） ----------
function renderMarkdown(md) {
  const lines = String(md || "").split(/\r?\n/);
  const out = []; let i = 0;
  const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, "<code>$1</code>")
    .replace(/\[(c\d{3})\]/g, '<a href="javascript:void(0)" class="cref" data-id="$1">[$1]</a>');
  while (i < lines.length) {
    const l = lines[i];
    if (/^\s*\|/.test(l)) {
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) { rows.push(lines[i]); i++; }
      const cells = r => r.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
      const body = rows.filter(r => !/^\s*\|[\s\-:|]+\|\s*$/.test(r));
      out.push("<table>" + body.map((r, k) => "<tr>" + cells(r).map(c => k === 0 ? `<th>${inline(c)}</th>` : `<td>${inline(c)}</td>`).join("") + "</tr>").join("") + "</table>");
      continue;
    }
    if (/^#{1,4}\s/.test(l)) { const n = l.match(/^#+/)[0].length; out.push(`<h${n}>${inline(l.replace(/^#+\s*/, ""))}</h${n}>`); i++; continue; }
    if (/^\s*([-*]|\d+\.)\s/.test(l)) {
      const items = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s/.test(lines[i])) { items.push(lines[i].replace(/^\s*([-*]|\d+\.)\s/, "")); i++; }
      out.push("<ul>" + items.map(x => `<li>${inline(x)}</li>`).join("") + "</ul>"); continue;
    }
    if (/^>\s?/.test(l)) { out.push(`<blockquote>${inline(l.replace(/^>\s?/, ""))}</blockquote>`); i++; continue; }
    if (!l.trim()) { i++; continue; }
    out.push(`<p>${inline(l)}</p>`); i++;
  }
  return out.join("\n");
}

// ---------- SVG 图表（离线可用，不依赖 CDN） ----------
const SVGNS = "http://www.w3.org/2000/svg";

function lineChart(el, labels, series, opts = {}) {
  const W = el.clientWidth || 600, H = opts.height || 240, P = { l: 36, r: 14, t: 16, b: 30 };
  const max = Math.max(1, ...series.flatMap(s => s.data)) * 1.15;
  const x = i => P.l + (labels.length <= 1 ? (W - P.l - P.r) / 2 : i * (W - P.l - P.r) / (labels.length - 1));
  const y = v => H - P.b - v / max * (H - P.t - P.b);
  let g = "";
  for (let k = 0; k <= 4; k++) {
    const v = max * k / 4, yy = y(v);
    g += `<line x1="${P.l}" x2="${W - P.r}" y1="${yy}" y2="${yy}" stroke="#eef1f6"/><text x="${P.l - 6}" y="${yy + 4}" font-size="11" text-anchor="end" fill="#8a94a6">${Math.round(v)}</text>`;
  }
  labels.forEach((lb, i) => { g += `<text x="${x(i)}" y="${H - 10}" font-size="11" text-anchor="middle" fill="#6b7385">${esc(lb)}</text>`; });
  series.forEach(s => {
    const pts = s.data.map((v, i) => `${x(i)},${y(v)}`).join(" ");
    g += `<polyline points="${pts}" fill="none" stroke="${s.color}" stroke-width="2.5"/>`;
    s.data.forEach((v, i) => { g += `<circle cx="${x(i)}" cy="${y(v)}" r="3.5" fill="${s.color}"><title>${esc(s.name)} ${esc(labels[i])}：${v}</title></circle><text x="${x(i)}" y="${y(v) - 7}" font-size="10" text-anchor="middle" fill="${s.color}">${v}</text>`; });
  });
  const legend = series.map((s, k) => `<rect x="${P.l + k * 90}" y="2" width="10" height="10" fill="${s.color}"/><text x="${P.l + 14 + k * 90}" y="11" font-size="11" fill="#4a5368">${esc(s.name)}</text>`).join("");
  el.innerHTML = `<svg width="${W}" height="${H}">${g}${legend}</svg>`;
}

function donutChart(el, parts, opts = {}) {
  const size = opts.size || 200, r = size / 2 - 14, cx = size / 2, cy = size / 2, total = parts.reduce((a, p) => a + p.value, 0) || 1;
  let a0 = -Math.PI / 2, g = "";
  parts.forEach(p => {
    if (!p.value) return;
    const a1 = a0 + p.value / total * Math.PI * 2, large = a1 - a0 > Math.PI ? 1 : 0;
    const seg = p.value === total
      ? `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${p.color}" stroke-width="26"/>`
      : `<path d="M${cx + r * Math.cos(a0)},${cy + r * Math.sin(a0)} A${r},${r} 0 ${large} 1 ${cx + r * Math.cos(a1)},${cy + r * Math.sin(a1)}" fill="none" stroke="${p.color}" stroke-width="26"/>`;
    g += seg.replace("/>", `><title>${esc(p.name)}：${p.value}</title></` + (p.value === total ? "circle>" : "path>"));
    a0 = a1;
  });
  const legend = parts.map(p => `<div><span class="tag" style="background:${p.color};color:#fff">${esc(p.name)}</span>${p.value} 条（${(p.value * 100 / total).toFixed(1)}%）</div>`).join("");
  el.innerHTML = `<div class="row" style="gap:18px"><svg width="${size}" height="${size}">${g}<text x="${cx}" y="${cy + 6}" text-anchor="middle" font-size="18" font-weight="bold">${total}</text></svg><div>${legend}</div></div>`;
}

function wordCloud(el, words) {
  if (!words.length) { el.innerHTML = '<p class="muted">暂无数据</p>'; return; }
  const max = Math.max(...words.map(w => w.count)), min = Math.min(...words.map(w => w.count));
  const colors = ["#d64541", "#2f6fde", "#e67e22", "#8e44ad", "#2e9e5b", "#16a085", "#c0392b"];
  el.innerHTML = '<div style="text-align:center;line-height:2.1">' + words.map((w, i) => {
    const fs = 13 + (max === min ? 8 : (w.count - min) / (max - min) * 20);
    return `<span title="${esc(w.word)}：${w.count} 次" style="font-size:${fs.toFixed(0)}px;color:${colors[i % colors.length]};margin:0 8px;font-weight:${fs > 24 ? "bold" : "normal"}">${esc(w.word)}</span>`;
  }).join(" ") + "</div>";
}

function alertHtml(a, fresh) {
  const cls = a.suppressed ? "suppressed" : a.alert_type === "升级" ? "up" : "";
  const ch = (a.notified || []).join("、");
  return `<div class="alert-item ${cls} ${fresh ? "fresh" : ""}">
    <div class="row"><b>${esc(a.alert_type)}</b>${a.suppressed ? '<span class="tag">静默期内已抑制</span>' : lv(a.level)}
    <span class="muted small">${esc(a.triggered_at)}（虚拟时间）</span>${!a.suppressed && !a.is_read ? '<span class="tag neg">未读</span>' : ""}</div>
    <div>${esc(a.summary)}</div>
    <div class="small muted">规则：${esc(a.rule_desc)}${a.suppressed ? "" : `｜静默至 ${esc((a.silence_until || "").slice(11))}｜已推送：${esc(ch || "无")}`}</div>
    <div class="small"><a href="/events/${esc(a.event_id)}">查看事件 ${esc(a.event_id)} →</a></div></div>`;
}
