import test from 'node:test';
import assert from 'node:assert/strict';
import {chooseGrouping,reportSeries} from '../report_grouping.mjs';
test('new source categories survive unchanged and grow beyond four groups',()=>{
 const models=Array.from({length:7},(_,i)=>({model:'全新车型'+i,segment:'内网档位'+i,brand:'单一品牌',energy:'未知动力'}));
 const g=chooseGrouping(models);assert.equal(g.dimension,'segment');assert.equal(g.categories.length,7);
 assert.ok(g.categories.includes('产品档位：内网档位6'));
});
test('auto chooses usable alternative; manual choice keeps every original category',()=>{
 const models=Array.from({length:12},(_,i)=>({model:String(i),segment:'档位'+i,brand:'品牌'+i%3,energy:'同一种'}));
 assert.equal(chooseGrouping(models).dimension,'brand');
 assert.equal(chooseGrouping(models,{groupBy:'segment'}).categories.length,12);
});
test('missing and conflicting values are explicit, never fake three groups',()=>{
 const g=chooseGrouping([{model:'A'},{model:'B',segment:'映射冲突'}],{groupBy:'segment'});
 assert.deepEqual(new Set(g.categories),new Set(['产品档位：未提供','产品档位：映射冲突']));
 assert.equal(chooseGrouping([{model:'A'}]).categories.length,1);
 assert.throws(()=>chooseGrouping([],{groupBy:'bad'}));
});
test('actual metric-stage combinations drive output, including unseen stages',()=>{
 const g=chooseGrouping([{model:'A',segment:'新类'},{model:'B',segment:'第二类'}]);
 const map=new Map(g.entries.map(r=>[r.model,r]));
 const s=reportSeries([{model:'A',metric:'大定',stage:'改款期'},{model:'A',metric:'大定',stage:'改款期'},{model:'B',metric:'交车锁单',stage:'平销'}],g.categories,map);
 assert.equal(s.length,4);assert.equal(s.filter(r=>r.stage==='改款期').length,2);
 assert.ok(!s.some(r=>r.metric==='小订数量'));
});
