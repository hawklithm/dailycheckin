'use strict';

// Pure in-memory gate/projector for a future, separately reviewed Cronet body
// observer. This module installs no hooks and performs no process or network
// operations. Callers must establish typed request/provider/callback mappings
// and an exact route match before they read a native buffer.
const NativeBodyProjectionCore = (function () {
  const MAX_UPLOAD_BYTES = 1024 * 1024;
  const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
  const MAX_TOTAL_BYTES = 4 * 1024 * 1024;
  const MAX_ACTIVE_FLOWS = 256;
  const MAX_TRACKED_IDENTITIES = 4096;
  const MAX_PENDING_READS = 512;
  const MAX_JSON_DEPTH = 12;
  const MAX_JSON_NODES = 20000;
  const MAX_SCHEMA_FIELDS = 128;
  const MAX_TOP_LEVEL_FIELDS = 64;
  const MAX_SSE_FRAMES = 256;
  const MAX_SSE_DATA_BYTES = 256 * 1024;
  const TARGET_MODEL = 'deepseek-v4.1-flash';

  const SAFE_KEY_RE = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;
  const SECRET_KEYS = new Set([
    'ak', 'api_key', 'access_token', 'authorization', 'cloudide_token',
    'cookie', 'cookies', 'credential', 'credentials', 'headers', 'jwt',
    'jwt_token', 'password', 'private_key', 'secret', 'token', 'x_api_key',
    'x_ide_token'
  ]);
  const ID_KEYS = new Set([
    'chat_session_id', 'session_id', 'message_id', 'user_message_id',
    'reply_to_message_id', 'request_id', 'task_id', 'agent_task_id',
    'conversation_id', 'operation_id', 'trace_id'
  ]);
  const MODEL_KEYS = new Set([
    'model', 'model_name', 'config_name', 'display_model_name',
    'model_selection_strategy', 'reasoning_effort', 'reasoning_mode'
  ]);
  const USAGE_KEYS = new Set([
    'prompt_tokens', 'completion_tokens', 'total_tokens', 'input_tokens',
    'output_tokens', 'cached_tokens', 'reasoning_tokens',
    'cache_read_tokens', 'cache_creation_tokens'
  ]);
  const ENUM_FIELDS = new Set(['model_selection_strategy', 'reasoning_effort', 'reasoning_mode']);
  const ENUM_VALUES = new Set([
    'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra',
    'auto', 'default', 'manual', 'enabled', 'disabled', 'on', 'off'
  ]);
  const ROLE_VALUES = new Set(['assistant', 'user', 'system', 'developer', 'tool']);
  const RESPONSE_TEXT_KEYS = new Set(['content', 'text', 'text_content', 'content_text', 'reasoning_content']);
  const EVENT_VALUES = new Set([
    'message', 'delta', 'content', 'model_config', 'token_usage',
    'context_usage', 'timing_events', 'done', 'error'
  ]);
  const CONTAINER_KEYS = new Set([
    'query', 'content', 'messages', 'message_contents', 'choices', 'message',
    'delta', 'response', 'output', 'data', 'payload', 'result', 'request',
    'params', 'agent', 'model_config', 'custom_model', 'common_params',
    'extra_chat_params', 'parsed_query', 'usage', 'token_usage',
    'context_usage', 'timing_events', 'tools', 'function', 'arguments'
  ]);
  const SECRET_COMPACT_KEYS = new Set([
    'apikey', 'xapikey', 'authorization', 'authorizationheader', 'auth', 'authmode',
    'authtoken', 'accesstoken', 'refreshtoken', 'bearertoken', 'cloudidetoken',
    'xidetoken', 'jwttoken', 'privatekey', 'password', 'passwd', 'credential',
    'credentials', 'cookie', 'cookies', 'secret', 'headers'
  ]);

  function isSecretKey(key) {
    const lower = key.toLowerCase();
    if (lower === 'token_usage' || USAGE_KEYS.has(lower)) return false;
    const compact = lower.replace(/[^a-z0-9]/g, '');
    if (SECRET_COMPACT_KEYS.has(compact)) return true;
    return SECRET_KEYS.has(lower) ||
      /(^|_)(auth|authorization|token|jwt|secret|password|passwd|credential|cookie|cookies|header|headers|private_key|privatekey|api_key|apikey)(_|$)/.test(lower);
  }

  function typeName(value) {
    if (value === null) return 'null';
    if (Array.isArray(value)) return 'array';
    if (typeof value === 'object') return 'object';
    if (typeof value === 'string') return 'string';
    if (typeof value === 'number') return Number.isInteger(value) ? 'integer' : 'number';
    if (typeof value === 'boolean') return 'boolean';
    return 'unknown';
  }

  function sha256Ascii(ascii) {
    if (typeof ascii !== 'string' || !/^[\x00-\x7f]*$/.test(ascii)) return null;
    const words = [];
    for (let i = 0; i < ascii.length; i++) {
      words[i >> 2] = (words[i >> 2] || 0) |
        (ascii.charCodeAt(i) << (24 - (i % 4) * 8));
    }
    const bitLength = ascii.length * 8;
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

  function hashId(value) {
    if (!((typeof value === 'string' && value.length > 0 && value.length <= 256 && /^[\x20-\x7e]+$/.test(value)) ||
        (typeof value === 'number' && Number.isSafeInteger(value) && value >= 0))) return null;
    try { return sha256Ascii(encodeURIComponent(String(value))); } catch (_) { return null; }
  }

  function bytesToUtf8(bytes) {
    let out = '';
    for (let i = 0; i < bytes.length;) {
      const a = bytes[i++];
      if (a <= 0x7f) out += String.fromCharCode(a);
      else if (a >= 0xc2 && a <= 0xdf) {
        if (i >= bytes.length) throw new Error('utf8');
        const b = bytes[i++];
        if ((b & 0xc0) !== 0x80) throw new Error('utf8');
        out += String.fromCharCode(((a & 0x1f) << 6) | (b & 0x3f));
      } else if (a >= 0xe0 && a <= 0xef) {
        if (i + 1 >= bytes.length) throw new Error('utf8');
        const b = bytes[i++], c = bytes[i++];
        if ((b & 0xc0) !== 0x80 || (c & 0xc0) !== 0x80 ||
            (a === 0xe0 && b < 0xa0) || (a === 0xed && b >= 0xa0)) throw new Error('utf8');
        out += String.fromCharCode(((a & 0x0f) << 12) | ((b & 0x3f) << 6) | (c & 0x3f));
      } else if (a >= 0xf0 && a <= 0xf4) {
        if (i + 2 >= bytes.length) throw new Error('utf8');
        const b = bytes[i++], c = bytes[i++], d = bytes[i++];
        if ((b & 0xc0) !== 0x80 || (c & 0xc0) !== 0x80 || (d & 0xc0) !== 0x80 ||
            (a === 0xf0 && b < 0x90) || (a === 0xf4 && b >= 0x90)) throw new Error('utf8');
        const cp = ((a & 7) << 18) | ((b & 0x3f) << 12) | ((c & 0x3f) << 6) | (d & 0x3f);
        const value = cp - 0x10000;
        out += String.fromCharCode(0xd800 + (value >> 10), 0xdc00 + (value & 0x3ff));
      } else throw new Error('utf8');
    }
    return out;
  }

  function concat(chunks, extra) {
    let total = extra ? extra.length : 0;
    for (const chunk of chunks) total += chunk.length;
    const output = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) { output.set(chunk, offset); offset += chunk.length; }
    if (extra) output.set(extra, offset);
    return output;
  }

  function clearChunks(chunks) {
    for (const chunk of chunks) if (chunk instanceof Uint8Array) chunk.fill(0);
    chunks.length = 0;
  }

  function hasMarker(text, marker) {
    const escaped = marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp('(^|[^A-Za-z0-9_])' + escaped + '($|[^A-Za-z0-9_])').test(text);
  }

  function readObjectPath(root, dottedPath) {
    let value = root;
    for (const segment of dottedPath.split('.')) {
      if (!value || typeof value !== 'object' || Array.isArray(value) ||
          !Object.prototype.hasOwnProperty.call(value, segment)) return {found: false};
      value = value[segment];
    }
    return {found: true, value: value};
  }

  function currentUserMarkerState(root, marker, contract) {
    if (!contract) return 'marker_contract_unconfigured';
    const located = readObjectPath(root, contract.arrayPath);
    if (!located.found || !Array.isArray(located.value)) return 'marker_contract_schema_unknown';
    if (!located.value.length) return 'current_user_entry_missing';
    const current = located.value[located.value.length - 1];
    if (!current || typeof current !== 'object' || Array.isArray(current)) return 'marker_contract_schema_unknown';
    if (current[contract.roleKey] !== contract.roleValue) return 'current_entry_not_user';
    if (typeof current[contract.contentKey] !== 'string') return 'marker_contract_schema_unknown';
    return hasMarker(current[contract.contentKey], marker) ? 'matched' : 'current_user_marker_missing';
  }

  function projectJson(root, marker, targetModel, trackMarker) {
    const projection = {
      schema: [], top_level_schema: [], roles: [], model_fields: {}, id_hashes: {},
      usage: {}, event_types: [], done: false, error_category: null,
      response_marker_hit: false, assistant_marker_hit: false, marker_roles: []
    };
    const schemaSeen = new Set(), roles = new Set(), events = new Set(), markerRoles = new Set();
    let nodeCount = 0;
    const boundedSet = (target, key, value, limit) => {
      if (Object.prototype.hasOwnProperty.call(target, key) || Object.keys(target).length < limit) target[key] = value;
    };

    function addSchema(path, key, value, top) {
      if (!SAFE_KEY_RE.test(key) || isSecretKey(key)) return;
      const item = {path: path ? path + '.' + key : key, type: typeName(value)};
      if (top) {
        if (projection.top_level_schema.length < MAX_TOP_LEVEL_FIELDS) {
          projection.top_level_schema.push({key: key, type: item.type});
        }
      } else if (!schemaSeen.has(item.path) && projection.schema.length < MAX_SCHEMA_FIELDS) {
        schemaSeen.add(item.path);
        projection.schema.push(item);
      }
    }

    function scan(value, path, key, depth, inheritedRole) {
      if (depth > MAX_JSON_DEPTH || nodeCount++ >= MAX_JSON_NODES) return;
      let role = inheritedRole;
      if (key && key.toLowerCase() === 'role' && typeof value === 'string' && ROLE_VALUES.has(value.toLowerCase())) {
        role = value.toLowerCase();
        roles.add(role);
      }
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        const ownRole = value.role;
        if (typeof ownRole === 'string' && ROLE_VALUES.has(ownRole.toLowerCase())) {
          role = ownRole.toLowerCase();
          roles.add(role);
        }
      }
      if (trackMarker !== false && typeof value === 'string' && hasMarker(value, marker)) {
        projection.response_marker_hit = true;
        if (role === 'assistant' && key && RESPONSE_TEXT_KEYS.has(key.toLowerCase())) {
          projection.assistant_marker_hit = true;
          markerRoles.add('assistant');
        } else if (key && RESPONSE_TEXT_KEYS.has(key.toLowerCase()) && role && ROLE_VALUES.has(role)) {
          markerRoles.add(role);
        }
      }
      if (key && (key.toLowerCase() === 'event' || key.toLowerCase() === 'type') && typeof value === 'string') {
        const event = value.toLowerCase();
        if (EVENT_VALUES.has(event)) events.add(event);
      }
      if (key && key.toLowerCase() === 'done' && value === true) projection.done = true;
      if (key && key.toLowerCase() === 'error' && value !== null && value !== false && value !== 0 && value !== '') {
        projection.error_category = 'error';
      }
      if (key && key.toLowerCase() === 'error_code' &&
          ((typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 65535) ||
           (typeof value === 'string' && /^[A-Za-z0-9_-]{1,32}$/.test(value)))) {
        projection.error_category = 'coded_error';
      }

      if (key && SAFE_KEY_RE.test(key) && !isSecretKey(key)) {
        const fieldPath = path ? path + '.' + key : key;
        const lowerKey = key.toLowerCase();
        if (fieldPath.length > 256) return;
        if (!path) addSchema('', key, value, true);
        else addSchema(path, key, value, false);
        if (ID_KEYS.has(lowerKey)) {
          const digest = hashId(value);
          if (digest) boundedSet(projection.id_hashes, fieldPath, digest, 64);
        }
        if (MODEL_KEYS.has(lowerKey) && typeof value === 'string' && value.length <= 128) {
          const normalized = value.trim().toLowerCase();
          if ((lowerKey === 'model' || lowerKey === 'model_name' || lowerKey === 'config_name' || lowerKey === 'display_model_name') &&
              targetModel && normalized === targetModel.toLowerCase()) {
            boundedSet(projection.model_fields, fieldPath, targetModel.toLowerCase(), 32);
          } else if (ENUM_FIELDS.has(lowerKey) && ENUM_VALUES.has(normalized)) {
            boundedSet(projection.model_fields, fieldPath, normalized, 32);
          }
        }
        if (USAGE_KEYS.has(lowerKey) && typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= 100000000) {
          boundedSet(projection.usage, fieldPath, value, 64);
        }
      }

      if (typeof value === 'string' && key && CONTAINER_KEYS.has(key.toLowerCase())) {
        const trimmed = value.trim();
        if (trimmed.length <= MAX_RESPONSE_BYTES && /^[\[{]/.test(trimmed)) {
          try { scan(JSON.parse(trimmed), path ? path + '.' + key : key, '', depth + 1, role); } catch (_) { }
        }
        return;
      }
      if (Array.isArray(value)) {
        if (!key || CONTAINER_KEYS.has(key.toLowerCase())) {
          for (const item of value) scan(item, key ? (path ? path + '.' + key : key) : path, '', depth + 1, role);
        }
        return;
      }
      if (value && typeof value === 'object') {
        if (!key || CONTAINER_KEYS.has(key.toLowerCase())) {
          for (const childKey of Object.keys(value).slice(0, 256)) {
            if (isSecretKey(childKey)) continue;
            scan(value[childKey], path ? path + (key ? '.' + key : '') : (key || ''), childKey, depth + 1, role);
          }
        }
      }
    }

    scan(root, '', '', 0, null);
    projection.roles = Array.from(roles).sort();
    projection.event_types = Array.from(events).sort();
    projection.marker_roles = Array.from(markerRoles).sort();
    return projection;
  }

  function projectSse(text, marker, targetModel) {
    const frames = text.replace(/\r\n/g, '\n').split('\n\n');
    if (frames.length > MAX_SSE_FRAMES + 1) return {parse_state: 'bounded_unknown'};
    const merged = {
      schema: [], top_level_schema: [], roles: [], model_fields: {}, id_hashes: {},
      usage: {}, event_types: new Set(), done: false, error_category: null,
      response_marker_hit: false, assistant_marker_hit: false, marker_roles: new Set()
    };
    const schema = new Set(), top = new Set();
    const mergeBounded = (target, source, limit) => {
      for (const [key, value] of Object.entries(source)) {
        if (Object.prototype.hasOwnProperty.call(target, key) || Object.keys(target).length < limit) target[key] = value;
      }
    };
    let parsedFrames = 0;
    for (const frame of frames) {
      if (!frame) continue;
      let event = '';
      const data = [];
      for (const line of frame.split('\n')) {
        if (line.startsWith(':')) continue;
        if (line.startsWith('event:')) event = line.slice(6).replace(/^ /, '').trim().toLowerCase();
        else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
      }
      if (EVENT_VALUES.has(event)) { merged.event_types.add(event); parsedFrames++; }
      if (event === 'done') merged.done = true;
      if (event === 'error') merged.error_category = 'error';
      if (!data.length) continue;
      const dataText = data.join('\n');
      if (dataText.length > MAX_SSE_DATA_BYTES) return {parse_state: 'bounded_unknown'};
      if (dataText.trim() === '[DONE]') {
        merged.done = true;
        merged.event_types.add('done');
        parsedFrames++;
        continue;
      }
      let parsed;
      try { parsed = JSON.parse(dataText); } catch (_) { continue; }
      const projection = projectJson(parsed, marker, targetModel, true);
      for (const item of projection.schema) {
        if (!schema.has(item.path) && merged.schema.length < MAX_SCHEMA_FIELDS) {
          schema.add(item.path); merged.schema.push(item);
        }
      }
      for (const item of projection.top_level_schema) {
        if (!top.has(item.key) && merged.top_level_schema.length < MAX_TOP_LEVEL_FIELDS) {
          top.add(item.key); merged.top_level_schema.push(item);
        }
      }
      mergeBounded(merged.model_fields, projection.model_fields, 32);
      mergeBounded(merged.id_hashes, projection.id_hashes, 64);
      mergeBounded(merged.usage, projection.usage, 64);
      for (const item of projection.roles) merged.roles.push(item);
      for (const item of projection.event_types) merged.event_types.add(item);
      for (const item of projection.marker_roles) merged.marker_roles.add(item);
      merged.response_marker_hit = merged.response_marker_hit || projection.response_marker_hit;
      merged.assistant_marker_hit = merged.assistant_marker_hit || projection.assistant_marker_hit;
      merged.done = merged.done || projection.done;
      if (projection.error_category) merged.error_category = projection.error_category;
      parsedFrames++;
    }
    if (parsedFrames === 0) return {parse_state: 'unknown_format'};
    return {
      parse_state: 'sse', schema: merged.schema, top_level_schema: merged.top_level_schema,
      roles: Array.from(new Set(merged.roles)).slice(0, 16), model_fields: merged.model_fields,
      id_hashes: merged.id_hashes, usage: merged.usage,
      event_types: Array.from(merged.event_types).sort(), done: merged.done,
      error_category: merged.error_category,
      response_marker_hit: merged.response_marker_hit,
      assistant_marker_hit: merged.assistant_marker_hit,
      marker_roles: Array.from(merged.marker_roles).sort()
    };
  }

  function projectResponse(text, marker, targetModel) {
    if (typeof text !== 'string' || text.length > MAX_RESPONSE_BYTES) return {parse_state: 'bounded_unknown'};
    if (/(^|\n)(event|data):/m.test(text)) return projectSse(text, marker, targetModel);
    let root;
    try { root = JSON.parse(text); } catch (_) { return {parse_state: 'unknown_format'}; }
    const projected = projectJson(root, marker, targetModel, true);
    return Object.assign({parse_state: 'json'}, projected);
  }

  function routeMatches(actual, expected) {
    return Boolean(actual && expected && actual.scheme === 'https' && actual.port === 443 &&
      actual.host === expected.host && actual.port === expected.port &&
      actual.method === expected.method && actual.path_sha256 === expected.path_sha256);
  }

  function create(options) {
    const marker = options && options.marker;
    const suppliedTargetModel = options && typeof options.targetModel === 'string' ? options.targetModel.trim().toLowerCase() : '';
    const targetModel = suppliedTargetModel === TARGET_MODEL ? TARGET_MODEL : '';
    const expectedRoute = options && options.expectedRoute;
    const requestMarkerContract = options && options.requestMarkerContract ? options.requestMarkerContract : null;
    if (typeof marker !== 'string' || !/^TRAE_[A-Z0-9_]{4,80}_OK$/.test(marker)) {
      throw new TypeError('invalid_marker');
    }
    if (!expectedRoute || !/^[a-z0-9.-]{1,253}$/.test(expectedRoute.host || '') ||
        expectedRoute.scheme !== 'https' || expectedRoute.port !== 443 ||
        expectedRoute.method !== 'POST' || !/^[0-9a-f]{64}$/.test(expectedRoute.path_sha256 || '')) {
      throw new TypeError('invalid_exact_route');
    }
    if (!targetModel) throw new TypeError('invalid_target_model');
    if (requestMarkerContract) {
      const path = requestMarkerContract.arrayPath;
      if (typeof path !== 'string' || path.length > 256 ||
          !path.split('.').every(segment => SAFE_KEY_RE.test(segment) && !isSecretKey(segment)) ||
          !SAFE_KEY_RE.test(requestMarkerContract.roleKey || '') ||
          !SAFE_KEY_RE.test(requestMarkerContract.contentKey || '') ||
          requestMarkerContract.roleValue !== 'user' || requestMarkerContract.newestOnly !== true) {
        throw new TypeError('invalid_request_marker_contract');
      }
    }
    const flows = new Map(), requests = new Map(), providers = new Map();
    const pendingUpload = new Map(), pendingResponse = new Map();
    const usedRequestKeys = new Set(), usedProviderKeys = new Set();
    const coverage = {
      flow_started: 0, route_rejected: 0, request_collision: 0, provider_bound: 0,
      provider_reused: 0, upload_reads: 0, upload_acks: 0, marker_matched: 0,
      marker_rejected: 0, response_reads: 0, response_projected: 0,
      skips: Object.create(null)
    };
    let nextSeq = 0, nextTicket = 0, totalBytes = 0;

    function skipped(reason) {
      coverage.skips[reason] = (coverage.skips[reason] || 0) + 1;
      return {accepted: false, reason: reason};
    }
    function getFlowBySeq(seq) {
      for (const flow of flows.values()) if (flow.seq === seq) return flow;
      return null;
    }
    function destroyFlow(flow, reason) {
      if (!flow) return;
      flow.uploadState = reason || flow.uploadState;
      clearChunks(flow.uploadChunks); clearChunks(flow.responseChunks);
      if (flow.requestKey) requests.delete(flow.requestKey);
      if (flow.providerKey) providers.delete(flow.providerKey);
      for (const [ticket, record] of pendingUpload) if (record.flow === flow) pendingUpload.delete(ticket);
      for (const [ticket, record] of pendingResponse) if (record.flow === flow) pendingResponse.delete(ticket);
      flows.delete(flow.requestKey);
    }
    function beginFlow(input) {
      if (!input || !routeMatches(input.route, expectedRoute)) {
        coverage.route_rejected++;
        return skipped('route_not_exact');
      }
      if (typeof input.requestKey !== 'string' || !input.requestKey ||
          typeof input.callbackKey !== 'string' || !input.callbackKey) return skipped('typed_request_mapping_missing');
      if (usedRequestKeys.has(input.requestKey) || requests.has(input.requestKey)) {
        coverage.request_collision++;
        const prior = requests.get(input.requestKey);
        if (prior) destroyFlow(prior, 'request_reused');
        usedRequestKeys.add(input.requestKey);
        return skipped('request_reused');
      }
      if (usedRequestKeys.size >= MAX_TRACKED_IDENTITIES) return skipped('request_identity_cap');
      if (flows.size >= MAX_ACTIVE_FLOWS) return skipped('active_flow_cap');
      const flow = {
        seq: ++nextSeq, requestKey: input.requestKey, callbackKey: input.callbackKey,
        route: input.route, providerKey: null, expectedUploadLength: null,
        uploadChunks: [], uploadBytes: 0, nextUploadSeq: 0, ackUploadSeq: 0,
        responseChunks: [], responseBytes: 0, totalBytes: 0,
        nextResponseSeq: 0, ackResponseSeq: 0,
        markerHit: false, uploadState: 'open', responseState: 'closed'
      };
      flows.set(flow.requestKey, flow); requests.set(flow.requestKey, flow);
      usedRequestKeys.add(flow.requestKey); coverage.flow_started++;
      return {accepted: true, request_seq: flow.seq};
    }
    function bindProvider(seq, providerKey, expectedLength) {
      const flow = getFlowBySeq(seq);
      if (!flow || flow.uploadState !== 'open') return skipped('flow_unavailable');
      if (typeof providerKey !== 'string' || !providerKey ||
          !Number.isSafeInteger(expectedLength) || expectedLength < -1 || expectedLength > MAX_UPLOAD_BYTES) {
        return skipped('provider_length_invalid');
      }
      if (usedProviderKeys.has(providerKey) || providers.has(providerKey)) {
        coverage.provider_reused++;
        const prior = providers.get(providerKey);
        if (prior) destroyFlow(prior, 'provider_reused');
        destroyFlow(flow, 'provider_reused');
        usedProviderKeys.add(providerKey);
        return skipped('provider_reused');
      }
      if (usedProviderKeys.size >= MAX_TRACKED_IDENTITIES) {
        destroyFlow(flow, 'provider_identity_cap');
        return skipped('provider_identity_cap');
      }
      flow.providerKey = providerKey;
      flow.expectedUploadLength = expectedLength;
      providers.set(providerKey, flow); usedProviderKeys.add(providerKey);
      coverage.provider_bound++;
      return {accepted: true, request_seq: flow.seq};
    }
    function beginUploadRead(providerKey, sinkKey, bufferKey, bufferCapacity) {
      if (!requestMarkerContract) return skipped('marker_contract_unconfigured');
      const flow = providers.get(providerKey);
      if (!flow || flow.uploadState !== 'open') return skipped('provider_unmapped');
      if (pendingUpload.size + pendingResponse.size >= MAX_PENDING_READS) return skipped('pending_read_cap');
      if (typeof sinkKey !== 'string' || !sinkKey || typeof bufferKey !== 'string' || !bufferKey) {
        return skipped('upload_pointer_mapping_missing');
      }
      for (const record of pendingUpload.values()) {
        if (record.sinkKey === sinkKey) return skipped('sink_in_flight');
      }
      if (!Number.isSafeInteger(bufferCapacity) || bufferCapacity < 0 || bufferCapacity > MAX_UPLOAD_BYTES) {
        return skipped('upload_capacity_invalid');
      }
      const ticket = ++nextTicket;
      const record = {flow: flow, providerKey: providerKey, sinkKey: sinkKey,
        bufferKey: bufferKey, capacity: bufferCapacity, seq: flow.nextUploadSeq++};
      pendingUpload.set(ticket, record); coverage.upload_reads++;
      return {accepted: true, ticket: ticket, request_seq: flow.seq};
    }
    function rewindProvider(providerKey) {
      const flow = providers.get(providerKey);
      if (!flow) return skipped('provider_unmapped');
      destroyFlow(flow, 'provider_rewind_ambiguous');
      return skipped('provider_rewind_ambiguous');
    }
    function ackUploadRead(ticket, providerKey, sinkKey, bufferKey, bytesRead, bufferSize, chunk, finalChunk) {
      const record = pendingUpload.get(ticket);
      if (!record) return skipped('upload_ticket_missing');
      pendingUpload.delete(ticket);
      const flow = record.flow;
      if (record.providerKey !== providerKey || record.sinkKey !== sinkKey || record.bufferKey !== bufferKey) {
        destroyFlow(flow, 'upload_mapping_mismatch');
        return skipped('upload_mapping_mismatch');
      }
      if (record.seq !== flow.ackUploadSeq++) {
        destroyFlow(flow, 'upload_sequence_ambiguous');
        return skipped('upload_sequence_ambiguous');
      }
      if (!Number.isSafeInteger(bytesRead) || bytesRead < 0 || bytesRead > record.capacity ||
          !Number.isSafeInteger(bufferSize) || bufferSize !== record.capacity || bufferSize < bytesRead ||
          !(chunk instanceof Uint8Array) || chunk.length !== bytesRead || typeof finalChunk !== 'boolean') {
        destroyFlow(flow, 'upload_read_invalid');
        return skipped('upload_read_invalid');
      }
      if (flow.uploadBytes + bytesRead > MAX_UPLOAD_BYTES || totalBytes + bytesRead > MAX_TOTAL_BYTES) {
        destroyFlow(flow, 'upload_cap_exceeded');
        return skipped('upload_cap_exceeded');
      }
      if (flow.expectedUploadLength >= 0 && flow.uploadBytes + bytesRead > flow.expectedUploadLength) {
        destroyFlow(flow, 'upload_length_mismatch');
        return skipped('upload_length_mismatch');
      }
      const copy = new Uint8Array(bytesRead); copy.set(chunk);
      flow.uploadChunks.push(copy); flow.uploadBytes += bytesRead; flow.totalBytes += bytesRead;
      totalBytes += bytesRead; coverage.upload_acks++;
      const complete = finalChunk || (flow.expectedUploadLength >= 0 && flow.uploadBytes === flow.expectedUploadLength);
      if (!complete) return {accepted: true, request_seq: flow.seq, upload_pending: true};
      if (flow.expectedUploadLength >= 0 && flow.uploadBytes !== flow.expectedUploadLength) {
        destroyFlow(flow, 'upload_length_mismatch');
        return skipped('upload_length_mismatch');
      }
      const bodyBytes = concat(flow.uploadChunks);
      clearChunks(flow.uploadChunks);
      flow.uploadState = 'complete';
      let bodyText = '';
      try { bodyText = bytesToUtf8(bodyBytes); }
      catch (_) { bodyBytes.fill(0); destroyFlow(flow, 'upload_utf8_invalid'); return skipped('upload_utf8_invalid'); }
      let parsed;
      try { parsed = JSON.parse(bodyText); }
      catch (_) {
        bodyText = '';
        bodyBytes.fill(0);
        flow.uploadState = 'invalid_json';
        flow.responseState = 'closed';
        return {kind: 'upload_gate', request_seq: flow.seq, matched: false, reason: 'invalid_json'};
      }
      const markerState = currentUserMarkerState(parsed, marker, requestMarkerContract);
      if (markerState !== 'matched') {
        bodyText = '';
        bodyBytes.fill(0);
        flow.uploadState = 'marker_rejected';
        coverage.marker_rejected++;
        flow.responseState = 'closed';
        return {kind: 'upload_gate', request_seq: flow.seq, matched: false, reason: markerState};
      }
      const fullProjection = projectJson(parsed, marker, targetModel, false);
      const projection = {
        schema: fullProjection.schema,
        top_level_schema: fullProjection.top_level_schema,
        roles: fullProjection.roles,
        model_fields: fullProjection.model_fields,
        id_hashes: fullProjection.id_hashes,
        usage: fullProjection.usage,
        event_types: fullProjection.event_types,
        done: fullProjection.done,
        error_category: fullProjection.error_category
      };
      bodyText = '';
      bodyBytes.fill(0);
      parsed = null;
      flow.markerHit = true; flow.uploadState = 'marker_matched'; flow.responseState = 'open';
      flow.requestProjection = projection; coverage.marker_matched++;
      return {kind: 'request_projection', request_seq: flow.seq, marker_hit: true, projection: projection};
    }
    function beginResponseRead(callbackKey, requestKey, bufferKey, bufferCapacity) {
      const flow = requests.get(requestKey);
      if (!flow || flow.callbackKey !== callbackKey) return skipped('response_request_mapping_invalid');
      if (!flow.markerHit || flow.responseState !== 'open') return skipped('marker_gate_closed');
      if (pendingUpload.size + pendingResponse.size >= MAX_PENDING_READS) return skipped('pending_read_cap');
      if (typeof bufferKey !== 'string' || !bufferKey || !Number.isSafeInteger(bufferCapacity) ||
          bufferCapacity < 0 || bufferCapacity > MAX_RESPONSE_BYTES) return skipped('response_buffer_invalid');
      const ticket = ++nextTicket;
      pendingResponse.set(ticket, {flow: flow, callbackKey: callbackKey,
        requestKey: requestKey, bufferKey: bufferKey, capacity: bufferCapacity,
        seq: flow.nextResponseSeq++});
      coverage.response_reads++;
      return {accepted: true, ticket: ticket, request_seq: flow.seq};
    }
    function completeResponseRead(ticket, callbackKey, requestKey, bufferKey, bytesRead, bufferSize, chunk) {
      const record = pendingResponse.get(ticket);
      if (!record) return skipped('response_ticket_missing');
      pendingResponse.delete(ticket);
      const flow = record.flow;
      if (record.callbackKey !== callbackKey || record.requestKey !== requestKey || record.bufferKey !== bufferKey ||
          requests.get(requestKey) !== flow || flow.callbackKey !== callbackKey) {
        destroyFlow(flow, 'response_mapping_mismatch');
        return skipped('response_mapping_mismatch');
      }
      if (record.seq !== flow.ackResponseSeq++) {
        destroyFlow(flow, 'response_sequence_ambiguous');
        return skipped('response_sequence_ambiguous');
      }
      if (!flow.markerHit || flow.responseState !== 'open') return skipped('marker_gate_closed');
      if (!Number.isSafeInteger(bytesRead) || bytesRead < 0 || bytesRead > record.capacity ||
          !Number.isSafeInteger(bufferSize) || bufferSize !== record.capacity || bufferSize < bytesRead ||
          !(chunk instanceof Uint8Array) || chunk.length !== bytesRead) {
        destroyFlow(flow, 'response_read_invalid');
        return skipped('response_read_invalid');
      }
      if (flow.responseBytes + bytesRead > MAX_RESPONSE_BYTES || totalBytes + bytesRead > MAX_TOTAL_BYTES) {
        destroyFlow(flow, 'response_cap_exceeded');
        return skipped('response_cap_exceeded');
      }
      const copy = new Uint8Array(bytesRead); copy.set(chunk);
      flow.responseChunks.push(copy); flow.responseBytes += bytesRead; flow.totalBytes += bytesRead;
      totalBytes += bytesRead;
      return {accepted: true, request_seq: flow.seq};
    }
    function finishRequest(requestKey, callbackKey, statusCode, outcome) {
      const flow = requests.get(requestKey);
      if (!flow || flow.callbackKey !== callbackKey) return skipped('terminal_mapping_invalid');
      if (!Number.isSafeInteger(statusCode) || (statusCode !== 0 && (statusCode < 100 || statusCode > 599))) {
        destroyFlow(flow, 'status_invalid');
        return skipped('status_invalid');
      }
      if (!['succeeded', 'failed', 'canceled'].includes(outcome)) outcome = 'unknown';
      let response = {parse_state: 'marker_gate_closed', response_marker_hit: null,
        assistant_marker_hit: false, marker_roles: [], schema: [], top_level_schema: [],
        roles: [], model_fields: {}, id_hashes: {}, usage: {}, event_types: [],
        done: false, error_category: null};
      const responsePending = Array.from(pendingResponse.values()).some(record => record.flow === flow);
      if (responsePending) {
        coverage.skips.response_read_pending_at_terminal = (coverage.skips.response_read_pending_at_terminal || 0) + 1;
        response = Object.assign({}, response, {parse_state: 'response_read_pending_at_terminal'});
      } else if (flow.markerHit && flow.responseState === 'open') {
        const bytes = concat(flow.responseChunks);
        clearChunks(flow.responseChunks);
        let text = '';
        try { text = bytesToUtf8(bytes); response = projectResponse(text, marker, targetModel); }
        catch (_) { response = {parse_state: 'invalid_utf8'}; }
        text = '';
        bytes.fill(0);
        coverage.response_projected++;
      }
      const result = {
        kind: 'terminal_projection', request_seq: flow.seq,
        marker_gate_open: flow.markerHit, status_code: statusCode,
        outcome: outcome, response: response
      };
      destroyFlow(flow, 'terminal');
      return result;
    }
    function dispose() {
      for (const flow of Array.from(flows.values())) destroyFlow(flow, 'disposed');
      pendingUpload.clear(); pendingResponse.clear(); requests.clear(); providers.clear(); flows.clear();
      return {active_flows: flows.size, pending_upload: pendingUpload.size, pending_response: pendingResponse.size};
    }
    return {
      beginFlow, bindProvider, beginUploadRead, rewindProvider, ackUploadRead,
      beginResponseRead, completeResponseRead, finishRequest, dispose,
      getCoverage: () => JSON.parse(JSON.stringify(coverage)),
      caps: {upload: MAX_UPLOAD_BYTES, response: MAX_RESPONSE_BYTES, total: MAX_TOTAL_BYTES}
    };
  }

  return {create: create, projectJson: projectJson, projectResponse: projectResponse,
    routeMatches: routeMatches, sha256Ascii: sha256Ascii, targetModel: TARGET_MODEL};
})();

if (typeof module !== 'undefined' && module.exports) module.exports = NativeBodyProjectionCore;
