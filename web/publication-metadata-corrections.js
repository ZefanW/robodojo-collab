'use strict';
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.PublicationMetadataCorrections = api;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  const VERSION = 'publication-metadata-corrections-v1';
  const FIELDS = ['prompt_sha256', 'tools_sha256'];
  const ENTRY_KEYS = ['run_id', 'algorithm_id', 'source_manifest_sha256', 'original', 'corrected', 'evidence', 'reason', 'verified_at'];
  const EVIDENCE_KEYS = ['actual_model_request_sha256', 'public_input_sha256', 'actual_system_sha256', 'actual_tools_sha256', 'gateway_source_sha256'];
  const isHash = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
  const isId = value => typeof value === 'string' && /^[A-Za-z0-9_.-]{1,200}$/.test(value);
  function exactKeys(value, keys) {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
      && Object.keys(value).length === keys.length
      && keys.every(key => Object.prototype.hasOwnProperty.call(value, key));
  }
  function validDocument(document) {
    if (!exactKeys(document, ['schema_version', 'corrections']) || document.schema_version !== VERSION || !Array.isArray(document.corrections)) return false;
    const bindings = new Set();
    for (const entry of document.corrections) {
      if (!exactKeys(entry, ENTRY_KEYS) || !isId(entry.run_id) || !isId(entry.algorithm_id) || !isHash(entry.source_manifest_sha256)) return false;
      if (!exactKeys(entry.original, FIELDS) || !exactKeys(entry.corrected, FIELDS)
        || !FIELDS.every(field => isHash(entry.original[field]) && isHash(entry.corrected[field]))
        || !FIELDS.some(field => entry.original[field] !== entry.corrected[field])) return false;
      if (!exactKeys(entry.evidence, EVIDENCE_KEYS) || !EVIDENCE_KEYS.every(field => isHash(entry.evidence[field]))
        || entry.evidence.actual_system_sha256 !== entry.corrected.prompt_sha256
        || entry.evidence.actual_tools_sha256 !== entry.corrected.tools_sha256) return false;
      if (typeof entry.reason !== 'string' || !entry.reason.trim() || entry.reason.length > 2000
        || typeof entry.verified_at !== 'string' || !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(entry.verified_at)
        || !Number.isFinite(Date.parse(entry.verified_at))) return false;
      const binding = JSON.stringify([entry.run_id, entry.algorithm_id, entry.source_manifest_sha256]);
      if (bindings.has(binding)) return false;
      bindings.add(binding);
    }
    return true;
  }
  // This returns display-only values. It never edits or merges into the archive.
  function resolve(document, manifest) {
    if (manifest?.execution_kind === 'native_vla') return Object.freeze({status:'none'});
    if (!validDocument(document)) return Object.freeze({status:'invalid'});
    const candidates = document.corrections.filter(entry => entry.run_id === manifest?.run_id);
    if (!candidates.length) return Object.freeze({status:'none'});
    const entry = candidates.find(item => item.algorithm_id === manifest.algorithm?.algorithm_id
      && item.source_manifest_sha256 === manifest.provenance?.source_manifest_sha256);
    if (!entry || !FIELDS.every(field => manifest.algorithm?.[field] === entry.original[field])) return Object.freeze({status:'rejected'});
    const fields = FIELDS.map(field => Object.freeze({field, original:entry.original[field], corrected:entry.corrected[field], changed:entry.original[field] !== entry.corrected[field]}));
    return Object.freeze({status:'applied', fields:Object.freeze(fields), source_manifest_sha256:entry.source_manifest_sha256});
  }
  return Object.freeze({validDocument, resolve});
});
