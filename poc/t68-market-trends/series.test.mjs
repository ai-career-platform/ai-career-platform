import {test} from 'node:test';import assert from 'node:assert/strict';import {filterSeries} from './series.mjs';
const p=[{period:'2026-02',role:'A',value:2},{period:'2026-01',role:'A',value:1},{period:'2026-01',role:'B',value:3}];
test('filters by role and interval in time order',()=>assert.deepEqual(filterSeries(p,'A','2026-01','2026-02').map(x=>x.value),[1,2]));
test('empty and reversed period',()=>{assert.deepEqual(filterSeries(p,'C','',''),[]);assert.throws(()=>filterSeries(p,'','2026-03','2026-01'),RangeError)});
