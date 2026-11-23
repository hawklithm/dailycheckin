'use strict';

// Offline-safe projection and bounded upload state machine for the separately
// reviewed native upload observer. This module does not install hooks or touch
// process memory. Callers provide bytes only after exact-route and typed
// Cronet object checks. Raw request text is never included in returned objects.
const NativeUploadProjectionCore = (function () {
  const MAX_UPLOAD_BYTES = 1024 * 1024;
  const MAX_TOTAL_BYTES = 4 * 1024 * 1024;
  const MAX_ACTIVE_FLOWS = 128;
  const MAX_PENDING_READS = 512;
  const MAX_CHUNKS_PER_FLOW = 128;
  const MAX_JSON_DEPTH = 16;
  const MAX_JSON_NODES = 20000;
  const MAX_SCHEMA_FIELDS = 128;
  const MAX_MARKER_PATHS = 16;
  const MAX_ID_FIELDS = 32;
  const MAX_MODEL_FIELDS = 24;
  const MAX_USAGE_FIELDS = 32;
  const TARGET_MODEL = 'deepseek-v4.1-flash';
  const TARGET_ROUTES = new Set([
    '/api/agent/v3/create_agent_task',
    '/api/agent/v3/llm_utils_chat',
    '/api/agent/v3/workflow/start'
  ]);
  const ROUTE_NAMES = new Map([
    ['/api/agent/v3/create_agent_task', 'create_agent_task'],
    ['/api/agent/v3/llm_utils_chat', 'llm_utils_chat'],
    ['/api/agent/v3/workflow/start', 'workflow_start']
  ]);

  // Only these fixed protocol names may be emitted verbatim. Other object keys
  // are represented by a one-way digest, never by their original spelling.
  const STATIC_KEYS = new Set((
    'agent agent_id agent_task_id agent_type arguments body chat_history ' +
    'chat_session_id client_info common_params content content_blocks ' +
    'conversation_id custom_model custom_params data developer display_model_name ' +
    'done error error_code event extra_chat_params function function_call ' +
    'function_name function_response id input input_tokens is_streaming items ' +
    'message message_id message_contents messages metadata model model_config ' +
    'model_name model_selection_strategy name operation_id output output_tokens ' +
    'params parsed_query payload prompt prompt_tokens query reasoning_content ' +
    'reasoning_effort reasoning_mode request request_id response result role ' +
    'scheduled_task_context session_id status stream task_id text text_content ' +
    'timestamp timing_events token_usage total_tokens trace_id type usage ' +
    'user_input user_message_id user_info value workflow workflow_id x ' +
    'cache_read_tokens cache_creation_tokens cached_tokens completion_tokens ' +
    'context_usage input output final_chunk tool tool_calls tool_choice tools ' +
    'system developer user assistant delta choices finish_reason model_config_name ' +
    'custom_model_config custom_model_name strategy scene_location agent_config'
  ).split(/\s+/));
  const SECRET_KEYS = new Set((
    'ak api_key access_token authorization cloudide_token cookie cookies credential ' +
    'credentials headers jwt jwt_token password private_key secret token x_api_key ' +
    'x_ide_token x_cloudide_token refresh_token privatekey auth_token bearer_token'
  ).split(/\s+/));
  const MODEL_KEYS = new Set([
    'model', 'model_name', 'config_name', 'display_model_name',
    'user_selected_model_name', 'custom_model_name', 'model_config_name'
  ]);
  const GENERAL_ENUM_VALUES = new Set([
    'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra',
    'auto', 'default', 'manual', 'enabled', 'disabled', 'on', 'off',
    'balanced', 'fast', 'quality'
  ]);
  const SAFE_ENUM_VALUES = new Map([
    ['model_selection_strategy', GENERAL_ENUM_VALUES],
    ['reasoning_effort', GENERAL_ENUM_VALUES],
    ['reasoning_mode', GENERAL_ENUM_VALUES],
    ['strategy', GENERAL_ENUM_VALUES],
    ['function', new Set([
      'chat', 'builder', 'agent', 'code', 'completion', 'solo', 'plan', 'edit',
      'inline_chat', 'reader', 'custom', 'assistant', 'chat_builder',
      'agent_builder', 'solo_builder', 'solo_coding', 'fast_apply',
      'commit_message', 'summary', 'terminal', 'solo_agent'
    ])],
    ['agent_type', new Set(['chat', 'builder', 'solo_agent'])],
    ['scene_location', new Set([1, 2])]
  ]);
  // These literals are a bounded safe-output list copied from repository
  // fixtures; their presence here does not assert endpoint acceptance.
  const SAFE_ENUM_KEYS = new Set(SAFE_ENUM_VALUES.keys());
  const ID_KEYS = new Set([
    'chat_session_id', 'session_id', 'message_id', 'user_message_id',
    'reply_to_message_id', 'request_id', 'task_id', 'agent_task_id',
    'conversation_id', 'operation_id', 'trace_id', 'workflow_id', 'agent_id'
  ]);
  const USAGE_KEYS = new Set([
    'prompt_tokens', 'completion_tokens', 'total_tokens', 'input_tokens',
    'output_tokens', 'cached_tokens', 'reasoning_tokens', 'cache_read_tokens',
    'cache_creation_tokens'
  ]);
  const NESTED_JSON_KEYS = new Set(['query', 'data', 'payload', 'request', 'params', 'body']);
  const MAX_EMBEDDED_JSON_CHARS = 256 * 1024;

  function safeEnumValue(key, value) {
    const allowed = SAFE_ENUM_VALUES.get(key);
    if (!allowed) return null;
    if (typeof value === 'string') {
      const normalized = value.trim().toLowerCase();
      return allowed.has(normalized) ? normalized : null;
    }
    if (typeof value === 'number' && Number.isSafeInteger(value) && allowed.has(value)) return value;
    return null;
  }

  function typeName(value) {
    if (value === null) return 'null';
    if (Array.isArray(value)) return 'array';
    switch (typeof value) {
      case 'object': return 'object';
      case 'string': return 'string';
      case 'number': return Number.isInteger(value) ? 'integer' : 'number';
      case 'boolean': return 'boolean';
      default: return 'unknown';
    }
  }

  function sha256Bytes(input) {
    if (!(input instanceof Uint8Array)) return null;
    const words = [];
    for (let i = 0; i < input.length; i++) {
      words[i >> 2] = (words[i >> 2] || 0) |
        (input[i] << (24 - (i % 4) * 8));
    }
    const bitLength = input.length * 8;
    words[bitLength >> 5] = (words[bitLength >> 5] || 0) |
      (0x80 << (24 - (bitLength % 32)));
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
        w[i] = (w[i - 16] + (rotr(x, 7) ^ rotr(x, 18) ^ (x >>> 3)) + w[i - 7] +
          (rotr(y, 17) ^ rotr(y, 19) ^ (y >>> 10))) | 0;
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
      .map(value => (value >>> 0).toString(16).padStart(8, '0')).join('');
  }

  function sha256Ascii(ascii) {
    if (typeof ascii !== 'string' || !/^[\x00-\x7f]*$/.test(ascii)) return null;
    const bytes = new Uint8Array(ascii.length);
    for (let i = 0; i < ascii.length; i++) bytes[i] = ascii.charCodeAt(i);
    return sha256Bytes(bytes);
  }

  function hashPathKey(key) {
    if (typeof key !== 'string' || key.length > 512) return null;
    try { return sha256Ascii(encodeURIComponent(key)); } catch (_) { return null; }
  }

  function pathKey(key) {
    const lower = String(key).toLowerCase();
    if (STATIC_KEYS.has(lower)) return {kind: 'key', value: lower};
    const digest = hashPathKey(key);
    return digest ? {kind: 'hash', sha256: digest} : {kind: 'omitted'};
  }

  function isSecretKey(key) {
    const lower = String(key).toLowerCase();
    if (lower === 'token_usage' || USAGE_KEYS.has(lower)) return false;
    const compact = lower.replace(/[^a-z0-9]/g, '');
    if (SECRET_KEYS.has(lower) || SECRET_KEYS.has(compact)) return true;
    return /(^|_)(auth|authorization|token|jwt|secret|password|passwd|credential|cookie|cookies|header|headers|private_key|privatekey|api_key|apikey)(_|$)/.test(lower);
  }

  function hasMarker(text, marker) {
    const escaped = marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp('(^|[^A-Za-z0-9_])' + escaped + '($|[^A-Za-z0-9_])').test(text);
  }

  function canonicalModel(value) {
    if (typeof value !== 'string' || value.length > 128) return null;
    const normalized = value.trim().toLowerCase().replace(/[ _]+/g, '-').replace(/-+/g, '-');
    return normalized === TARGET_MODEL ? TARGET_MODEL : null;
  }

  function validId(value) {
    return (typeof value === 'string' && value.length > 0 && value.length <= 256 && /^[\x20-\x7e]+$/.test(value)) ||
      (typeof value === 'number' && Number.isSafeInteger(value) && value >= 0);
  }

  function bytesToUtf8(bytes) {
    let out = '';
    for (let i = 0; i < bytes.length;) {
      const a = bytes[i++];
      if (a <= 0x7f) out += String.fromCharCode(a);
      else if (a >= 0xc2 && a <= 0xdf) {
        if (i >= bytes.length) throw new Error('invalid_utf8');
        const b = bytes[i++];
        if ((b & 0xc0) !== 0x80) throw new Error('invalid_utf8');
        out += String.fromCharCode(((a & 0x1f) << 6) | (b & 0x3f));
      } else if (a >= 0xe0 && a <= 0xef) {
        if (i + 1 >= bytes.length) throw new Error('invalid_utf8');
        const b = bytes[i++], c = bytes[i++];
        if ((b & 0xc0) !== 0x80 || (c & 0xc0) !== 0x80 ||
            (a === 0xe0 && b < 0xa0) || (a === 0xed && b >= 0xa0)) throw new Error('invalid_utf8');
        out += String.fromCharCode(((a & 15) << 12) | ((b & 63) << 6) | (c & 63));
      } else if (a >= 0xf0 && a <= 0xf4) {
        if (i + 2 >= bytes.length) throw new Error('invalid_utf8');
        const b = bytes[i++], c = bytes[i++], d = bytes[i++];
        if ((b & 0xc0) !== 0x80 || (c & 0xc0) !== 0x80 || (d & 0xc0) !== 0x80 ||
            (a === 0xf0 && b < 0x90) || (a === 0xf4 && b >= 0x90)) throw new Error('invalid_utf8');
        const cp = ((a & 7) << 18) | ((b & 63) << 12) | ((c & 63) << 6) | (d & 63);
        const v = cp - 0x10000;
        out += String.fromCharCode(0xd800 + (v >> 10), 0xdc00 + (v & 1023));
      } else throw new Error('invalid_utf8');
    }
    return out;
  }

  function projectParsed(root, marker, byteCount) {
    const output = {
      parse_state: 'json', body_bytes: byteCount, marker_hit: false,
      marker_semantics: 'unverified', marker_paths: [], schema: [],
      model_fields: [], enum_fields: [], id_hashes: [], usage: []
    };
    const schemaSeen = new Set(), topSeen = new Set(), idSeen = new Set(), enumSeen = new Set();
    let nodes = 0;
    function addSchema(path, type, topLevel) {
      if (!path.length || path[path.length - 1].kind === 'omitted') return;
      const key = JSON.stringify(path);
      if (topLevel) {
        if (!topSeen.has(key) && output.schema.length < MAX_SCHEMA_FIELDS) {
          topSeen.add(key);
          output.schema.push({path: path.slice(), type: type, top_level: true});
        }
      } else if (!schemaSeen.has(key) && output.schema.length < MAX_SCHEMA_FIELDS) {
        schemaSeen.add(key);
        output.schema.push({path: path.slice(), type: type, top_level: false});
      }
    }
    function addEnum(path, key, value) {
      if (!SAFE_ENUM_KEYS.has(key) || output.enum_fields.length >= MAX_MODEL_FIELDS) return;
      const safeValue = safeEnumValue(key, value);
      const identityPath = JSON.stringify(path);
      if (safeValue !== null && !enumSeen.has(identityPath)) {
        enumSeen.add(identityPath);
        output.enum_fields.push({path: path.slice(), value: safeValue});
      }
    }
    function visit(value, path, depth, topLevel, parentKey) {
      if (++nodes > MAX_JSON_NODES || depth > MAX_JSON_DEPTH) return;
      const kind = typeName(value);
      if (path.length) addSchema(path, kind, topLevel);
      if (typeof value === 'string') {
        if (hasMarker(value, marker)) {
          output.marker_hit = true;
          if (output.marker_paths.length < MAX_MARKER_PATHS) {
            output.marker_paths.push(path.map(item => Object.assign({}, item)));
          }
        }
        if (parentKey && MODEL_KEYS.has(parentKey) && output.model_fields.length < MAX_MODEL_FIELDS) {
          output.model_fields.push({path: path.slice(), value_state: canonicalModel(value) ? 'target' : 'other'});
        }
        if (parentKey) addEnum(path, parentKey, value);
        if (parentKey && NESTED_JSON_KEYS.has(parentKey) && depth < 3 && value.length <= MAX_EMBEDDED_JSON_CHARS) {
          const trimmed = value.trim();
          if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
            try {
              const nested = JSON.parse(trimmed);
              visit(nested, path.concat([{kind: 'embedded_json'}]), depth + 1, false, null);
            } catch (_) { /* The original value remains private and unprojected. */ }
          }
        }
        return;
      }
      if (Array.isArray(value)) {
        for (const item of value) {
          if (nodes >= MAX_JSON_NODES) break;
          visit(item, path.concat([{kind: 'array_item'}]), depth + 1, false, null);
        }
        return;
      }
      if (!value || typeof value !== 'object') {
        if (parentKey) addEnum(path, parentKey, value);
        if (parentKey && ID_KEYS.has(parentKey) && validId(value) && output.id_hashes.length < MAX_ID_FIELDS) {
          const digest = hashPathKey(String(value));
          const identityPath = JSON.stringify(path);
          if (digest && !idSeen.has(identityPath)) {
            idSeen.add(identityPath);
            output.id_hashes.push({path: path.slice(), sha256: digest});
          }
        }
        if (parentKey && USAGE_KEYS.has(parentKey) && typeof value === 'number' &&
            Number.isSafeInteger(value) && value >= 0 && value <= 1_000_000_000 &&
            output.usage.length < MAX_USAGE_FIELDS) {
          output.usage.push({path: path.slice(), value: value});
        }
        return;
      }
      const keys = Object.keys(value);
      for (const key of keys) {
        if (nodes >= MAX_JSON_NODES) break;
        if (isSecretKey(key)) continue;
        const segment = pathKey(key);
        if (segment.kind === 'omitted') continue;
        const lower = key.toLowerCase();
        const childPath = path.concat([segment]);
        const child = value[key];
        addSchema(childPath, typeName(child), path.length === 0);
        if (MODEL_KEYS.has(lower) && typeof child === 'string' && output.model_fields.length < MAX_MODEL_FIELDS) {
          output.model_fields.push({path: childPath.slice(), value_state: canonicalModel(child) ? 'target' : 'other'});
        }
        if (ID_KEYS.has(lower) && validId(child) && output.id_hashes.length < MAX_ID_FIELDS) {
          const digest = hashPathKey(String(child));
          const identityPath = JSON.stringify(childPath);
          if (digest && !idSeen.has(identityPath)) {
            idSeen.add(identityPath);
            output.id_hashes.push({path: childPath.slice(), sha256: digest});
          }
        }
        if (USAGE_KEYS.has(lower) && typeof child === 'number' && Number.isSafeInteger(child) &&
            child >= 0 && child <= 1_000_000_000 && output.usage.length < MAX_USAGE_FIELDS) {
          output.usage.push({path: childPath.slice(), value: child});
        }
        visit(child, childPath, depth + 1, false, lower);
      }
    }
    visit(root, [], 0, false, null);
    output.schema.sort((a, b) => JSON.stringify(a.path).localeCompare(JSON.stringify(b.path)));
    output.marker_paths.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
    output.enum_fields.sort((a, b) => JSON.stringify(a.path).localeCompare(JSON.stringify(b.path)));
    return output;
  }

  function projectUploadBytes(bytes, marker) {
    if (!(bytes instanceof Uint8Array)) return {parse_state: 'invalid_buffer', body_bytes: 0, marker_hit: false, marker_semantics: 'unverified', marker_paths: []};
    const length = bytes.length;
    let result;
    try {
      if (length > MAX_UPLOAD_BYTES) {
        result = {parse_state: 'bounded_unknown', body_bytes: length, marker_hit: false, marker_semantics: 'unverified', marker_paths: []};
      } else {
        const text = bytesToUtf8(bytes);
        let parsed, parsedOk = false;
        try { parsed = JSON.parse(text); parsedOk = true; }
        catch (_) {
          result = {parse_state: 'invalid_json', body_bytes: length, marker_hit: false, marker_semantics: 'unverified', marker_paths: []};
          parsed = null;
        }
        if (parsedOk) result = projectParsed(parsed, marker, length);
        parsed = null;
      }
    } catch (error) {
      const reason = error && error.message === 'invalid_utf8' ? 'invalid_utf8' : 'bounded_unknown';
      result = {parse_state: reason, body_bytes: length, marker_hit: false, marker_semantics: 'unverified', marker_paths: []};
    } finally {
      bytes.fill(0);
    }
    return result;
  }

  function createCaptureModel(options) {
    options = options || {};
    const marker = typeof options.marker === 'string' && options.marker.length <= 64 ? options.marker : '';
    const emit = typeof options.emit === 'function' ? options.emit : function () {};
    const requests = new Map(), providers = new Map(), pendingBySink = new Map(), pendingBuffers = new Map();
    const routeCounts = Object.create(null);
    let sequence = 0, totalBytes = 0, disposed = false;
    const stats = {
      route_eligible: 0, flow_started: 0, provider_bound: 0, provider_unbound: 0,
      get_length_seen: 0, read_wrapper: 0, read_callback: 0, read_ack: 0,
      read_duplicate: 0, zero_progress_skip: 0, chunk_cap_skip: 0,
      upload_projection: 0, marker_matched: 0, marker_rejected: 0,
      skip_unmapped_provider: 0, skip_ambiguous_read: 0, skip_buffer_mismatch: 0,
      skip_length_mismatch: 0, skip_over_cap: 0, skip_rewind: 0,
      request_pointer_collision: 0, provider_reuse: 0, pending_cap_skip: 0,
      request_cap_skip: 0, active_cap_skip: 0, pending_at_end: 0,
      total_bytes_at_end: 0, callback_module_skip: 0, pointer_collision: 0
    };

    function keyOk(value) { return typeof value === 'string' && value.length > 0 && value.length <= 128; }
    function zeroFlow(flow) {
      if (!flow) return;
      for (const chunk of flow.chunks) chunk.fill(0);
      flow.chunks.length = 0;
    }
    function clearFlow(flow) {
      if (!flow) return;
      zeroFlow(flow);
      if (requests.get(flow.requestKey) === flow) requests.delete(flow.requestKey);
      if (flow.providerKey && providers.get(flow.providerKey) === flow) providers.delete(flow.providerKey);
      for (const [sink, record] of pendingBySink) {
        if (record.flow === flow) {
          pendingBySink.delete(sink);
          if (pendingBuffers.get(record.bufferKey) === sink) pendingBuffers.delete(record.bufferKey);
        }
      }
    }
    function skip(key) { if (Object.prototype.hasOwnProperty.call(stats, key)) stats[key]++; return {accepted: false, reason: key}; }
    function beginRequest(requestKey, route, method) {
      if (disposed) return skip('skip_unmapped_provider');
      if (!keyOk(requestKey)) return skip('request_pointer_collision');
      if (typeof route !== 'string' || !TARGET_ROUTES.has(route) || method !== 'POST') return {accepted: false, reason: 'route_not_allowlisted'};
      if (requests.has(requestKey)) {
        stats.request_pointer_collision++;
        const old = requests.get(requestKey);
        if (old) clearFlow(old);
        return {accepted: false, reason: 'request_pointer_collision'};
      }
      const routeName = ROUTE_NAMES.get(route);
      if ((routeCounts[routeName] || 0) >= 16 || stats.route_eligible >= 48) return skip('request_cap_skip');
      if (requests.size >= MAX_ACTIVE_FLOWS) return skip('active_cap_skip');
      routeCounts[routeName] = (routeCounts[routeName] || 0) + 1;
      const flow = {
        seq: ++sequence, requestKey, route, routeName, providerKey: null,
        started: false, expectedLength: null, received: 0, chunks: [], state: 'pending'
      };
      requests.set(requestKey, flow);
      stats.route_eligible++;
      return {accepted: true, request_seq: flow.seq, route_name: routeName};
    }
    function bindProvider(requestKey, providerKey) {
      const flow = requests.get(requestKey);
      if (!flow || !keyOk(providerKey)) { stats.provider_unbound++; return skip('skip_unmapped_provider'); }
      const existing = providers.get(providerKey);
      if (existing) {
        stats.provider_reuse++;
        clearFlow(existing);
        clearFlow(flow);
        return {accepted: false, reason: 'provider_reuse'};
      }
      flow.providerKey = providerKey;
      providers.set(providerKey, flow);
      stats.provider_bound++;
      return {accepted: true, request_seq: flow.seq};
    }
    function startRequest(requestKey, success) {
      const flow = requests.get(requestKey);
      if (!flow) return {accepted: false, reason: 'request_unmapped'};
      if (success !== true) { clearFlow(flow); return {accepted: false, reason: 'start_failed'}; }
      flow.started = true;
      flow.state = 'started';
      stats.flow_started++;
      return {accepted: true, request_seq: flow.seq, route_name: flow.routeName};
    }
    function reportLength(providerKey, length) {
      const flow = providers.get(providerKey);
      if (!flow || !flow.started) { stats.skip_unmapped_provider++; return {accepted: false, reason: 'provider_unmapped'}; }
      if (!Number.isSafeInteger(length) || (length !== -1 && (length < 0 || length > MAX_UPLOAD_BYTES))) {
        stats.skip_over_cap++;
        clearFlow(flow);
        return {accepted: false, reason: 'length_out_of_range'};
      }
      if (flow.expectedLength !== null && flow.expectedLength !== length) {
        stats.skip_length_mismatch++;
        clearFlow(flow);
        return {accepted: false, reason: 'length_changed'};
      }
      flow.expectedLength = length;
      stats.get_length_seen++;
      if (length === 0) {
        const projection = projectUploadBytes(new Uint8Array(0), marker);
        const event = {
          kind: 'upload_projection', request_seq: flow.seq, route_name: flow.routeName,
          route: flow.route, route_sha256: hashPathKey(flow.route),
          time_utc_ms: Date.now(), projection: projection
        };
        stats.upload_projection++;
        stats.marker_rejected++;
        emit(event);
        clearFlow(flow);
        return {accepted: true, request_seq: event.request_seq, empty_upload: true, marker_hit: false};
      }
      return {accepted: true, request_seq: flow.seq, expected_length_known: length >= 0};
    }
    function beginRead(providerKey, sinkKey, bufferKey, capacity, source) {
      const flow = providers.get(providerKey);
      if (!flow || !flow.started) { stats.skip_unmapped_provider++; return {accepted: false, reason: 'provider_unmapped'}; }
      if (!keyOk(sinkKey) || !keyOk(bufferKey) || !Number.isSafeInteger(capacity) || capacity <= 0 || capacity > MAX_UPLOAD_BYTES) {
        stats.skip_over_cap++;
        clearFlow(flow);
        return {accepted: false, reason: 'buffer_capacity_invalid'};
      }
      const existingSink = pendingBySink.get(sinkKey);
      if (existingSink && existingSink.flow === flow && existingSink.providerKey === providerKey &&
          existingSink.bufferKey === bufferKey && existingSink.capacity === capacity) {
        stats.read_duplicate++;
        return {accepted: true, ticket: existingSink.ticket, request_seq: flow.seq,
          capacity: capacity, duplicate: true};
      }
      if (pendingBySink.size >= MAX_PENDING_READS) { stats.pending_cap_skip++; clearFlow(flow); return {accepted: false, reason: 'pending_cap'}; }
      if (existingSink || pendingBuffers.has(bufferKey)) {
        stats.skip_ambiguous_read++;
        clearFlow(flow);
        const otherSink = pendingBuffers.get(bufferKey);
        if (otherSink) {
          const other = pendingBySink.get(otherSink);
          if (other) clearFlow(other.flow);
        }
        return {accepted: false, reason: 'pending_identity_collision'};
      }
      const ticket = flow.seq + ':' + (flow.readSequence = (flow.readSequence || 0) + 1);
      const record = {ticket, flow, providerKey, sinkKey, bufferKey, capacity, source: source === 'callback' ? 'callback' : 'wrapper'};
      pendingBySink.set(sinkKey, record);
      pendingBuffers.set(bufferKey, sinkKey);
      if (record.source === 'callback') stats.read_callback++; else stats.read_wrapper++;
      return {accepted: true, ticket, request_seq: flow.seq, capacity: capacity};
    }
    function concatenate(chunks, extra) {
      let length = extra ? extra.length : 0;
      for (const chunk of chunks) length += chunk.length;
      const out = new Uint8Array(length);
      let offset = 0;
      for (const chunk of chunks) { out.set(chunk, offset); offset += chunk.length; }
      if (extra) out.set(extra, offset);
      return out;
    }
    function ackRead(sinkKey, bytesRead, capacityAtAck, finalChunk, chunk) {
      const record = pendingBySink.get(sinkKey);
      if (!record) { stats.skip_ambiguous_read++; return {accepted: false, reason: 'sink_unmapped'}; }
      pendingBySink.delete(sinkKey);
      if (pendingBuffers.get(record.bufferKey) === sinkKey) pendingBuffers.delete(record.bufferKey);
      const flow = record.flow;
      if (providers.get(record.providerKey) !== flow || requests.get(flow.requestKey) !== flow) {
        clearFlow(flow);
        return {accepted: false, reason: 'flow_mapping_changed'};
      }
      if (!Number.isSafeInteger(bytesRead) || bytesRead < 0 || bytesRead > record.capacity ||
          capacityAtAck !== record.capacity || !(chunk instanceof Uint8Array) || chunk.length !== bytesRead) {
        stats.skip_buffer_mismatch++;
        clearFlow(flow);
        return {accepted: false, reason: 'buffer_snapshot_mismatch'};
      }
      if (bytesRead === 0 && finalChunk !== true) {
        stats.zero_progress_skip++;
        clearFlow(flow);
        return {accepted: false, reason: 'zero_progress'};
      }
      if (flow.received + bytesRead > MAX_UPLOAD_BYTES || totalBytes + bytesRead > MAX_TOTAL_BYTES) {
        stats.skip_over_cap++;
        clearFlow(flow);
        return {accepted: false, reason: 'upload_cap'};
      }
      if (flow.expectedLength !== null && flow.expectedLength >= 0 && flow.received + bytesRead > flow.expectedLength) {
        stats.skip_length_mismatch++;
        clearFlow(flow);
        return {accepted: false, reason: 'length_exceeded'};
      }
      if (flow.chunks.length >= MAX_CHUNKS_PER_FLOW) {
        stats.chunk_cap_skip++;
        clearFlow(flow);
        return {accepted: false, reason: 'chunk_cap'};
      }
      const owned = new Uint8Array(bytesRead);
      owned.set(chunk);
      flow.chunks.push(owned);
      flow.received += bytesRead;
      totalBytes += bytesRead;
      stats.read_ack++;
      const lengthComplete = flow.expectedLength !== null && flow.expectedLength >= 0 && flow.received === flow.expectedLength;
      const complete = finalChunk === true || lengthComplete;
      if (flow.expectedLength !== null && flow.expectedLength >= 0 && complete && flow.received !== flow.expectedLength) {
        stats.skip_length_mismatch++;
        clearFlow(flow);
        return {accepted: false, reason: 'length_mismatch'};
      }
      if (!complete) return {accepted: true, request_seq: flow.seq, upload_pending: true};
      if (flow.expectedLength === null) {
        // A final chunk is enough to delimit chunked uploads; absent GetLength
        // coverage is retained as a coverage limitation, not guessed.
      }
      let combined = concatenate(flow.chunks, null);
      const projection = projectUploadBytes(combined, marker);
      combined = null;
      const event = {
        kind: 'upload_projection', request_seq: flow.seq, route_name: flow.routeName,
        route: flow.route, route_sha256: hashPathKey(flow.route),
        time_utc_ms: Date.now(), projection: projection
      };
      stats.upload_projection++;
      if (projection.marker_hit) stats.marker_matched++; else stats.marker_rejected++;
      emit(event);
      clearFlow(flow);
      return {accepted: true, request_seq: event.request_seq, marker_hit: projection.marker_hit};
    }
    function rewindProvider(providerKey) {
      const flow = providers.get(providerKey);
      if (!flow) return {accepted: false, reason: 'provider_unmapped'};
      stats.skip_rewind++;
      clearFlow(flow);
      return {accepted: false, reason: 'rewind_invalidated'};
    }
    function invalidateRequest(requestKey, reason) {
      const flow = requests.get(requestKey);
      if (!flow) return {accepted: false, reason: reason || 'request_unmapped'};
      clearFlow(flow);
      return {accepted: true, request_seq: flow.seq};
    }
    function dispose() {
      if (disposed) return {active_flows: 0, pending_reads: 0};
      disposed = true;
      for (const flow of requests.values()) zeroFlow(flow);
      requests.clear(); providers.clear(); pendingBySink.clear(); pendingBuffers.clear();
      stats.pending_at_end = 0; stats.total_bytes_at_end = totalBytes;
      return {active_flows: 0, pending_reads: 0};
    }
    return {
      beginRequest, bindProvider, startRequest, reportLength, beginRead, ackRead,
      rewindProvider, invalidateRequest, dispose,
      getCoverage: function () {
        return Object.assign({}, stats, {
          active_flows: requests.size, pending_reads: pendingBySink.size,
          total_bytes: totalBytes, route_counts: Object.assign({}, routeCounts)
        });
      }
    };
  }

  return {
    MAX_UPLOAD_BYTES, MAX_TOTAL_BYTES, MAX_CHUNKS_PER_FLOW, TARGET_MODEL, TARGET_ROUTES,
    projectUploadBytes, createCaptureModel, sha256Ascii, sha256Bytes, hashPathKey,
    canonicalModel, pathKey, hasMarker
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = NativeUploadProjectionCore;
