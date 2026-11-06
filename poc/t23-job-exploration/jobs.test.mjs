import {test} from 'node:test';
import assert from 'node:assert/strict';
import {filterJobs,pageJobs} from './jobs.mjs';
const jobs=[{name:'데이터 분석가',category:'데이터'}, {name:'Backend',category:'개발'}, {name:'프론트엔드',category:'개발'}];
test('name search ignores case and searches names only',()=>{assert.deepEqual(filterJobs(jobs,' BACK ').map(x=>x.name),['Backend']);assert.deepEqual(filterJobs(jobs,'개발'),[])});
test('empty and category sorting are deterministic and input is not mutated',()=>{const before=jobs.map(x=>x.name);assert.equal(filterJobs(jobs,'').length,3);assert.deepEqual(filterJobs(jobs,'','category').slice(0,2).map(x=>x.name),['프론트엔드','Backend']);assert.deepEqual(jobs.map(x=>x.name),before)});

test('pages 25 roles without losing items and clamps after filtering',()=>{const data=Array.from({length:25},(_,i)=>i);assert.deepEqual(pageJobs(data,1).items,data.slice(0,20));assert.deepEqual(pageJobs(data,2).items,data.slice(20));assert.equal(pageJobs(data.slice(0,3),2).current,1);assert.deepEqual(pageJobs([],1).items,[]);assert.throws(()=>pageJobs(data,0));});
