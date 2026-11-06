import {test} from 'node:test';import assert from 'node:assert/strict';import {filterPostings} from './filter.mjs';
const a=[{id:'a',title:'분석가',company:'가상',role:'분석',status:'published',published:'2026-01-01',expires:'2026-02-01'},{id:'b',title:'개발자',company:'예시',role:'개발',status:'closed',published:'2026-01-02',expires:'2026-01-03'}];
test('closed hidden, search and filters',()=>{assert.deepEqual(filterPostings(a).map(x=>x.id),['a']);assert.equal(filterPostings(a,{query:'없는'}).length,0);assert.deepEqual(filterPostings(a,{company:'예시',includeClosed:true}).map(x=>x.id),['b'])});
test('deadline and recent order deterministic',()=>{const b=[a[0],{...a[0],id:'c',published:'2026-01-02',expires:'2026-01-05'}];assert.deepEqual(filterPostings(b).map(x=>x.id),['c','a']);assert.deepEqual(filterPostings(b,{order:'deadline'}).map(x=>x.id),['c','a'])});
test('draft postings remain hidden even when closed are included',()=>{assert.equal(filterPostings([{...a[0],status:'draft'}],{includeClosed:true}).length,0)});

test('expired published postings are closed relative to the supplied local date',()=>{const item={...a[0],expires:'2026-02-01'};assert.deepEqual(filterPostings([item],{asOf:'2026-02-01'}).map(x=>x.id),['a']);assert.equal(filterPostings([item],{asOf:'2026-02-02'}).length,0);assert.equal(filterPostings([item],{asOf:'2026-02-02',includeClosed:true}).length,1)});

test('undated deadlines remain open and sort after dated postings',()=>{const open={...a[0],id:'open',expires:null};const dated={...a[0],id:'dated',expires:'2027-01-01'};assert.deepEqual(filterPostings([open,dated],{asOf:'2026-11-06',order:'deadline'}).map(x=>x.id),['dated','open']);});
