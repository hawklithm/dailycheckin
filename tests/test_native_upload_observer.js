'use strict';

const assert = require('node:assert/strict');
const Core = require('../tools/native_upload_projection_core.js');
const Observer = require('../tools/native_upload_observer.js');

const MARKER = 'TRAE_NATIVE_20261027_B_OK';
const TARGET_MODEL = 'deepseek-v4.1-flash';
const ROUTE = '/api/agent/v3/llm_utils_chat';
const PREFIX = 'Cloud-IDE-JWT ';
const TOKEN = 'synthetic-auth-token-only';
let cases = 0;

function run(name, fn) {
  fn();
  cases++;
}

function utf8Encode(value) {
  const bytes = [];
  for (let index = 0; index < value.length; index++) {
    let codePoint = value.charCodeAt(index);
    if (codePoint >= 0xd800 && codePoint <= 0xdbff && index + 1 < value.length) {
      const next = value.charCodeAt(index + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        codePoint = 0x10000 + ((codePoint - 0xd800) << 10) + (next - 0xdc00);
        index++;
      }
    }
    if (codePoint <= 0x7f) bytes.push(codePoint);
    else if (codePoint <= 0x7ff) bytes.push(0xc0 | (codePoint >> 6), 0x80 | (codePoint & 0x3f));
    else if (codePoint <= 0xffff) bytes.push(0xe0 | (codePoint >> 12),
      0x80 | ((codePoint >> 6) & 0x3f), 0x80 | (codePoint & 0x3f));
    else bytes.push(0xf0 | (codePoint >> 18), 0x80 | ((codePoint >> 12) & 0x3f),
      0x80 | ((codePoint >> 6) & 0x3f), 0x80 | (codePoint & 0x3f));
  }
  return new Uint8Array(bytes);
}

class FakePointer {
  constructor(key, bytes = null, offset = 0, numeric = null, readLimit = null, onForbiddenRead = null) {
    this.key = key;
    this.bytes = bytes;
    this.offset = offset;
    this.numeric = numeric;
    this.readLimit = readLimit;
    this.onForbiddenRead = onForbiddenRead;
  }
  toString() {
    if (this.numeric !== null) return '0x' + this.numeric.toString(16);
    return this.key;
  }
  isNull() { return this.key === '0x0' || this.key === 'null'; }
  add(amount) { return new FakePointer(this.key, this.bytes, this.offset + amount, this.numeric, this.readLimit, this.onForbiddenRead); }
  sub(other) {
    assert.ok(this.numeric !== null && other.numeric !== null);
    return new FakePointer('rva', null, 0, this.numeric - other.numeric);
  }
  readU8() {
    if (!this.bytes || this.offset < 0 || this.offset >= this.bytes.length ||
        (this.readLimit !== null && this.offset > this.readLimit)) {
      if (this.readLimit !== null && this.offset > this.readLimit && this.onForbiddenRead) this.onForbiddenRead();
      throw new Error('unreadable');
    }
    return this.bytes[this.offset];
  }
  readByteArray(length) {
    if (!this.bytes || this.offset < 0 || this.offset + length > this.bytes.length) throw new Error('unreadable');
    return this.bytes.slice(this.offset, this.offset + length).buffer;
  }
  toInt32() { return Number(this.key); }
}

class FakeInteger {
  constructor(value) { this.value = value; }
  toString() { return String(this.value); }
  toInt32() { return Number(this.value); }
}

class FakeNativeInteger {
  constructor(text) { this.text = text; }
  toString() { return this.text; }
  toInt32() { return Number(this.text); }
}

function nativeInteger(value) {
  if (value === -1) return new FakeNativeInteger('0xffffffffffffffff');
  if (typeof value === 'string') return new FakeNativeInteger(value);
  return new FakeNativeInteger('0x' + Number(value).toString(16));
}

function cString(value, key, readLimit = null, onForbiddenRead = null) {
  const content = utf8Encode(value);
  const bytes = new Uint8Array(content.length + 1);
  bytes.set(content);
  return new FakePointer(key || ('str:' + value), bytes, 0, null, readLimit, onForbiddenRead);
}

function makeHarness(options = {}) {
  const messages = [];
  const attachmentMap = new Map();
  const exportsByName = new Map();
  const addressByKey = new Map();
  const headerByKey = new Map();
  const bufferCapacityByKey = new Map();
  const bufferDataByKey = new Map();
  let bufferDataCalls = 0;
  let nativeProviderGetterCalls = 0;
  let headerValueCalls = 0;
  let routeUrlReadsAfterQuery = 0;

  const request = new FakePointer('0x1000');
  const engine = new FakePointer('0x1010');
  const params = new FakePointer('0x1020');
  const provider = new FakePointer('0x1030');
  const requestCallback = new FakePointer('0x1040');
  const executor = new FakePointer('0x1050');
  const sink = new FakePointer('0x1060');
  const buffer = new FakePointer('0x1070');
  const responseInfo = new FakePointer('0x1080');
  const methodPointer = cString('POST', 'method-post');
  const urlText = options.url || ('https://' + (options.host || 'trae-api-cn.mchost.guru') + ROUTE + '?opaque=DO_NOT_READ');
  const queryAt = urlText.indexOf('?');
  const urlPointer = cString(urlText, 'url', queryAt >= 0 ? queryAt : null,
    function () { routeUrlReadsAfterQuery++; });

  const headerName = options.headerName || 'authorization';
  const headerValue = options.headerValue === undefined ? PREFIX + TOKEN : options.headerValue;
  const headerPtr = new FakePointer('0x2000');
  const namePtr = cString(headerName, 'header-name');
  const valuePtr = cString(headerValue, 'header-value');
  headerByKey.set(headerPtr.toString(), {name: namePtr, value: valuePtr});
  const headers = options.noHeaders ? [] : [headerPtr];

  const callbackBase = new FakePointer('callback-module-base', null, 0, 0x5000);
  const callbackPointers = {
    get_length: new FakePointer('callback-get-length', null, 0, 0x5100),
    read: new FakePointer('callback-read', null, 0, 0x5110),
    rewind: new FakePointer('callback-rewind', null, 0, 0x5120),
    close: new FakePointer('callback-close', null, 0, 0x5130)
  };
  if (options.aliasCallbackReadClose) callbackPointers.close = callbackPointers.read;
  const callbackModule = {
    name: 'agent_callbacks.dll', path: 'C:\\Trae CN\\agent_callbacks.dll', size: 0x1000,
    base: callbackBase
  };
  const sscronet = {
    name: 'sscronet.dll', path: 'C:\\Trae CN\\sscronet.dll', size: 0x9000,
    base: new FakePointer('sscronet-base', null, 0, 0x100000),
    findExportByName(name) { return exportsByName.get(name) || null; }
  };

  let nextAddress = 0x200000;
  function address(name) {
    if (!addressByKey.has(name)) {
      const item = new FakePointer(name, null, 0, nextAddress);
      item.exportName = name;
      addressByKey.set(name, item);
      nextAddress += 0x10;
    }
    return addressByKey.get(name);
  }
  const getterAlias = address('getter-alias');
  const closeDataAlias = address('close-data-alias');
  const exportNames = [
    'Cronet_UrlRequest_InitWithParams', 'Cronet_UrlRequest_Start',
    'Cronet_UrlRequestParams_http_method_get',
    'Cronet_UrlRequestParams_upload_data_provider_get',
    'Cronet_UrlRequestParams_request_headers_size',
    'Cronet_UrlRequestParams_request_headers_at',
    'Cronet_HttpHeader_name_get', 'Cronet_HttpHeader_value_get',
    'Cronet_UploadDataProvider_CreateWith', 'Cronet_UploadDataProvider_GetLength',
    'Cronet_UploadDataProvider_Read', 'Cronet_UploadDataProvider_Rewind',
    'Cronet_UploadDataProvider_Close', 'Cronet_UploadDataSink_OnReadSucceeded',
    'Cronet_UploadDataSink_OnReadError', 'Cronet_UploadDataSink_OnRewindError',
    'Cronet_Buffer_GetSize', 'Cronet_Buffer_GetData'
  ];
  for (const name of exportNames) exportsByName.set(name, address(name));
  exportsByName.set('Cronet_UrlRequestParams_http_method_get', getterAlias);
  exportsByName.set('Cronet_HttpHeader_name_get', getterAlias);
  exportsByName.set('Cronet_UploadDataProvider_Close', closeDataAlias);
  exportsByName.set('Cronet_Buffer_GetData', closeDataAlias);

  function attachedFor(target) { return attachmentMap.get(target.toString().toLowerCase()) || []; }
  function invokeAddress(target, args, retval) {
    for (const item of attachedFor(target).slice()) {
      if (item.detached || !item.callbacks.onEnter) continue;
      item.context = {};
      item.callbacks.onEnter.call(item.context, args);
    }
    for (const item of attachedFor(target).slice()) {
      if (item.detached || !item.callbacks.onLeave) continue;
      item.callbacks.onLeave.call(item.context || {}, retval);
    }
  }
  function invokeName(name, args, retval = new FakeInteger(0)) {
    invokeAddress(exportsByName.get(name), args, retval);
  }

  const nativeFunctions = new Map();
  nativeFunctions.set('method', function (arg) {
    if (arg.toString() === params.toString()) return methodPointer;
    const header = headerByKey.get(arg.toString());
    return header ? header.name : null;
  });
  nativeFunctions.set('provider', function () { nativeProviderGetterCalls++; return provider; });
  nativeFunctions.set('headers_size', function () { return headers.length; });
  nativeFunctions.set('headers_at', function (_params, index) { return headers[index] || null; });
  nativeFunctions.set('header_name', function (arg) { const item = headerByKey.get(arg.toString()); return item ? item.name : null; });
  nativeFunctions.set('header_value', function (arg) {
    headerValueCalls++;
    const item = headerByKey.get(arg.toString());
    return item ? item.value : null;
  });
  nativeFunctions.set('buffer_size', function () {
    const key = buffer.toString();
    return new FakeInteger(bufferCapacityByKey.has(key) ? bufferCapacityByKey.get(key) : 0);
  });
  nativeFunctions.set('buffer_data', function (arg) {
    bufferDataCalls++;
    // GetData and Provider_Close share an RVA in the installed build. The
    // mock exercises the attached Close dispatcher with a typed buffer object.
    invokeName('Cronet_UploadDataProvider_Close', [arg], new FakeInteger(0));
    return new FakePointer('buffer-bytes', bufferDataByKey.get(arg.toString()) || new Uint8Array(0));
  });

  const callbackManifest = options.noCallbackManifest ? [] : [{
    module_name: 'agent_callbacks.dll', module_path: callbackModule.path,
    module_sha256: 'b'.repeat(64), memory_size: callbackModule.size,
    executable_ranges: options.callbackRanges || [{rva_start: 0x100, rva_end: 0x200}]
  }];
  const config = {
    pid: 777, expected_module_path: sscronet.path,
    expected_module_sha256: 'a'.repeat(64), expected_module_size: sscronet.size,
    max_seconds: 30, marker: MARKER, target_model: TARGET_MODEL,
    route_allowlist: Array.from(Observer.routePaths, path => ({
      path: path, path_sha256: Core.hashPathKey(path), host: 'trae-api-cn.mchost.guru',
      port: 443, method: 'POST', route_name: path === '/api/agent/v3/workflow/start'
        ? 'workflow_start' : path.slice(path.lastIndexOf('/') + 1)
    })),
    callback_modules: callbackManifest
  };

  const runtime = {
    Process: {
      id: 777,
      getModuleByName(name) { if (name.toLowerCase() !== 'sscronet.dll') throw new Error('missing'); return sscronet; },
      findModuleByAddress(pointer) {
        return pointer.numeric >= callbackModule.base.numeric &&
          pointer.numeric < callbackModule.base.numeric + callbackModule.size ? callbackModule : null;
      },
      findRangeByAddress(pointer) {
        return pointer.numeric >= callbackModule.base.numeric &&
          pointer.numeric < callbackModule.base.numeric + callbackModule.size
          ? {protection: options.callbackProtection || 'r-x', base: callbackModule.base, size: callbackModule.size}
          : null;
      }
    },
    Interceptor: {
      attach(target, callbacks) {
        if (options.failHook && options.failHook === target.exportName) throw new Error('mock attach failure');
        const key = target.toString().toLowerCase();
        if (!attachmentMap.has(key)) attachmentMap.set(key, []);
        const item = {callbacks: callbacks, detached: false};
        attachmentMap.get(key).push(item);
        return {detach() { item.detached = true; }};
      }
    },
    NativeFunction: function (target) {
      const name = target === getterAlias ? 'method' :
        target === exportsByName.get('Cronet_UrlRequestParams_upload_data_provider_get') ? 'provider' :
        target === exportsByName.get('Cronet_UrlRequestParams_request_headers_size') ? 'headers_size' :
        target === exportsByName.get('Cronet_UrlRequestParams_request_headers_at') ? 'headers_at' :
        target === exportsByName.get('Cronet_HttpHeader_value_get') ? 'header_value' :
        target === exportsByName.get('Cronet_Buffer_GetSize') ? 'buffer_size' :
        target === closeDataAlias ? 'buffer_data' : null;
      if (name === 'method') return nativeFunctions.get('method');
      if (name === 'headers_size') return nativeFunctions.get('headers_size');
      if (name === 'headers_at') return nativeFunctions.get('headers_at');
      if (name === 'header_value') return nativeFunctions.get('header_value');
      if (name === 'buffer_size') return nativeFunctions.get('buffer_size');
      if (name === 'buffer_data') return nativeFunctions.get('buffer_data');
      if (name === 'provider') return nativeFunctions.get('provider');
      // Header name shares the generic getter alias and dispatches by object type.
      if (target === getterAlias) return nativeFunctions.get('method');
      throw new Error('unexpected NativeFunction target');
    },
    send(record) { messages.push(JSON.parse(JSON.stringify(record))); },
    setInterval() { return {timer: 'interval'}; },
    clearInterval() {},
    setTimeout() { return {timer: 'timeout'}; },
    clearTimeout() {}
  };

  const observer = Observer.install(config, runtime);
  function invokeCreateWith() {
    invokeName('Cronet_UploadDataProvider_CreateWith', [
      callbackPointers.get_length, callbackPointers.read,
      callbackPointers.rewind, callbackPointers.close
    ], provider);
  }
  function begin() {
    invokeName('Cronet_UrlRequest_InitWithParams', [request, engine, urlPointer, params, requestCallback, executor], new FakeInteger(0));
    invokeName('Cronet_UrlRequest_Start', [request], new FakeInteger(0));
  }
  function invokeGetLength(length, callbackOnly = false) {
    if (callbackOnly) invokeAddress(callbackPointers.get_length, [provider], nativeInteger(length));
    else invokeName('Cronet_UploadDataProvider_GetLength', [provider], nativeInteger(length));
  }
  function readChunk(chunk, optionsForRead = {}) {
    const bytes = chunk instanceof Uint8Array ? chunk : utf8Encode(chunk);
    bufferCapacityByKey.set(buffer.toString(), optionsForRead.capacity || bytes.length);
    bufferDataByKey.set(buffer.toString(), bytes);
    const useCallback = optionsForRead.callback === true;
    if (!useCallback || optionsForRead.alsoWrapper === true) {
      invokeName('Cronet_UploadDataProvider_Read', [provider, sink, buffer]);
    }
    if (useCallback) invokeAddress(callbackPointers.read, [provider, sink, buffer]);
    invokeName('Cronet_UploadDataSink_OnReadSucceeded', [sink,
      nativeInteger(optionsForRead.bytesRead === undefined ? bytes.length : optionsForRead.bytesRead),
      nativeInteger(optionsForRead.finalChunk ? 1 : 0)]);
  }
  return {
    config, runtime, observer, messages, request, engine, params, provider,
    requestCallback, executor, sink, buffer, responseInfo, callbackPointers,
    invokeCreateWith, begin, invokeGetLength, readChunk, invokeName, invokeAddress,
    setBufferData(bytes) { bufferDataByKey.set(buffer.toString(), bytes); },
    setBufferCapacity(size) { bufferCapacityByKey.set(buffer.toString(), size); },
    get bufferDataCalls() { return bufferDataCalls; },
    get nativeProviderGetterCalls() { return nativeProviderGetterCalls; },
    get headerValueCalls() { return headerValueCalls; },
    get routeUrlReadsAfterQuery() { return routeUrlReadsAfterQuery; },
    publicEvents() { return observer.getPublicEventsForTest(); },
    attachedCount() { let count = 0; for (const entries of attachmentMap.values()) count += entries.filter(x => !x.detached).length; return count; }
  };
}

function fixtureBody(withMarker = true) {
  return JSON.stringify({
    messages: [{role: 'user', content: withMarker ? '只回复 ' + MARKER : 'synthetic without marker'}],
    model_config: {model_name: TARGET_MODEL, reasoning_effort: 'low'},
    function: 'chat',
    function_name: 'DO_NOT_PROJECT_DYNAMIC_FUNCTION',
    agent_type: 'builder',
    scene_location: 2,
    assistant: {name: 'SYNTHETIC_ASSISTANT_VALUE'},
    model_config_name: 'SYNTHETIC_CONFIG_NAME',
    system: {mode: 'SYNTHETIC_SYSTEM_VALUE'},
    user: {role: 'SYNTHETIC_USER_VALUE'},
    x: 1,
    session_id: 'SYNTHETIC_SESSION_ONLY',
    api_key: 'DO_NOT_PROJECT_SECRET',
    credentials: {password: 'DO_NOT_PROJECT_PASSWORD'}
  });
}

function stressFixtureBody() {
  const branchKeys = [
    'arguments', 'common_params', 'content', 'custom_model', 'done',
    'error', 'extra_chat_params', 'function_name', 'message'
  ];
  const root = {};
  let cursor = root;
  for (let depth = 0; depth < 13; depth++) {
    for (const key of branchKeys) cursor[key] = null;
    cursor.scheduled_task_context = {};
    cursor = cursor.scheduled_task_context;
  }
  return JSON.stringify(root);
}

function splitInsideChinese(bytes) {
  for (let index = 0; index < bytes.length - 1; index++) {
    if (bytes[index] >= 0xe0 && bytes[index] <= 0xef) return index + 1;
  }
  throw new Error('fixture has no multibyte UTF-8');
}

function driveKnownLength(harness, options = {}) {
  const text = options.body || fixtureBody(true);
  const body = utf8Encode(text);
  harness.invokeCreateWith();
  harness.begin();
  harness.invokeGetLength(body.length, options.callbackLength === true);
  const split = options.split ? splitInsideChinese(body) : body.length;
  const chunks = split < body.length ? [body.slice(0, split), body.slice(split)] : [body];
  for (let index = 0; index < chunks.length; index++) {
    harness.readChunk(chunks[index], {
      callback: options.callbackRead === true,
      alsoWrapper: options.bothReadPaths === true,
      capacity: body.length,
      finalChunk: options.finalChunk === true
    });
  }
  return body;
}

function projectionEvents(harness) {
  return harness.publicEvents().filter(event => event.kind === 'upload_projection');
}

if (process.argv.includes('--fixture-events')) {
  const fixture = makeHarness();
  driveKnownLength(fixture, {split: true, callbackLength: true, callbackRead: true});
  // Exercise the production observer and core with a synthetic, bounded schema
  // large enough to cover the Python JSONL writer's single-line limit.
  driveKnownLength(fixture, {body: stressFixtureBody(), callbackLength: true, callbackRead: true});
  const safeEvents = fixture.messages.filter(event => event.kind !== 'native_auth_digest');
  process.stdout.write(JSON.stringify(safeEvents) + '\n');
} else {
  run('callback-only GetLength and Read capture known length without final_chunk', () => {
    const harness = makeHarness();
    const body = driveKnownLength(harness, {split: true, callbackLength: true, callbackRead: true});
    const events = projectionEvents(harness);
    assert.equal(events.length, 1);
    assert.equal(events[0].projection.parse_state, 'json');
    assert.equal(events[0].projection.marker_hit, true);
    assert.equal(events[0].projection.marker_semantics, 'unverified');
    assert.equal(events[0].route, ROUTE);
    assert.equal(events[0].route_sha256, Core.hashPathKey(ROUTE));
    assert.ok(events[0].projection.schema.some(field =>
      JSON.stringify(field.path).includes('messages')));
    const encoded = JSON.stringify(events[0]);
    for (const forbidden of [MARKER, '只回复', 'SYNTHETIC_SESSION_ONLY', 'DO_NOT_PROJECT_SECRET',
      'DO_NOT_PROJECT_PASSWORD', 'SYNTHETIC_ASSISTANT_VALUE', 'SYNTHETIC_CONFIG_NAME',
      'SYNTHETIC_SYSTEM_VALUE', 'SYNTHETIC_USER_VALUE', TOKEN, PREFIX]) {
      assert.equal(encoded.includes(forbidden), false);
    }
    assert.ok(body.length > 0);
    assert.ok(harness.bufferDataCalls >= 2);
    assert.equal(harness.observer.getCoverage().callback_attached, 4);
    assert.equal(harness.nativeProviderGetterCalls, 1);
    assert.equal(harness.routeUrlReadsAfterQuery, 0);
  });

  run('wrapper and callback Read paths deduplicate the same in-flight typed read', () => {
    const harness = makeHarness();
    driveKnownLength(harness, {callbackLength: true, callbackRead: true, bothReadPaths: true});
    assert.equal(projectionEvents(harness).length, 1);
    assert.equal(harness.observer.getCoverage().callback_attached, 4);
  });

  run('unknown length requires final_chunk and completes only on the final acknowledgement', () => {
    const harness = makeHarness();
    const bytes = utf8Encode(fixtureBody(true));
    harness.invokeCreateWith();
    harness.begin();
    harness.invokeGetLength(-1, true);
    const split = splitInsideChinese(bytes);
    harness.readChunk(bytes.slice(0, split), {callback: true, capacity: bytes.length, finalChunk: false});
    assert.equal(projectionEvents(harness).length, 0);
    harness.readChunk(bytes.slice(split), {callback: true, capacity: bytes.length, finalChunk: true});
    assert.equal(projectionEvents(harness).length, 1);
    assert.equal(projectionEvents(harness)[0].projection.marker_hit, true);
  });

  run('unknown length without a final acknowledgement remains incomplete', () => {
    const harness = makeHarness();
    const bytes = utf8Encode(fixtureBody(true));
    harness.invokeCreateWith();
    harness.begin();
    harness.invokeGetLength(-1, true);
    harness.readChunk(bytes, {callback: true, capacity: bytes.length, finalChunk: false});
    assert.equal(projectionEvents(harness).length, 0);
    assert.equal(harness.observer.getCoverage().active_flows, 1);
    assert.equal(harness.observer.getCoverage().callback_attached, 4);
    assert.equal(harness.attachedCount(), 14);
    harness.observer.stop();
    assert.equal(harness.attachedCount(), 0);
  });

  run('known GetLength conflict invalidates the flow before any projection', () => {
    const harness = makeHarness();
    harness.invokeCreateWith();
    harness.begin();
    harness.invokeGetLength(32, true);
    harness.invokeGetLength(33, false);
    assert.equal(projectionEvents(harness).length, 0);
    assert.equal(harness.observer.getCoverage().length_invalid, 1);
    assert.equal(harness.observer.getCoverage().active_flows, 0);
  });

  run('oversize signed GetLength is rejected before body bytes are read', () => {
    const harness = makeHarness();
    harness.invokeCreateWith();
    harness.begin();
    harness.invokeGetLength(Core.MAX_UPLOAD_BYTES + 1, true);
    assert.equal(harness.bufferDataCalls, 0);
    assert.equal(projectionEvents(harness).length, 0);
    assert.equal(harness.observer.getCoverage().length_invalid, 1);
  });

  run('native hex scalar values parse signed length and bounded read acknowledgements', () => {
    const harness = makeHarness();
    harness.invokeCreateWith();
    harness.begin();
    harness.invokeGetLength(-1, true);
    assert.equal(harness.observer.getCoverage().length_invalid, 0);
    const bytes = utf8Encode(fixtureBody(true));
    harness.readChunk(bytes, {callback: true, capacity: bytes.length, finalChunk: true});
    assert.equal(projectionEvents(harness).length, 1);
    assert.equal(projectionEvents(harness)[0].projection.marker_hit, true);

    const overCap = makeHarness();
    overCap.invokeCreateWith();
    overCap.begin();
    overCap.invokeGetLength('0x0000000000100001', true);
    assert.equal(overCap.observer.getCoverage().length_invalid, 1);
    assert.equal(overCap.bufferDataCalls, 0);
  });

  run('failed required public hook is absent from installed names and prevents readiness', () => {
    const harness = makeHarness({failHook: 'Cronet_UploadDataProvider_Read'});
    const install = harness.observer.getHookInstall();
    assert.equal(install.hooks.includes('Cronet_UploadDataProvider_Read'), false);
    assert.equal(install.missing.includes('Cronet_UploadDataProvider_Read'), true);
    assert.equal(install.upload_api_ready, false);
  });

  run('zero length is a bounded complete empty upload and never calls Buffer_GetData', () => {
    const harness = makeHarness();
    harness.invokeCreateWith();
    harness.begin();
    harness.invokeGetLength(0, true);
    const events = projectionEvents(harness);
    assert.equal(events.length, 1);
    assert.equal(events[0].projection.parse_state, 'invalid_json');
    assert.equal(events[0].projection.body_bytes, 0);
    assert.equal(events[0].projection.marker_hit, false);
    assert.equal(harness.bufferDataCalls, 0);
  });

  run('uint64 bytes_read above the snapshot capacity is rejected without pointer copy', () => {
    const harness = makeHarness();
    harness.invokeCreateWith();
    harness.begin();
    harness.invokeGetLength(5, true);
    harness.setBufferCapacity(8);
    harness.setBufferData(new Uint8Array([1, 2, 3, 4, 5]));
    harness.invokeAddress(harness.callbackPointers.read, [harness.provider, harness.sink, harness.buffer]);
    harness.invokeName('Cronet_UploadDataSink_OnReadSucceeded', [harness.sink,
      new FakeNativeInteger('0xffffffffffffffff'), nativeInteger(1)]);
    assert.equal(harness.bufferDataCalls, 0);
    assert.equal(projectionEvents(harness).length, 0);
    assert.equal(harness.observer.getCoverage().buffer_invalid, 1);
  });

  run('zero byte non-final reads fail closed while zero byte final uploads remain bounded', () => {
    const harness = makeHarness();
    harness.invokeCreateWith();
    harness.begin();
    harness.invokeGetLength(-1, true);
    harness.setBufferCapacity(8);
    harness.setBufferData(new Uint8Array(0));
    harness.invokeAddress(harness.callbackPointers.read, [harness.provider, harness.sink, harness.buffer]);
    harness.invokeName('Cronet_UploadDataSink_OnReadSucceeded', [harness.sink,
      nativeInteger(0), nativeInteger(0)]);
    assert.equal(projectionEvents(harness).length, 0);
    assert.equal(harness.observer.getCoverage().active_flows, 0);
    assert.equal(harness.observer.getCoverage().zero_progress_skip, 1);
  });

  run('unverified or non-executable callback module is skipped while wrapper capture remains usable', () => {
    const harness = makeHarness({callbackRanges: [{rva_start: 0x200, rva_end: 0x300}]});
    driveKnownLength(harness, {callbackLength: false, callbackRead: false});
    assert.equal(projectionEvents(harness).length, 1);
    assert.equal(harness.observer.getCoverage().callback_module_skip, 4);
    assert.equal(harness.observer.getCoverage().callback_attached, 0);
  });

  run('same callback address registered for conflicting roles is detached and wrapper path still works', () => {
    const harness = makeHarness({aliasCallbackReadClose: true});
    driveKnownLength(harness, {callbackLength: false, callbackRead: false});
    assert.equal(projectionEvents(harness).length, 1);
    assert.ok(harness.observer.getCoverage().callback_alias_skip >= 1);
  });

  run('request callback and response-shaped alias invocation are ignored by typed provider map', () => {
    const harness = makeHarness();
    harness.invokeCreateWith();
    harness.begin();
    const before = harness.observer.getCoverage().read_wrapper;
    // The installed Read export aliases OnResponseStarted. Its first typed
    // argument is a request callback, not an upload provider.
    harness.invokeName('Cronet_UploadDataProvider_Read', [
      harness.requestCallback, harness.request, harness.responseInfo
    ]);
    assert.equal(harness.observer.getCoverage().read_wrapper, before);
    assert.equal(projectionEvents(harness).length, 0);
    assert.equal(harness.bufferDataCalls, 0);
  });

  run('typed GetData reentry through the Provider_Close alias does not close an active provider', () => {
    const harness = makeHarness();
    driveKnownLength(harness, {callbackLength: true, callbackRead: true});
    assert.equal(projectionEvents(harness).length, 1);
    assert.equal(harness.observer.getCoverage().close_invalidated, 0);
  });

  run('Rewind and sink errors clean up partial uploads without projecting them', () => {
    const rewind = makeHarness();
    const bytes = utf8Encode(fixtureBody(true));
    rewind.invokeCreateWith(); rewind.begin(); rewind.invokeGetLength(-1, true);
    rewind.readChunk(bytes.slice(0, 12), {callback: true, capacity: bytes.length, finalChunk: false});
    rewind.invokeAddress(rewind.callbackPointers.rewind, [rewind.provider, rewind.sink]);
    assert.equal(projectionEvents(rewind).length, 0);
    assert.equal(rewind.observer.getCoverage().active_flows, 0);
    assert.equal(rewind.observer.getCoverage().rewind_invalidated, 1);

    const failed = makeHarness();
    failed.invokeCreateWith(); failed.begin(); failed.invokeGetLength(-1, true);
    failed.setBufferCapacity(bytes.length);
    failed.setBufferData(bytes.slice(0, 12));
    failed.invokeAddress(failed.callbackPointers.read, [failed.provider, failed.sink, failed.buffer]);
    failed.invokeName('Cronet_UploadDataSink_OnReadError', [failed.sink, cString('private error', 'error')]);
    assert.equal(projectionEvents(failed).length, 0);
    assert.equal(failed.observer.getCoverage().active_flows, 0);
  });

  run('marker miss retains only safe schema, model, enum, ID, and usage projections', () => {
    const harness = makeHarness();
    driveKnownLength(harness, {body: fixtureBody(false), callbackLength: true, callbackRead: true});
    const event = projectionEvents(harness)[0];
    assert.equal(event.projection.marker_hit, false);
    assert.deepEqual(event.projection.marker_paths, []);
    assert.ok(event.projection.schema.some(field =>
      field.path[field.path.length - 1].value === 'function_name' && field.type === 'string'));
    assert.ok(event.projection.model_fields.some(field => field.value_state === 'target'));
    assert.deepEqual(new Set(event.projection.enum_fields.map(field => field.value)),
      new Set(['low', 'chat', 'builder', 2]));
    assert.ok(event.projection.id_hashes.some(field =>
      field.path[field.path.length - 1].value === 'session_id'));
    assert.deepEqual(event.projection.usage, []);
    const encoded = JSON.stringify(event);
    assert.equal(encoded.includes('SYNTHETIC_SESSION_ONLY'), false);
    assert.equal(encoded.includes('DO_NOT_PROJECT_SECRET'), false);
    assert.equal(encoded.includes('DO_NOT_PROJECT_PASSWORD'), false);
    assert.equal(encoded.includes('DO_NOT_PROJECT_DYNAMIC_FUNCTION'), false);
  });

  run('only field-specific repository-proven enum literals are projected', () => {
    const safeCandidate = Core.projectUploadBytes(utf8Encode(JSON.stringify({
      function: 'solo_agent'
    })), MARKER);
    assert.deepEqual(safeCandidate.enum_fields, [{
      path: [{kind: 'key', value: 'function'}], value: 'solo_agent'
    }]);

    const projection = Core.projectUploadBytes(utf8Encode(JSON.stringify({
      function: 'unknown_function', function_name: 'lookup_weather',
      agent_type: 'coder', scene_location: 99
    })), MARKER);
    assert.deepEqual(projection.enum_fields, []);
    assert.equal(projection.schema.some(field =>
      field.path[field.path.length - 1].value === 'function_name' && field.type === 'string'), true);
    assert.equal(projection.schema.some(field =>
      field.path[field.path.length - 1].value === 'scene_location' && field.type === 'integer'), true);
  });

  run('auth digest is private, uses exact UTF-8 bytes, allowlisted name, and strips one exact prefix', () => {
    const harness = makeHarness();
    driveKnownLength(harness, {callbackLength: true, callbackRead: true});
    const auth = harness.messages.filter(event => event.kind === 'native_auth_digest');
    assert.equal(auth.length, 1);
    assert.equal(auth[0].header_name, 'authorization');
    assert.equal(auth[0].header_prefix_kind, 'cloud_ide_jwt');
    assert.equal(auth[0].header_digest_sha256, Core.sha256Bytes(utf8Encode(TOKEN)));
    const publicText = JSON.stringify(harness.publicEvents());
    assert.equal(publicText.includes('header_digest_sha256'), false);
    assert.equal(publicText.includes(TOKEN), false);
    assert.equal(publicText.includes(PREFIX), false);

    const lowerPrefix = makeHarness({headerValue: 'cloud-ide-jwt ' + TOKEN});
    driveKnownLength(lowerPrefix, {callbackLength: true, callbackRead: true});
    const lowerAuth = lowerPrefix.messages.filter(event => event.kind === 'native_auth_digest');
    assert.equal(lowerAuth[0].header_prefix_kind, 'none');
    assert.equal(lowerAuth[0].header_digest_sha256,
      Core.sha256Bytes(utf8Encode('cloud-ide-jwt ' + TOKEN)));

    const repeatedPrefix = makeHarness({headerValue: PREFIX + PREFIX + TOKEN});
    driveKnownLength(repeatedPrefix, {callbackLength: true, callbackRead: true});
    const repeatedAuth = repeatedPrefix.messages.filter(event => event.kind === 'native_auth_digest');
    assert.equal(repeatedAuth[0].header_prefix_kind, 'cloud_ide_jwt');
    assert.equal(repeatedAuth[0].header_digest_sha256,
      Core.sha256Bytes(utf8Encode(PREFIX + TOKEN)));
  });

  run('the three allowlisted authentication headers are the only values digested', () => {
    for (const name of ['authorization', 'x-ide-token', 'x-cloudide-token']) {
      const harness = makeHarness({headerName: name});
      driveKnownLength(harness, {callbackLength: true, callbackRead: true});
      const digests = harness.messages.filter(event => event.kind === 'native_auth_digest');
      assert.equal(digests.length, 1);
      assert.equal(digests[0].header_name, name);
    }
  });

  run('non-allowlisted header values are never passed to the value getter', () => {
    const harness = makeHarness({headerName: 'x-icube-token', headerValue: 'PRIVATE_NOT_ALLOWED'});
    driveKnownLength(harness, {callbackLength: true, callbackRead: true});
    assert.equal(harness.messages.filter(event => event.kind === 'native_auth_digest').length, 0);
    assert.equal(harness.headerValueCalls, 0);
    assert.equal(JSON.stringify(harness.publicEvents()).includes('PRIVATE_NOT_ALLOWED'), false);
  });

  run('projection core accepts JSON null, exact SHA-256 bytes, and rejects malformed UTF-8', () => {
    const nullProjection = Core.projectUploadBytes(utf8Encode('null'), MARKER);
    assert.equal(nullProjection.parse_state, 'json');
    assert.equal(Core.sha256Ascii('abc'), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
    const utf8 = utf8Encode('中文');
    assert.equal(Core.sha256Bytes(utf8), '72726d8818f693066ceb69afa364218b692e62ea92b385782363780f47529c21');
    const malformed = Core.projectUploadBytes(new Uint8Array([0x7b, 0x22, 0x78, 0x22, 0x3a, 0x22, 0xe4]), MARKER);
    assert.equal(malformed.parse_state, 'invalid_utf8');
  });

  run('observer emits a bounded 128-field synthetic projection for writer stress coverage', () => {
    const harness = makeHarness();
    driveKnownLength(harness, {body: stressFixtureBody(), callbackLength: true, callbackRead: true});
    const events = projectionEvents(harness);
    assert.equal(events.length, 1);
    const event = events[0];
    assert.equal(event.projection.parse_state, 'json');
    assert.equal(event.projection.marker_hit, false);
    assert.equal(event.projection.schema.length, 128);
    assert.ok(event.projection.schema.every(field => field.path.length <= 16));
    assert.ok(Buffer.byteLength(JSON.stringify(event) + '\n', 'utf8') > 32 * 1024);
    assert.ok(Buffer.byteLength(JSON.stringify(event) + '\n', 'utf8') < 128 * 1024);
    const encoded = JSON.stringify(event);
    assert.equal(encoded.includes(MARKER), false);
    assert.equal(encoded.includes('SYNTHETIC'), false);
    assert.equal(encoded.includes('null'), true);
  });

  console.log(JSON.stringify({self_test: 'passed', cases}));
}
