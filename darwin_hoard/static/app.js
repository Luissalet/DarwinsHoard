'use strict';
// Darwin's Hoard UI: overview, filterable history with each discovery's genealogy, the capability tree, what changed
// and the gaps. Every action goes through the same tools the agents use (/api/ui/call).

const $ = (id) => document.getElementById(id);
const plain = (s) => String(s ?? '').replace(/\*\*/g, '').replace(/`/g, '');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const STATE_LABEL = { integrada: 'Integrada', mixta: 'En parte', parcial: 'Parcial', aceptada: 'Aceptada', investigando: 'En marcha', debatida: 'Debatida',
  pendiente: 'Pendiente', aplazada: 'Aplazada', cubierta: 'Ya cubierta', descartada: 'Descartada', sin_propuesta: 'Sin propuesta',
  sin_implementar: 'Sin implementar', sustituida: 'Sustituida' };
const PROPOSAL_STATES = ['pendiente', 'investigando', 'debatida', 'aceptada', 'aplazada', 'descartada', 'cubierta'];
const CHANNEL_LABEL = { radar: 'Radar', 'radar-ideas': 'Radar (proyecto)', tracker: 'Seguimiento', guide: 'Guía', agora: 'Ágora',
  whatsapp: 'WhatsApp', links: 'Links', talos: 'Captura', agent: 'Agente', manual: 'A mano' };
const VERIF_LABEL = { documentada: 'documentada', probada: 'probada', recomprobar: 'recomprobar', desconocida: 'sin comprobar' };
const RELATION_LABEL = { inspirado_por: 'inspirado por', codigo_de: 'código de', dependencia: 'dependencia', desconocida: 'relación sin precisar' };
const SUIT_STATUS = { proposed: ['Propuesto', 'st-pendiente'], partial: ['Respaldo parcial', 'st-parcial'], backed: ['Respaldado', 'st-integrada'], evaluated: ['Evaluado', 'st-aceptada'] };
const OP_STATE = { backed: ['con prueba', 'st-integrada'], unproven: ['existe, sin prueba', 'st-parcial'], missing: ['falta', 'st-aplazada'] };
const EVID_LABEL = { commit: 'commit', test: 'test', qa_file: 'QA' };
const evidenceHtml = (list) => (list || []).map((e) => `<span class="chip" title="${esc(e.note || '')}">${EVID_LABEL[e.kind] || esc(e.kind)}: <code>${esc(e.ref)}</code></span>`).join('');
const LEVEL_LABEL = { root: 'raíz', hub: 'hub', app: 'hoard', module: 'módulo', capability: 'capacidad', tool: 'tool' };
const state = { suit: null, view: 'overview', page: 0, pageSize: 60, selected: null, names: {}, targets: [], treeSel: null };

async function api(path, opts = {}) {
  const init = { method: opts.method || 'GET', headers: {} };
  if (opts.body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
  const res = await fetch(path, init);
  const text = await res.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { error: text }; }
  if (!res.ok) { const e = new Error(data.error || `HTTP ${res.status}`); e.hint = data.hint || ''; throw e; }
  return data;
}
const call = (name, args = {}) => api('/api/ui/call', { method: 'POST', body: { name, arguments: args } });
function toast(text, kind = '') { const el = document.createElement('div'); el.className = `toast ${kind}`; el.textContent = text; $('toasts').appendChild(el); setTimeout(() => el.remove(), kind === 'err' ? 7000 : 3500); }
const fail = (e) => toast(e.hint ? `${e.message} ${e.hint}` : e.message, 'err');
const when = (t) => t ? new Date(t * 1000).toLocaleDateString('es-ES', { day: '2-digit', month: 'short', year: '2-digit' }) : '—';
const whenFull = (t) => t ? new Date(t * 1000).toLocaleString('es-ES', { dateStyle: 'short', timeStyle: 'short' }) : '—';
const chip = (st, label) => `<span class="chip st-${esc(st)}">${esc(label || STATE_LABEL[st] || st)}</span>`;
const PROOF = { en_main: ['commit en main', 'st-integrada'], documentos: ['según documentos', 'st-pendiente'], fuera_de_main: ['commit fuera de main', 'st-aplazada'] };
const proofChip = (p) => p && PROOF[p] ? `<span class="chip ${PROOF[p][1]}" title="Cómo se sabe que está integrada">${PROOF[p][0]}</span>` : '';
const appName = (id) => state.names[id] || id;
const appChip = (id) => `<span class="chip app" data-app="${esc(id)}" title="Ver en el historial">${esc(appName(id))}</span>`;
function store(key, value) { try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch { return null; } return null; }

// ------------------------------------------------------------------ navigation

const VIEW_ALIASES = { resumen: 'overview', historial: 'history', bandeja: 'inbox', arbol: 'tree', 'árbol': 'tree', novedades: 'changes', carencias: 'gaps', trajes: 'suits', suits: 'suits' };
const VIEWS = ['overview', 'history', 'inbox', 'tree', 'changes', 'gaps', 'suits'];

function show(view) {
  view = VIEW_ALIASES[decodeURIComponent(view || '').toLowerCase()] || view;
  if (!VIEWS.includes(view)) view = 'overview';
  state.view = view;
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.view === view));
  document.querySelectorAll('.view').forEach((v) => v.classList.toggle('active', v.id === `view-${view}`));
  if (location.hash !== `#${view}`) history.replaceState(null, '', `#${view}`);
  ({ overview: loadOverview, history: loadHistory, inbox: loadInbox, tree: loadTree, changes: loadChanges, gaps: loadGaps, suits: loadSuits })[view]?.();
}
document.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => show(t.dataset.view)));
window.addEventListener('hashchange', () => { const v = location.hash.slice(1); if (v && v !== state.view) show(v); });
document.addEventListener('click', (ev) => {
  const a = ev.target.closest('[data-app]');
  if (a) { ev.stopPropagation(); $('f-target').value = a.dataset.app; state.page = 0; show('history'); }
});

async function loadNames() {
  try {
    const t = await api('/api/tree?root=hoardhub&depth=2&tools=false');
    const walk = (n) => { if (n.app_id && ['app', 'module', 'hub', 'root'].includes(n.level)) state.names[n.app_id] = n.name; (n.children || []).forEach(walk); };
    walk(t.tree);
  } catch { /* the tree may be empty on first start */ }
  state.names.faustus = 'Faustus';
  const targets = await api('/api/targets');
  state.targets = targets.targets;
  for (const sel of [$('f-target'), $('add-target'), $('gap-target')]) {
    const keep = sel.value;
    sel.querySelectorAll('option:not(:first-child)').forEach((o) => o.remove());
    const ids = [...new Set([...targets.targets.map((t) => t.target), ...Object.keys(state.names)])].sort((a, b) => appName(a).localeCompare(appName(b)));
    for (const id of ids) { const o = document.createElement('option'); o.value = id; o.textContent = appName(id); sel.appendChild(o); }
    sel.value = keep;
  }
}

// ------------------------------------------------------------------ overview

function bars(el, entries, onClick) {
  const max = Math.max(1, ...entries.map((e) => e[1]));
  el.innerHTML = entries.map(([k, n, label]) => `<div class="bar" data-k="${esc(k)}"><span class="lbl">${esc(label || k)}</span><span class="track"><span class="fill" style="width:${(100 * n / max).toFixed(1)}%"></span></span><span class="n">${n}</span></div>`).join('') || '<div class="empty">Nada aún.</div>';
  if (onClick) el.querySelectorAll('.bar').forEach((b) => b.addEventListener('click', () => onClick(b.dataset.k)));
}

async function loadOverview() {
  loadAccounts(); postsStatus();
  try {
    const ov = await api('/api/overview');
    const c = ov.counts;
    $('kpis').innerHTML = [
      [c.sources, 'descubrimientos'], [c.captures, 'apariciones'], [c.proposals, 'propuestas'], [c.deliveries, 'entregas'],
      [c.capabilities, 'nodos del árbol'], [c.gaps, 'carencias'], [ov.captures_last_7_days, 'nuevas esta semana (sin el histórico)'],
    ].map(([n, l]) => `<div class="kpi"><b>${(n ?? 0).toLocaleString('es-ES')}</b><span>${l}</span></div>`).join('');
    const order = ['integrada', 'mixta', 'parcial', 'aceptada', 'investigando', 'debatida', 'pendiente', 'aplazada', 'cubierta', 'descartada', 'sin_propuesta'];
    bars($('ov-states'), order.filter((k) => ov.sources_by_state[k]).map((k) => [k, ov.sources_by_state[k], STATE_LABEL[k]]),
      (k) => { $('f-state').value = k; state.page = 0; show('history'); });
    bars($('ov-targets'), ov.targets.slice(0, 14).map((t) => [t.target, t.proposals, appName(t.target)]),
      (k) => { $('f-target').value = k; state.page = 0; show('history'); });
    bars($('ov-channels'), Object.entries(ov.captures_by_channel).sort((a, b) => b[1] - a[1]).map(([k, n]) => [k, n, CHANNEL_LABEL[k] || k]),
      (k) => { $('f-channel').value = k; state.page = 0; show('history'); });
    const ANC = { en_main: 'Commit en main', fuera_de_main: 'Commit fuera de main', commit_no_encontrado: 'Commit no encontrado', sin_comprobar: 'Sin poder comprobar' };
    const dv = [...Object.entries(ov.deliveries_by_implementation).map(([k, n]) => [k, n, `Declarada ${(STATE_LABEL[k] || k).toLowerCase()}`]),
      ...['en_main', 'fuera_de_main', 'commit_no_encontrado', 'sin_comprobar'].filter((k) => ov.deliveries_by_ancestry?.[k]).map((k) => [`a:${k}`, ov.deliveries_by_ancestry[k], ANC[k]])];
    bars($('ov-deliveries'), dv);
    $('ov-deliveries').insertAdjacentHTML('beforeend', `<p class="hint">${ov.deliveries_verified_at ? `Commits comprobados contra la rama principal el ${whenFull(ov.deliveries_verified_at)}.` : 'Aún no se han comprobado los commits: pulsa «Comprobar entregas».'} Un commit en main es evidencia de código, no una prueba de que funcione.</p>`);
    $('ov-imports').innerHTML = ov.imports.length ? `<table><thead><tr><th>Qué</th><th>Fichero</th><th>Entradas</th><th>Nuevas</th><th>Cuándo</th></tr></thead><tbody>${ov.imports.map((i) => `<tr><td>${esc(CHANNEL_LABEL[i.name] || i.name)}</td><td class="mono" title="sha256 ${esc(i.sha256)}">${esc(i.file)}</td><td>${i.counts?.entries ?? ''}</td><td>${i.counts?.new_captures ?? ''}</td><td>${whenFull(i.at)}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">Todavía no se ha importado nada. Pulsa «Importar histórico».</div>';
    const miss = ov.radar_missing || [];
    $('ov-missing').textContent = ov.radar?.n ? `Radar: ${ov.radar.n} números distintos, el más alto el ${ov.radar.max}.${miss.length ? ` Sin entrada en ninguna fuente: ${miss.join(', ')}.` : ''}` : '';
  } catch (e) { fail(e); }
}
$('btn-import').addEventListener('click', async () => {
  const b = $('btn-import'); b.disabled = true; b.textContent = 'Importando…';
  try { const r = await call('darwin_import_legacy', {}); toast(`Importado: ${r.counts.sources} descubrimientos, ${r.counts.captures} apariciones.`); await loadNames(); loadOverview(); }
  catch (e) { fail(e); } finally { b.disabled = false; b.textContent = 'Importar histórico'; }
});
$('btn-verify').addEventListener('click', async () => {
  const b = $('btn-verify'); b.disabled = true; b.textContent = 'Comprobando…';
  try { const r = await call('darwin_verify_deliveries'); const s = r.summary; toast(`Entregas: ${s.integrated || 0} en main, ${s.not_in_main || 0} fuera de main, ${r.checked - (s.integrated || 0) - (s.not_in_main || 0)} sin poder comprobar.`); loadOverview(); }
  catch (e) { fail(e); } finally { b.disabled = false; b.textContent = 'Comprobar entregas'; }
});
async function loadWaSettings() {
  try {
    const st = await api('/api/settings');
    if (st.whatsapp_chat && ![...$('wa-chat').options].some((o) => o.value === st.whatsapp_chat)) { const o = document.createElement('option'); o.value = st.whatsapp_chat; o.textContent = st.whatsapp_chat_name || st.whatsapp_chat; $('wa-chat').appendChild(o); }
    $('wa-chat').value = st.whatsapp_chat || '';
  } catch { /* ignore */ }
}
$('wa-find').addEventListener('click', async () => {
  try {
    const r = await call('darwin_whatsapp_chats', { query: '' });
    const sel = $('wa-chat'); sel.querySelectorAll('option:not(:first-child)').forEach((o) => o.remove());
    for (const c of r.chats) { const id = c.jid || c.id; const o = document.createElement('option'); o.value = id; o.textContent = `${c.name || c.chat_name || id}`; sel.appendChild(o); }
    const g = r.chats.find((c) => /gittrend/i.test(c.name || c.chat_name || ''));
    if (g) sel.value = g.jid || g.id;
    $('wa-status').textContent = `${r.chats.length} chats en el puente.${g ? ' Gittrend encontrado.' : ''}`;
  } catch (e) { $('wa-status').textContent = /not running|ConnectError|503/.test(e.message) ? 'El puente de WhatsApp de Faustus está parado. Arráncalo en Faustus (Herramientas → WhatsApp) y vincúlalo escaneando el QR con el móvil; después pulsa «Buscar chats».' : `No se pudo leer el puente de WhatsApp: ${e.message}`; }
});
$('wa-chat').addEventListener('change', async () => { try { await api('/api/settings', { method: 'PUT', body: { whatsapp_chat: $('wa-chat').value, whatsapp_chat_name: $('wa-chat').selectedOptions[0]?.textContent || '' } }); toast('Chat guardado.'); } catch (e) { fail(e); } });
$('wa-sync').addEventListener('click', async () => {
  const b = $('wa-sync'); b.disabled = true; b.textContent = 'Sincronizando…';
  try { const r = await call('darwin_sync_whatsapp', {}); $('wa-status').textContent = r.busy ? 'Ya hay una sincronización en marcha.' : `${r.created} mensajes nuevos, ${r.existing} ya guardados, ${r.sources} enlaces o repos. Cubre lo que guarda el puente, no todo el historial del teléfono.`; loadInbox(); }
  catch (e) { $('wa-status').textContent = e.hint ? `${e.message} ${e.hint}` : e.message; } finally { b.disabled = false; b.textContent = 'Sincronizar'; }
});

$('btn-tree-refresh').addEventListener('click', async () => {
  try { const r = await call('darwin_tree_refresh'); toast(`Árbol: ${r.nodes} nodos (${r.created} nuevos).`); await loadNames(); loadOverview(); } catch (e) { fail(e); }
});

// ------------------------------------------------------------------ history

function fillStaticFilters() {
  for (const k of ['integrada', 'mixta', 'parcial', 'aceptada', 'investigando', 'pendiente', 'aplazada', 'cubierta', 'descartada', 'sin_propuesta']) {
    const o = document.createElement('option'); o.value = k; o.textContent = STATE_LABEL[k]; $('f-state').appendChild(o);
  }
  for (const [k, l] of Object.entries(CHANNEL_LABEL)) { for (const sel of [$('f-channel'), $('in-channel')]) { const o = document.createElement('option'); o.value = k; o.textContent = l; sel.appendChild(o); } }
  const saved = JSON.parse(store('darwin.filters') || '{}');
  for (const [id, v] of Object.entries(saved)) { const el = $(id); if (!el) continue; if (el.type === 'checkbox') el.checked = !!v; else el.value = v; }
}
function saveFilters() { store('darwin.filters', JSON.stringify({ 'f-state': $('f-state').value, 'f-channel': $('f-channel').value, 'f-order': $('f-order').value, 'f-pinned': $('f-pinned').checked })); }

let qTimer = 0;
$('f-q').addEventListener('input', () => { clearTimeout(qTimer); qTimer = setTimeout(() => { state.page = 0; loadHistory(); }, 250); });
for (const id of ['f-state', 'f-target', 'f-channel', 'f-order', 'f-pinned']) $(id).addEventListener('change', () => { state.page = 0; saveFilters(); loadHistory(); });
$('pg-prev').addEventListener('click', () => { if (state.page > 0) { state.page--; loadHistory(); } });
$('pg-next').addEventListener('click', () => { state.page++; loadHistory(); });

async function loadHistory() {
  const params = new URLSearchParams({ q: $('f-q').value, state: $('f-state').value, target: $('f-target').value, channel: $('f-channel').value,
    order: $('f-order').value, limit: state.pageSize, offset: state.page * state.pageSize });
  if ($('f-pinned').checked) params.set('pinned', 'true');
  try {
    const r = await api(`/api/discoveries?${params}`);
    const pages = Math.max(1, Math.ceil(r.total / state.pageSize));
    if (state.page >= pages) { state.page = pages - 1; if (r.total) return loadHistory(); }
    $('f-count').textContent = `${r.total.toLocaleString('es-ES')} descubrimientos`;
    $('pg-info').textContent = `Página ${state.page + 1} de ${pages}`;
    $('pg-prev').disabled = state.page === 0; $('pg-next').disabled = state.page + 1 >= pages;
    const tb = $('list').querySelector('tbody');
    tb.innerHTML = r.items.map((i) => `<tr data-id="${i.id}" class="${state.selected === i.id ? 'sel' : ''}">
      <td class="num">${i.radar_no ?? ''}</td>
      <td><div class="t-title">${i.pinned ? '📌 ' : ''}${esc(i.title || i.repo || i.url)}</div><div class="t-sub">${esc(plain(i.summary || i.url || ''))}</div></td>
      <td>${chip(i.state)}${proofChip(i.proof)}${i.fitness ? `<span class="chip fit" title="${esc((i.fitness_reasons || []).join(' · '))}">${i.fitness}</span>` : ''}</td>
      <td>${i.targets.map(appChip).join('')}</td>
      <td class="num">${i.captures}</td><td class="meta">${when(i.last_seen)}</td></tr>`).join('') || '<tr><td colspan="6" class="empty">Nada con esos filtros.</td></tr>';
    tb.querySelectorAll('tr[data-id]').forEach((tr) => tr.addEventListener('click', () => openDetail(+tr.dataset.id)));
  } catch (e) { fail(e); }
}

async function openDetail(id) {
  state.selected = id;
  document.querySelectorAll('#list tr').forEach((tr) => tr.classList.toggle('sel', +tr.dataset.id === id));
  const el = $('detail');
  el.innerHTML = '<div class="empty">Cargando…</div>';
  try {
    const g = await api(`/api/discoveries/${id}`);
    const s = g.source;
    const meta = s.meta && typeof s.meta === 'object' ? s.meta : {};
    el.innerHTML = `
      <h2>${meta.pinned ? '📌 ' : ''}${esc(s.title || s.repo)}</h2>
      <div>${chip(g.state)} ${proofChip(g.proof)} ${s.kind ? `<span class="chip">${esc(s.kind)}</span>` : ''} ${s.legacy_radar_no ? `<span class="chip">radar #${s.legacy_radar_no}</span>` : ''}</div>
      <dl class="kv" style="margin-top:10px">
        ${s.url ? `<dt>Enlace</dt><dd><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a></dd>` : ''}
        ${s.stars ? `<dt>Estrellas</dt><dd>${esc(s.stars)}</dd>` : ''}
        <dt>Primera vez</dt><dd>${whenFull(s.first_seen)}</dd><dt>Última vez</dt><dd>${whenFull(s.last_seen)}</dd>
        <dt>Clave</dt><dd class="mono">${esc(s.key)}</dd>${g.aliases.length ? `<dt>Alias</dt><dd class="mono">${g.aliases.map(esc).join(', ')}</dd>` : ''}
      </dl>
      ${s.summary ? `<p class="t-sub" style="-webkit-line-clamp:unset">${esc(plain(s.summary))}</p>` : ''}
      ${g.fitness && g.fitness.score ? `<p class="meta">Puntuación ${g.fitness.score}/100: ${esc(g.fitness.reasons.join(' · '))}</p>` : ''}
      ${meta.triage ? `<p class="meta">Triaje automático: ${meta.triage.app ? `propuesto para ${esc(appName(meta.triage.app))}` : (meta.triage.useful === false ? 'parece ruido' : 'ninguna app encaja')} — ${esc(meta.triage.reason || '')}</p>` : ''}
      <h4>Propuestas (${g.proposals.length})</h4>
      ${g.proposals.map((p) => `<div class="item"><div class="head">${p.target ? appChip(p.target) : '<span class="chip">sin app</span>'}${chip(p.state)}
          <span class="meta">${esc(CHANNEL_LABEL[p.origin] || p.origin || '')}${p.agora_task ? ` · Ágora ${esc(p.agora_space)} #${p.agora_task}` : ''}</span></div>
        ${p.reason ? `<div class="body">${esc(p.reason)}</div>` : ''}
        ${p.history.length ? `<div class="hist">${p.history.map((h) => `${whenFull(h.at)}: ${esc(STATE_LABEL[h.old] || h.old)} → ${esc(STATE_LABEL[h.new] || h.new)}${h.note ? ` (${esc(h.note)})` : ''}`).join('<br>')}</div>` : ''}
        <div class="inline-form"><select data-pid="${p.id}">${PROPOSAL_STATES.map((k) => `<option value="${k}" ${k === p.state ? 'selected' : ''}>${STATE_LABEL[k]}</option>`).join('')}</select>
          <input data-note="${p.id}" placeholder="Motivo del cambio"><button class="btn small" data-save="${p.id}">Cambiar</button></div>
        <div class="debate" data-debate="${p.id}">${p.agora_thread ? `<button class="btn small" data-thread="${p.id}">Ver debate (Ágora #${p.agora_thread})</button>` : `<button class="btn small" data-discuss="${p.id}">Debatir en el Ágora</button>`}</div></div>`).join('') || '<div class="empty">Sin propuestas.</div>'}
      <div class="inline-form"><select id="new-target"><option value="">Proponer para…</option>${Object.keys(state.names).sort((a, b) => appName(a).localeCompare(appName(b))).map((a) => `<option value="${esc(a)}">${esc(appName(a))}</option>`).join('')}</select>
        <input id="new-reason" placeholder="Por qué"><button class="btn small" id="new-propose">Proponer</button></div>
      <h4>Entregas (${g.deliveries.length})</h4>
      ${g.deliveries.map((d) => `<div class="item"><div class="head">${appChip(d.target)}${chip(d.implementation)}<span class="chip">${esc(VERIF_LABEL[d.verification] || d.verification)}</span>
          <span class="meta">${esc(RELATION_LABEL[d.relation] || d.relation)}</span></div>
        <div class="prov">${d.repo ? esc(d.repo) + ' ' : ''}${d.commit_sha ? esc(d.commit_sha) : 'sin commit'}${d.agora_task ? ` · Ágora ${esc(d.agora_space)} #${d.agora_task}` : ''}</div>
        ${ancestry(d)}
        ${d.declared?.what ? `<div class="body">${esc(d.declared.what)}</div>` : ''}</div>`).join('') || '<div class="empty">Nada entregado todavía.</div>'}
      <h4>Apariciones (${g.captures.length})</h4>
      ${g.captures.map((c) => `<div class="item"><div class="head"><span class="chip">${esc(CHANNEL_LABEL[c.channel] || c.channel)}</span><span class="meta">${whenFull(c.at)}${c.author ? ' · ' + esc(c.author) : ''}</span></div>
        <div class="body">${esc((c.text || '').slice(0, 600))}</div>
        <div class="prov">${c.provenance?.file ? `${esc(c.provenance.file)}:${c.provenance.line}` : ''}${c.provenance?.task ? `Ágora ${esc(c.provenance.space)} #${c.provenance.task}` : ''}${c.provenance?.file_sha256 ? ` · sha256 ${esc(c.provenance.file_sha256.slice(0, 12))}…` : ''}</div></div>`).join('')}`;
    el.querySelectorAll('[data-discuss]').forEach((btn) => btn.addEventListener('click', () => discussProposal(+btn.dataset.discuss, true)));
    el.querySelectorAll('[data-thread]').forEach((btn) => btn.addEventListener('click', () => discussProposal(+btn.dataset.thread, false)));
    el.querySelectorAll('[data-save]').forEach((b) => b.addEventListener('click', async () => {
      const pid = +b.dataset.save;
      try { await call('darwin_set_state', { entity: 'proposals', id: pid, field: 'state', value: el.querySelector(`[data-pid="${pid}"]`).value, note: el.querySelector(`[data-note="${pid}"]`).value, by: 'luis' }); toast('Estado cambiado.'); openDetail(id); loadHistory(); }
      catch (e) { fail(e); }
    }));
    $('new-propose').addEventListener('click', async () => {
      const target = $('new-target').value; if (!target) return toast('Elige la app.', 'err');
      try { await call('darwin_propose', { source_id: id, target, reason: $('new-reason').value }); toast('Propuesta guardada.'); openDetail(id); loadHistory(); } catch (e) { fail(e); }
    });
  } catch (e) { fail(e); el.innerHTML = '<div class="empty">No se pudo cargar.</div>'; }
}

function ancestry(d) {
  const a = d.evidence?.commit_ancestry;
  if (!a) return '';
  const label = { integrated: `en ${esc(a.branch)} (${esc((a.commit || '').slice(0, 10))})`, not_in_main: `no está en ${esc(a.branch)}`, unknown: esc(({ repository_not_mapped: 'repositorio sin mapear', commit_not_found: 'commit no encontrado', invalid_commit_id: 'sin id de commit', main_branch_not_found: 'sin rama principal', repository_unavailable: 'repositorio no disponible' })[a.reason] || a.reason || 'sin comprobar') }[a.status];
  return `<div class="hist">Comprobación de commit: ${label}</div>`;
}

// ------------------------------------------------------------------ inbox

async function loadInbox() {
  try {
    const r = await api(`/api/inbox?channel=${encodeURIComponent($('in-channel').value)}&limit=200`);
    $('in-count').textContent = `${r.total} capturas sin fuente`;
    $('inbox-badge').hidden = !r.total; $('inbox-badge').textContent = r.total;
    $('inbox').innerHTML = r.items.map((c) => {
      const ocr = (c.declared && c.declared.ocr) || null;
      const img = c.attachment && /\.(jpe?g|png|webp|gif|bmp)"?$/i.test(c.attachment);
      const read = ocr ? (ocr.error ? `<div class="prov">No se pudo leer: ${esc(ocr.error)}</div>`
        : `<details class="ocr"><summary>Leída: ${ocr.refs && ocr.refs.length ? 'enlaces encontrados' : 'sin repos ni enlaces reconocibles'}${ocr.unverified && ocr.unverified.length ? ` · sin confirmar: ${esc(ocr.unverified.join(', '))}` : ''}</summary><pre>${esc(ocr.text || '(sin texto)')}</pre></details>`)
        : (img ? '<div class="prov">Pendiente de leer</div>' : '');
      return `<div class="card inbox-card"><div class="head"><span class="chip">${esc(CHANNEL_LABEL[c.channel] || c.channel)}</span><span class="meta">${whenFull(c.at)}${c.author ? ' · ' + esc(c.author) : ''}</span></div>
      ${img ? `<a href="/api/captures/${c.id}/media" target="_blank" rel="noopener"><img class="thumb" loading="lazy" src="/api/captures/${c.id}/media" alt="Captura"></a>` : ''}
      ${c.text ? `<p>${esc(c.text)}</p>` : (img ? '' : '<p>(sin texto)</p>')}${read}
      <div class="inline-form"><input data-cap="${c.id}" placeholder="URL u owner/repo de esta captura"><button class="btn small" data-link="${c.id}">Convertir en descubrimiento</button></div></div>`;
    }).join('') || '<div class="empty">Nada pendiente.</div>';
    $('inbox').querySelectorAll('[data-link]').forEach((b) => b.addEventListener('click', async () => {
      const cap = r.items.find((c) => c.id === +b.dataset.link);
      const ref = $('inbox').querySelector(`[data-cap="${b.dataset.link}"]`).value.trim();
      try { await call('darwin_add', { text: ref ? `${ref}\n${cap.text || ''}` : (cap.text || ''), channel: 'manual', author: 'luis', note: `Desde la bandeja (${cap.channel})` }); toast('Convertido en descubrimiento.'); loadInbox(); } catch (e) { fail(e); }
    }));
  } catch (e) { fail(e); }
  ocrStatus();
}

let ocrTimer = null;
function ocrText(j) {
  if (j.running) return j.total ? `Leyendo capturas… ${j.done}/${j.total}` : 'Leyendo capturas…';
  if (j.error) return `OCR detenido: ${j.error}`;
  if (j.finished) return `Última lectura: ${j.read || 0} capturas, ${j.linked || 0} con repos o enlaces${j.missing ? `, ${j.missing} sin imagen` : ''}.`;
  return '';
}
async function ocrStatus() {
  try {
    const j = await api('/api/inbox/ocr');
    $('in-ocr-status').textContent = ocrText(j);
    $('in-ocr').disabled = !!j.running;
    clearTimeout(ocrTimer);
    if (j.running) ocrTimer = setTimeout(async () => { const k = await api('/api/inbox/ocr'); if (!k.running) loadInbox(); else ocrStatus(); }, 2000);
  } catch (e) { /* the inbox still works without it */ }
}
$('in-ocr').addEventListener('click', async () => {
  try { await api('/api/inbox/ocr', { method: 'POST' }); ocrStatus(); } catch (e) { fail(e); }
});
$('in-channel').addEventListener('change', loadInbox);

// ------------------------------------------------------------------ tree

function nodeRow(n) {
  const li = document.createElement('li');
  const kids = n.children_count || 0;
  const disc = n.discoveries ? Object.values(n.discoveries).reduce((a, b) => a + b, 0) : 0;
  li.innerHTML = `<div class="node lv-${n.level}" data-key="${esc(n.key)}"><span class="twisty">${kids ? '▸' : '·'}</span>
    <span class="nm op-${esc(n.operation)}" title="${esc(n.detail || '')}">${esc(n.name)}</span><span class="lvl">${LEVEL_LABEL[n.level] || n.level}</span>
    <span class="ev ${esc(n.evidence)}">${esc(n.evidence)}</span>
    <span class="counts">${kids ? `${kids} ramas` : ''}${disc ? ` · ${disc} propuestas` : ''}</span></div>`;
  const row = li.firstElementChild;
  row.addEventListener('click', () => { toggleNode(li, n); selectNode(n); });
  return li;
}
async function toggleNode(li, n) {
  const sub = li.querySelector(':scope > ul');
  const tw = li.querySelector('.twisty');
  if (sub) { sub.remove(); tw.textContent = '▸'; return; }
  if (!n.children_count) return;
  try {
    const t = await api(`/api/tree?root=${encodeURIComponent(n.key)}&depth=1&tools=${$('t-tools').checked}`);
    const ul = document.createElement('ul');
    (t.tree.children || []).forEach((c) => ul.appendChild(nodeRow(c)));
    li.appendChild(ul); tw.textContent = '▾';
  } catch (e) { fail(e); }
}
async function selectNode(n) {
  state.treeSel = n.key;
  document.querySelectorAll('.node').forEach((el) => el.classList.toggle('sel', el.dataset.key === n.key));
  const el = $('node-detail');
  try {
    const t = await api(`/api/tree?root=${encodeURIComponent(n.key)}&depth=1&tools=true`);
    const node = t.tree;
    const isApp = ['app', 'module', 'hub', 'root'].includes(node.level);
    let disc = '';
    if (node.app_id && isApp) {
      const r = await api(`/api/discoveries?target=${encodeURIComponent(node.app_id)}&limit=40&order=recent`);
      disc = `<h4>Descubrimientos para ${esc(node.name)} (${r.total})</h4>` + (r.items.map((i) => `<div class="item" data-open="${i.id}" style="cursor:pointer"><div class="head">${chip(i.state)}<b>${esc(i.title || i.repo)}</b>${i.radar_no ? `<span class="meta">#${i.radar_no}</span>` : ''}</div></div>`).join('') || '<div class="empty">Ninguno.</div>');
    }
    const caps = (node.children || []).filter((c) => c.level === 'capability');
    const tools = (node.children || []).filter((c) => c.level === 'tool');
    const mods = (node.children || []).filter((c) => ['app', 'module'].includes(c.level));
    el.innerHTML = `<div class="meta">${t.path.map((p) => esc(p.name)).join(' › ')}</div><h2>${esc(node.name)}</h2>
      <div><span class="chip">${LEVEL_LABEL[node.level]}</span><span class="chip op-${esc(node.operation)}">${esc(node.operation)}</span><span class="chip">evidencia ${esc(node.evidence)}</span></div>
      ${node.detail ? `<p>${esc(node.detail)}</p>` : ''}
      ${node.backed ? `<p><span class="chip st-integrada">implementada, con prueba</span> ${evidenceHtml(node.backing_evidence)}</p>` : (['capability', 'tool'].includes(node.level) ? '<p class="hint">Sin prueba registrada: el nombre no demuestra que funcione.</p>' : '')}
      <dl class="kv"><dt>Visto desde</dt><dd>${whenFull(node.since)}</dd><dt>Última vez</dt><dd>${whenFull(node.seen)}</dd>${node.discoveries && Object.keys(node.discoveries).length ? `<dt>Propuestas</dt><dd>${Object.entries(node.discoveries).map(([k, v]) => `${esc(STATE_LABEL[k] || k)}: ${v}`).join(' · ')}</dd>` : ''}</dl>
      ${mods.length ? `<h4>Hoards y módulos (${mods.length})</h4>${mods.map((c) => `<span class="chip op-${esc(c.operation)}">${esc(c.name)}</span>`).join('')}` : ''}
      ${caps.length ? `<h4>Capacidades (${caps.length})</h4>${caps.map((c) => `<span class="chip" title="${esc(c.detail || '')}">${esc(c.name)}</span>`).join('')}` : ''}
      ${tools.length ? `<h4>Herramientas que ve Faustus (${tools.length})</h4>${tools.map((c) => `<div class="item"><div class="head"><code>${esc(c.name)}</code><span class="ev ${esc(c.evidence)}">${esc(c.evidence)}</span></div>${c.detail ? `<div class="body">${esc(c.detail)}</div>` : ''}</div>`).join('')}` : ''}
      ${disc}`;
    el.querySelectorAll('[data-open]').forEach((d) => d.addEventListener('click', () => { show('history'); openDetail(+d.dataset.open); }));
  } catch (e) { fail(e); }
}
async function loadTree() {
  try {
    const t = await api(`/api/tree?root=faustus&depth=1&tools=${$('t-tools').checked}`);
    const ul = $('tree'); ul.innerHTML = '';
    const li = nodeRow(t.tree); ul.appendChild(li);
    const sub = document.createElement('ul'); (t.tree.children || []).forEach((c) => sub.appendChild(nodeRow(c)));
    li.appendChild(sub); li.querySelector('.twisty').textContent = '▾';
    $('tree-meta').textContent = t.refreshed_at ? `Árbol actualizado ${whenFull(t.refreshed_at)}` : '';
    const hub = sub.querySelector('[data-key="hoardhub"]');
    if (hub) hub.click();
  } catch (e) { fail(e); }
}
$('t-tools').addEventListener('change', loadTree);
$('cap-find').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const q = $('cap-q').value.trim(); if (!q) { $('cap-results').innerHTML = ''; return; }
  try {
    const r = await api(`/api/capabilities/find?q=${encodeURIComponent(q)}`);
    $('cap-results').innerHTML = `<div class="meta" style="padding:4px 12px">${r.apps.length} apps para «${esc(q)}» (busca también: ${esc((r.terms || []).join(', '))})</div>` +
      r.apps.map((a) => `<div class="cap-hit"><div class="head"><b class="op-${esc(a.node?.operation || 'desconocida')}">${esc(a.node?.name || a.app_id)}</b> <span class="path">${esc(a.path.join(' › '))}</span>
        <button class="btn small" data-node="${esc(a.node?.key || '')}" style="float:right">Ver</button></div>
        <div>${a.matches.map((m) => `<span class="chip" title="${esc(m.detail)}">${m.level === 'tool' ? '🔧 ' : ''}${esc(m.name)}</span>`).join('')}</div></div>`).join('');
    $('cap-results').querySelectorAll('[data-node]').forEach((b) => b.addEventListener('click', () => selectNode({ key: b.dataset.node })));
  } catch (e) { fail(e); }
});

// ------------------------------------------------------------------ changes

function sinceValue() {
  const v = $('changes-range').value;
  if (v === 'visit') return +(store('darwin.lastVisit') || 0) || (Date.now() / 1000 - 7 * 86400);
  return Date.now() / 1000 - (+v) * 86400;
}
async function loadChanges() {
  const since = sinceValue();
  $('changes-since').textContent = `Desde ${whenFull(since)}`;
  try {
    const r = await api(`/api/changes?since=${since}`);
    const block = (title, rows, fn) => `<div class="card"><h3>${title} (${rows.length})</h3>${rows.map(fn).join('') || '<div class="empty">Nada.</div>'}</div>`;
    $('changes').innerHTML = block('Descubrimientos nuevos', r.new_sources, (s) => `<div class="item" data-open="${s.id}" style="cursor:pointer"><b>${esc(s.title)}</b> <span class="meta">${s.legacy_radar_no ? '#' + s.legacy_radar_no + ' · ' : ''}${whenFull(s.created)}</span></div>`)
      + block('Cambios de estado', r.state_changes, (h) => `<div class="item"><span class="meta">${whenFull(h.at)}</span> ${esc(h.entity)} ${h.entity_id}: ${esc(STATE_LABEL[h.old] || h.old)} → ${esc(STATE_LABEL[h.new] || h.new)} ${h.note ? `<span class="meta">(${esc(h.note)})</span>` : ''}</div>`)
      + block('Entregas nuevas', r.new_deliveries, (d) => `<div class="item">${appChip(d.target)}${chip(d.implementation)} <span class="mono">${esc(d.commit_sha || '')}</span></div>`)
      + block('Apariciones nuevas', r.new_captures.slice(0, 80), (c) => `<div class="item"><span class="chip">${esc(CHANNEL_LABEL[c.channel] || c.channel)}</span> ${esc(c.text)}</div>`);
    $('changes').querySelectorAll('[data-open]').forEach((d) => d.addEventListener('click', () => { show('history'); openDetail(+d.dataset.open); }));
  } catch (e) { fail(e); }
}
$('changes-range').addEventListener('change', loadChanges);
$('btn-mark-seen').addEventListener('click', () => { store('darwin.lastVisit', String(Date.now() / 1000)); $('changes-badge').hidden = true; loadChanges(); });
async function updateBadge() {
  const last = +(store('darwin.lastVisit') || 0);
  if (!last) return;
  try { const r = await api(`/api/changes?since=${last}`); const n = r.new_sources.length + r.new_deliveries.length; $('changes-badge').hidden = !n; $('changes-badge').textContent = n; } catch { /* ignore */ }
}

// ------------------------------------------------------------------ gaps

async function loadGaps() {
  try {
    const r = await call('darwin_gaps');
    const stale = r.gaps.filter((g) => g.possibly_stale && g.state === 'abierta');
    $('gaps-stale').innerHTML = stale.length ? `<div class="card"><div class="card-head"><h3>Posiblemente obsoletas (${stale.length})</h3>
      <div class="actions"><button class="btn small" id="gaps-recheck" type="button">Reconciliar</button></div></div>
      <p class="hint">El árbol marca como implementada, con prueba, una capacidad que estas carencias nombran. Siguen abiertas hasta que las confirmes; no cuentan como pendientes.</p>
      ${stale.map((g) => `<div class="item"><div class="head"><b>${esc(g.title)}</b><span class="chip st-parcial">posiblemente obsoleta</span></div>
        <div class="body">Capacidad: <code>${esc(g.possibly_stale.capability_name)}</code> ${evidenceHtml(g.possibly_stale.evidence)}</div>
        <div class="actions"><button class="btn small" data-confirm="${g.id}" type="button">Confirmar: ya está resuelta</button><button class="btn small ghost" data-dismiss="${g.id}" type="button">No es lo mismo</button></div></div>`).join('')}</div>`
      : `<p class="hint" style="margin:0 0 10px">${r.open} carencias abiertas. <button class="btn small ghost" id="gaps-recheck" type="button">Reconciliar con el árbol</button></p>`;
    $('gaps-recheck')?.addEventListener('click', async () => { try { const x = await call('darwin_gaps_reconcile', { by: 'luis' }); toast(`${x.stale_count} posiblemente obsoletas, ${x.open} abiertas.`); loadGaps(); } catch (e) { fail(e); } });
    document.querySelectorAll('[data-confirm]').forEach((b) => b.addEventListener('click', async () => { try { await call('darwin_gaps_reconcile', { confirm_ids: [+b.dataset.confirm], by: 'luis' }); loadGaps(); } catch (e) { fail(e); } }));
    document.querySelectorAll('[data-dismiss]').forEach((b) => b.addEventListener('click', async () => { try { await call('darwin_gaps_reconcile', { dismiss_ids: [+b.dataset.dismiss], by: 'luis' }); loadGaps(); } catch (e) { fail(e); } }));
    $('gaps-badge').hidden = !stale.length; $('gaps-badge').textContent = stale.length;
    $('gaps').innerHTML = r.gaps.filter((g) => !(g.possibly_stale && g.state === 'abierta')).map((g) => `<div class="card"><div class="card-head"><h3 style="text-transform:none;font-size:15px;color:var(--hoard-text)">${esc(g.title)}</h3>${chip(g.state === 'abierta' ? 'pendiente' : 'integrada', g.state)}</div>
      ${g.detail ? `<p>${esc(g.detail)}</p>` : ''}<div class="meta">${g.target ? 'Para ' + esc(appName(g.target)) + ' · ' : ''}${whenFull(g.created)}${g.watch?.condition ? ' · Se podrá cuando: ' + esc(g.watch.condition) : ''}</div></div>`).join('') || '<div class="empty">No hay carencias apuntadas. Apunta aquí lo que quieres poder hacer y ninguna app hace: el radar buscará contra esto.</div>'
  } catch (e) { fail(e); }
}
$('gap-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  try { await call('darwin_gap_add', { title: $('gap-title').value, detail: $('gap-detail').value, target: $('gap-target').value, watch: $('gap-watch').value }); ev.target.reset(); toast('Carencia guardada.'); loadGaps(); } catch (e) { fail(e); }
});

// ------------------------------------------------------------------ suits (trajes)

async function loadSuits() {
  try {
    const r = await api(`/api/suits?status=${encodeURIComponent($('su-status').value)}`);
    $('su-count').textContent = Object.entries(r.counts).map(([k, n]) => `${SUIT_STATUS[k][0]}: ${n}`).join(' · ');
    $('su-list').querySelector('tbody').innerHTML = r.suits.map((s) => `<tr data-slug="${esc(s.slug)}" class="${state.suit === s.slug ? 'sel' : ''}"><td><b>${esc(s.name)}</b><div class="meta">${esc(s.slug)}</div></td>
      <td>${chip(SUIT_STATUS[s.status][1].replace('st-', ''), SUIT_STATUS[s.status][0])}</td><td class="num">${s.backed}/${s.required}</td>
      <td class="meta">${s.missing.length ? 'sin capacidad: ' + esc(s.missing.join(', ')) : ''}${s.unproven.length ? `${s.missing.length ? ' · ' : ''}sin prueba: ${esc(s.unproven.join(', '))}` : ''}</td></tr>`).join('')
      || '<tr><td colspan="4" class="empty">No hay trajes con ese estado.</td></tr>';
    $('su-list').querySelectorAll('tr[data-slug]').forEach((tr) => tr.addEventListener('click', () => openSuit(tr.dataset.slug)));
  } catch (e) { fail(e); }
}
$('su-status').addEventListener('change', loadSuits);
const list = (items, fn) => (items || []).length ? `<ul class="plain">${items.map((i) => `<li>${fn(i)}</li>`).join('')}</ul>` : '<p class="hint">—</p>';

async function openSuit(slug) {
  state.suit = slug;
  document.querySelectorAll('#su-list tr[data-slug]').forEach((tr) => tr.classList.toggle('sel', tr.dataset.slug === slug));
  const el = $('su-detail');
  try {
    const s = await api(`/api/suits/${encodeURIComponent(slug)}`);
    const st = s.state;
    const ev = s.evaluation;
    const arms = ev?.payload?.aggregate || {};
    el.innerHTML = `<h2>${esc(s.name)}</h2><div>${chip(SUIT_STATUS[s.status][1].replace('st-', ''), SUIT_STATUS[s.status][0])}<span class="chip">${st.backed}/${st.required} operaciones con prueba</span>${s.proposal || s.origin ? `<span class="chip">${esc(s.proposal || s.origin)}</span>` : ''}</div>
      <p>${esc(s.objective)}</p>
      <h4>Operaciones y herramientas</h4>
      ${list(st.operations, (o) => `<b>${esc(o.name)}</b> ${chip(OP_STATE[o.state][1].replace('st-', ''), OP_STATE[o.state][0])}${o.required ? '' : ' <span class="meta">(opcional)</span>'}
        ${o.node ? `<div class="meta">${esc(o.node.name)} · <code>${esc(o.capability_key)}</code> · ${esc(o.node.operation)}</div>` : (o.capability_key ? `<div class="meta">«${esc(o.capability_key)}» no está en el árbol</div>` : '')}
        ${o.evidence?.length ? `<div>${evidenceHtml(o.evidence)}</div>` : ''}${o.missing_reason ? `<div class="meta">${esc(o.missing_reason)}</div>` : ''}${o.note ? `<div class="meta">${esc(o.note)}</div>` : ''}`)}
      <h4>Entradas e identidad</h4>${list(s.inputs, (i) => `<b>${esc(i.name)}</b> <span class="meta">${esc(i.kind || '')} · identificada por: ${esc(i.identity || '—')}</span>`)}
      <h4>Conceptos del dominio</h4>${list(s.concepts, (c) => `<b>${esc(c.term)}</b>: ${esc(c.meaning || '')}`)}
      <h4>Vistas para inspeccionar</h4>${list(s.views, (v) => `<b>${esc(v.name)}</b>: ${esc(v.shows || '')}`)}
      <h4>Criterios de aceptación</h4>${list(s.acceptance, (a) => `<b>${esc(a.id)}</b> <span class="chip">${a.kind === 'judge' ? 'juicio de modelo' : 'ejecutable'}</span> ${esc(a.check || '')}`)}
      <h4>Receta de ejecución</h4>${list(s.recipe, (r) => `${esc(r.step)}${r.op ? ` <span class="meta">(${esc(r.op)})</span>` : ''}`)}
      <h4>Dónde hace falta juicio del modelo</h4>${list(s.judgement, (j) => `<b>${esc(j.point)}</b> <span class="meta">${esc(j.why || '')}</span>`)}
      <h4>Evaluación</h4>${ev ? `<p>Importada ${whenFull(ev.imported)} (${esc(ev.eval_id)}). Casos puntuados: ${ev.cases_scored}. Respaldo al importar: ${esc(ev.backing_at_import?.backing || '—')}${ev.backing_at_import?.missing?.length ? ' (faltaba: ' + esc(ev.backing_at_import.missing.join(', ')) + ')' : ''}.</p>
        ${ev.excluded.length ? `<p class="meta">Excluidos de la puntuación por haberse usado para construir la mejora: ${esc(ev.excluded.map((e) => e.case).join(', '))}.</p>` : ''}
        <div class="table-wrap"><table><thead><tr><th>Brazo</th><th class="num">Casos</th><th class="num">Éxito</th></tr></thead><tbody>${Object.entries(arms).map(([a, v]) => `<tr><td>${esc(a)}</td><td class="num">${v.cases}</td><td class="num">${v.success_rate == null ? '—' : (100 * v.success_rate).toFixed(0) + ' %'}</td></tr>`).join('')}</tbody></table></div>`
        : '<p class="hint">Sin evaluación. Se define y se ejecuta en Pygmalion\'s Hoard y sus resultados se importan aquí.</p>'}`;
  } catch (e) { fail(e); }
}

// ------------------------------------------------------------------ add

$('quick-add').addEventListener('submit', (ev) => { ev.preventDefault(); $('add-full').value = $('add-text').value; $('add-result').innerHTML = ''; $('add-dialog').showModal(); });
$('add-save').addEventListener('click', async (ev) => {
  ev.preventDefault();
  const text = $('add-full').value.trim(); if (!text) return;
  try {
    const r = await call('darwin_add', { text, target: $('add-target').value, note: $('add-note').value, channel: 'manual', author: 'luis' });
    $('add-result').innerHTML = r.sources.map((s) => `<div class="item"><div class="head">${s.existing ? '<span class="chip st-cubierta">Ya estaba</span>' : '<span class="chip st-aceptada">Nuevo</span>'}${s.candidate ? '<span class="chip">sin verificar</span>' : ''}${chip(s.state)}
      <a href="#" data-open="${s.source.id}">${esc(s.source.title || s.source.repo)}</a></div>${s.existing && s.proposals?.length ? `<div class="body">${s.proposals.map((p) => `${esc(appName(p.target || '?'))}: ${esc(STATE_LABEL[p.state] || p.state)}`).join(' · ')}</div>` : ''}</div>`).join('');
    $('add-result').querySelectorAll('[data-open]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); $('add-dialog').close(); show('history'); openDetail(+a.dataset.open); }));
    $('add-text').value = '';
  } catch (e) { fail(e); }
});

// ------------------------------------------------------------------ start

fillStaticFilters();
loadWaSettings();
api('/api/inbox?limit=1').then((r) => { $('inbox-badge').hidden = !r.total; $('inbox-badge').textContent = r.total; }).catch(() => {});
call('darwin_gaps').then((r) => { const n = r.possibly_stale; $('gaps-badge').hidden = !n; $('gaps-badge').textContent = n; }).catch(() => {});
loadNames().catch(fail).finally(() => { show((location.hash || '#overview').slice(1)); updateBadge(); });
if (!store('darwin.lastVisit')) store('darwin.lastVisit', String(Date.now() / 1000));


// ------------------------------------------------------------------ ask

function linkCites(text, ids) {
  return esc(text).replace(/\[#(\d+)\]/g, (m, n) => `<a href="#" data-open="${n}">[#${n}]</a>`);
}
$('ask-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const q = $('ask-q').value.trim();
  if (q.length < 3) return;
  const out = $('ask-out');
  $('ask-go').disabled = true;
  out.innerHTML = '<p class="meta">Buscando en el árbol y el historial y preguntando al modelo local…</p>';
  try {
    const r = await call('darwin_ask', { question: q });
    const apps = (r.apps || []).map((a) => appChip(a.app_id)).join(' ');
    const disc = (r.discoveries || []).slice(0, 8).map((d) => `<li><a href="#" data-open="${d.id}">#${d.id} ${esc(d.title || '')}</a> ${chip(d.state)}</li>`).join('');
    out.innerHTML = `${r.answer ? `<div class="ask-answer">${linkCites(r.answer).replace(/\n/g, '<br>')}</div>` : `<p class="meta">${esc(r.note || 'Sin respuesta del modelo.')}</p>`}
      ${apps ? `<div class="ask-row"><span class="meta">Apps que lo cubren:</span> ${apps}</div>` : ''}
      ${disc ? `<details class="ask-row"${r.answer ? '' : ' open'}><summary class="meta">Descubrimientos relacionados (${r.discoveries.length})</summary><ul>${disc}</ul></details>` : ''}
      ${r.model ? `<div class="meta">Modelo: ${esc(r.model)}</div>` : ''}`;
    out.querySelectorAll('[data-open]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); show('history'); openDetail(+a.dataset.open); }));
  } catch (e) { out.innerHTML = ''; fail(e); } finally { $('ask-go').disabled = false; }
});


// ------------------------------------------------------------------ triage

let triageTimer = null;
function triageText(j) {
  if (j.running) return j.total ? `Proponiendo apps… ${j.done}/${j.total}` : 'Proponiendo apps…';
  if (j.error) return `Triaje detenido: ${j.error}`;
  if (j.finished) return `Último triaje: ${(j.proposed || []).length} propuestas, ${j.skipped || 0} sin app, ${j.noise || 0} ruido.`;
  return '';
}
async function triageStatus() {
  try {
    const j = await api('/api/triage');
    $('f-triage-status').textContent = triageText(j);
    $('f-triage').disabled = !!j.running;
    clearTimeout(triageTimer);
    if (j.running) triageTimer = setTimeout(async () => { const k = await api('/api/triage'); if (!k.running) { loadHistory(); triageStatus(); } else triageStatus(); }, 3000);
  } catch (e) { /* optional */ }
}
$('f-triage').addEventListener('click', async () => {
  try { await api(`/api/triage?channel=${encodeURIComponent($('f-channel').value)}&limit=100`, { method: 'POST' }); triageStatus(); } catch (e) { fail(e); }
});
triageStatus();


// ------------------------------------------------------------------ debate in the Ágora

function renderThread(box, pid, r) {
  const msgs = (r.messages || []).map((m) => `<div class="msg"><span class="meta">${esc(m.by || '?')} · ${esc(m.kind || '')}${m.at ? ' · ' + whenFull(m.at) : ''}</span><div>${esc(m.body || '').replace(/\n/g, '<br>')}</div></div>`).join('');
  box.innerHTML = `<div class="thread"><div class="meta">Ágora · ${esc(r.thread?.space || 'darwin')} · hilo #${r.thread?.id}${r.thread?.status ? ' · ' + esc(r.thread.status) : ''}${r.error ? ' · ' + esc(r.error) : ''}</div>${msgs || '<div class="meta">Sin mensajes todavía.</div>'}
    <div class="inline-form"><input data-reply="${pid}" placeholder="Tu nota (la publica Darwin en tu nombre)"><button class="btn small" data-send="${pid}">Añadir al debate</button></div></div>`;
  box.querySelector('[data-send]').addEventListener('click', async () => {
    const note = box.querySelector('[data-reply]').value.trim(); if (!note) return;
    try { renderThread(box, pid, await call('darwin_discuss', { proposal_id: pid, note })); toast('Nota añadida al debate.'); } catch (e) { fail(e); }
  });
}
async function discussProposal(pid, open) {
  const box = document.querySelector(`[data-debate="${pid}"]`);
  box.innerHTML = '<span class="meta">Cargando el debate…</span>';
  try { renderThread(box, pid, open ? await call('darwin_discuss', { proposal_id: pid }) : await api(`/api/proposals/${pid}/thread`)); }
  catch (e) { box.innerHTML = ''; fail(e); }
}


// ------------------------------------------------------------------ accounts and posts

const ACC_LABEL = { x: 'X', instagram: 'Instagram', threads: 'Threads', tiktok: 'TikTok', reddit: 'Reddit', facebook: 'Facebook', youtube: 'YouTube' };
let accTimer = null;
async function loadAccounts() {
  const box = $('acc-sites');
  try {
    const r = await api('/api/accounts');
    if (!r.ok) { box.innerHTML = `<p class="meta">Links no responde (${esc(r.error || '')}). Ábrelo desde el Hub.</p>`; return; }
    const active = r.active && r.active.open ? r.active : null;
    box.innerHTML = r.sites.map((s) => `<div class="acc"><span class="acc-name">${esc(ACC_LABEL[s.id] || s.label)}</span>
      ${s.logged_in ? `<span class="chip st-integrada">conectada</span>` : `<span class="chip">sin conectar</span>`}
      ${active && active.site === s.id ? `<span class="meta">${esc(active.detail || 'Ventana abierta')}</span><button class="btn small" data-acc-finish="${s.id}">Ya he entrado</button><button class="btn small" data-acc-cancel="${s.id}">Cancelar</button>`
        : `<button class="btn small" data-acc-login="${s.id}">${s.logged_in ? 'Volver a conectar' : 'Conectar'}</button>`}</div>`).join('');
    box.querySelectorAll('[data-acc-login]').forEach((b) => b.addEventListener('click', () => accAction(b.dataset.accLogin, '')));
    box.querySelectorAll('[data-acc-finish]').forEach((b) => b.addEventListener('click', () => accAction(b.dataset.accFinish, '?finish=true')));
    box.querySelectorAll('[data-acc-cancel]').forEach((b) => b.addEventListener('click', () => accAction(b.dataset.accCancel, '?cancel=true')));
    clearTimeout(accTimer);
    if (active) accTimer = setTimeout(loadAccounts, 3000);
  } catch (e) { box.innerHTML = `<p class="meta">${esc(e.message)}</p>`; }
}
async function accAction(site, q) {
  try { await api(`/api/accounts/${site}/login${q}`, { method: 'POST' }); if (!q) toast(`Se ha abierto una ventana para entrar en ${ACC_LABEL[site]}. Inicia sesión allí.`); loadAccounts(); } catch (e) { fail(e); }
}
let postsTimer = null;
function postsText(j) {
  if (j.running) return j.total ? `Leyendo posts… ${j.done}/${j.total}` : 'Leyendo posts…';
  if (j.login_needed) return `Para seguir, conecta ${ACC_LABEL[j.login_needed] || j.login_needed} (quedan ${j.remaining}).`;
  if (j.error) return `Lectura detenida: ${j.error}`;
  if (j.finished) return `Última lectura: ${j.read || 0} posts, ${j.linked || 0} con repos o enlaces${(j.errors || []).length ? `, ${j.errors.length} con error` : ''}.`;
  return '';
}
async function postsStatus() {
  try {
    const j = await api('/api/posts');
    $('posts-status').textContent = postsText(j);
    $('posts-read').disabled = !!j.running;
    clearTimeout(postsTimer);
    if (j.running) postsTimer = setTimeout(postsStatus, 2500); else if (j.finished && state.view === 'overview') loadAccounts();
  } catch (e) { /* optional */ }
}
$('posts-read').addEventListener('click', async () => { try { await api('/api/posts', { method: 'POST' }); postsStatus(); } catch (e) { fail(e); } });
