# Native authorization candidate matching — 2026-10-27

## Scope and safety boundary

`tools/native_auth_matcher.py` provides a local, read-only matcher for a later
reviewed observer. It does not call `TraeAuth`, `get_jwt`, OAuth, HTTP, token
refresh, or token rotation. It does not read the Trae device-key record. The
Trae storage path selects only `iCubeAuthInfo://icube.cloudide`, decrypts that
value with the existing `credential_decrypt.decrypt_value`, and selects only
the resulting `token` field. The proxy credentials path selects only `token`
and `jwt`, either under `auth` or at the JSON root. A selective JSON parser
validates other fields without decoding their string values into Python
objects.

The CLI defaults to `safe_preview`: it checks whether the two expected files
exist and does not open them. Reading credential contents requires the
explicit `--live` switch. Even in live mode, output contains only fixed source
and field reason codes, presence booleans, and an optional expiration boolean.
No paths, tokens, token hashes, refresh tokens, private keys, user identifiers,
or exception text are emitted. Digest comparisons compute candidate SHA-256
values ephemerally in memory; no digest is retained or emitted. The initial
implementation and fixture tests did not read real credentials. After explicit
main-agent approval, one local candidate-availability check used `--live`; its
safe result is recorded below. It did not establish remote authorization.

## In-memory API for the reviewed observer

```python
from tools.native_auth_matcher import load_candidate_inventory

inventory = load_candidate_inventory(storage_path, credentials_path)
match = inventory.match_authorization_value(authorization_value)
# Safe fields only: match.matched_sources, match.same_value,
# match.cloud_ide_jwt_prefix, match.reason
```

Keep `inventory` inside the Python process and do not log or serialize it. The
raw-value API accepts a header value already held by that process; matching
strips only one exact leading
`Cloud-IDE-JWT ` prefix from each side, then compares the exact UTF-8 bytes with
`hmac.compare_digest`. It does not trim whitespace, alter token case, decode,
URL-encode, or guess another prefix. Source labels are
`trae.storage.token`, `proxy.token`, and `proxy.jwt`.

For a Frida observer that must not send the raw header value over IPC, use the
digest-only API. The event keys are `header_name`, `header_prefix_kind`, and
`header_digest_sha256`; canonical header names are `authorization`,
`x-ide-token`, and `x-cloudide-token`, while prefix kinds are `none` and
`cloud_ide_jwt`.

```python
match = inventory.match_token_digest(
    event["header_digest_sha256"],
    prefix_kind=event["header_prefix_kind"],
    header_name=event["header_name"],
)
```

The digest is lowercase SHA-256 hex over the normalized token's exact UTF-8
bytes. Python computes candidate digests ephemerally and compares them in
constant time; it does not return, retain, print, or log either digest. The
digest event must bypass the general event sanitizer and all persistent logs;
consume it in memory, discard it, and emit only the safe match result. The JS
side must reject non-ASCII header values if its hashing path cannot hash their
exact UTF-8 bytes. It must not substitute `encodeURIComponent`, trimming,
case folding, or token decoding.

Expiration is only a parsed, unverified JWT `exp` claim. It is not signature
validation and must not be described as token validity. A value without a
bounded, parseable numeric claim reports `expired: null`.

## Offline verification

`tests/test_native_auth_matcher.py` uses synthetic JSON and an injected fake
decryptor only. The 17 cases cover matching token aliases, distinct JWTs,
raw/digest API agreement, exact prefix handling, digest validation, exact-case
behavior, empty/wrong-type values, top-level and nested proxy fields, duplicate
JSON keys, expiry reporting, missing/bad JSON, decryption exceptions,
selective field parsing, and CLI output redaction.

Command:

```powershell
& 'E:/tools/frida/venv/Scripts/python.exe' -m unittest discover -s tests -p test_native_auth_matcher.py -v
& 'E:/tools/frida/venv/Scripts/python.exe' -c 'import tools.native_auth_matcher as m; print("module import: ok; digest API: " + str(hasattr(m.CandidateInventory, "match_token_digest")))'
```

Result: 17 tests passed; module import and digest API presence confirmed. No
live mode was used for these fixture tests.

## Approved local candidate availability check

The main agent approved one controlled local read to confirm that the
capture-time interpreter could load candidate token fields. The controlled
command that read credentials was run once before and once after the dependency
repair:

```powershell
& 'E:/tools/frida/venv/Scripts/python.exe' tools/native_auth_matcher.py --live
```

At 2026-10-27 13:29:27 UTC, before dependency repair, the fixed result was
`trae_storage: exists=true, reason=decrypt_failed` and
`proxy_credentials: exists=true, reason=ready`; the proxy token candidate was
present with `expired=false`. Static dependency inspection found that the
capture venv lacked `cryptography`, which `credential_decrypt.decrypt_blob`
imports lazily for AES-CBC decryption.

Only the dedicated Frida venv was updated. The installer output was suppressed:

```powershell
$env:PIP_DISABLE_PIP_VERSION_CHECK='1'; & 'E:/tools/frida/venv/Scripts/python.exe' -m pip install --quiet --only-binary=:all: cryptography *> $null
```

The installed version is `cryptography 50.0.2`. The same `--live` command was
rerun at 2026-10-27 13:30 UTC. Its safe status was:

- Trae storage: `ready`; token candidate `present=true`, `expired=false`.
- Proxy credentials: `ready`; token candidate `present=true`, `expired=false`.
- Proxy JWT field: `missing_field`.

The post-install Frida-venv fixture suite again passed all 17 tests, and the
module import/digest API check passed. No token, digest, plaintext, user ID,
private key, or exception message was emitted. `expired=false` reflects only
the unverified numeric JWT `exp` claim; these local results do not prove that a
remote endpoint accepts either candidate or that a native request used either
one.

## Targeted native request-header static follow-through

This pass was limited to the user-supplied installed Trae CN 3.4.7 / VS Code
1.107.1 directory and the seven named header strings. It searched extracted
application `.js`, `.mjs`, `.cjs`, `.ts`, `.json`, and `.html` files (excluding
source maps and logs), then inspected only `ai_agent.dll` and `harness.dll`.
The text bundles had no exact header-name hits. Current DLL identities were
`ai_agent.dll` SHA-256
`1691ABEDD6DC084F620291F27613EB5D60E77685E6D3FC137ECF2D76C4C7A362`
(280,218,000 bytes) and `harness.dll` SHA-256
`F27F80B06B15047DC6519CCC2E04FDC9A6187D38D2EB0C6DA79FE6EC043D027C`
(219,872,656 bytes). Offsets below are file offsets, not RVAs.

| Header literal (actual case) | `ai_agent.dll` file offsets | `harness.dll` file offsets |
|---|---|---|
| `X-Request-Pin` | `0x9B2F181`, `0x9C3A09D`, `0xA41B9F0`, `0xA5307E1` | `0xADC4F78` |
| `X-Requested-At` | `0x9B2F18E`, `0x9C3A0AA`, `0xA41B9FD`, `0xA5307EE` | `0xADC4F85` |
| `x-agent-host-type` | `0xA6B58E2` | `0xADC4F65` |
| `x-harness` | no hit | `0x94820A2`, `0x97E8C83`, `0xADC3254` |
| `x-bridge-transport` | `0xCB20DAE`, `0xCC13ADE`, `0xCC141A1` | `0x953E83E`, `0xB044FF8`, `0xB046340`, `0xB2276D8` |
| `x-app-version-code` | `0xA4B0CE7`, `0xA6B3607` | `0x9CD2275`, `0xADC35C0` |
| `x-ide-version-type` | `0x9B2F202`, `0xA4B0DA4`, `0xA530862`, `0xA6B36E4` | `0x9CD1BAB`, `0xADC359C` |

The pin and requested-at literals are capitalized in the binary; the other
five are lowercase. The old lowercase-only search therefore missed the first
two. This is string evidence only until an instruction xref or a construction
path is shown.

### `X-Request-Pin` and `X-Requested-At`

The reusable `tools/native_xref_harness.py` was run with the exact-case
`X-Request-Pin` and `X-Requested-At` targets against the current `harness.dll`.
The `.rdata` mapping is raw `0x9460E00` to RVA `0x9462000`. The key literals
are at raw `0xADC4F78` / RVA `0xADC6178` and raw `0xADC4F85` / RVA
`0xADC6185`. Capstone-validated RIP-relative `LEA` references point to them
at code RVAs `0x67FFB91` and `0x67FFBCD`, both inside one `.pdata` function,
`0x67FF8D0–0x67FFD59`. Each is followed by its literal length (13 and 14)
and a call to the same map-entry helper at RVA `0x67FDBE0`. This is direct
evidence that this function creates both entries in one returned header map.

At `0x67FFB2A`, the function calls helper RVA `0x67DAD10` with an output
object at `[rbp+0x30]`, input pointer/length loaded from the fourth argument's
`+8` and `+0x10` fields, and an auxiliary pointer loaded from the second
argument's `+0x48` field. The pin insertion at `0x67FFB91` uses the first
string-like value from that helper result. Before the requested-at insertion
at `0x67FFBCD`, the caller copies helper-result fields at offsets `+0x38`,
`+0x40`, and `+0x48` into the second three-field value. Thus both values come
from a dynamic helper result, not fixed literals; the helper also reads the
system clock as detailed below.

The helper's narrow local path contains these additional findings:

- At `0x67DAD49`, a 0x28-byte wrapper at RVA `0x8A5DDA0` calls through IAT
  slot RVA `0x9462E20`. LIEF maps that slot to
  `kernel32!GetSystemTimePreciseAsFileTime`; the wrapper copies the returned
  low/high words from its stack buffer.
- At `0x67DAD68` and `0x67DAD6E`, the code loads `0xD53E8000` and
  `0x019DB1DE` before calling `0x8A5DD50`. Together they are the Windows
  FILETIME-to-Unix-epoch offset `0x019DB1DED53E8000`. A nearby error literal
  begins at file offset `0xADC314D` and contains
  `system clock is before Unix epoch:`.
- At `0x67DB27E`, the helper calls `0x1888C8130`, loads a context pointer,
  then calls a method through `[r12+8]` at `0x67DB2B7`. That failure branch
  references the literals `AES-256-GCM encryption failed` (file offset
  `0xADC31A0`) and `failed to initialize AES-256-GCM key` (file offset
  `0xADC31BD`). This establishes an AES-256-GCM-related crypto stage in the
  helper, but the indirect method's key, nonce, AAD, and exact input layout
  are not identified by this bounded inspection.
- At `0x67DB469`, the helper calls encoder RVA `0x67F5560` with an input
  pointer in `r13` and length in `r14`. Its configuration points to RVA
  `0xADC41ED` / file offset `0xADC2FED`, whose bytes start with flags
  `01 00 01` followed by the standard Base64 alphabet. The encoder computes
  output capacity using division by 3 and writes `=` padding. This proves a
  standard-alphabet padded Base64 stage; it does not prove the full bytes
  encoded or whether the encoded result is combined with other data later.

One bounded caller sample was confirmed by disassembling `.pdata` function
`0x35DBA0–0x35F9DB`. At callsite `0x35E661`, its fourth argument points to a
stack record at `[rbp+0xC50]`. The caller first invokes helper `0x1818DCE10`
at `0x35E56F`, then copies returned fields from `[rbp+0xD50]`, `+0xD58`,
`+0xD60`, and `+0xD68` into that record's `+0x00`, `+0x08`, `+0x10`, and
`+0x18` slots. The record is then passed as argument four at `0x35E661`.
The upstream helper's semantic output remains unknown. A byte scan found 67
raw `E8 rel32` candidates targeting `0x67FF8D0`; only this selected caller
was instruction-boundary checked. No route was linked to it, so this does
not establish which caller is active for a native request.

### Other requested header names

The route/header helper reports these current `harness.dll` code references:

- `x-agent-host-type`: literal raw offset `0xADC4F65` (RVA `0xADC6165`),
  adjacent to the pin/at strings; no direct RIP-relative LEA/MOV reference
  was found by the helper's supported forms.
- `x-harness`: references at code RVAs `0x3658F9` and `0x2F19F90` target
  literal RVAs `0x94832A2` and `0x97E9E83`. A third literal at raw
  `0xADC3254` had no reference. The two containing functions exceed the
  helper's 0x2000-byte caller-inspection limit.
- `x-bridge-transport`: a reference at `0x16E293D` targets RVA `0x953FA3E`;
  two more at `0x8188C1E` and `0x8188C6B` target RVA `0xB2288D8`. The
  containing function at `0x16DFFA0–0x16E8A63` exceeds the helper limit;
  the smaller function `0x8188BF0–0x8188DC9` has direct calls but no named
  caller or route identity. The other two occurrences had no reference.
- `x-app-version-code`: reference at code RVA `0x3B02604` targets literal
  RVA `0x9CD3475`; the other literal at raw `0xADC35C0` had no reference.
- `x-ide-version-type`: references at code RVAs `0x3B00CB2`, `0x3B02B67`,
  and `0x67DFFD8` target literal RVAs `0x9CD2DAB` (the first two) and
  `0xADC479C`. Their containing functions did not identify a semantic caller
  or a native route in this bounded pass.

These references show where selected string addresses enter code, not the
runtime values, header transmission, or active caller. The original bounded
route scan remains unchanged: it found route literals but no identified
route caller or auth construction. No process was attached, no credential was
read, no request or refresh was performed, and no configuration was changed.

### Python reproduction boundary

The evidence supports only a non-executable parameter-boundary sketch:

```python
def build_native_header_values(
    *,
    filetime_100ns: int,          # current source: GetSystemTimePreciseAsFileTime
    upstream_bytes: bytes,        # observed pointer/length pair; semantics unknown
    opaque_crypto_context: object,  # key/nonce/AAD mapping not recovered
) -> tuple[bytes, bytes]:         # X-Request-Pin, X-Requested-At values
    ...
```

This is not a Python implementation contract. Before reproducing the bytes,
the remaining evidence must identify the AES key, nonce, AAD and plaintext
layout; the GCM ciphertext/tag/nonce concatenation and Base64 input; the
upstream fields' meanings; and the exact timestamp text, units, and format.
No signing algorithm, active route, or Python-equivalent header value is
claimed from this static pass.

## Bounded AES-GCM parameter-flow addendum (2026-10-27)

This addendum supersedes the earlier statement that the AES call's key, nonce,
and input pairs were all unidentified. It resolves the local parameter boundary
and part of the byte assembly, but does not recover the full protocol or prove
the semantic names of every argument. The inspected image remains the installed
`harness.dll` SHA-256 `F27F80B06B15047DC6519CCC2E04FDC9A6187D38D2EB0C6DA79FE6EC043D027C`.

The image's `.text` section maps VA `0x180001000` to raw file offset
`0x400`, so for code RVAs in that section raw offset is `RVA - 0xC00`.
Addresses below are RVAs unless a VA or raw file offset is explicitly named.

### Caller inputs and 32-byte key-init material

At `0x67FFB00–0x67FFB2A` (raw `0x67FEF00–0x67FEF2A`), the header helper
loads the fourth argument record's `+0x08` and `+0x10` fields into RDX and R8,
then calls `0x67DAD10`. It separately loads a pointer from the second argument's
`+0x38` field and adds `0x10`; this remains in R9 at the call. The callee saves
RDX/R8 as its input pointer/length pair and R9 as the seed pointer. Thus the
seed source is precisely `*(arg2 + 0x38) + 0x10` (32 bytes read), while the
payload candidate comes from `(arg4 + 0x08, arg4 + 0x10)`. The pointed-to
structures' meanings are still unknown.

The callee requests 8 random bytes at `0x67DAE50` and 12 at `0x67DAF2E`, both
through fill helper RVA `0x8A2EB50` (raw `0x8A2DF50`). That helper calls imported
`BCryptGenRandom` through IAT RVA `0x9462848` (raw `0x9461648`) with
`RCX=0`, destination in RDX, requested length in R8D, and `R9D=2`; on failure
it tries `SystemFunction036` through IAT RVA `0x9462130` (raw `0x9460F30`).
The import table confirms the two symbol names. This is static import evidence;
no random values were sampled.

At `0x67DB002–0x67DB073` (raw `0x67DA402–0x67DA473`), the callee copies 32
bytes from the R9 seed pointer to a stack key buffer. It XORs the first 8 seed
bytes with the 8-byte random value byte-by-byte, least-significant byte first;
the remaining 24 bytes are copied unchanged. At `0x67DB079–0x67DB099` (raw
`0x67DA479–0x67DA499`) it passes that buffer and length `0x20` to the key-init
dispatch. This proves the 32-byte key-init input construction, not whether the
key initializer further transforms it into the final AES key schedule.

### Resolved crypto dispatch and call arguments

The key-init dispatch pointer is loaded from global VA `0x18CA7FD80` (RVA
`0xCA7FD80`, raw `.data` offset `0xCA7E980`). Its value points to the static
`.rdata` table at VA `0x18B3E2F28` (RVA `0xB3E2F28`, raw offset `0xB3E1D28`).
The table's first two entries point to code RVAs `0x88C8280` (key-init wrapper)
and `0x88C81C0` (the next method). The key-init result stores this table
pointer at `[rbp+0x3F0]`; the `0x67DB168` copy of `0x1C0` bytes from
`[rbp+0x240]` to `[rbp+0x20]` carries it to `[rbp+0x1D0]`. Therefore the
load at `0x67DB277` is resolved: `[rbp+0x1D0]` is that dispatch table, and
`call [r12+8]` at `0x67DB2B7` calls method RVA `0x88C81C0`.

At the indirect method call `0x67DB2B7` (raw `0x67DA6B7`), the arguments are:

- RCX: result/status object at `[rbp+0x1E0]`.
- RDX: key-init context at `[rbp-0x40]`.
- R8: pointer to the 12 random bytes at `[rbp+0x4C8]`.
- R9: pointer `[rbp+0x528]` to a decimal timestamp buffer.
- stack `+0x20`: timestamp-buffer length `[rbp+0x530]`.
- stack `+0x28` and `+0x30`: copied caller-input pointer `[rbp+0x518]` and length `[rbp+0x520]`.

Method RVA `0x88C81C0` forwards these register and stack arguments to helper
RVA `0x88EA1B0`; that helper reads the 12-byte third argument as a qword plus a
dword and forwards separate time-buffer and input-buffer pointer/length pairs
to core helper RVA `0x88CE3B0` (callsite VA `0x1888EA2AE`, RVA `0x88EA2AE`,
raw `0x88E96AE`). This resolves the previous unknown indirect method and its
argument boundary. The time pair occupies an AAD-like argument position and
the caller-input pair a plaintext-like position; those role labels remain
inferred from argument ordering until the core helper is inspected. The
12-byte value's counter-block construction is documented below.

### Clock-derived value and pre-Base64 assembly

The time converter at RVA `0x8A5DD50` (raw `0x8A5D150`) subtracts the FILETIME
epoch constant `0x019DB1DED53E8000`, divides 100-nanosecond ticks by
`10,000,000`, and stores whole Unix seconds plus a subsecond remainder scaled
by 100. On the normal non-pre-epoch path, the whole-seconds field is passed at
`0x67DB1FE` to integer-to-decimal formatter RVA `0x8A78D20` (raw `0x8A78120`)
with a 20-byte capacity. The formatter returns pointer/length; the caller
copies that decimal ASCII seconds string to `[rbp+0x528]` and records its
length at `[rbp+0x530]`. That pair is passed into the crypto method as R9 and
stack `+0x20`. This proves a decimal Unix-seconds component enters the method;
it does not by itself prove that this is the final `X-Requested-At` value or
that the crypto core treats it as AAD.

On the successful crypto-result branch (`[rbp+0x1E0] == 0`), code at
`0x67DB34D` calls append helper RVA `0xA5B910` (raw `0xA5AD10`) to append 16
bytes starting at `[rbp+0x1E1]` to the copied input vector at `[rbp+0x510]`.
The helper updates that vector's length at `[rbp+0x520]` by 16. The caller
then allocates an output buffer of the resulting vector length plus 12, writes
the same 12-byte random value at the front, and copies the vector after it.
Immediately before the Base64 encoder call at `0x67DB469` (raw `0x67DA869`),
R13 points to that assembled buffer and R14 is exactly `12 + vector_length`.
Therefore the bytes submitted to padded standard Base64 have the structural
form `12-byte random prefix || copied-input vector after crypto call ||
16-byte crypto-result block`. The 16-byte block is a GCM-tag candidate, and
the copied-input region is a ciphertext candidate; the inspected wrapper does
not prove the core mutates that region in place or assign a typed meaning to
the returned 16 bytes. The final returned header string can also be combined
or formatted after Base64, so the encoded bytes are not claimed to equal the
final `X-Request-Pin` value byte-for-byte.

### Reproduction boundary and unresolved items

A safe Python interface sketch may now expose these observed inputs:

```python
def native_pin_boundary(
    *,
    seed_material_32: bytes,   # source: *(arg2 + 0x38) + 0x10
    input_bytes: bytes,        # source: arg4 + 0x08 / arg4 + 0x10
    filetime_100ns: int,       # GetSystemTimePreciseAsFileTime
    random8: bytes,            # XORed into seed_material_32[0:8]
    random12: bytes,           # passed as crypto argument 3 and prefixed
    crypto_context: object,    # key-init method at RVA 0x88C8280
) -> tuple[bytes, bytes]:
    ...
```

This remains an interface sketch, not a Python implementation contract. Still
unproven: the seed object's semantic source and whether the key initializer
RVA `0x88C8280` further derives the actual AES key; the exact AAD/plaintext
semantics at core helper RVA `0x88CE3B0`; whether the input buffer is mutated
to ciphertext; the semantic identity and exact placement of the 16-byte result
(tag candidate); and how the decimal Unix-seconds string maps into the
returned header fields, especially the `X-Requested-At` value. No route or
active network caller was linked by this follow-through. No process was
attached, no credential was read, and no remote call or refresh was made.

Correction to an earlier parameter note: `[rbp+0x4C8]` contains the raw FILETIME
low/high words immediately after the clock read, but the helper later overwrites
that stack region with the 12-byte random value before the `0x67DB2B7` crypto
call. At that call, R8 therefore points to the random 12-byte value, not the
original FILETIME. The clock-derived decimal seconds travel separately in the
R9 plus stack-length pair described above.

Nonce/IV confirmation detail: helper RVA `0x88EA1B0` copies the 12-byte
R8 value into a 16-byte scratch block, sets the trailing word to `0x00000001`,
then uses `bswap / increment / bswap` on that 32-bit counter. This is direct
byte-level evidence for the GCM `IV[12] || counter` preparation (including
big-endian counter increment), so the 12-byte random value is the nonce/IV
input, not just an arbitrary 12-byte parameter. The time pair and payload pair
are passed separately to core RVA `0x88CE3B0` in AAD-like and plaintext-like
positions respectively; those role labels remain inferred from argument order
until that core implementation is inspected.

## Core GCM, returned-header, and 8-byte RNG follow-up (2026-10-27)

This addendum supersedes the prior unresolved labels for the AAD, payload
mutation, 16-byte result, and `X-Requested-At` field. It remains a static
control/data-flow result for the same installed image; no runtime values were
read. Raw offsets use the `.text` mapping stated above (`raw = RVA - 0xC00`).

### AES-GCM core semantics

At core RVA `0x88CE3B0` (raw `0x88CD7B0`), the time slice and payload slice
arrive as separate stack pairs. After the prologue, the core uses the time
pointer/length first: it processes the slice in chunks of up to 16 bytes,
zero-pads a final partial block, and feeds each block to helper RVA `0x88EC7E0`
(callsite in the AAD loop begins at RVA `0x88CE4D5`). Only after this loop
finishes does it load the payload pointer/length and call RVA `0x88ED840` at
RVA `0x88CE57A` (raw `0x88CD97A`). That call passes the same payload pointer in
RCX and RDX, plus the payload length in R8; the target writes to the buffer
address in RDX. Thus the caller's copied input buffer is transformed in place.
The preceding time pair is the AAD input; the following payload pair is the
plaintext input, based on their distinct processing paths and the GCM core's
AAD-before-payload structure.

The core performs the counter-mode transform and GHASH path, then calls finalizer
RVA `0x88E9550` (raw `0x88E8950`) at callsite RVA `0x88CE672`. The finalizer
writes exactly 16 bytes at result pointer `+1` and writes success status zero
at result byte `+0`. In conjunction with the helper's AES-256-GCM error path,
its preceding GHASH/AES processing, and the outer append below, this 16-byte
result is the GCM authentication tag.

On success, helper RVA `0x67DAD10` appends the 16-byte result block to the
in-place-encrypted payload vector at RVA `0x67DB34D` (raw `0x67DA74D`). It then
builds the Base64 input as `12-byte GCM IV || ciphertext || 16-byte tag` and
passes that buffer and its exact combined length to the standard padded
Base64 encoder at RVA `0x67DB469` (raw `0x67DA869`). The earlier uncertainty
about whether the payload changed in place and whether the 16-byte block was a
tag is therefore closed by the local core and output path.

### Exact `X-Requested-At` value

The decimal formatter call at RVA `0x67DB50A` (raw `0x67DA90A`) receives RDI,
which still contains the whole Unix-seconds value from the FILETIME conversion.
It returns a pointer/length into a temporary buffer. At RVA `0x67DB551` (raw
`0x67DA951`) the returned bytes are copied into a separately allocated output
string. The helper returns the output string's length, pointer, and length in
fields `+0x38`, `+0x40`, and `+0x48` at RVAs `0x67DB586–0x67DB58E` (raw
`0x67DA986–0x67DA98E`). The header helper copies those fields into the
`X-Requested-At` value object and inserts it with the literal at RVA
`0x67FFBCD` (raw `0x67FEFCD`). This proves the header value is the ASCII
whole-Unix-seconds decimal string on the normal path; it is not merely a
candidate AAD component.

### One selected caller's seed-object path

For the instruction-boundary-verified caller at RVA `0x35E661` (raw
`0x35DA61`), the containing function begins at RVA `0x35DBA0` (raw
`0x35CFA0`). Its incoming RDX object is saved as RDI at function entry. At RVA
`0x35E388` (raw `0x35D788`), it loads a pointer from `[RDI+0x710]`, adds
`0x10`, preserves that value through the local setup, and at RVA `0x35E500`
(raw `0x35D900`) saves it. The call at `0x35E661` passes the saved pointer as
RDX to header helper `0x67FF8D0`. Inside that helper, the seed pointer is
`*[RDX+0x38] + 0x10`; for this caller the combined pointer path is
`*(*(caller_arg2 + 0x710) + 0x48) + 0x10`, with 32 bytes read from that address.
This identifies the seed object's nested field path for one verified caller,
not the object's semantic name or the active route. No additional caller scan
was done.

### Bounded audit of the separate 8-byte random value

The 8-byte value is produced by the BCryptGenRandom/SystemFunction036 helper;
it is not loaded from the seed buffer. Its direct uses in this function are:

1. At RVA `0x67DAFEB`, it is loaded as a little-endian qword and XORed into
   the first eight bytes of the 32-byte key-init input.
2. At RVA `0x67DB4AF` (raw `0x67DA8AF`), it is copied to stack `[rbp+0x4F0]`.
   The immediately following format descriptor points to `[rbp+0x4F8]`, not
   `[rbp+0x4F0]`, when it calls opaque helper RVA `0x125AE90`.
3. At RVA `0x67DB50A`, `[rbp+0x4F0]` becomes the destination buffer for the
   decimal Unix-seconds formatter; only the formatter's returned pointer/length
   is copied into the returned time string.

The assembled Base64 buffer has no explicit copy of the 8 random bytes: it is
formed from the 12-byte IV and the encrypted payload vector plus tag. The
8-byte value necessarily influences the key-init input and hence the encrypted
payload/tag. This bounded trace found no explicit raw-byte concatenation of
that value into the Base64 buffer or `X-Requested-At` string. The format helper
RVA `0x125AE90` also receives the key-context object, so this pass cannot rule
out a separate serialization inside that opaque formatting call or another
returned pin field. Whether the raw 8 bytes are transmitted as metadata remains
unproven; the local wire layout alone does not resolve how the service obtains
or agrees on this per-request key input.

### Python implementation boundary after this follow-up

The byte-level operations that can now be implemented from code evidence are:

- key-init input: 32-byte caller seed with a fresh 8-byte random value XORed
  into bytes `0:8`;
- nonce/IV: fresh 12-byte random value;
- AAD: ASCII decimal whole Unix seconds;
- plaintext: caller input bytes, encrypted in place;
- GCM tag: detached 16-byte result appended after ciphertext;
- wire encoding before later formatting: standard padded Base64 of
  `IV || ciphertext || tag`;
- `X-Requested-At`: ASCII decimal whole Unix seconds.

A byte-for-byte replay of a particular native sample would need its caller-seed
bytes and sampled random values. A fresh Python request could generate new
random values, but how the remote side learns or agrees on the 8-byte key salt
is not established. The key initializer's further processing and opaque
`0x125AE90` formatting path must be understood before claiming the final
`X-Request-Pin` string bytes. The local 8-byte-random trace does not establish
whether that value is separately serialized. No Python implementation or
request was run.
