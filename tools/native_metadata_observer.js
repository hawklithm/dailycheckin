'use strict';

// Passive Cronet request metadata observer. It never reads request/response
// bodies, response buffers, header values, or URL query/fragment text.
// Public ABI reference: Chromium generated cronet.idl_c.h, pinned at
// 42bcd13e37f9b0a9efc540ae8feee9b4aae8e948. Init/Start ABI is in lines
// 580-610; Params header/method getters in 990-1003; header name getter 865-878.
const NativeMetadataObserver = (function () {
  const KNOWN_HOSTS = new Set([
    'trae-api-cn.mchost.guru', 'api.trae.cn', 'api.trae.com.cn'
  ]);
  // Only words already seen in the installed SDK/native static route corpus
  // are emitted literally. Every other path segment is hashed for offline
  // dictionary matching, so a short opaque identifier cannot leak as a route.
  const STATIC_PATH_TOKENS = new Set([
    'api', 'ide', 'agent', 'inner', 'v1', 'v2', 'v3', 'chat', 'ping', 'model_list',
    'get_detail_param', 'batch_get_detail_param', 'llm_raw_chat', 'llm_raw_chat_prompt',
    'web_search', 'create_agent_task', 'commit_toolcall_result', 'interrupt',
    'resume_agent_task', 'get_resume_agent_task_status', 'query_history_state',
    'sync_history_state', 'compact', 'llm_utils_chat', 'workflow', 'start',
    'commit_toolcall', 'use_fast_request', 'generate_summary', 'dsl', 'logs',
    'subscribe', 'templates', 'render', 'resources', 'custom_model_connectivity_check',
    'generated_skill', 'restore_pending', 'dismiss_pending', 'get_pending', 'list_pending'
  ]);
  const HOOKS = ['Cronet_UrlRequest_InitWithParams', 'Cronet_UrlRequest_Start'];
  const MAX_URL_BYTES = 4096;
  const MAX_ORIGIN_BYTES = 512;
  const MAX_PATH_BYTES = 2048;
  const MAX_SEGMENTS = 32;
  const MAX_PENDING = 256;
  const MAX_HEADERS = 64;
  const MAX_HEADER_NAME_BYTES = 128;
  const MAX_METHOD_BYTES = 16;
  const EVENT_LIMIT = 512;
  const NORMAL_EVENT_LIMIT = 480;
  const HEADER_NAME_RE = /^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,64}$/;

  function sha256Ascii(input) {
    if (typeof input !== 'string' || !/^[\x00-\x7f]*$/.test(input)) return null;
    const words = [];
    for (let i = 0; i < input.length; i++) {
      words[i >> 2] = (words[i >> 2] || 0) |
        (input.charCodeAt(i) << (24 - (i % 4) * 8));
    }
    const bitLength = input.length * 8;
    words[bitLength >> 5] = (words[bitLength >> 5] || 0) |
      (0x80 << (24 - bitLength % 32));
    const end = (((bitLength + 64) >> 9) << 4) + 15;
    words[end] = bitLength;
    words[end - 1] = Math.floor(bitLength / 0x100000000);
    const k = [
      0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
      0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
      0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
      0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
      0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
      0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
      0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
      0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
    ];
    let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a;
    let h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19;
    const w = new Array(64);
    const rotr = (x, n) => (x >>> n) | (x << (32 - n));
    for (let offset = 0; offset <= end; offset += 16) {
      for (let i = 0; i < 16; i++) w[i] = words[offset + i] | 0;
      for (let i = 16; i < 64; i++) {
        const x = w[i - 15], y = w[i - 2];
        const s0 = rotr(x, 7) ^ rotr(x, 18) ^ (x >>> 3);
        const s1 = rotr(y, 17) ^ rotr(y, 19) ^ (y >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
      }
      let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7;
      for (let i = 0; i < 64; i++) {
        const s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
        const ch = (e & f) ^ (~e & g);
        const t1 = (h + s1 + ch + k[i] + w[i]) | 0;
        const s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
        const maj = (a & b) ^ (a & c) ^ (b & c);
        const t2 = (s0 + maj) | 0;
        h = g; g = f; f = e; e = (d + t1) | 0;
        d = c; c = b; b = a; a = (t1 + t2) | 0;
      }
      h0 = (h0 + a) | 0; h1 = (h1 + b) | 0; h2 = (h2 + c) | 0; h3 = (h3 + d) | 0;
      h4 = (h4 + e) | 0; h5 = (h5 + f) | 0; h6 = (h6 + g) | 0; h7 = (h7 + h) | 0;
    }
    return [h0,h1,h2,h3,h4,h5,h6,h7]
      .map(n => (n >>> 0).toString(16).padStart(8, '0')).join('');
  }

  function hashValue(value) {
    if (typeof value !== 'string' || value.length > MAX_PATH_BYTES) return null;
    try { return sha256Ascii(encodeURIComponent(value)); } catch (_) { return null; }
  }

  function projectPath(path) {
    if (typeof path !== 'string' || path.length > MAX_PATH_BYTES ||
        !/^[\x00-\x7f]*$/.test(path) || !path.startsWith('/') ||
        /[?#\x00-\x1f\x7f]/.test(path)) return null;
    const parts = path.split('/').slice(1);
    if (parts.length > MAX_SEGMENTS || parts.some(part => part.length > 256)) return null;
    const segments = [];
    for (let index = 0; index < parts.length; index++) {
      const part = parts[index];
      if (!part) continue;
      if (STATIC_PATH_TOKENS.has(part)) {
        segments.push({kind: 'static', index: index + 1, value: part});
      } else {
        const digest = hashValue(part);
        if (!digest) return null;
        segments.push({kind: 'hash', index: index + 1, sha256: digest});
      }
    }
    const pathHash = hashValue(path);
    if (!pathHash) return null;
    return {path_sha256: pathHash, path_segments: segments};
  }

  function parseOrigin(originText) {
    if (typeof originText !== 'string' || originText.length < 8 ||
        originText.length > MAX_ORIGIN_BYTES || /[\x00-\x20\x7f]/.test(originText)) return null;
    const match = /^([A-Za-z][A-Za-z0-9+.-]*):\/\/([^/?#]+)$/.exec(originText);
    if (!match || match[2].indexOf('@') >= 0) return null;
    const scheme = match[1].toLowerCase();
    if (scheme !== 'http' && scheme !== 'https') return null;
    const authority = match[2].toLowerCase();
    let host = authority, port = scheme === 'https' ? 443 : 80;
    const colon = authority.lastIndexOf(':');
    if (colon > 0 && authority.indexOf(':') === colon) {
      const rawPort = authority.slice(colon + 1);
      if (!/^[0-9]{1,5}$/.test(rawPort)) return null;
      port = Number(rawPort);
      if (port < 1 || port > 65535) return null;
      host = authority.slice(0, colon);
    }
    host = host.replace(/\.$/, '');
    if (!/^[a-z0-9.-]{1,253}$/.test(host) || host.includes('..') || host.startsWith('.') || host.endsWith('.')) return null;
    if (!host.split('.').every(label => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label))) return null;
    return {scheme: scheme, host: host, port: port, known_trae_host: KNOWN_HOSTS.has(host)};
  }

  function projectUrlForTest(rawUrl) {
    if (typeof rawUrl !== 'string' || rawUrl.length > MAX_URL_BYTES || /[\x00-\x1f\x7f]/.test(rawUrl)) return null;
    const originMatch = /^([A-Za-z][A-Za-z0-9+.-]*:\/\/[^/?#]+)/.exec(rawUrl);
    if (!originMatch) return null;
    const origin = parseOrigin(originMatch[1]);
    if (!origin) return null;
    if (!origin.known_trae_host || origin.scheme !== 'https' || origin.port !== 443) {
      return {kind: 'other_origin', scheme: origin.scheme, host: origin.host, port: origin.port};
    }
    const tail = rawUrl.slice(originMatch[0].length);
    const path = (tail.split(/[?#]/, 1)[0] || '/');
    const pathProjection = projectPath(path);
    if (!pathProjection) return null;
    return Object.assign({kind: 'known_origin', scheme: origin.scheme, host: origin.host, port: origin.port}, pathProjection);
  }

  function readAscii(pointer, maximum, delimiters) {
    if (!pointer || pointer.isNull()) return null;
    const chars = [];
    try {
      for (let i = 0; i < maximum; i++) {
        const byte = pointer.add(i).readU8();
        if (byte === 0 || delimiters.has(byte)) return chars.join('');
        if (byte > 0x7e || byte < 0x20) return null;
        chars.push(String.fromCharCode(byte));
      }
    } catch (_) { return null; }
    return null;
  }

  function readOriginPointer(pointer) {
    if (!pointer || pointer.isNull()) return null;
    const chars = [];
    let inAuthority = false;
    try {
      for (let i = 0; i < MAX_ORIGIN_BYTES; i++) {
        const byte = pointer.add(i).readU8();
        if (byte === 0 || byte === 63 || byte === 35) {
          const origin = parseOrigin(chars.join(''));
          return origin ? {origin: origin, pathOffset: i} : null;
        }
        if (byte > 0x7e || byte < 0x20) return null;
        const ch = String.fromCharCode(byte);
        if (inAuthority && ch === '/') {
          const origin = parseOrigin(chars.join(''));
          return origin ? {origin: origin, pathOffset: i} : null;
        }
        chars.push(ch);
        if (!inAuthority && chars.length >= 3 && chars.slice(-3).join('') === '://') inAuthority = true;
      }
    } catch (_) { return null; }
    return null;
  }

  function readPathPointer(pointer, pathOffset) {
    if (!pointer || pointer.isNull() || !Number.isInteger(pathOffset) || pathOffset < 0) return null;
    const chars = [];
    try {
      for (let i = 0; i < MAX_PATH_BYTES + 1; i++) {
        const byte = pointer.add(pathOffset + i).readU8();
        if (byte === 0 || byte === 63 || byte === 35) break;
        if (byte > 0x7e || byte < 0x20) return null;
        chars.push(String.fromCharCode(byte));
        if (chars.length > MAX_PATH_BYTES) return null;
      }
    } catch (_) { return null; }
    return chars.length ? chars.join('') : '/';
  }

  function readCStringValue(pointer, maximum, pattern) {
    const value = readAscii(pointer, maximum, new Set());
    if (value === null || !pattern.test(value)) return null;
    return value;
  }

  function safePublicOrigin(origin) {
    const host = origin.host;
    const isIpv4 = /^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$/.test(host);
    const localName = host === 'localhost' || host.endsWith('.localhost') ||
      host.endsWith('.local') || host.endsWith('.internal') || host.endsWith('.lan') ||
      host.endsWith('.home');
    if (isIpv4 || localName || !host.includes('.')) return null;
    return {scheme: origin.scheme, host: host, port: origin.port};
  }

  function readHeaderNames(params, readers, stats) {
    if (!readers.headersReady) return {status: 'unavailable', names: []};
    try {
      const count = readers.headersSize(params);
      if (!Number.isInteger(count) || count < 0 || count > MAX_HEADERS) {
        if (stats) stats.too_many_headers++;
        return {status: 'over_limit', names: []};
      }
      const names = new Set();
      for (let index = 0; index < count; index++) {
        const header = readers.headersAt(params, index);
        if (!header || header.isNull()) return {status: 'unreadable', names: []};
        const namePointer = readers.headerName(header);
        const name = readCStringValue(namePointer, MAX_HEADER_NAME_BYTES, HEADER_NAME_RE);
        if (!name) return {status: 'unreadable', names: []};
        names.add(name.toLowerCase());
      }
      return {status: 'read', names: Array.from(names).sort()};
    } catch (_) {
      if (stats) stats.header_names_unreadable++;
      return {status: 'unreadable', names: []};
    }
  }

  function readMethod(params, readers, stats) {
    if (!readers.methodReady) return 'unknown';
    try {
      const value = readCStringValue(readers.method(params), MAX_METHOD_BYTES, /^[A-Z]{1,12}$/);
      if (!value && stats) stats.method_unreadable++;
      return value || 'unknown';
    } catch (_) {
      if (stats) stats.method_unreadable++;
      return 'unknown';
    }
  }

  function captureInit(args, readers, stats) {
    const parsed = readOriginPointer(args[2]);
    if (!parsed) return {kind: 'invalid_url'};
    const origin = parsed.origin;
    if (!origin.known_trae_host || origin.scheme !== 'https' || origin.port !== 443) {
      const safe = safePublicOrigin(origin);
      return {
        kind: safe ? 'other_origin' : 'other_origin_hidden', origin: safe,
        method: readMethod(args[3], readers, stats)
      };
    }
    const path = readPathPointer(args[2], parsed.pathOffset);
    const projection = projectPath(path);
    if (!projection) return {kind: 'invalid_url'};
    return {
      kind: 'known_origin', origin: {scheme: origin.scheme, host: origin.host, port: origin.port},
      method: readMethod(args[3], readers, stats),
      headers: readHeaderNames(args[3], readers, stats),
      path_sha256: projection.path_sha256,
      path_segments: projection.path_segments
    };
  }

  function install(config) {
    const installed = [];
    const missing = [];
    const pending = new Map();
    const ambiguous = new Set();
    const stats = {
      init_calls: 0, start_calls: 0, route_metadata: 0, other_origin: 0,
      invalid_url: 0, method_unreadable: 0, header_names_unreadable: 0,
      too_many_headers: 0, pointer_collision: 0, pending_cap_skip: 0,
      ambiguous_start_skip: 0, start_without_init: 0, start_failed: 0,
      pending_at_end: 0, output_cap_skip: 0
    };
    let eventCount = 0;
    let requestSeq = 0;
    let active = true;

    function emit(record, critical) {
      if (!active && !critical) return;
      const limit = critical ? EVENT_LIMIT : NORMAL_EVENT_LIMIT;
      if (eventCount >= limit) {
        if (!critical) stats.output_cap_skip++;
        return;
      }
      eventCount++;
      send(record);
    }
    function ptrKey(pointer) {
      try { return pointer && !pointer.isNull() ? pointer.toString() : ''; }
      catch (_) { return ''; }
    }
    function emitCoverage() {
      stats.pending_at_end = pending.size;
      emit({kind: 'coverage_summary', coverage: Object.assign({}, stats)}, true);
    }
    function installHook(address, label, callbacks) {
      if (!address) { missing.push(label); return false; }
      try {
        Interceptor.attach(address, callbacks);
        installed.push(label);
        return true;
      } catch (_) { missing.push(label); return false; }
    }

    if (Process.id !== config.pid) {
      emit({kind: 'hook_install', pid: config.pid, hook_count: 0, hooks: [], missing: ['pid_mismatch'], module_name: null, module_path_match: false, method_getter_ready: false, header_getters_ready: false, body_api_ready: false}, true);
      return;
    }
    let module;
    try { module = Process.getModuleByName('sscronet.dll'); }
    catch (_) {
      emit({kind: 'hook_install', pid: config.pid, hook_count: 0, hooks: [], missing: ['sscronet_missing'], module_name: null, module_path_match: false, method_getter_ready: false, header_getters_ready: false, body_api_ready: false}, true);
      return;
    }
    const normalizedPath = String(module.path || '').replace(/\\/g, '/').toLowerCase();
    const expectedPath = String(config.expected_module_path || '').replace(/\\/g, '/').toLowerCase();
    const pathMatch = normalizedPath === expectedPath;
    if (!pathMatch) {
      emit({kind: 'hook_install', pid: config.pid, hook_count: 0, hooks: [], missing: ['module_path_mismatch'], module_name: module.name, module_path_match: false, method_getter_ready: false, header_getters_ready: false, body_api_ready: false}, true);
      return;
    }

    const exports = {};
    const exportNames = [
      'Cronet_UrlRequest_InitWithParams', 'Cronet_UrlRequest_Start',
      'Cronet_UrlRequestParams_http_method_get',
      'Cronet_UrlRequestParams_request_headers_size',
      'Cronet_UrlRequestParams_request_headers_at',
      'Cronet_HttpHeader_name_get'
    ];
    for (const name of exportNames) exports[name] = module.findExportByName(name);
    const initAddress = exports.Cronet_UrlRequest_InitWithParams;
    const startAddress = exports.Cronet_UrlRequest_Start;
    if (!initAddress || !startAddress || initAddress.equals(startAddress)) {
      emit({kind: 'hook_install', pid: config.pid, hook_count: 0, hooks: [], missing: ['hook_export_unavailable_or_alias'], module_name: module.name, module_path_match: true, method_getter_ready: false, header_getters_ready: false, body_api_ready: false}, true);
      return;
    }

    const readers = {
      method: null, headersSize: null, headersAt: null, headerName: null,
      methodReady: false, headersReady: false
    };
    try {
      if (exports.Cronet_UrlRequestParams_http_method_get) {
        readers.method = new NativeFunction(exports.Cronet_UrlRequestParams_http_method_get, 'pointer', ['pointer']);
        readers.methodReady = true;
      }
    } catch (_) { readers.methodReady = false; }
    try {
      if (exports.Cronet_UrlRequestParams_request_headers_size &&
          exports.Cronet_UrlRequestParams_request_headers_at &&
          exports.Cronet_HttpHeader_name_get) {
        readers.headersSize = new NativeFunction(exports.Cronet_UrlRequestParams_request_headers_size, 'uint', ['pointer']);
        readers.headersAt = new NativeFunction(exports.Cronet_UrlRequestParams_request_headers_at, 'pointer', ['pointer', 'uint']);
        readers.headerName = new NativeFunction(exports.Cronet_HttpHeader_name_get, 'pointer', ['pointer']);
        readers.headersReady = true;
      }
    } catch (_) { readers.headersReady = false; }

    installHook(initAddress, 'Cronet_UrlRequest_InitWithParams', {
      onEnter: function (args) {
        stats.init_calls++;
        this.requestKey = ptrKey(args[0]);
        this.capture = null;
        if (!this.requestKey || ambiguous.has(this.requestKey)) return;
        try { this.capture = captureInit(args, readers, stats); }
        catch (_) { this.capture = {kind: 'invalid_url'}; stats.invalid_url++; }
      },
      onLeave: function (retval) {
        if (!this.capture || !this.requestKey || retval.toInt32() !== 0) return;
        if (ambiguous.has(this.requestKey)) return;
        if (pending.has(this.requestKey)) {
          pending.delete(this.requestKey);
          stats.pointer_collision++;
          if (ambiguous.size < MAX_PENDING) ambiguous.add(this.requestKey);
          else stats.pending_cap_skip++;
          return;
        }
        if (pending.size >= MAX_PENDING) { stats.pending_cap_skip++; return; }
        pending.set(this.requestKey, {request_seq: ++requestSeq, capture: this.capture});
      }
    });
    installHook(startAddress, 'Cronet_UrlRequest_Start', {
      onEnter: function (args) {
        stats.start_calls++;
        const key = ptrKey(args[0]);
        if (!key) return;
        if (ambiguous.has(key)) {
          ambiguous.delete(key);
          pending.delete(key);
          stats.ambiguous_start_skip++;
          return;
        }
        this.item = pending.get(key) || null;
        pending.delete(key);
        if (!this.item) stats.start_without_init++;
      },
      onLeave: function (retval) {
        if (!this.item) return;
        if (retval.toInt32() !== 0) { stats.start_failed++; return; }
        const capture = this.item.capture;
        if (capture.kind === 'invalid_url') {
          stats.invalid_url++;
          return;
        }
        const base = {time_utc_ms: Date.now(), request_seq: this.item.request_seq};
        if (capture.kind === 'other_origin' || capture.kind === 'other_origin_hidden') {
          stats.other_origin++;
          emit(Object.assign(base, {
            kind: 'other_origin', origin: capture.origin || null,
            origin_status: capture.origin ? 'public' : 'hidden',
            method: capture.method || 'unknown',
            path_read: false, headers_read: false
          }), false);
          return;
        }
        stats.route_metadata++;
        emit(Object.assign({kind: 'request_metadata'}, base, {
          origin: capture.origin, path_sha256: capture.path_sha256,
          path_segments: capture.path_segments, method: capture.method,
          configured_header_names: capture.headers.names,
          header_names_status: capture.headers.status,
          body_read: false, response_read: false
        }), false);
      }
    });

    emit({
      kind: 'hook_install', pid: config.pid, hook_count: installed.length,
      hooks: installed, missing: missing, module_name: module.name,
      module_path_match: pathMatch, method_getter_ready: readers.methodReady,
      header_getters_ready: readers.headersReady, body_api_ready: false
    }, true);
    emitCoverage();
    const coverageTimer = setInterval(emitCoverage, 30000);
    setTimeout(function () {
      clearInterval(coverageTimer);
      stats.pending_at_end = pending.size;
      emit({kind: 'observer_timeout', elapsed_seconds: config.max_seconds}, true);
      emitCoverage();
      active = false;
    }, config.max_seconds * 1000);

    return {
      stop: function () {
        if (!active) return;
        active = false;
        clearInterval(coverageTimer);
        emitCoverage();
      }
    };
  }

  return {
    install: install,
    hooks: HOOKS.slice(),
    knownHosts: Array.from(KNOWN_HOSTS),
    hashValue: hashValue,
    projectPath: projectPath,
    parseUrlForTest: projectUrlForTest,
    captureInitForTest: function (urlPointer, params, readers) {
      return captureInit([null, null, urlPointer, params], readers, {
        too_many_headers: 0, header_names_unreadable: 0, method_unreadable: 0
      });
    }
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = NativeMetadataObserver;
