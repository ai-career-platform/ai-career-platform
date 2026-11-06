import {test} from 'node:test';
import assert from 'node:assert/strict';
import {filterJobs} from './jobs.mjs';
const jobs=[{name:'데이터 분석가',category:'데이터'}, {name:'Backend',category:'개발'}, {name:'프론트엔드',category:'개발'}];
test('name search ignores case and searches names only',()=>{assert.deepEqual(filterJobs(jobs,' BACK ').map(x=>x.name),['Backend']);assert.deepEqual(filterJobs(jobs,'개발'),[])});
test('empty and category sorting are deterministic and input is not mutated',()=>{const before=jobs.map(x=>x.name);assert.equal(filterJobs(jobs,'').length,3);assert.deepEqual(filterJobs(jobs,'','category').slice(0,2).map(x=>x.name),['프론트엔드','Backend']);assert.deepEqual(jobs.map(x=>x.name),before)});
