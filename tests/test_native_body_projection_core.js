'use strict';

const assert = require('node:assert/strict');
const Core = require('../tools/native_body_projection_core.js');

const MARKER = 'TRAE_NATIVE_20261027_A_OK';
const TARGET = 'deepseek-v4.1-flash';
const PATH = '/api/agent/v3/llm_utils_chat';
const ROUTE = Object.freeze({
  scheme: 'https', host: 'trae-api-cn.mchost.guru', port: 443,
  method: 'POST', path_sha256: Core.sha256Ascii(encodeURIComponent(PATH))
});
// This is only a local fixture schema. It is not a claim about Trae's wire body.
const FIXTURE_REQUEST_MARKER_CONTRACT = Object.freeze({
  arrayPath: 'messages', roleKey: 'role', roleValue: 'user',
  contentKey: 'content', newestOnly: true
});
const encoder = new TextEncoder();
let cases = 0;

function run(name, fn) {
  fn();
  cases++;
}

function makeCore(overrides = {}) {
  return Core.create(Object.assign({marker: MARKER, targetModel: TARGET, expectedRoute: ROUTE,
    requestMarkerContract: FIXTURE_REQUEST_MARKER_CONTRACT}, overrides));
}

function begin(core, requestKey = 'request-1', callbackKey = 'callback-shared', route = ROUTE) {
  return core.beginFlow({route, requestKey, callbackKey});
}

function upload(core, seq, requestText, options = {}) {
  const requestKey = options.requestKey || 'request-1';
  const callbackKey = options.callbackKey || 'callback-shared';
  const providerKey = options.providerKey || 'provider-1';
  const sinkKey = options.sinkKey || 'sink-shared';
  const body = encoder.encode(requestText);
  const expectedLength = options.expectedLength === undefined ? body.length : options.expectedLength;
  const bound = core.bindProvider(seq, providerKey, expectedLength);
  if (!bound.accepted) return bound;
  const splitPoints = options.splitPoints || [body.length];
  let offset = 0;
  let last = null;
  for (let i = 0; i < splitPoints.length; i++) {
    const end = splitPoints[i];
    const chunk = body.slice(offset, end);
    const bufferKey = options.bufferKey || 'upload-buffer';
    const pending = core.beginUploadRead(providerKey, sinkKey, bufferKey, Math.max(chunk.length, 1));
    if (!pending.accepted) return pending;
    last = core.ackUploadRead(pending.ticket, providerKey, sinkKey, bufferKey,
      chunk.length, chunk.length, chunk, i === splitPoints.length - 1);
    if (i !== splitPoints.length - 1 && !last.accepted) return last;
    offset = end;
  }
  return last;
}

function addMarkerRequest(core, requestKey = 'request-1', callbackKey = 'callback-shared', providerKey = 'provider-1') {
  const started = begin(core, requestKey, callbackKey);
  assert.equal(started.accepted, true);
  const text = JSON.stringify({
    messages: [
      {role: 'user', content: 'older synthetic turn'},
      {role: 'user', content: '只回复 ' + MARKER}
    ],
    model_config: {model_name: TARGET, reasoning_effort: 'low'},
    session_id: 'SYNTHETIC_SESSION_ID', tools: [],
    access_token: 'NEVER_PROJECT_THIS_VALUE',
    cloudide_token: 'NEVER_PROJECT_CLOUDIDE',
    x_ide_token: 'NEVER_PROJECT_XIDE',
    apiKey: 'NEVER_PROJECT_API_KEY',
    AuthorizationHeader: 'NEVER_PROJECT_AUTH_HEADER',
    credentials: {password: 'NEVER_PROJECT_PASSWORD'}
  });
  const bytes = encoder.encode(text);
  const markerAt = text.indexOf(MARKER);
  const markerByteAt = encoder.encode(text.slice(0, markerAt)).length;
  const split = markerByteAt + 8;
  const result = upload(core, started.request_seq, text, {
    requestKey, callbackKey, providerKey,
    splitPoints: [split, bytes.length]
  });
  return {seq: started.request_seq, result, text};
}

function addResponse(core, requestKey, callbackKey, responseText, options = {}) {
  const bufferKey = options.bufferKey || 'response-buffer';
  const bytes = encoder.encode(responseText);
  const pending = core.beginResponseRead(callbackKey, requestKey, bufferKey, bytes.length);
  if (!pending.accepted) return pending;
  return core.completeResponseRead(pending.ticket, callbackKey, requestKey, bufferKey,
    bytes.length, bytes.length, bytes);
}

run('exact route rejects other paths', () => {
  const core = makeCore();
  const result = begin(core, 'request-wrong-route', 'callback-shared', Object.assign({}, ROUTE, {
    path_sha256: Core.sha256Ascii(encodeURIComponent('/api/agent/v3/unknown'))
  }));
  assert.equal(result.accepted, false);
  assert.equal(result.reason, 'route_not_exact');
  assert.equal(core.getCoverage().flow_started, 0);
  core.dispose();
});

run('target model is fixed to the observed target', () => {
  assert.throws(() => makeCore({targetModel: 'other-model'}), /invalid_target_model/);
});

run('cross-chunk marker opens only the matching request gate', () => {
  const core = makeCore();
  const {result} = addMarkerRequest(core);
  assert.equal(result.kind, 'request_projection');
  assert.equal(result.marker_hit, true);
  assert.equal(result.projection.model_fields['model_config.model_name'], TARGET);
  assert.match(result.projection.id_hashes.session_id, /^[0-9a-f]{64}$/);
  const safe = JSON.stringify(result);
  for (const forbidden of [MARKER, '只回复', 'SYNTHETIC_SESSION_ID', 'NEVER_PROJECT_THIS_VALUE',
    'NEVER_PROJECT_CLOUDIDE', 'NEVER_PROJECT_XIDE', 'NEVER_PROJECT_PASSWORD',
    'NEVER_PROJECT_API_KEY', 'NEVER_PROJECT_AUTH_HEADER', 'access_token',
    'cloudide_token', 'x_ide_token', 'apiKey', 'AuthorizationHeader', 'credentials']) {
    assert.equal(safe.includes(forbidden), false);
  }
  assert.equal(core.getCoverage().marker_matched, 1);
  core.dispose();
});

run('response cannot be read before upload marker verification', () => {
  const core = makeCore();
  const started = begin(core);
  assert.equal(started.accepted, true);
  const denied = core.beginResponseRead('callback-shared', 'request-1', 'response-buffer', 10);
  assert.equal(denied.accepted, false);
  assert.equal(denied.reason, 'marker_gate_closed');
  core.dispose();
});

run('nonmatching upload marker permanently closes response gate', () => {
  const core = makeCore();
  const started = begin(core);
  const result = upload(core, started.request_seq,
    JSON.stringify({query: [{role: 'user', content: 'synthetic unrelated input'}]}));
  assert.equal(result.kind, 'upload_gate');
  assert.equal(result.matched, false);
  assert.equal(core.beginResponseRead('callback-shared', 'request-1', 'response-buffer', 10).reason, 'marker_gate_closed');
  core.dispose();
});

run('missing request marker contract prevents upload buffer acceptance', () => {
  const core = makeCore({requestMarkerContract: null});
  const started = begin(core);
  core.bindProvider(started.request_seq, 'provider-1', 8);
  const result = core.beginUploadRead('provider-1', 'sink-1', 'buffer-1', 8);
  assert.equal(result.reason, 'marker_contract_unconfigured');
  assert.equal(core.getCoverage().upload_reads, 0);
  assert.equal(core.beginResponseRead('callback-shared', 'request-1', 'response-1', 8).reason,
    'marker_gate_closed');
  core.dispose();
});

run('marker found only in older history does not open current user gate', () => {
  const core = makeCore();
  const started = begin(core);
  const body = JSON.stringify({messages: [
    {role: 'user', content: 'old turn ' + MARKER},
    {role: 'user', content: 'new turn without marker'}
  ]});
  const result = upload(core, started.request_seq, body);
  assert.equal(result.kind, 'upload_gate');
  assert.equal(result.matched, false);
  assert.equal(result.reason, 'current_user_marker_missing');
  assert.equal(core.beginResponseRead('callback-shared', 'request-1', 'response-1', 8).reason,
    'marker_gate_closed');
  core.dispose();
});

run('marker found only in unrelated metadata does not open current user gate', () => {
  const core = makeCore();
  const started = begin(core);
  const body = JSON.stringify({messages: [{role: 'user', content: 'new turn without marker'}],
    metadata: {marker_reference: MARKER}});
  const result = upload(core, started.request_seq, body);
  assert.equal(result.matched, false);
  assert.equal(result.reason, 'current_user_marker_missing');
  core.dispose();
});

run('newest entry must be the configured user role', () => {
  const core = makeCore();
  const started = begin(core);
  const body = JSON.stringify({messages: [
    {role: 'user', content: 'older user'},
    {role: 'assistant', content: MARKER}
  ]});
  const result = upload(core, started.request_seq, body);
  assert.equal(result.matched, false);
  assert.equal(result.reason, 'current_entry_not_user');
  core.dispose();
});

run('wrong typed upload mapping fails closed', () => {
  const core = makeCore();
  const started = begin(core);
  assert.equal(core.bindProvider(started.request_seq, 'provider-1', 4).accepted, true);
  const pending = core.beginUploadRead('provider-1', 'sink-1', 'buffer-1', 4);
  const mismatch = core.ackUploadRead(pending.ticket, 'provider-other', 'sink-1', 'buffer-1',
    4, 4, new Uint8Array([1, 2, 3, 4]), true);
  assert.equal(mismatch.reason, 'upload_mapping_mismatch');
  assert.equal(core.getCoverage().marker_matched, 0);
  core.dispose();
});

run('bytesRead cannot exceed the typed buffer capacity', () => {
  const core = makeCore();
  const started = begin(core);
  core.bindProvider(started.request_seq, 'provider-1', 4);
  const pending = core.beginUploadRead('provider-1', 'sink-1', 'buffer-1', 3);
  const result = core.ackUploadRead(pending.ticket, 'provider-1', 'sink-1', 'buffer-1',
    4, 4, new Uint8Array([1, 2, 3, 4]), true);
  assert.equal(result.reason, 'upload_read_invalid');
  core.dispose();
});

run('buffer size must match the captured typed capacity', () => {
  const core = makeCore();
  const started = begin(core);
  core.bindProvider(started.request_seq, 'provider-1', 3);
  const pending = core.beginUploadRead('provider-1', 'sink-1', 'buffer-1', 3);
  const mismatch = core.ackUploadRead(pending.ticket, 'provider-1', 'sink-1', 'buffer-1',
    1, 4, new Uint8Array([0x7b]), false);
  assert.equal(mismatch.reason, 'upload_read_invalid');
  core.dispose();
});

run('oversize upload is rejected before provider content is accepted', () => {
  const core = makeCore();
  const started = begin(core);
  const result = core.bindProvider(started.request_seq, 'provider-1', 1024 * 1024 + 1);
  assert.equal(result.reason, 'provider_length_invalid');
  core.dispose();
});

run('same sink and buffer can be reused sequentially for chunked upload', () => {
  const core = makeCore();
  const text = JSON.stringify({messages: [{role: 'user', content: MARKER}]});
  const bytes = encoder.encode(text);
  const started = begin(core);
  core.bindProvider(started.request_seq, 'provider-1', bytes.length);
  const first = core.beginUploadRead('provider-1', 'sink-reused', 'buffer-reused', bytes.length);
  assert.equal(core.ackUploadRead(first.ticket, 'provider-1', 'sink-reused', 'buffer-reused',
    5, bytes.length, bytes.slice(0, 5), false).upload_pending, true);
  const second = core.beginUploadRead('provider-1', 'sink-reused', 'buffer-reused', bytes.length);
  const last = core.ackUploadRead(second.ticket, 'provider-1', 'sink-reused', 'buffer-reused',
    bytes.length - 5, bytes.length, bytes.slice(5), true);
  assert.equal(last.kind, 'request_projection');
  core.dispose();
});

run('an in-flight sink cannot be ambiguously reused', () => {
  const core = makeCore();
  const started = begin(core);
  core.bindProvider(started.request_seq, 'provider-1', 5);
  assert.equal(core.beginUploadRead('provider-1', 'sink-one', 'buffer-one', 5).accepted, true);
  const overlap = core.beginUploadRead('provider-1', 'sink-one', 'buffer-two', 5);
  assert.equal(overlap.reason, 'sink_in_flight');
  core.dispose();
});

run('provider reuse invalidates both flows', () => {
  const core = makeCore();
  const one = begin(core, 'request-one', 'callback-shared');
  const two = begin(core, 'request-two', 'callback-shared');
  assert.equal(core.bindProvider(one.request_seq, 'provider-reused', 1).accepted, true);
  const result = core.bindProvider(two.request_seq, 'provider-reused', 1);
  assert.equal(result.reason, 'provider_reused');
  assert.equal(core.getCoverage().provider_reused, 1);
  assert.deepEqual(core.dispose(), {active_flows: 0, pending_upload: 0, pending_response: 0});
});

run('shared callback can map two concurrent requests by request pointer', () => {
  const core = makeCore();
  const one = addMarkerRequest(core, 'request-one', 'callback-shared', 'provider-one');
  const two = addMarkerRequest(core, 'request-two', 'callback-shared', 'provider-two');
  assert.equal(one.result.kind, 'request_projection');
  assert.equal(two.result.kind, 'request_projection');
  const responseOne = addResponse(core, 'request-one', 'callback-shared', JSON.stringify({done: true}));
  const responseTwo = addResponse(core, 'request-two', 'callback-shared', JSON.stringify({done: true}));
  assert.equal(responseOne.accepted, true);
  assert.equal(responseTwo.accepted, true);
  assert.equal(core.finishRequest('request-one', 'callback-shared', 200, 'succeeded').response.done, true);
  assert.equal(core.finishRequest('request-two', 'callback-shared', 200, 'succeeded').response.done, true);
  core.dispose();
});

run('terminal before upload marker gate emits no body projection', () => {
  const core = makeCore();
  const started = begin(core);
  core.bindProvider(started.request_seq, 'provider-1', 100);
  const pending = core.beginUploadRead('provider-1', 'sink-1', 'buffer-1', 100);
  const terminal = core.finishRequest('request-1', 'callback-shared', 200, 'succeeded');
  assert.equal(terminal.marker_gate_open, false);
  assert.equal(terminal.response.parse_state, 'marker_gate_closed');
  const lateAck = core.ackUploadRead(pending.ticket, 'provider-1', 'sink-1', 'buffer-1',
    5, 5, new Uint8Array([1, 2, 3, 4, 5]), true);
  assert.equal(lateAck.reason, 'upload_ticket_missing');
  assert.equal(JSON.stringify(terminal).includes(MARKER), false);
  core.dispose();
});

run('invalid JSON with marker does not open response gate', () => {
  const core = makeCore();
  const started = begin(core);
  const result = upload(core, started.request_seq, '{"text":"' + MARKER);
  assert.equal(result.kind, 'upload_gate');
  assert.equal(result.reason, 'invalid_json');
  assert.equal(core.beginResponseRead('callback-shared', 'request-1', 'response-buffer', 1).reason, 'marker_gate_closed');
  core.dispose();
});

run('assistant role and response metadata are projected without text', () => {
  const core = makeCore();
  const {result: requestResult} = addMarkerRequest(core);
  assert.equal(requestResult.kind, 'request_projection');
  const responseText = JSON.stringify({
    choices: [{message: {role: 'assistant', content: MARKER}}],
    model: TARGET, usage: {prompt_tokens: 11, completion_tokens: 4, total_tokens: 15},
    done: true, session_id: 'SYNTHETIC_RESPONSE_SESSION', token: 'DO_NOT_PROJECT'
  });
  assert.equal(addResponse(core, 'request-1', 'callback-shared', responseText).accepted, true);
  const terminal = core.finishRequest('request-1', 'callback-shared', 200, 'succeeded');
  assert.equal(terminal.response.parse_state, 'json');
  assert.equal(terminal.response.assistant_marker_hit, true);
  assert.equal(terminal.response.marker_roles.includes('assistant'), true);
  assert.equal(terminal.response.model_fields.model, TARGET);
  assert.equal(terminal.response.usage['usage.prompt_tokens'], 11);
  assert.equal(terminal.response.usage['usage.total_tokens'], 15);
  const safe = JSON.stringify(terminal);
  for (const forbidden of [MARKER, 'SYNTHETIC_RESPONSE_SESSION', 'DO_NOT_PROJECT']) {
    assert.equal(safe.includes(forbidden), false);
  }
  core.dispose();
});

run('assistant content marker is a field match and can still be prompt echo', () => {
  const core = makeCore();
  addMarkerRequest(core);
  const echo = JSON.stringify({choices: [{message: {role: 'assistant', content: MARKER}}]});
  assert.equal(addResponse(core, 'request-1', 'callback-shared', echo).accepted, true);
  const terminal = core.finishRequest('request-1', 'callback-shared', 200, 'succeeded');
  assert.equal(terminal.response.assistant_marker_hit, true);
  assert.equal(terminal.response.response_marker_hit, true);
  // A marker in an assistant content field is not proof that a model generated it.
  assert.equal(JSON.stringify(terminal).includes(MARKER), false);
  core.dispose();
});

run('SSE chunks preserve assistant marker, usage, and done metadata', () => {
  const core = makeCore();
  addMarkerRequest(core);
  const sse = 'event:message\ndata:' + JSON.stringify({
    choices: [{delta: {role: 'assistant', content: MARKER}}],
    model_name: TARGET, usage: {completion_tokens: 3}
  }) + '\n\n' + 'event:done\ndata:[DONE]\n\n';
  const bytes = encoder.encode(sse);
  const splitAt = Math.floor(bytes.length / 2);
  for (const chunk of [bytes.slice(0, splitAt), bytes.slice(splitAt)]) {
    const pending = core.beginResponseRead('callback-shared', 'request-1', 'response-buffer', chunk.length);
    assert.equal(pending.accepted, true);
    assert.equal(core.completeResponseRead(pending.ticket, 'callback-shared', 'request-1',
      'response-buffer', chunk.length, chunk.length, chunk).accepted, true);
  }
  const terminal = core.finishRequest('request-1', 'callback-shared', 200, 'succeeded');
  assert.equal(terminal.response.parse_state, 'sse');
  assert.equal(terminal.response.assistant_marker_hit, true);
  assert.equal(terminal.response.done, true);
  assert.equal(terminal.response.event_types.includes('done'), true);
  assert.equal(terminal.response.usage['usage.completion_tokens'], 3);
  assert.equal(JSON.stringify(terminal).includes(MARKER), false);
  core.dispose();
});

run('marker split across SSE delta frames remains unverified', () => {
  const core = makeCore();
  addMarkerRequest(core);
  const midpoint = Math.floor(MARKER.length / 2);
  const sse = 'event:message\ndata:' + JSON.stringify({choices: [{delta: {role: 'assistant', content: MARKER.slice(0, midpoint)}}]}) +
    '\n\n' + 'event:message\ndata:' + JSON.stringify({choices: [{delta: {role: 'assistant', content: MARKER.slice(midpoint)}}]}) + '\n\n';
  const bytes = encoder.encode(sse);
  assert.equal(addResponse(core, 'request-1', 'callback-shared', new TextDecoder().decode(bytes)).accepted, true);
  const terminal = core.finishRequest('request-1', 'callback-shared', 200, 'succeeded');
  assert.equal(terminal.response.parse_state, 'sse');
  assert.equal(terminal.response.assistant_marker_hit, false);
  assert.equal(terminal.response.response_marker_hit, false);
  core.dispose();
});

run('out-of-order response acknowledgements fail closed', () => {
  const core = makeCore();
  addMarkerRequest(core);
  const first = core.beginResponseRead('callback-shared', 'request-1', 'response-one', 1);
  const second = core.beginResponseRead('callback-shared', 'request-1', 'response-two', 1);
  const result = core.completeResponseRead(second.ticket, 'callback-shared', 'request-1',
    'response-two', 1, 1, new Uint8Array([0x7b]));
  assert.equal(result.reason, 'response_sequence_ambiguous');
  assert.equal(core.finishRequest('request-1', 'callback-shared', 200, 'succeeded').reason,
    'terminal_mapping_invalid');
  core.dispose();
});

run('response buffer size must match its captured typed capacity', () => {
  const core = makeCore();
  addMarkerRequest(core);
  const pending = core.beginResponseRead('callback-shared', 'request-1', 'response-buffer', 20);
  const mismatch = core.completeResponseRead(pending.ticket, 'callback-shared', 'request-1',
    'response-buffer', 1, 21, new Uint8Array([0x7b]));
  assert.equal(mismatch.reason, 'response_read_invalid');
  core.dispose();
});

run('response terminal with pending read does not project partial data', () => {
  const core = makeCore();
  addMarkerRequest(core);
  const pending = core.beginResponseRead('callback-shared', 'request-1', 'response-buffer', 100);
  assert.equal(pending.accepted, true);
  const terminal = core.finishRequest('request-1', 'callback-shared', 200, 'succeeded');
  assert.equal(terminal.response.parse_state, 'response_read_pending_at_terminal');
  assert.equal(terminal.response.assistant_marker_hit, false);
  assert.equal(core.getCoverage().skips.response_read_pending_at_terminal, 1);
  core.dispose();
});

run('rewind invalidates ambiguous provider payloads', () => {
  const core = makeCore();
  const started = begin(core);
  core.bindProvider(started.request_seq, 'provider-1', -1);
  const result = core.rewindProvider('provider-1');
  assert.equal(result.reason, 'provider_rewind_ambiguous');
  assert.equal(core.beginUploadRead('provider-1', 'sink-1', 'buffer-1', 1).reason, 'provider_unmapped');
  assert.equal(core.getCoverage().skips.provider_rewind_ambiguous, 1);
  core.dispose();
});

run('dispose clears active flow and read mappings', () => {
  const core = makeCore();
  const started = begin(core);
  core.bindProvider(started.request_seq, 'provider-1', -1);
  core.beginUploadRead('provider-1', 'sink-1', 'buffer-1', 8);
  assert.deepEqual(core.dispose(), {active_flows: 0, pending_upload: 0, pending_response: 0});
});

console.log(JSON.stringify({self_test: 'passed', cases}));
