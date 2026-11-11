"""Run the page's domain handlers with its UI callbacks and a queued bridge."""
import subprocess
from pathlib import Path


def test_domain_navigation_and_changed_preserve_proposal_drafts():
    source = Path(__file__).resolve().parents[1] / "darwin_hoard/static/app.js"
    code = r'''
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8').split('// App Dock: domain navigation')[1];
const elements = new Map();
const $ = (id) => {
  if (!elements.has(id)) elements.set(id, { value: '', tagName: 'INPUT', options: [], querySelector: () => null, querySelectorAll: () => [] });
  return elements.get(id);
};
for (const id of ['f-state', 'f-target', 'f-channel']) Object.assign($(id), { tagName: 'SELECT', options: [{value:''}, {value: id === 'f-target' ? 'links' : 'pending'}] });
const state = { view: 'overview', page: 2, selected: null };
let loaded = 0, detail = 0;
const context = { window: { HoardApp: {q:[]} }, state, $, URLSearchParams,
  STATE_LABEL: { pending:'Pending' }, CHANNEL_LABEL:{ pending:'Pending' }, VIEWS:['overview','history'],
  document: { querySelector: () => null },
  show: (view) => state.view = view, saveFilters: () => {}, loadHistory: async () => loaded++, loadNames: async () => {},
  openDetail: async (id) => { state.selected=id; detail++; },
  api: async (path) => path.includes('?') ? {items:[{id:1,title:'Árbol'}, {id:2,title:'Arbol'}]} : {source:{id:1,title:'Árbol'}},
};
vm.runInNewContext('//' + source, context);
const queued = context.window.HoardApp.q;
const tools = new Map(queued.filter(([m]) => m === 'registerTool').map(([,n,d,h]) => [n,h]));
const actor = {cursor:{to:async()=>{}}};
(async () => {
  assert.equal(tools.size, 3);
  await assert.rejects(tools.get('darwin_open')({title:'árbol'}, actor), (e) => e.code === 'ambiguous');
  await tools.get('darwin_open')({id:1}, actor);
  assert.equal(state.view,'history'); assert.equal(state.selected,1);
  assert.equal(queued.find(([m])=>m==='setContext')[1]().focus.id,'1');
  await assert.rejects(tools.get('darwin_filter')({target:'missing'},actor), (e)=>e.code==='not_found');
  await tools.get('darwin_filter')({q:'example',target:'links'},actor);
  assert.equal($('f-q').value,'example'); assert.equal(state.page,0);
  context.openDetail=async(id,options)=>{assert.equal(options.preserveDrafts,true);detail++;};
  await queued.find(([m])=>m==='onChanged')[1]();
  assert.equal(loaded,1); assert.equal(detail,2);
  context.loadNames=async()=>{state.selected=2;};
  await queued.find(([m])=>m==='onChanged')[1]();
  assert.equal(state.selected,2); assert.equal(detail,2);
})().catch((e)=>{console.error(e);process.exitCode=1;});
'''
    result = subprocess.run(["node", "-e", code, str(source)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
