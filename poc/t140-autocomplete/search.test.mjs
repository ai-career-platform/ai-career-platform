import {test} from 'node:test';
import assert from 'node:assert/strict';
import {findSkills} from './search.mjs';
const skills=[{code:'py',name:'Python'},{code:'cpy',name:'CPython'},{code:'py',name:'Python'}, {code:'js',name:'JavaScript'},{code:'ko',name:'데이터 분석'}];
test('two characters, case insensitive, prefix first, unique code',()=>assert.deepEqual(findSkills('PY',skills).map(x=>x.code),['py','cpy']));
test('one character, empty and missing',()=>{assert.deepEqual(findSkills('p',skills),[]);assert.deepEqual(findSkills('',skills),[]);assert.deepEqual(findSkills('없는기술',skills),[])});
test('Korean normalization',()=>assert.equal(findSkills('데이터',skills)[0].code,'ko'));
test('limit to 20',()=>assert.equal(findSkills('기술',Array.from({length:25},(_,i)=>({code:String(i),name:'기술'+i}))).length,20));
test('reject invalid query and data',()=>{assert.throws(()=>findSkills('a'.repeat(61),skills),RangeError);assert.throws(()=>findSkills('python',[{code:'',name:'Python'}]),TypeError)});
