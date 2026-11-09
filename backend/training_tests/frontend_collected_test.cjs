// Execute the page script against a minimal DOM and out-of-order HTTP results.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
class Element {
  constructor(tag = '') { this.tag = tag; this.children = []; this.listeners = {}; this.value = ''; }
  append(...items) { this.children.push(...items); }
  replaceChildren() { this.children = []; }
  addEventListener(event, fn) { this.listeners[event] = fn; }
  setAttribute() {}
}
const ids = Object.fromEntries(['jobs', 'status', 'reload', 'filters', 'dataset', 'title-search', 'location-filter', 'employment-filter'].map(id => [id, new Element()]));
ids.dataset.value = 'synthetic';
const headings = {h1: new Element(), '.intro': new Element()};
const requests = [];
const apiPrefix = process.argv.includes('--staging') ? '/api' : '';
const context = vm.createContext({
  document: {getElementById: id => ids[id], createElement: tag => new Element(tag), querySelector: s => headings[s]},
  URL, URLSearchParams,
  window: {location: {pathname: apiPrefix + '/training'}},
  fetch: url => new Promise(resolve => requests.push({url, resolve})),
});
const html = fs.readFileSync('backend/training_frontend/index.html', 'utf8');
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
const tick = () => new Promise(resolve => setImmediate(resolve));
function respond(index, jobs) { requests[index].resolve({ok: true, json: async () => jobs}); }
(async () => {
  assert.ok(requests[0].url.startsWith(apiPrefix + '/jobs?'));
  ids.dataset.value = 'collected';
  ids.dataset.listeners.change();
  assert.ok(requests[1].url.startsWith(apiPrefix + '/jobs/collected?'));
  const job = {external_posting_id: '123', title: '<img onerror=bad()>', company_name: 'Example', location_text: 'Seoul', employment_type: 'intern', evidence: 'imported_html', collected_at: '2026-11-07', source_url: 'https://www.jobkorea.co.kr/Recruit/GI_Read/123'};
  respond(1, [job]); await tick();
  const card = ids.jobs.children[0];
  assert.equal(card.children.find(el => el.tag === 'h2').textContent, job.title);
  assert.equal(card.children.find(el => el.tag === 'a').href, job.source_url);
  assert.ok(card.children.some(el => String(el.textContent).includes('HTML')));
  respond(0, [{title: 'stale synthetic'}]); await tick();
  assert.equal(ids.jobs.children[0], card);
  vm.runInContext('draw([{evidence:"imported_html", source_url:"javascript:alert(1)"}])', context);
  assert.equal(ids.jobs.children[0].children.some(el => el.tag === 'a'), false);
  console.log('FRONTEND_COLLECTED_DOM=PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
