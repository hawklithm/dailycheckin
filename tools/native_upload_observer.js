'use strict';

// Passive, upload-only Cronet observer. The Python runner concatenates
// native_upload_projection_core.js before this file and supplies a JSON config.
// Only exact allowlisted AgentV3 POSTs are projected. No response callbacks or
// response buffers are read.
const NativeUploadProjectionCoreForObserver = typeof NativeUploadProjectionCore !== 'undefined'
  ? NativeUploadProjectionCore
  : (typeof require === 'function' ? require('./native_upload_projection_core.js') : null);

const NativeUploadObserver = (function (Core) {
  const ROUTE_PATHS = new Map([
    ['/api/agent/v3/create_agent_task', 'create_agent_task'],
    ['/api/agent/v3/llm_utils_chat', 'llm_utils_chat'],
    ['/api/agent/v3/workflow/start', 'workflow_start']
  ]);
  const HEADER_ALLOWLIST = new Set([
    'authorization', 'x-ide-token', 'x-cloudide-token'
  ]);
  const CLOUD_IDE_PREFIX = [67, 108, 111, 117, 100, 45, 73, 68, 69, 45, 74, 87, 84, 32];
  const MAX_URL_BYTES = 4096;
  const MAX_METHOD_BYTES = 16;
  const MAX_HEADERS = 64;
  const MAX_HEADER_VALUE_BYTES = 16384;
  const MAX_PRIVATE_AUTH_EVENTS = 192;
  const MAX_PUBLIC_EVENTS = 128;
  const MAX_PENDING_REQUESTS = 128;
  const MAX_CALLBACK_POINTERS = 256;
  const EXPECTED_MODEL = 'deepseek-v4.1-flash';
  const EXPECTED_GATEWAY_HOST = 'trae-api-cn.mchost.guru';

  const EXPORT_NAMES = [
    'Cronet_UrlRequest_InitWithParams', 'Cronet_UrlRequest_Start',
    'Cronet_UrlRequestParams_http_method_get',
    'Cronet_UrlRequestParams_upload_data_provider_get',
    'Cronet_UrlRequestParams_request_headers_size',
    'Cronet_UrlRequestParams_request_headers_at',
    'Cronet_HttpHeader_name_get', 'Cronet_HttpHeader_value_get',
    'Cronet_UploadDataProvider_CreateWith',
    'Cronet_UploadDataProvider_GetLength', 'Cronet_UploadDataProvider_Read',
    'Cronet_UploadDataProvider_Rewind', 'Cronet_UploadDataProvider_Close',
    'Cronet_UploadDataSink_OnReadSucceeded', 'Cronet_UploadDataSink_OnReadError',
    'Cronet_UploadDataSink_OnRewindError',
    'Cronet_Buffer_GetSize', 'Cronet_Buffer_GetData'
  ];
  const HOOK_EXPORTS = [
    'Cronet_UrlRequest_InitWithParams', 'Cronet_UrlRequest_Start',
    'Cronet_UploadDataProvider_CreateWith', 'Cronet_UploadDataProvider_GetLength',
    'Cronet_UploadDataProvider_Read', 'Cronet_UploadDataProvider_Rewind',
    'Cronet_UploadDataProvider_Close', 'Cronet_UploadDataSink_OnReadSucceeded',
    'Cronet_UploadDataSink_OnReadError', 'Cronet_UploadDataSink_OnRewindError'
  ];
  const REQUIRED_BODY_EXPORTS = [
    'Cronet_UrlRequest_InitWithParams', 'Cronet_UrlRequest_Start',
    'Cronet_UrlRequestParams_http_method_get',
    'Cronet_UrlRequestParams_upload_data_provider_get',
    'Cronet_UploadDataProvider_CreateWith', 'Cronet_UploadDataProvider_GetLength',
    'Cronet_UploadDataProvider_Read', 'Cronet_UploadDataProvider_Rewind',
    'Cronet_UploadDataProvider_Close', 'Cronet_UploadDataSink_OnReadSucceeded',
    'Cronet_UploadDataSink_OnReadError', 'Cronet_UploadDataSink_OnRewindError',
    'Cronet_Buffer_GetSize', 'Cronet_Buffer_GetData'
  ];

  function normalizedPath(value) {
    return String(value || '').replace(/\\/g, '/').toLowerCase();
  }

  function ptrKey(pointer) {
    try {
      if (!pointer || (typeof pointer.isNull === 'function' && pointer.isNull())) return '';
      const value = pointer.toString();
      return typeof value === 'string' && value.length <= 128 ? value.toLowerCase() : '';
    } catch (_) { return ''; }
  }

  function pointerIsNull(pointer) {
    try { return !pointer || (typeof pointer.isNull === 'function' && pointer.isNull()); }
    catch (_) { return true; }
  }

  function nativeIntegerText(value) {
    try { return value && typeof value.toString === 'function' ? value.toString() : String(value); }
    catch (_) { return null; }
  }

  function parseHexUnsignedBounded(text, maximum) {
    if (typeof text !== 'string' || !/^0x[0-9a-f]{1,16}$/i.test(text)) return null;
    const digits = text.slice(2).replace(/^0+/, '').toLowerCase() || '0';
    const cap = maximum.toString(16);
    if (digits.length > cap.length || (digits.length === cap.length && digits > cap)) return null;
    const number = parseInt(digits, 16);
    return Number.isSafeInteger(number) && number <= maximum ? number : null;
  }

  function pointerBytes(pointer, maximum, stopAtQuery) {
    if (pointerIsNull(pointer)) return null;
    const bytes = [];
    try {
      for (let index = 0; index < maximum; index++) {
        const value = pointer.add(index).readU8();
        if (value === 0 || (stopAtQuery && (value === 63 || value === 35))) {
          return new Uint8Array(bytes);
        }
        bytes.push(value);
      }
    } catch (_) { return null; }
    return null;
  }

  function asciiString(bytes) {
    if (!(bytes instanceof Uint8Array)) return null;
    let value = '';
    for (let index = 0; index < bytes.length; index++) {
      const byte = bytes[index];
      if (byte < 0x20 || byte > 0x7e) return null;
      value += String.fromCharCode(byte);
    }
    return value;
  }

  function parseUnsignedBounded(value, maximum) {
    const text = nativeIntegerText(value);
    if (text === null) return null;
    if (/^0x/i.test(text)) return parseHexUnsignedBounded(text, maximum);
    if (!/^(?:0|[1-9][0-9]*)$/.test(text) || text.length > 16) return null;
    if (text.length > String(maximum).length ||
        (text.length === String(maximum).length && text > String(maximum))) return null;
    const number = Number(text);
    return Number.isSafeInteger(number) && number <= maximum ? number : null;
  }

  function parseSignedLength(value, maximum) {
    const text = nativeIntegerText(value);
    if (text === null) return null;
    if (text === '-1' || /^0xffffffffffffffff$/i.test(text)) return -1;
    if (/^0x/i.test(text)) return parseHexUnsignedBounded(text, maximum);
    if (!/^(?:0|[1-9][0-9]*)$/.test(text) || text.length > 16) return null;
    if (text.length > String(maximum).length ||
        (text.length === String(maximum).length && text > String(maximum))) return null;
    const number = Number(text);
    return Number.isSafeInteger(number) && number <= maximum ? number : null;
  }

  function decodeRouteUrl(urlPointer) {
    const bytes = pointerBytes(urlPointer, MAX_URL_BYTES, true);
    if (!bytes) return null;
    const prefix = asciiString(bytes);
    if (!prefix) return null;
    const match = /^(https?):\/\/([^/]+)(\/.*)?$/i.exec(prefix);
    if (!match || match[2].indexOf('@') !== -1) return null;
    const scheme = match[1].toLowerCase();
    const authority = match[2].toLowerCase();
    let host = authority;
    let port = scheme === 'https' ? 443 : 80;
    const colon = authority.lastIndexOf(':');
    if (colon > 0 && authority.indexOf(':') === colon) {
      const portText = authority.slice(colon + 1);
      if (!/^[0-9]{1,5}$/.test(portText)) return null;
      port = Number(portText);
      if (port < 1 || port > 65535) return null;
      host = authority.slice(0, colon);
    }
    if (!/^[a-z0-9.-]{1,253}$/.test(host) || host.includes('..')) return null;
    return {scheme: scheme, host: host, port: port, path: match[3] || '/'};
  }

  function validUtf8(bytes) {
    for (let index = 0; index < bytes.length;) {
      const first = bytes[index++];
      if (first <= 0x7f) {
        if (first < 0x20 || first === 0x7f) return false;
      } else if (first >= 0xc2 && first <= 0xdf) {
        if (index >= bytes.length || (bytes[index++] & 0xc0) !== 0x80) return false;
      } else if (first >= 0xe0 && first <= 0xef) {
        if (index + 1 >= bytes.length) return false;
        const second = bytes[index++], third = bytes[index++];
        if ((second & 0xc0) !== 0x80 || (third & 0xc0) !== 0x80 ||
            (first === 0xe0 && second < 0xa0) || (first === 0xed && second >= 0xa0)) return false;
      } else if (first >= 0xf0 && first <= 0xf4) {
        if (index + 2 >= bytes.length) return false;
        const second = bytes[index++], third = bytes[index++], fourth = bytes[index++];
        if ((second & 0xc0) !== 0x80 || (third & 0xc0) !== 0x80 || (fourth & 0xc0) !== 0x80 ||
            (first === 0xf0 && second < 0x90) || (first === 0xf4 && second >= 0x90)) return false;
      } else return false;
    }
    return true;
  }

  function normalizedHeaderDigest(valuePointer) {
    const bytes = pointerBytes(valuePointer, MAX_HEADER_VALUE_BYTES, false);
    if (!bytes || !bytes.length || !validUtf8(bytes)) return null;
    let prefixKind = 'none';
    let offset = 0;
    if (bytes.length >= CLOUD_IDE_PREFIX.length) {
      let match = true;
      for (let index = 0; index < CLOUD_IDE_PREFIX.length; index++) {
        if (bytes[index] !== CLOUD_IDE_PREFIX[index]) { match = false; break; }
      }
      if (match) {
        prefixKind = 'cloud_ide_jwt';
        offset = CLOUD_IDE_PREFIX.length;
      }
    }
    const tokenBytes = bytes.slice(offset);
    const digest = Core.sha256Bytes(tokenBytes);
    tokenBytes.fill(0);
    bytes.fill(0);
    return digest ? {prefix_kind: prefixKind, digest: digest} : null;
  }

  function validRouteConfig(config) {
    if (!config || !Array.isArray(config.route_allowlist) || config.route_allowlist.length !== 3) return null;
    if (config.target_model !== EXPECTED_MODEL) return null;
    if (typeof config.marker !== 'string' || config.marker.length < 8 || config.marker.length > 64) return null;
    const routes = new Map();
    for (const route of config.route_allowlist) {
      if (!route || typeof route.path !== 'string' || ROUTE_PATHS.get(route.path) !== route.route_name ||
          route.method !== 'POST' || route.host !== EXPECTED_GATEWAY_HOST || route.port !== 443 ||
          route.path_sha256 !== Core.hashPathKey(route.path) || routes.has(route.path)) return null;
      routes.set(route.path, {
        path: route.path, path_sha256: route.path_sha256, host: route.host,
        port: route.port, method: route.method, route_name: route.route_name
      });
    }
    for (const path of ROUTE_PATHS.keys()) if (!routes.has(path)) return null;
    return routes;
  }

  function validCallbackManifest(config) {
    if (!Array.isArray(config.callback_modules) || config.callback_modules.length > 256) return null;
    const manifest = [];
    for (const item of config.callback_modules) {
      if (!item || typeof item.module_name !== 'string' || typeof item.module_path !== 'string' ||
          !/^[0-9a-f]{64}$/i.test(item.module_sha256) ||
          !Number.isSafeInteger(item.memory_size) || item.memory_size <= 0 ||
          !Array.isArray(item.executable_ranges) || item.executable_ranges.length > 64) return null;
      const ranges = [];
      for (const range of item.executable_ranges) {
        if (!range || !Number.isSafeInteger(range.rva_start) || !Number.isSafeInteger(range.rva_end) ||
            range.rva_start < 0 || range.rva_end <= range.rva_start || range.rva_end > item.memory_size) return null;
        ranges.push({rva_start: range.rva_start, rva_end: range.rva_end});
      }
      manifest.push({
        module_name: item.module_name.toLowerCase(), module_path: normalizedPath(item.module_path),
        module_sha256: item.module_sha256.toLowerCase(), memory_size: item.memory_size,
        executable_ranges: ranges
      });
    }
    return manifest;
  }

  function install(config, injectedRuntime) {
    const runtime = injectedRuntime || {
      Process: Process, Interceptor: Interceptor, NativeFunction: NativeFunction,
      send: send, setInterval: setInterval, clearInterval: clearInterval,
      setTimeout: setTimeout, clearTimeout: clearTimeout
    };
    const publicEvents = [];
    const listeners = [];
    const hookGroups = new Map();
    const requests = new Map();
    const providers = new Map();
    const pendingReads = new Map();
    const pendingBuffers = new Map();
    const sinkOwners = new Map();
    const requestCallbackKeys = new Set();
    const requestCallbackOwners = new Map();
    const callbacksByAddress = new Map();
    const callbackModules = validCallbackManifest(config || {});
    const routes = validRouteConfig(config || {});
    const stats = {
      init_calls: 0, start_calls: 0, route_eligible: 0, flow_started: 0,
      provider_bound: 0, get_length_seen: 0, read_wrapper: 0, read_callback: 0,
      read_ack: 0, upload_projection: 0, marker_candidate: 0,
      callback_attached: 0, callback_module_skip: 0, callback_alias_skip: 0,
      callback_attach_failure: 0, route_skip: 0, request_pointer_collision: 0,
      provider_pointer_collision: 0, pending_read_collision: 0,
      length_invalid: 0, buffer_invalid: 0, read_error: 0, rewind_invalidated: 0,
      close_invalidated: 0, auth_digest_sent: 0, auth_digest_skip: 0,
      output_cap_skip: 0, pending_at_end: 0
    };
    let active = true;
    let privateAuthEvents = 0;
    let nextCallbackId = 0;
    let callbackAttachments = 0;
    let hookInstallStatus = null;
    let attachedPublicGroups = 0;
    const attachedPublicNames = new Set();

    function sendSafe(record, privateMessage) {
      if (!active && !privateMessage) return false;
      if (!privateMessage) {
        if (publicEvents.length >= MAX_PUBLIC_EVENTS) { stats.output_cap_skip++; return false; }
        publicEvents.push(record);
      }
      try { runtime.send(record); return true; }
      catch (_) { return false; }
    }

    function providerFlow(providerKey) { return providers.get(providerKey) || null; }

    function removePendingForFlow(flow) {
      for (const [sinkKey, record] of pendingReads) {
        if (record.flow !== flow) continue;
        pendingReads.delete(sinkKey);
        if (pendingBuffers.get(record.bufferKey) === sinkKey) pendingBuffers.delete(record.bufferKey);
        if (sinkOwners.get(sinkKey) === flow.providerKey) sinkOwners.delete(sinkKey);
      }
    }

    function removeRuntimeFlow(flow) {
      if (!flow) return;
      if (requests.get(flow.requestKey) === flow) requests.delete(flow.requestKey);
      if (flow.providerKey && providers.get(flow.providerKey) === flow) providers.delete(flow.providerKey);
      if (flow.callbackKey) {
        const owners = requestCallbackOwners.get(flow.callbackKey);
        if (owners) {
          owners.delete(flow.requestKey);
          if (!owners.size) {
            requestCallbackOwners.delete(flow.callbackKey);
            requestCallbackKeys.delete(flow.callbackKey);
          }
        }
      }
      removePendingForFlow(flow);
      flow.authDigests = [];
      flow.pendingLength = null;
    }

    function invalidateFlow(flow, reason) {
      if (!flow) return;
      if (flow.requestKey) core.invalidateRequest(flow.requestKey, reason);
      removeRuntimeFlow(flow);
    }

    function processRead(providerKey, sinkPointer, bufferPointer, source) {
      const flow = providerFlow(providerKey);
      if (!flow || !flow.started) return null;
      const sinkKey = ptrKey(sinkPointer), bufferKey = ptrKey(bufferPointer);
      if (!sinkKey || !bufferKey || requestCallbackKeys.has(providerKey) ||
          sinkKey === flow.requestKey || bufferKey === flow.requestKey ||
          bufferKey === flow.providerKey || bufferKey === flow.callbackKey ||
          sinkKey === flow.providerKey || sinkKey === flow.callbackKey ||
          providers.has(bufferKey) || requests.has(bufferKey) ||
          providers.has(sinkKey) || requests.has(sinkKey) || requestCallbackKeys.has(sinkKey)) {
        stats.pending_read_collision++;
        if (providers.has(bufferKey)) invalidateFlow(providers.get(bufferKey), 'typed_pointer_collision');
        if (providers.has(sinkKey)) invalidateFlow(providers.get(sinkKey), 'typed_pointer_collision');
        invalidateFlow(flow, 'typed_pointer_collision');
        return null;
      }
      const priorAtSink = pendingReads.get(sinkKey);
      if (priorAtSink && priorAtSink.flow !== flow) {
        stats.pending_read_collision++;
        invalidateFlow(priorAtSink.flow, 'typed_pointer_collision');
        invalidateFlow(flow, 'typed_pointer_collision');
        return null;
      }
      const priorSink = pendingBuffers.get(bufferKey);
      if (priorSink && priorSink !== sinkKey) {
        const priorRead = pendingReads.get(priorSink);
        stats.pending_read_collision++;
        if (priorRead) invalidateFlow(priorRead.flow, 'typed_pointer_collision');
        invalidateFlow(flow, 'typed_pointer_collision');
        return null;
      }
      const capacityValue = safeGetter(readers.bufferSize, bufferPointer);
      const capacity = parseUnsignedBounded(capacityValue, Core.MAX_UPLOAD_BYTES);
      if (capacity === null || capacity <= 0) {
        stats.buffer_invalid++;
        invalidateFlow(flow, 'buffer_capacity_invalid');
        return null;
      }
      const result = core.beginRead(providerKey, sinkKey, bufferKey, capacity, source);
      if (!result.accepted) {
        if (result.reason !== 'provider_unmapped') invalidateFlow(flow, result.reason);
        return null;
      }
      if (result.duplicate === true) {
        const existing = pendingReads.get(sinkKey);
        if (!existing || existing.bufferKey !== bufferKey || existing.capacity !== capacity ||
            existing.flow !== flow) {
          stats.pending_read_collision++;
          invalidateFlow(flow, 'duplicate_read_mapping_mismatch');
          return null;
        }
        return existing;
      }
      const record = {
        ticket: result.ticket, flow: flow, providerKey: providerKey,
        sinkKey: sinkKey, bufferKey: bufferKey, capacity: capacity,
        bufferPointer: bufferPointer
      };
      pendingReads.set(sinkKey, record);
      pendingBuffers.set(bufferKey, sinkKey);
      sinkOwners.set(sinkKey, providerKey);
      if (source === 'callback') stats.read_callback++; else stats.read_wrapper++;
      return record;
    }

    function safeGetter(getter, argument) {
      if (typeof getter !== 'function') return null;
      try { return getter(argument); } catch (_) { return null; }
    }

    function readAuthDigests(params, requestSeq) {
      if (!readers.headersReady) { stats.auth_digest_skip++; return []; }
      let count;
      try { count = readers.headersSize(params); } catch (_) { stats.auth_digest_skip++; return []; }
      if (!Number.isInteger(count) || count < 0 || count > MAX_HEADERS) {
        stats.auth_digest_skip++;
        return [];
      }
      const digests = [];
      for (let index = 0; index < count; index++) {
        let header, namePointer, nameBytes, name, valuePointer, normalized;
        try {
          header = readers.headersAt(params, index);
          if (pointerIsNull(header)) continue;
          namePointer = readers.headerName(header);
          nameBytes = pointerBytes(namePointer, 128, false);
          name = asciiString(nameBytes);
          if (!name || !HEADER_ALLOWLIST.has(name.toLowerCase())) continue;
          valuePointer = readers.headerValue(header);
          normalized = normalizedHeaderDigest(valuePointer);
        } catch (_) { normalized = null; }
        if (!normalized) { stats.auth_digest_skip++; continue; }
        digests.push({
          request_seq: requestSeq, header_name: name.toLowerCase(),
          header_prefix_kind: normalized.prefix_kind,
          header_digest_sha256: normalized.digest
        });
        if (digests.length >= 8) break;
      }
      return digests;
    }

    function emitPrivateAuth(flow) {
      if (!flow || !Array.isArray(flow.authDigests)) return;
      for (const item of flow.authDigests) {
        if (privateAuthEvents >= MAX_PRIVATE_AUTH_EVENTS) { stats.auth_digest_skip++; break; }
        privateAuthEvents++;
        const sent = sendSafe({
          kind: 'native_auth_digest', request_seq: item.request_seq,
          header_name: item.header_name, header_prefix_kind: item.header_prefix_kind,
          header_digest_sha256: item.header_digest_sha256
        }, true);
        if (sent) stats.auth_digest_sent++; else stats.auth_digest_skip++;
      }
      flow.authDigests = [];
    }

    function invalidateProvider(providerKey, reason) {
      const flow = providerFlow(providerKey);
      if (!flow) return false;
      if (reason === 'rewind') stats.rewind_invalidated++;
      if (reason === 'close') stats.close_invalidated++;
      invalidateFlow(flow, reason);
      return true;
    }

    function processLength(providerKey, nativeLength) {
      const flow = providerFlow(providerKey);
      if (!flow) return;
      const length = parseSignedLength(nativeLength, Core.MAX_UPLOAD_BYTES);
      if (length === null) {
        stats.length_invalid++;
        invalidateFlow(flow, 'length_invalid');
        return;
      }
      stats.get_length_seen++;
      if (!flow.started) {
        if (flow.pendingLength !== null && flow.pendingLength !== length) {
          stats.length_invalid++;
          invalidateFlow(flow, 'length_changed');
          return;
        }
        flow.pendingLength = length;
        return;
      }
      const result = core.reportLength(providerKey, length);
      if (!result.accepted) {
        if (result.reason === 'length_changed' || result.reason === 'length_out_of_range') stats.length_invalid++;
        invalidateFlow(flow, result.reason);
        return;
      }
      if (result.empty_upload === true) removeRuntimeFlow(flow);
    }

    function processAck(sinkPointer, bytesReadNative, finalNative) {
      const sinkKey = ptrKey(sinkPointer);
      const record = pendingReads.get(sinkKey);
      if (!record) return;
      const bytesRead = parseUnsignedBounded(bytesReadNative, record.capacity);
      const finalNumber = parseUnsignedBounded(finalNative, 1);
      if (bytesRead === null || (finalNumber !== 0 && finalNumber !== 1)) {
        stats.buffer_invalid++;
        invalidateFlow(record.flow, 'read_ack_invalid');
        return;
      }
      const capacityValue = safeGetter(readers.bufferSize, record.bufferPointer);
      const capacityNow = parseUnsignedBounded(capacityValue, Core.MAX_UPLOAD_BYTES);
      if (capacityNow === null || capacityNow !== record.capacity) {
        stats.buffer_invalid++;
        invalidateFlow(record.flow, 'buffer_snapshot_mismatch');
        return;
      }
      let chunk = new Uint8Array(0);
      if (bytesRead > 0) {
        let dataPointer;
        try { dataPointer = readers.bufferData(record.bufferPointer); }
        catch (_) { dataPointer = null; }
        if (pointerIsNull(dataPointer)) {
          stats.buffer_invalid++;
          invalidateFlow(record.flow, 'buffer_data_unavailable');
          return;
        }
        try {
          const arrayBuffer = dataPointer.readByteArray(bytesRead);
          if (!arrayBuffer || arrayBuffer.byteLength !== bytesRead) throw new Error('short_buffer');
          chunk = new Uint8Array(arrayBuffer);
        } catch (_) {
          stats.buffer_invalid++;
          invalidateFlow(record.flow, 'buffer_copy_failed');
          return;
        }
      }
      const result = core.ackRead(sinkKey, bytesRead, capacityNow, finalNumber === 1, chunk);
      chunk.fill(0);
      pendingReads.delete(sinkKey);
      if (pendingBuffers.get(record.bufferKey) === sinkKey) pendingBuffers.delete(record.bufferKey);
      if (sinkOwners.get(sinkKey) === record.providerKey) sinkOwners.delete(sinkKey);
      if (!result.accepted) {
        invalidateFlow(record.flow, result.reason);
        return;
      }
      stats.read_ack++;
      if (result.upload_pending !== true) removeRuntimeFlow(record.flow);
    }

    function sinkError(sinkPointer) {
      stats.read_error++;
      const sinkKey = ptrKey(sinkPointer);
      const read = pendingReads.get(sinkKey);
      const providerKey = read ? read.providerKey : sinkOwners.get(sinkKey);
      if (read) invalidateFlow(read.flow, 'upload_sink_error');
      else if (providerKey) invalidateProvider(providerKey, 'upload_sink_error');
    }

    function addHook(name, address, handler) {
      if (!address) return false;
      const key = ptrKey(address);
      if (!key) return false;
      let group = hookGroups.get(key);
      if (!group) {
        group = {address: address, names: [], handlers: []};
        hookGroups.set(key, group);
      }
      if (group.names.indexOf(name) < 0) group.names.push(name);
      group.handlers.push(handler);
      return true;
    }

    function attachHooks() {
      for (const group of hookGroups.values()) {
        try {
          const listener = runtime.Interceptor.attach(group.address, {
            onEnter: function (args) {
              for (let index = 0; index < group.handlers.length; index++) {
                const item = group.handlers[index];
                if (item.onEnter) {
                  try { item.onEnter.call(this, args); } catch (_) {}
                }
              }
            },
            onLeave: function (retval) {
              for (let index = 0; index < group.handlers.length; index++) {
                const item = group.handlers[index];
                if (item.onLeave) {
                  try { item.onLeave.call(this, retval); } catch (_) {}
                }
              }
            }
          });
          listeners.push(listener);
          attachedPublicGroups++;
          for (const name of group.names) attachedPublicNames.add(name);
        } catch (_) {
          for (const name of group.names) missing.push(name);
        }
      }
    }

    function callbackManifestFor(pointer) {
      let module, range;
      try {
        module = runtime.Process.findModuleByAddress(pointer);
        range = runtime.Process.findRangeByAddress(pointer);
      } catch (_) { return null; }
      if (!module || !range || typeof range.protection !== 'string' || !range.protection.includes('x')) return null;
      const moduleName = String(module.name || '').toLowerCase();
      const modulePath = normalizedPath(module.path);
      const memorySize = Number(module.size);
      const item = callbackModules.find(candidate => candidate.module_name === moduleName &&
        candidate.module_path === modulePath && candidate.memory_size === memorySize);
      if (!item) return null;
      let rvaText;
      try { rvaText = pointer.sub(module.base).toString().replace(/^0x/i, ''); }
      catch (_) { return null; }
      if (!/^[0-9a-f]{1,8}$/i.test(rvaText)) return null;
      const rva = parseInt(rvaText, 16);
      if (!Number.isSafeInteger(rva) || !item.executable_ranges.some(section =>
        rva >= section.rva_start && rva < section.rva_end)) return null;
      return {manifest: item, module: module, range: range, rva: rva};
    }

    function callbackCall(role, args, retval, onLeave) {
      const providerKey = ptrKey(args[0]);
      if (!providerFlow(providerKey)) return;
      if (role === 'get_length' && onLeave) processLength(providerKey, retval);
      else if (role === 'read' && !onLeave) processRead(providerKey, args[1], args[2], 'callback');
      else if (role === 'rewind' && !onLeave) invalidateProvider(providerKey, 'rewind');
      else if (role === 'close' && !onLeave) invalidateProvider(providerKey, 'close');
    }

    function registerCallback(pointer, role, providerKey) {
      const address = ptrKey(pointer);
      if (!address) return;
      if (callbacksByAddress.size >= MAX_CALLBACK_POINTERS && !callbacksByAddress.has(address)) {
        stats.callback_module_skip++;
        return;
      }
      const verified = callbackManifestFor(pointer);
      if (!verified) { stats.callback_module_skip++; return; }
      let record = callbacksByAddress.get(address);
      if (!record) {
        record = {address: pointer, roles: new Set(), providers: new Set(), manifest: verified.manifest, ambiguous: false, listener: null};
        callbacksByAddress.set(address, record);
      }
      record.providers.add(providerKey);
      record.roles.add(role);
      if (record.roles.size !== 1) {
        record.ambiguous = true;
        stats.callback_alias_skip++;
        if (record.listener) {
          try { record.listener.detach(); } catch (_) {}
          record.listener = null;
        }
        for (const key of record.providers) invalidateProvider(key, 'callback_role_alias');
        return;
      }
      if (record.listener) return;
      const callbackRole = role;
      try {
        record.listener = runtime.Interceptor.attach(pointer, {
          onEnter: function (args) {
            if (record.ambiguous || !record.roles.has(callbackRole)) return;
            this.providerKey = ptrKey(args[0]);
            callbackCall(callbackRole, args, null, false);
          },
          onLeave: function (retval) {
            if (record.ambiguous || !record.roles.has(callbackRole)) return;
            if (callbackRole === 'get_length' && this.providerKey) {
              processLength(this.providerKey, retval);
            }
          }
        });
        listeners.push(record.listener);
        stats.callback_attached++;
        sendSafe({kind: 'callback_attached', attached: true, role: role,
          module_name: verified.manifest.module_name,
          module_sha256: verified.manifest.module_sha256,
          rva: verified.rva}, true);
      } catch (_) {
        stats.callback_attach_failure++;
        record.listener = null;
      }
    }

    function captureAuth(params, flow) {
      flow.authDigests = readAuthDigests(params, flow.requestSeq);
    }

    const missing = [];
    if (!routes || !callbackModules || !config || !Number.isSafeInteger(config.pid) ||
        typeof config.expected_module_path !== 'string' || !/^[0-9a-f]{64}$/i.test(config.expected_module_sha256 || '') ||
        !Number.isSafeInteger(config.expected_module_size) || config.expected_module_size <= 0) {
      sendSafe({kind: 'hook_install', pid: config && config.pid || 0, hook_count: 0,
        hooks: [], missing: ['invalid_config'], module_name: null,
        module_path_match: false, module_size_match: false,
        method_getter_ready: false, header_getters_ready: false,
        upload_api_ready: false, response_api_ready: false}, false);
      return {stop: function () {}, getCoverage: function () { return {}; }};
    }
    if (runtime.Process.id !== config.pid) {
      sendSafe({kind: 'hook_install', pid: config.pid, hook_count: 0,
        hooks: [], missing: ['pid_mismatch'], module_name: null,
        module_path_match: false, module_size_match: false,
        method_getter_ready: false, header_getters_ready: false,
        upload_api_ready: false, response_api_ready: false}, false);
      return {stop: function () {}, getCoverage: function () { return {}; }};
    }

    let module;
    try { module = runtime.Process.getModuleByName('sscronet.dll'); }
    catch (_) { module = null; }
    const modulePathMatch = !!module && normalizedPath(module.path) === normalizedPath(config.expected_module_path);
    const moduleSizeMatch = !!module && Number(module.size) === config.expected_module_size;
    if (!module || !modulePathMatch || !moduleSizeMatch) {
      sendSafe({kind: 'hook_install', pid: config.pid, hook_count: 0,
        hooks: [], missing: [!module ? 'sscronet_missing' : (!modulePathMatch ? 'module_path_mismatch' : 'module_size_mismatch')],
        module_name: module ? module.name : null, module_path_match: modulePathMatch,
        module_size_match: moduleSizeMatch, method_getter_ready: false,
        header_getters_ready: false, upload_api_ready: false,
        response_api_ready: false}, false);
      return {stop: function () {}, getCoverage: function () { return {}; }};
    }

    const exports = Object.create(null);
    for (const name of EXPORT_NAMES) {
      try { exports[name] = module.findExportByName(name); }
      catch (_) { exports[name] = null; }
    }
    const addresses = Object.create(null);
    for (const name of Object.keys(exports)) addresses[name] = exports[name];
    let readers = {
      method: null, provider: null, headersSize: null, headersAt: null,
      headerName: null, headerValue: null, bufferSize: null, bufferData: null,
      methodReady: false, headersReady: false, bodyReady: false
    };
    function makeReader(name, returnType, argTypes) {
      if (!addresses[name]) return null;
      try { return new runtime.NativeFunction(addresses[name], returnType, argTypes); }
      catch (_) { return null; }
    }
    readers.method = makeReader('Cronet_UrlRequestParams_http_method_get', 'pointer', ['pointer']);
    readers.provider = makeReader('Cronet_UrlRequestParams_upload_data_provider_get', 'pointer', ['pointer']);
    readers.headersSize = makeReader('Cronet_UrlRequestParams_request_headers_size', 'uint', ['pointer']);
    readers.headersAt = makeReader('Cronet_UrlRequestParams_request_headers_at', 'pointer', ['pointer', 'uint']);
    readers.headerName = makeReader('Cronet_HttpHeader_name_get', 'pointer', ['pointer']);
    readers.headerValue = makeReader('Cronet_HttpHeader_value_get', 'pointer', ['pointer']);
    readers.bufferSize = makeReader('Cronet_Buffer_GetSize', 'uint64', ['pointer']);
    readers.bufferData = makeReader('Cronet_Buffer_GetData', 'pointer', ['pointer']);
    readers.methodReady = typeof readers.method === 'function';
    readers.headersReady = typeof readers.headersSize === 'function' &&
      typeof readers.headersAt === 'function' && typeof readers.headerName === 'function' &&
      typeof readers.headerValue === 'function';
    readers.bodyReady = typeof readers.provider === 'function' &&
      typeof readers.bufferSize === 'function' && typeof readers.bufferData === 'function';
    const bodyExportsReady = REQUIRED_BODY_EXPORTS.every(name => !!addresses[name]);
    const hookExportsReady = HOOK_EXPORTS.every(name => !!addresses[name]);
    let bodyApiReady = readers.bodyReady && bodyExportsReady && hookExportsReady;
    const headerGettersReady = readers.headersReady;
    const methodGetterReady = readers.methodReady;
    const core = Core.createCaptureModel({
      marker: config.marker,
      emit: function (event) {
        if (event && event.kind === 'upload_projection') {
          stats.upload_projection++;
          if (event.projection && event.projection.marker_hit === true) stats.marker_candidate++;
        }
        sendSafe(event, false);
      }
    });

    function readMethod(params) {
      if (!readers.methodReady) return null;
      return asciiString(pointerBytes(readers.method(params), MAX_METHOD_BYTES, false));
    }

    function routeFor(urlPointer, params) {
      const url = decodeRouteUrl(urlPointer);
      const method = readMethod(params);
      if (!url || !method) return null;
      for (const route of routes.values()) {
        if (url.scheme === 'https' && url.host === route.host && url.port === route.port &&
            url.path === route.path && method === route.method &&
            Core.hashPathKey(url.path) === route.path_sha256) return route;
      }
      return null;
    }

    function getLengthHandler() {
      return {
        onEnter: function (args) { this.providerKey = ptrKey(args[0]); },
        onLeave: function (retval) { if (this.providerKey) processLength(this.providerKey, retval); }
      };
    }

    function getReadHandler(source) {
      return {
        onEnter: function (args) {
          const providerKey = ptrKey(args[0]);
          if (!providerFlow(providerKey)) return;
          this.providerKey = providerKey;
          processRead(providerKey, args[1], args[2], source);
        }
      };
    }

    function getRewindHandler() {
      return {onEnter: function (args) { invalidateProvider(ptrKey(args[0]), 'rewind'); }};
    }

    function getCloseHandler() {
      return {onEnter: function (args) {
        const key = ptrKey(args[0]);
        if (pendingBuffers.has(key) && providers.has(key)) {
          stats.provider_pointer_collision++;
          invalidateProvider(key, 'provider_buffer_alias');
          const sink = pendingBuffers.get(key);
          const record = pendingReads.get(sink);
          if (record) invalidateFlow(record.flow, 'provider_buffer_alias');
          return;
        }
        if (providers.has(key)) invalidateProvider(key, 'close');
        // This export aliases Buffer_GetData in the installed build. A typed
        // buffer pointer is intentionally ignored here; only provider-map hits
        // can reach the Close lifecycle branch.
      }};
    }

    function getReadSucceededHandler() {
      return {onEnter: function (args) { processAck(args[0], args[1], args[2]); }};
    }

    function getSinkErrorHandler() {
      return {onEnter: function (args) { sinkError(args[0]); }};
    }

    addHook('Cronet_UrlRequest_InitWithParams', addresses.Cronet_UrlRequest_InitWithParams, {
      onEnter: function (args) {
        stats.init_calls++;
        this.requestKey = ptrKey(args[0]);
        this.flow = null;
        const route = routeFor(args[2], args[3]);
        if (!route || !this.requestKey || !readers.bodyReady) { stats.route_skip++; return; }
        if (requests.size >= MAX_PENDING_REQUESTS) { stats.route_skip++; return; }
        const result = core.beginRequest(this.requestKey, route.path, route.method);
        if (!result.accepted) {
          const stale = requests.get(this.requestKey);
          if (stale) invalidateFlow(stale, 'request_pointer_collision');
          stats.route_skip++;
          return;
        }
        const callbackKey = ptrKey(args[4]);
        if (callbackKey && callbackKey === this.requestKey) {
          core.invalidateRequest(this.requestKey, 'request_callback_pointer_collision');
          stats.request_pointer_collision++;
          return;
        }
        let providerPointer;
        try { providerPointer = readers.provider(args[3]); }
        catch (_) { providerPointer = null; }
        const providerKey = ptrKey(providerPointer);
        if (!providerKey || providerKey === this.requestKey || providerKey === callbackKey ||
            requests.has(providerKey) || requestCallbackKeys.has(providerKey)) {
          core.invalidateRequest(this.requestKey, 'provider_pointer_invalid');
          stats.provider_pointer_collision++;
          return;
        }
        if (providers.has(providerKey)) {
          const existingFlow = providers.get(providerKey);
          stats.provider_pointer_collision++;
          invalidateFlow(existingFlow, 'provider_reused');
          core.invalidateRequest(this.requestKey, 'provider_reused');
          return;
        }
        const bound = core.bindProvider(this.requestKey, providerKey);
        if (!bound.accepted) { stats.provider_pointer_collision++; return; }
        const flow = {
          requestKey: this.requestKey, callbackKey: callbackKey,
          providerKey: providerKey, route: route, requestSeq: result.request_seq,
          started: false, pendingLength: null, authDigests: []
        };
        requests.set(this.requestKey, flow);
        providers.set(providerKey, flow);
        if (callbackKey) {
          requestCallbackKeys.add(callbackKey);
          if (!requestCallbackOwners.has(callbackKey)) requestCallbackOwners.set(callbackKey, new Set());
          requestCallbackOwners.get(callbackKey).add(this.requestKey);
        }
        captureAuth(args[3], flow);
        this.flow = flow;
        this.requestSeq = result.request_seq;
        stats.route_eligible++;
        stats.provider_bound++;
      },
      onLeave: function (retval) {
        if (!this.flow) return;
        if (!retval || retval.toInt32() !== 0) invalidateFlow(this.flow, 'init_failed');
      }
    });

    addHook('Cronet_UrlRequest_Start', addresses.Cronet_UrlRequest_Start, {
      onEnter: function (args) { stats.start_calls++; this.requestKey = ptrKey(args[0]); this.flow = requests.get(this.requestKey) || null; },
      onLeave: function (retval) {
        if (!this.flow) return;
        if (!retval || retval.toInt32() !== 0) { invalidateFlow(this.flow, 'start_failed'); return; }
        const result = core.startRequest(this.flow.requestKey, true);
        if (!result.accepted) { invalidateFlow(this.flow, result.reason); return; }
        this.flow.started = true;
        stats.flow_started++;
        emitPrivateAuth(this.flow);
        if (this.flow.pendingLength !== null) {
          const length = this.flow.pendingLength;
          this.flow.pendingLength = null;
          processLength(this.flow.providerKey, length);
        }
      }
    });

    addHook('Cronet_UploadDataProvider_CreateWith', addresses.Cronet_UploadDataProvider_CreateWith, {
      onEnter: function (args) {
        this.callbacks = [
          {role: 'get_length', pointer: args[0]}, {role: 'read', pointer: args[1]},
          {role: 'rewind', pointer: args[2]}, {role: 'close', pointer: args[3]}
        ];
      },
      onLeave: function (retval) {
        const providerKey = ptrKey(retval);
        if (!providerKey || !this.callbacks) return;
        for (const item of this.callbacks) registerCallback(item.pointer, item.role, providerKey);
      }
    });
    addHook('Cronet_UploadDataProvider_GetLength', addresses.Cronet_UploadDataProvider_GetLength, getLengthHandler());
    addHook('Cronet_UploadDataProvider_Read', addresses.Cronet_UploadDataProvider_Read, getReadHandler('wrapper'));
    addHook('Cronet_UploadDataProvider_Rewind', addresses.Cronet_UploadDataProvider_Rewind, getRewindHandler());
    addHook('Cronet_UploadDataProvider_Close', addresses.Cronet_UploadDataProvider_Close, getCloseHandler());
    addHook('Cronet_UploadDataSink_OnReadSucceeded', addresses.Cronet_UploadDataSink_OnReadSucceeded, getReadSucceededHandler());
    addHook('Cronet_UploadDataSink_OnReadError', addresses.Cronet_UploadDataSink_OnReadError, getSinkErrorHandler());
    addHook('Cronet_UploadDataSink_OnRewindError', addresses.Cronet_UploadDataSink_OnRewindError, getSinkErrorHandler());

    if (!bodyApiReady || !methodGetterReady) {
      for (const name of REQUIRED_BODY_EXPORTS) if (!addresses[name]) missing.push(name);
      for (const name of HOOK_EXPORTS) if (!addresses[name] && missing.indexOf(name) < 0) missing.push(name);
      if (!methodGetterReady) missing.push('method_getter_unavailable');
    } else attachHooks();

    for (const name of HOOK_EXPORTS) {
      if (!attachedPublicNames.has(name) && missing.indexOf(name) < 0) missing.push(name);
    }
    bodyApiReady = bodyApiReady && HOOK_EXPORTS.every(name => attachedPublicNames.has(name));
    const installedNames = Array.from(attachedPublicNames).sort();
    const installedAddressCount = attachedPublicGroups;
    hookInstallStatus = {
      kind: 'hook_install', pid: config.pid, hook_count: installedAddressCount,
      hooks: installedNames.sort(), missing: missing,
      module_name: module.name, module_path_match: modulePathMatch,
      module_size_match: moduleSizeMatch, module_sha256_preflight: true,
      method_getter_ready: methodGetterReady, header_getters_ready: headerGettersReady,
      upload_api_ready: bodyApiReady, response_api_ready: false,
      callback_manifest_count: callbackModules.length
    };
    sendSafe(hookInstallStatus, false);

    function emitCoverage() {
      const coverage = Object.assign({}, stats, {
        active_flows: requests.size, pending_reads: pendingReads.size,
        route_counts: core.getCoverage().route_counts
      });
      stats.pending_at_end = pendingReads.size;
      sendSafe({kind: 'coverage_summary', coverage: coverage}, false);
    }
    emitCoverage();
    const coverageTimer = runtime.setInterval(emitCoverage, 30000);
    const maxSeconds = Math.max(1, Math.min(300, Number(config.max_seconds) || 1));
    const timeoutTimer = runtime.setTimeout(function () {
      emitCoverage();
      sendSafe({kind: 'observer_timeout', elapsed_seconds: maxSeconds}, false);
      active = false;
      stopHooks();
    }, maxSeconds * 1000);

    function stopHooks() {
      try { runtime.clearInterval(coverageTimer); } catch (_) {}
      try { runtime.clearTimeout(timeoutTimer); } catch (_) {}
      for (const listener of listeners) {
        try { listener.detach(); } catch (_) {}
      }
      for (const flow of requests.values()) {
        flow.authDigests = [];
      }
      core.dispose();
      requests.clear(); providers.clear(); pendingReads.clear(); pendingBuffers.clear(); sinkOwners.clear();
      stats.pending_at_end = 0;
    }

    return {
      stop: function () {
        if (!active) return;
        emitCoverage();
        active = false;
        stopHooks();
      },
      getCoverage: function () {
        const coverage = Object.assign({}, stats);
        const coreCoverage = core.getCoverage();
        for (const key of Object.keys(coreCoverage)) {
          if (!Object.prototype.hasOwnProperty.call(stats, key)) coverage[key] = coreCoverage[key];
        }
        return coverage;
      },
      getHookInstall: function () { return hookInstallStatus; },
      getPublicEventsForTest: function () { return publicEvents.slice(); }
    };
  }

  return {install: install, expectedModel: EXPECTED_MODEL,
    routePaths: Array.from(ROUTE_PATHS.keys()), headerAllowlist: Array.from(HEADER_ALLOWLIST)};
})(NativeUploadProjectionCoreForObserver);

if (typeof module !== 'undefined' && module.exports) module.exports = NativeUploadObserver;
