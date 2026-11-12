/* The delivery/skill map in Research. Uses the same product API as MCP. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const list = $('skill-impacts-list'), status = $('skill-impacts-status');
  const node = (tag, text = '') => { const e = document.createElement(tag); e.textContent = text; return e; };
  let offset = 0, data, serial = 0;
  async function request(path, body) {
    const r = await fetch(path, body ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : {});
    const value = await r.json();
    if (!r.ok || value.error) throw new Error(value.error || `HTTP ${r.status}`);
    return value;
  }
  function render() {
    list.replaceChildren();
    const q = $('skill-impacts-query').value.trim().toLocaleLowerCase();
    for (const item of data.items) {
      if (q && !JSON.stringify(item).toLocaleLowerCase().includes(q)) continue;
      const detail = node('details'); detail.className = 'item';
      detail.append(node('summary', `${item.repo} → ${item.target} · ${item.skills.length ? 'Vínculo documentado' : item.suggestions.length ? 'Sugerencias por revisar' : 'Sin skill identificada'}`));
      const source = node('a', 'Abrir descubrimiento'); source.href = item.source_url; detail.append(source);
      const shelf = node('a', 'Elegir skills de esta app'); shelf.href = item.shelf_url; shelf.target = '_blank'; shelf.rel = 'noreferrer'; shelf.style.marginInlineStart = '16px'; detail.append(shelf);
      detail.append(node('p', `${item.target_repo || item.target} · ${item.commit_sha || 'Sin commit declarado'}${item.radar_no ? ' · Radar #' + item.radar_no : ''}`));
      const output = node('pre'); output.style.cssText = 'white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;max-width:75ch'; output.hidden = true;
      for (const skill of [...item.skills, ...item.suggestions]) {
        const line = node('div'); line.className = 'item';
        line.append(node('strong', skill.slug), node('p', skill.reason));
        line.append(node('p', skill.status === 'suggested' ? 'Sugerencia por coincidencia de términos; no acredita una mejora.' :
          `${skill.available ? 'Skill publicada' : 'Skill no disponible'}${skill.source_changed ? ' · Su texto ha cambiado desde el vínculo' : ''}`));
        const read = node('button', 'Leer skill'); read.type = 'button'; read.className = 'btn small';
        read.onclick = async () => {
          try { const r = await request(skill.skill_url); output.textContent = r.text; output.hidden = false; }
          catch (error) { output.textContent = error.message; output.hidden = false; }
        };
        line.append(read);
        if (skill.status === 'documented') {
          const remove = node('button', 'Quitar vínculo'); remove.type = 'button'; remove.className = 'btn small';
          remove.onclick = async () => { remove.disabled = true; try { await request('/api/skill-impacts/link', {delivery_id: item.delivery_id, slug: skill.slug, on: false}); await load(); } catch (error) { status.textContent = error.message; remove.disabled = false; } };
          line.append(remove);
        }
        detail.append(line);
      }
      const form = node('form'); form.className = 'inline-form';
      const pick = node('select'); pick.setAttribute('aria-label', 'Skill que mejora esta entrega');
      for (const skill of data.library) { const option = node('option', skill.name); option.value = skill.slug; pick.append(option); }
      if (item.suggestions[0]) pick.value = item.suggestions[0].slug;
      const reason = node('input'); reason.placeholder = 'Qué parte de la skill mejora esta entrega'; reason.setAttribute('aria-label', reason.placeholder); reason.required = true; reason.maxLength = 2000;
      const save = node('button', 'Documentar vínculo'); save.type = 'submit'; save.className = 'btn small'; save.disabled = !data.library.length;
      form.append(pick, reason, save);
      form.onsubmit = async event => {
        event.preventDefault(); save.disabled = true;
        try { await request('/api/skill-impacts/link', {delivery_id: item.delivery_id, slug: pick.value, reason: reason.value}); await load(); }
        catch (error) { status.textContent = error.message; save.disabled = false; }
      };
      detail.append(form, output); list.append(detail);
    }
    if (!list.children.length) list.append(node('p', data.total ? 'No hay coincidencias en esta página.' : 'No hay repos con una entrega declarada integrada.'));
  }
  async function load() {
    const turn = ++serial; status.textContent = 'Consultando entregas y estanterías…';
    try {
      const result = await request(`/api/skill-impacts?limit=40&offset=${offset}`);
      if (turn !== serial) return;
      data = result; render();
      status.textContent = `${data.total} entregas · ${offset + (data.items.length ? 1 : 0)}–${offset + data.items.length}${data.library_available ? '' : ' · Biblioteca no disponible'}${data.shelves_available ? '' : ' · Estanterías del Hub no disponibles; afinidad por app'}.`;
      $('skill-impacts-prev').disabled = offset === 0;
      $('skill-impacts-next').disabled = offset + data.items.length >= data.total;
    } catch (error) { if (turn === serial) status.textContent = `${error.message}. Pulsa Actualizar vínculos para reintentar.`; }
  }
  $('skill-impacts-refresh').onclick = load;
  $('skill-impacts-query').oninput = () => { if (data) render(); };
  $('skill-impacts-prev').onclick = () => { offset = Math.max(0, offset - 40); void load(); };
  $('skill-impacts-next').onclick = () => { offset += 40; void load(); };
  document.querySelector('[data-view="research"]')?.addEventListener('click', () => { void load(); });
  window.addEventListener('hashchange', () => { if (location.hash === '#research') void load(); });
  if (location.hash === '#research') void load();
})();
