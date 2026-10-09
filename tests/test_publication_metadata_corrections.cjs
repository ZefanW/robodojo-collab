'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {validDocument, resolve} = require('../web/publication-metadata-corrections.js');
const hash = character => character.repeat(64);
const clone = value => JSON.parse(JSON.stringify(value));
function fixture() {
  const entry = {
    run_id:'original-run', algorithm_id:'original-algorithm', source_manifest_sha256:hash('a'),
    original:{prompt_sha256:hash('b'),tools_sha256:hash('c')},
    corrected:{prompt_sha256:hash('d'),tools_sha256:hash('c')},
    evidence:{actual_model_request_sha256:hash('e'),public_input_sha256:hash('f'),actual_system_sha256:hash('d'),actual_tools_sha256:hash('c'),gateway_source_sha256:hash('a')},
    reason:'The original input establishes the corrected fingerprint.', verified_at:'2026-10-10T00:00:00Z'
  };
  return {
    document:{schema_version:'publication-metadata-corrections-v1',corrections:[entry]},
    manifest:{run_id:entry.run_id,algorithm:{algorithm_id:entry.algorithm_id,...entry.original},provenance:{source_manifest_sha256:entry.source_manifest_sha256},outcome:{score:0.37},artifacts:[{kind:'trajectory',sha256:hash('f')}]}
  };
}
function freeze(value) { if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); } return value; }

test('exact binding returns independent hash display values without changing either input', () => {
  const {document,manifest}=fixture(), beforeManifest=clone(manifest), beforeDocument=clone(document);
  freeze(document); freeze(manifest);
  const result=resolve(document,manifest);
  assert.equal(validDocument(document),true);
  assert.equal(result.status,'applied');
  assert.deepEqual(result.fields,[{field:'prompt_sha256',original:hash('b'),corrected:hash('d'),changed:true},{field:'tools_sha256',original:hash('c'),corrected:hash('c'),changed:false}]);
  assert.deepEqual(manifest,beforeManifest); assert.deepEqual(document,beforeDocument);
  assert.throws(()=>{result.fields[0].corrected=hash('f');},TypeError);
});
test('a changed tools fingerprint is supported only with matching evidence', () => {
  const {document,manifest}=fixture(); document.corrections[0].corrected.tools_sha256=hash('e');
  assert.equal(resolve(document,manifest).status,'invalid');
  document.corrections[0].evidence.actual_tools_sha256=hash('e');
  assert.equal(resolve(document,manifest).fields[1].changed,true);
});
test('all identity and original hash fields must match exactly', () => {
  for (const mutate of [m=>m.algorithm.algorithm_id='another-algorithm',m=>m.provenance.source_manifest_sha256=hash('b'),m=>m.algorithm.prompt_sha256=hash('f'),m=>m.algorithm.tools_sha256=hash('f'),m=>delete m.provenance.source_manifest_sha256]) {
    const {document,manifest}=fixture(); mutate(manifest); assert.equal(resolve(document,manifest).status,'rejected');
  }
  const {document,manifest}=fixture(); manifest.run_id='another-run'; assert.equal(resolve(document,manifest).status,'none');
});
test('non-hashes are rejected in source binding, original, corrected and evidence', () => {
  for (const location of ['source_manifest_sha256','original','corrected','evidence']) {
    const {document,manifest}=fixture(), entry=document.corrections[0];
    if (location==='source_manifest_sha256') entry[location]='not-a-hash';
    else entry[location][Object.keys(entry[location])[0]]='not-a-hash';
    assert.equal(resolve(document,manifest).status,'invalid');
  }
});
test('extra score mutations and arbitrary keys are rejected at every schema level', () => {
  for (const location of ['document','entry','original','corrected','evidence']) {
    const {document,manifest}=fixture(), entry=document.corrections[0];
    (location==='document'?document:location==='entry'?entry:entry[location]).score=100;
    assert.equal(resolve(document,manifest).status,'invalid'); assert.equal(manifest.outcome.score,0.37);
  }
});
test('malformed schemas, duplicate bindings, missing keys and no-op changes fail closed', () => {
  for (const mutate of [d=>d.schema_version='unknown',d=>d.corrections.push(clone(d.corrections[0])),d=>delete d.corrections[0].original.tools_sha256,d=>d.corrections[0].corrected=clone(d.corrections[0].original),d=>d.corrections[0].verified_at='not-a-date',d=>d.corrections={length:1},d=>d.corrections[0].reason='']) {
    const {document,manifest}=fixture(); mutate(document); assert.equal(resolve(document,manifest).status,'invalid');
  }
  assert.equal(validDocument(null),false);
});
test('unmatched and native VLA records stay outside the correction display', () => {
  const {document,manifest}=fixture(); assert.equal(resolve({...document,corrections:[]},manifest).status,'none');
  manifest.execution_kind='native_vla';
  assert.deepEqual(resolve(document,manifest),{status:'none'});
  assert.deepEqual(resolve({unexpected:'invalid'},manifest),{status:'none'});
});
