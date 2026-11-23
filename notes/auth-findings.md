# Trae CN `main.js` auth reverse-engineering findings

Target: `d:\Users\marcus\AppData\Local\Programs\Trae CN\resources\app\out\main.js`
(3,376,307 bytes, mtime 2026-10-16). All excerpts below are verbatim substrings of that
bundle unless the heading says `product.json` (copied to `notes\_product_snapshot.json`:
`d:\Users\marcus\AppData\Local\Programs\Trae CN\resources\app\product.json`).

Product identity (product.json): `"nameShort": "Trae CN"`, `"quality": "stable"`,
`"dataFolderName": ".trae-cn"`, `"version": "1.107.1"`,
`"commit": "871bca3bb55e7a37af74c1eef2a9696f29aa7b26"`.

---

## 1. ExchangeToken: request, response fields, and where they are persisted

### 1.1 ClientID selection — module `out-build/vs/code/electron-main/oauth/common/util.js`

```js
function Jy(t){const e=Vo(t),i=ti(t),r=t.iCubeApp?.authConfig;return i?r?.SOLO?.[e]||"en1oxy7wnw8j9n":r?.TRAE?.[e]||"ono9krqynydwx5"}
```

`Vo(t)` = quality ("stable"/"beta"/…), `ti(t)` = is-SOLO. product.json confirms the map:

```json
"authConfig": {
  "TRAE": { "stable": "ono9krqynydwx5", "beta": "2k472yneke6pw3", "alpha": "pl2689e0l0xr1n", "dev": "8e4olyd5e5pn36", "local": "qjpvq9k8j8ryde" },
  "SOLO": { "stable": "en1oxy7wnw8j9n", "beta": "nn572p8wnw1vd7", "alpha": "0r4x5yq0r07nwp", "dev": "y6d1xnrk6k28o3", "local": "4v468ylkvkwn02" }
}
```

### 1.2 Signature + body — module `out-build/vs/code/electron-main/oauth/marscode/request.js` (class `Poe`)

Refresh-token exchange (host = Marscode `apiHost`, see §1.5):

```js
async exchangeTokenByRefreshToken(t,e,i,r){const n=`${t}/trae/api/v3/oauth/ExchangeToken`,s=Jy(this.productService),o=await this._buildDeviceInfo(r.publicKeyPEM),a=Nxe("POST","/trae/api/v3/oauth/ExchangeToken",s,e,r.privateKeyPEM),c={Signature:a.signature,Timestamp:a.timestamp,Nonce:a.nonce},l={ClientID:s,ClientSecret:"",RefreshToken:e,DeviceInfo:o,DeviceProof:c,IDEVersion:this.productService.appVersion},u={headers:this.getHeaders(i)};return this.logService.info("[exchangeTokenByRefreshToken]","request",n,Nn(l)),this._doExchangeToken(n,l,u)}
```

Auth-code exchange (no DeviceProof):

```js
async exchangeTokenByAuthCode(t,e,i,r){const n=`${t}/trae/api/v3/oauth/ExchangeToken`,s=Jy(this.productService),o=await this._buildDeviceInfo(r.publicKeyPEM),a={ClientID:s,AuthCode:e,CodeVerifier:i,DeviceInfo:o,IDEVersion:this.productService.appVersion},l={headers:this.getHeaders("")};return this.logService.info("[exchangeTokenByAuthCode]","request",n,Nn(a)),this._doExchangeToken(n,a,l)}
```

ECDSA P-256 signature — module `out-build/vs/code/electron-main/oauth/marscode/util.js`:

```js
function Oxe(){const{privateKey:t,publicKey:e}=Yy.generateKeyPairSync("ec",{namedCurve:"P-256",publicKeyEncoding:{type:"spki",format:"pem"},privateKeyEncoding:{type:"pkcs8",format:"pem"}});return{privateKeyPEM:t,publicKeyPEM:e}}
function Nxe(t,e,i,r,n){const s=Math.floor(Date.now()/1e3),o=Yy.randomBytes(16).toString("hex"),a=[t,e,i,r,String(s),o].join("\n"),c=Yy.sign("sha256",Buffer.from(a),n).toString("base64");return{timestamp:s,nonce:o,signature:c}}
```

→ message = `POST\n/trae/api/v3/oauth/ExchangeToken\n{ClientID}\n{RefreshToken}\n{unix_sec}\n{nonce=32 hex chars}` signed with the persisted device key (§5.2). PKCE helper: `Mxe()` = 48-byte base64url verifier + `sha256` → base64url challenge, method `S256`.

DeviceInfo builder (`Poe._buildDeviceInfo`) — exact field order:

```js
const e=await this.iCubeSystemInformationService.getSystemInformation(),i={DeviceID:await this.getDeviceId(),MachineID:this.machineId,PlatformCode:this.getPlatformCode(),DeviceType:"PC",DeviceName:await Uxe(),DeviceModel:e?.deviceModel??"",ClientVersion:this.productService.appVersion,DevicePublicKey:t,DeviceBrand:e?.deviceManufacturer??"",DeviceCPU:e?.cpuBrand??"",OSInfo:e?.osName??"",OSVersion:e?.osVersion??""};
...
getPlatformCode(){return ti(this.productService)?"SOLO_PC":"IDE_PC"}
```

Headers for all cloudide/trae API calls: `getHeaders(t)` → `{"Content-Type":"application/json","x-cloudide-token":t}` (t = access token, "" when exchanging).

### 1.3 Response fields and mapping — module `.../oauth/marscode/util.js` (`v9` / `zM`)

`_doExchangeToken` returns the raw `Result` object; `v9` maps it into the internal `userInfo`:

```js
v9=(t,e,i,r,n)=>{const s=zM(i,r,n);return{token:e.Token,refreshToken:e.RefreshToken,expiredAt:xxe(e.TokenExpireAt,e.TokenExpireDuration),refreshExpiredAt:new Date(e.RefreshExpireAt).toISOString(),tokenReleaseAt:new Date().toISOString(),userId:i.UserID,host:t,userRegion:{region:i.AIRegion,_aiRegion:i.AIRegion},account:s}},
zM=(t,e,i)=>({username:t.ScreenName,iss:"",iat:0,organization:"",work_country:"",email:t.NonPlainTextEmail??"",avatar_url:t.AvatarUrl,description:t.Description,scope:Dt.MARSCODE,loginScope:gi.TRAE,nonPlainTextMobile:t.NonPlainTextMobile,storeCountryCode:i?.countryCode??"",storeCountrySrc:t.StoreCountrySrc??"",storeRegion:i?.region??It.UNKNOWN,userTag:e??co.ROW,migrateToSG:t?.MigrateToSG??!1})
```

**ExchangeToken `Result` response fields actually read:** `Token`, `RefreshToken`,
`TokenExpireAt`, `TokenExpireDuration` (ms to add when TokenExpireAt is past),
`RefreshExpireAt`. User info comes from a separate `GetUserInfo` call
(`{ReqSource:"IDE"|"Lite", IDEVersion}` → `Result.UserID`, `Result.ScreenName`,
`Result.NonPlainTextEmail`, `Result.AvatarUrl`, `Result.Description`,
`Result.NonPlainTextMobile`, `Result.MigrateToSG`, `Result.StoreCountrySrc`,
`Result.AIRegion`). Errors surface as `ResponseMetadata.Error.Code`.

Error mapping in `_doExchangeToken`:

```js
.catch(n=>{...const s=n.response?.data?.ResponseMetadata?.Error?.Code||"";if(JM.includes(s)){const o=new Error(cd.RefreshTokenInvalid);throw o.errorCode=s||"token_expired",o}else throw n});if(!r?.Result)throw ...new Error("[exchangeToken]no response");return this.logService.info("[exchangeToken]","response success",Nn(r)),r.Result
```

Legacy/SAAS variant (module `.../oauth/saas/oauthService.js`, host `{consoleHost}/oauth/ExchangeToken`):

```js
async getJwtToken(e){const i=await this.getRequestUrl("/oauth/ExchangeToken"),r={RefreshToken:e,ClientSecret:"-",UserID:""},...const{Token:n,RefreshToken:s,TokenExpireAt:o,RefreshExpireAt:a,TokenExpireDuration:c}=i;...
```

Temp token (`GenerateTempToken`, used for the JWT file, §4.2):

```js
async function Doe(t,e,i,r){const s=(await t.request({method:"POST",url:`${e}/cloudide/api/v3/trae/GenerateTempToken`,data:{IDEVersion:r},headers:{"Content-Type":"application/json","x-cloudide-token":i},timeout:3e4,tryAgent:!1}))?.Result;if(!s?.Token||!s.ExpiredAt)throw new Error("[generateTempToken] missing token or expiredAt in response");return{Token:s.Token,ExpiredAt:s.ExpiredAt}}
```

### 1.4 Persistence — NOT auth.json; VS Code state DB + one JWT file

Module `out-build/vs/platform/iCubeAuth/electron-main/components/userStorage.js` (class `BN`):

```js
UN=`${G5}://usertag`,rE=`${G5}://icube-dc`,BN=class{constructor(t,e,i,r){...}get persistedKey(){const{authProviderId:t}=this.productService.iCubeApp?.nativeAppConfig||{};if(t)return`${G5}://${t}`}
async getUserInfoFromLocalStorage(){...const t=this.stateService.getItem(this.persistedKey);...const e=await b2(t);return this.parseUserInfo(e)...}
async storeUserInfo(t){if(this.persistedKey&&t)try{await this.storeUserTag(t.userId,t.account.userTag);const e=JSON.stringify(t),i=await H1(e);this.stateService.setItem(this.persistedKey,i)}catch(e){...}}
```

with `G5="iCubeAuthInfo"` (module `out-build/vs/base/common/iCube/userInfo.js`):

```js
G5="iCubeAuthInfo",zK="iCubeServerData",bw="iCubeNativeAppStartSetup",z5="iCubeNativeAppInitialEvent",K5="iCubeSetupPageLoginFailed"
```

* **UserInfo blob key:** `iCubeAuthInfo://icube.cloudide` (`authProviderId` from product.json
  `"nativeAppConfig": { "authProviderId": "icube.cloudide", "authDomain": "www.trae.cn", "authFrom": "trae", ... }`).
  Value = `base64(AES-GCM(JSON.stringify(userInfo)))` — `H1` encrypts, `b2` decrypts
  (WebCrypto key material is the two hard-coded Uint8Arrays right above `BN`).
  The JSON contains `token`, `refreshToken`, `expiredAt`, `refreshExpiredAt`,
  `tokenReleaseAt`, `userId`, `host`, `userRegion`, `account{...}` (fields from §1.3).
* **Device ECDSA keypair key:** `iCubeAuthInfo://icube-dc:{deviceId}` —
  `getDeviceKeyPair(t){...const e=`${rE}:${t}`,i=this.stateService.getItem(e);...n.privateKeyPEM&&n.publicKeyPEM?n:void 0...}` and `saveDeviceKeyPair(t,e){...const r=await H1(JSON.stringify(e));this.stateService.setItem(i,r)}`. (Legacy migrate keys: `"device_id"`, `"install_id"`.)
* **UserTag key:** `iCubeAuthInfo://usertag` (JSON `{userId: userTag}`).
* **Storage file on disk:** VS Code main-process `stateService` =
  `state.vscdb` (SQLite `ItemTable`) under `%USERPROFILE%\.trae-cn\` (user data folder
  `dataFolderName: ".trae-cn"`). There is no `auth.json`; the string `auth.json` occurs 0
  times in the bundle. The literal log phrase "OAuthenticator#write ide_credential file to
  local path" is legacy wording — no file write is performed for the Marscode flow.
* **Write triggers:** `context.js` — `setUserInfo` → `onDidMainContextChangeUserInfo` →
  `await this.userStorage.updateUserInfoStorage(e,i)`; `updateUserInfoStorage(t,e){t?await this.storeUserInfo(t):e&&await this.clearUserInfo()}`.
  `loginSuccess()` calls `this.userContext.setUserInfo(t)` after every exchange/login.
* **SAAS hosts cache:** separate key `iCubeHostInfo`
  (`Q2e.ICUBE_SAAS_INFO_KEY`) storing `{consoleHost, apiHost}`.
* **Plain-text JWT file (temp token):** see §4.2.

### 1.5 Host used for ExchangeToken/CheckLogin/GetUserInfo

Marscode OAuth service `YM` (module `.../oauth/marscode/oauthService.js`):

```js
this.consoleHost=this.productService.bootConfig.consoleHost,
...
get apiHost(){const t=this.productService.bootConfig.account.trae;return this.productService.provider===Bi.YINLI?t.normal:this._apiHost?this._apiHost:t.normal}
setApiHostByUserInfo(t){const e=this.productService.bootConfig.account.trae;...const i=t?.account?.storeRegion;if(i===It.USTTP&&e.USTTP){this._apiHost=e.USTTP;return}if((i===It.SG||i===It.US)&&e.SG){this._apiHost=e.SG;return}if(i===It.CN){this._apiHost=e.normal;return}...}
```

→ CN default: **ExchangeToken/CheckLogin/GetUserInfo hit `https://api.trae.cn`**
(`bootConfig.account.trae.normal`), switching to `account.trae.SG`/`.USTTP` variants when
the account storeRegion says so. `bootConfig.consoleHost` (`https://www.trae.cn`) is the
login/console host.

---

## 2. Default bootConfig (product.json, verbatim) + host inventory

The bundle contains **no** hard-coded default boot-config object literal (counts:
`mono-cn`=0, `aigw`=0, `ibytedtos`=0, `traffic`=0); all defaults ship in product.json
`bootConfig` and are refreshed at runtime from the server (`HostInfo`). CN-relevant
excerpt of product.json (lines 1614–1804):

```json
"bootConfig": {
  "feedbackMail": "feedback@mail.trae.cn",
  "defaultGitEmail": "git@mail.trae.cn",
  "iCube":   { "normal": "https://api.trae.com.cn" },
  "market":  { "trae": { "normal": "https://api.trae.com.cn" }, "bytedance": { "normal": "https://ide-market.bytedance.net" } },
  "iCubeAgent": { "normal": "https://api.trae.com.cn" },
  "frontier": { "normal": "wss://frontier.zijieapi.com/ws/v2", "boe": "wss://frontier-boe.bytedance.net/ws/v2" },
  "asr": { "engine": "volcengine", "domain": { "normal": "https://api.trae.com.cn" }, "appId": "4089030846",
           "bigmodelApiUrl": "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel", ... },
  "account": {
    "trae": { "normal": "https://api.trae.cn" },
    "saas": { "boe": "https://enterprise.mcdemo.show", "prod": "https://console.enterprise.trae.cn" },
    "bytedance": { "OLD": "https://ide.bytedance.net", "NEW": "https://solo-web.bytedance.net" },
    "bypassHosts": ["byted.org","bytedance.net","bytedance.com","tiktok-row.org","bytednsdoc.com","byteimg.com",".trae.com.cn",".trae.cn"]
  },
  "ug":    { "trae": { "normal": "https://api.trae.cn" }, "appId": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8", "bytedance": { "normal": "https://solo-web.bytedance.net" } },
  "agent": { "trae": { "normal": "https://trae-api-cn.mchost.guru" }, "appId": "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8",
             "bytedance": { "normal": "", "CN": "https://copilot-cn.bytedance.net", "SG": "https://copilot-sg-og.byteintl.net", "US": "https://copilot-og.byteintl.net" },
             "bytedanceRemote": { "normal": "", "CN": "https://copilot-cn.bytedance.net", "SG": "https://copilot-sg.byteintl.net", "US": "https://copilot.byteintl.net" } },
  "remote": { "trae": { "normal": "https://trae-api-cn.mchost.guru" }, "bytedance": { "normal": "", "CN": "https://copilot-cn.bytedance.net", "SG": "https://copilot-sg-og.byteintl.net", "US": "https://copilot-og.byteintl.net" }, ... },
  "ckg"/"cue"/"hub": { "trae": { "normal": "https://trae-api-cn.mchost.guru" }, ...same bytedance CN/SG/US map... },
  "ws":  { "trae": { "normal": "wss://trae-ws-cn.mchost.guru/custom_model" }, ... },
  "consoleHost": "https://www.trae.cn",
  "homeUrl": "https://www.trae.cn",
  "soloUrl": "https://work.trae.cn",
  "artifactShareOrigin": { "trae": { "normal": "https://share.traecontent.cn" }, "bytedance": { "normal": "https://solo-web-share.bytedance.net" } },
  "repoAuthorizationUrl": "http://solo-web.bytedance.net/authorization",
  "downloadUrl": "https://www.trae.cn/ide/download",
  "tea": { "verifyHost": "https://mcs.bytedance.net", "debugHost": "https://data.bytedance.net", "appId": { "TRAE": 711126, "SOLO": 932204 }, "channelDomain": { "normal": "https://mcs.zijieapi.com" }, ... },
  "slardar": { "bid": { "TRAE": "trae_cn", "SOLO": "solo_pc" }, "domain": { "normal": "https://mon.zijieapi.com" }, ... },
  "slardarPC": { "domain": { "normal": "https://pc-mon.zijieapi.com" }, "aid": { "TRAE": 787976, "SOLO": 931506 } },
  "doc": { "baseUrl": "https://docs.trae.cn", ... },
  ...
  "ahaDoctorDomains": ["lf-cdn.trae.com.cn","ide-copilot-online.tos-cn-beijing.volces.com"],
  "networkDiagnosticToBOnlyDomains": ["ide-copilot-online.tos-cn-beijing.volces.com"]
}
```

Additional URL-domain lists in the bundle (webRequest interceptors,
module `.../electron-main/webRequestInterceptor.js`):

```js
const r=["https://*.trae.cn/*","https://*.trae.com.cn/*","https://*.trae.ai/*","https://*.traecdn.us/*","https://*.tiktokd.org/*","https://*.trae.ai/*","https://*.traeapi.us/*","https://*/trae/*","wss://*/explorer/*","ws://*/explorer/*","https://*/api/remote/*","https://*/explorer/*","https://*.amazonaws.com/*","https://*.volces.com/*"]
...
vee=[".trae.cn",".trae.com.cn",".trae.ai",".traecdn.us",".traeapi.us",".bytedance.net"]
```

TTNet access-policy whitelist (two copies, quality-dependent):

```js
domain_white_list:{"*.trae.ai":["*"],"*.traeapi.us":["*"],"*.mchost.guru":["*"],"*.bytedance.net":["*"],"*.tiktok-row.net":["*"],"*.byteintl.net":["*"],"*.byted.org":["*"],"*.trae.com.cn":["*"],"*.trae.cn":["*"],"*.mcdemo.show":["*"],"*.bytepluses.com":["*"],"*.volces.com":["*"]}  (second copy adds "*.snssdk.com","*.bytedance.com")
domain_black_list:["127.0.0.1","::1"]
```

SG region endpoints (from the bytedance maps above): `copilot-sg-og.byteintl.net` /
`copilot-sg.byteintl.net`; SG account/UG host comes from server `HostInfo` at runtime
(no static `"https://api.trae.sg"`-style literal exists in the bundle).

Runtime host override — BootService stores server `HostInfo` and exposes
`Console`/`Api`/`RemoteApi`/`SoloDomain`; SAAS variant persists them under state key
`iCubeHostInfo` (`updateHost(e,i){...this.stateService.setItem(this.persistedKey,{consoleHost:this.consoleHost,apiHost:this.apiHost})}`).

---

## 3. Local OAuth callback server — module `out-build/vs/code/electron-main/oauth/oauthLocalServer.js`

```js
import{createServer as RVe}from"http";
...
function(t){t.LOGIN_CONFIRM="/login-confirm",t.LOGIN_SUCCESS="/login-success",t.AUTHORIZE="/authorize"}(Vf||(Vf={})),
IN=class C4 extends he{static{this.TIMEOUT_MS=30*60*1e3}static{this.AUTHORIZATION_TIMEOUT_MS=5*60*1e3}
...
async _createServer(){return new Promise((e,i)=>{const r=RVe(async(n,s)=>{...});r.listen(0,"127.0.0.1",()=>{...this._pendingGetPortPromise?.complete(n?.port)...})})}
```

Handler (verbatim; note: substring matching, `e.url?.includes(...)`):

```js
async handleRequest(e,i){const{url:r}=e;...i.setHeader("Access-Control-Allow-Origin","*"),...,
e.method==="OPTIONS")i.statusCode=200,i.end();
else if(e.url?.includes(Vf.LOGIN_CONFIRM)){this.authorizationTimeoutTimer||(this.authorizationTimeoutTimer=setTimeout(...,C4.AUTHORIZATION_TIMEOUT_MS));
  const{query:n}=le.parse(e.url||""),s=await import("qs"),{IDEUserToken:o}=s.parse(n);o&&(this.userToken=o);
  let a={};try{const l=(await this.fileService.readFile(this.environmentMainService.argvResource)).value.toString();a=JSON.parse(Um(l))}catch{}
  i.statusCode=200,i.end(Koe(this.productService.urlProtocol,C4.AUTHORIZATION_TIMEOUT_MS,a.locale||da,await this._themeService.getCssCode("Dark"),this.productService.provider))}
else if(e.url?.includes(Vf.LOGIN_SUCCESS))try{await this.responseToken(this.userToken),i.statusCode=200,i.end()}
  catch(n){n.message.includes("GetAiRegionError:NotAllowed")?i.statusCode=401:n.message.includes("CloudIDETokenError:LinkExpired")?i.statusCode=402:i.statusCode=500,i.end()}
else if(e.url?.includes(Vf.AUTHORIZE)){const n=e.url.split("?")[1];this.responseToken(n,i)}}
async responseToken(e,i){const r=this.authCodeHandlerId;if(this.authCodeHandler){let n=!1;try{n=await this.authCodeHandler(e,i),this.logService.info("OAuthLocalServer#Received oauth2 jwt success")}catch(s){...}r===this.authCodeHandlerId&&n&&(...this.dispose())}else this.logService.error("OAuthLocalServer#[Server] can't find authCodeHandler.")}
```

Wiring (`out-build/vs/code/electron-main/oauth/userLogin/loginService.js`):

```js
async login(t){...await this.server.getServer(),this.server.setAuthCodeHandler(async(i,r)=>await this.updateLocalCredential(t,i,r)),this.openLogin(t,await this.server.getPort(),t.windowId);const e=await this._pendingOAuthLoginDeferredPromise.p;...}
```

**The browser hits `GET http://127.0.0.1:{port}/authorize?<query>` and the raw query
string is passed to `updateLocalCredential`:**

```js
async updateLocalCredential(t,e,i){let r=Ile.parse(decodeURIComponent(e||""));try{JSON.parse(r.userInfo||"")}catch{r=Ile.parse(e||"")}...
if(r?.error_code)return ...new Error("SetupLoginError:banned")...
r.codeVerifier=this._codeVerifier;
const o=await s?.loginCredentialCallback(r);return o?.code===_c.Success&&o?.userInfo?(this._pendingOAuthLoginDeferredPromise?.complete(o.userInfo),n(),!0):...}
```

Expected callback params (Marscode/TRAE flow, `qs`-parsed):
* `authCodeInfo` — JSON (URI-encoded) `{"AuthCode":"..."}` (read in
  `marscode/login.js`: `const a=JSON.parse(t.authCodeInfo);a.AuthCode?n=a.AuthCode:...`)
* `userInfo` — optional JSON blob of user fields (preferred over a follow-up GetUserInfo:
  `o=r??await this.request.getUserInfo(e,s.Token||"")`)
* `codeVerifier` is *not* taken from the URL — `loginService` stamps the local PKCE
  verifier: `r.codeVerifier=this._codeVerifier`
* `error_code` — failure path → `SetupLoginError:banned`
* `consoleHost` — optional override honored by some providers
  (`getLoginUrl(...,r.consoleHost)`)

Alternative handoff SSO callback (same `/authorize` path, built with `URLSearchParams`)
accepts `credential` (JSON/URL-encoded with `userJwt{Token,TokenExpireAt}, refreshToken,
host, refreshExpireAt`) or a `userJwt` param — module `.../iCubeAuthService.js`
`handleHandoffExternalSso`.

Login URL builder (`Ple.buildLoginUrl`, module near usdsService) — verbatim:

```js
const a=Jy(this.productService),c=this.productService.tronBuildVersion||"local",l=MVe(),d=this.telemetryService.machineId,u=await this.oauthProviders.get(gi.TRAE)?.request?.getDeviceId()||"0",p=this.configurationService.getValue("ai_assistant.request.env")===df.BOE?df.BOE:void 0,w=await this.iCubeSystemInformationService.getSystemInformation(),{codeVerifier:g,codeChallenge:m}=Mxe(),y={x_device_id:u,x_machine_id:d,x_device_brand:w?.deviceModel,x_device_type:w?.osName,x_os_version:w?.osVersion,x_env:p,x_app_version:this.productService.appVersion,x_app_type:Vo(this.productService),code_challenge:m,code_challenge_method:"S256"},_=OVe(y);
t.customDomain?(o=...):(o=o||`${t.loginHost}`);
const E=Fl(this.productService)===os.SOLO_Lite?"solo":"trae",k=`http://127.0.0.1:${i}/authorize`;
let I=`${o}/authorization?login_version=1&auth_from=${E}&login_channel=native_ide&plugin_version=${c}&auth_type=local&client_id=${a}&redirect=${r||0}&login_trace_id=${l}&auth_callback_url=${k}&machine_id=${d}&device_id=${u}&${_}`;
E==="solo"&&(I+="&hide_saas_login=true"),t.email&&(I+=`&email=${encodeURIComponent(t.email)}`)...
```

(`loginHost` resolves from `nativeAppConfig.authDomain` = `www.trae.cn`.)

---

## 4. Token refresh scheduling & forced logout

### 4.1 Token-state machine — module `out-build/vs/platform/iCubeAuth/electron-main/utils/authUtil.js`

```js
HM=24*60*60*1e3,
m9=(t,e)=>{if(t?.account?.scope===Dt.BYTEDANCE){...}if(gr(t)&&t.token&&t.expiredAt){const i=woe(t,e);if(i===pn.NEED_UPDATE||i===pn.DROPPED)return i;const r=moe(t);if(r===pn.NEED_UPDATE||r===pn.DROPPED)return r;const n=Date.parse(t.expiredAt)-Date.now(),s=t.tokenReleaseAt?(Date.parse(t.expiredAt)-Date.parse(t.tokenReleaseAt))/3>n:!1;return n<=0?pn.NEED_LOGIN:s||n<=HM?pn.NEED_REFRESH:pn.VALID_TOKEN}return pn.NEED_LOGIN}
```

States (`iCubeAuth.js`): `NEED_REFRESH="need-refresh", VALID_TOKEN="valid-token", NEED_LOGIN="need-login", NEED_UPDATE="need-update", DROPPED="dropped"`.
→ refresh runs when expired, when <24 h remain, or when >1/3 of the token's total
lifetime has elapsed; `NEED_LOGIN` (no token) triggers a refresh-as-create.

* On every `userInfo` getter access: `verifyTokenInBackground(userInfo)` → `m9` →
  `safeRefresh(refreshToken, uc.REFRESH_TOKEN, scope)` (async, no await).
* On startup: `userInfoManager.getUserInfo()` → storage read → same `m9` decision
  (`CREATE_TOKEN` when `need-login`).
* On OS resume + network change: `checkAndRefreshJwtTokenOnResume()` and
  `recheckBytedanceNetwork` (BootService `setInterval(i,5*60*1e3)` = 5 min network recheck).

### 4.2 Temp-token (JWT) scheduling — module `.../components/tokenManager.js`

```js
Foe="trae-jwt-token",ZM=60*1e3,Uoe=class{...this._tempTokenFilePath=Loe.join(Wxe(),this.productService.dataFolderName,Foe)}
...
scheduleNextJwtTokenRefresh(t){...this.jwtTokenExpiredAt=t;const e=Date.now(),i=t-e,r=Math.max(i/2,ZM);...this.jwtTokenRefreshTimer=setTimeout(async()=>{...this.refreshTempToken(this.userContext.userInfo)},r)}
async writeTempTokenFile(t){...Xy.writeFileSync(this._tempTokenFilePath,t,{mode:384}),...}
```

→ **Plain JWT file: `%USERPROFILE%\.trae-cn\trae-jwt-token`** (mode 384 = 0600),
refreshed via `POST {apiHost}/cloudide/api/v3/trae/GenerateTempToken`
(x-cloudide-token = access token) at `max(now+~50% of remaining, 60 s)` before
`ExpiredAt`; `startJwtTokenRefresh` gated by `setJwtTokenEnabled`.

### 4.3 Forced logout conditions

Logout error codes — `marscode/request.js`:

```js
JM=["20324","20101","20315","20125","20126","20401","20403"]
async checkLogin(t,e){const i=`${t}/cloudide/api/v3/trae/CheckLogin`,r={IDEVersion:this.productService.appVersion,ReqSource:ti(this.productService)?"Lite":"IDE",GetAIPayHost:!0},...const o=s?.ResponseMetadata?.Error?.Code||"";return JM.includes(o)||s?.Result?.IsLogin===!1?(...,{isValid:!1,errorCode:o}):{isValid:!0,migrateToSG:s?.Result?.MigrateToSG??!1}}
```

(_doExchangeToken throws `cd.RefreshTokenInvalid` with `errorCode = code || "token_expired"`
for these codes._)

Handling — `refreshUserInfoByToken` catch:

```js
u.message==="RefreshTokenError:TokenVersionError:1.0"||u.message==="RefreshTokenError:TokenNullError"||u.message==="OauthService:UserInfoNotMatchError"?this.disableRefreshFlag=!0:u.message===cd.RefreshTokenInvalid&&(p=!0),(e===uc.CREATE_TOKEN||p)&&(this.userContext.setUserInfo(void 0,p),p&&this.broadcastToCodeWindows?.(ae.MAIN_TO_SANDBOX_SHOW_AUTH_INVALID_DIALOG,{errorCode:u.errorCode||"refresh_token_invalid"}))
```

and `checkLoginToken`: `if(!i)this.userContext.setUserInfo(void 0,!0),this.broadcastToCodeWindows?.(ae.MAIN_TO_SANDBOX_SHOW_AUTH_INVALID_DIALOG,{errorCode:r})`
(clears storage → logged out). Logout also calls
`POST /cloudide/api/v3/trae/oauth/ClearRefreshToken` with
`{ClientID, DeviceID, MachineID, PlatformCode}`.

Server-pushed CheckLogin (`UgHandler.handleCheckLogin`) re-validates when a Frontier/UG
message lists this device: `e.some(a=>a.deviceId===i&&a.code===r&&a.clientId===n)` →
`checkLoginToken(o)`.

---

## 5. Device ID (`iCubeDeviceRegisterMainService`) & aha_kit

### 5.1 Module `out-build/vs/platform/iCubeDeviceRegister/electron-main/iCubeDeviceRegisterMainService.js`

```js
import{ahaDeviceService as e9}from"electron/main";
...
Ny="has_device_id_updated_to_aha",lM="device_id",fse="install_id",
Ly=class extends pse{constructor(e,i,r){...
(this.deviceId=e9?.deviceId?.deviceId||Mf,this.remoteDeviceId=e9?.deviceId?.deviceId||Mf,this.localDeviceId=e9?.deviceId?.localDeviceId||Mf),...}
async init(){...const s=e9.getDeviceId(r).then(({deviceId:a})=>{this.deviceId=a,this.remoteDeviceId=a,...this.remoteDeviceIdBarrier.open(),...});
s.then(()=>{this.stateService.setItem(Ny,"true"),this.applicationStorageMainService.store(Ny,!0,-1,1),this.stateService.removeItem(lM),this.stateService.removeItem(fse);...}),
await xc(s,aM,()=>{...||(this.deviceId=this.localDeviceId,this.logService.warn(`[ICDRS] (init) ahaDeviceService timeout ${aM}ms`))}),...}
...
async resolveDeviceId(){return this.initializationBarrier.isOpen()||await this.initializationBarrier.wait(),this.deviceId}
get guaranteedDeviceId(){return this.deviceId!=="0"?this.deviceId:this.localDeviceId}
```

* `Mf="0"` fallback, `aM=4e4` (40 s timeout for the aha SDK), migration flags
  `has_device_id_updated_to_aha`, legacy keys `device_id`/`install_id` (removed after
  aha handoff).
* **Device ID comes from the native `ahaDeviceService` Electron module
  (`import {ahaDeviceService} from "electron/main"`)** — not from JS. `getDeviceId()`
  is the SDK's registration call; the string `aha_kit`/`doctor_sdk` does **not** appear
  in the bundle (counts 0/0), but the aha SDK surfaces as `electron/main` built-ins
  (`ahaDebugger` also imported elsewhere) and the doctor endpoints are the
  `ahaDoctorDomains`: `lf-cdn.trae.com.cn`, `ide-copilot-online.tos-cn-beijing.volces.com`.
* **No server-side "RegisterDevice" HTTP call exists in the bundle** (count 0);
  `device_register` occurrences are telemetry event names only:
  `icube_device_register_init`, `icube_device_register_init_from_sdk`,
  `icube_device_register_init_from_sdk_attempt`,
  `icube_device_register_check_and_report_device_id_from_aha` (Slardar events,
  categories include `ahaDeviceIdVersion:"1"`).
* Consumers: OAuth `DeviceInfo.DeviceID`, headers `x-device-id` /
  `x_device_id` (login URL), telemetry `deviceId` common param.

### 5.2 Device keypair (ECDSA P-256) storage

```js
async _loadDeviceKeyPair(){const t=await this.request.getDeviceId(),e=await this.userStorage.getDeviceKeyPair(t);if(e)return this.logService.info("[OAuthMarscodeService] loaded device key pair from storage"),e;const i=Oxe();return await this.userStorage.saveDeviceKeyPair(t,i),i}
```

→ persisted at state key `iCubeAuthInfo://icube-dc:{deviceId}` (§1.4); regenerated only
when absent.

---

## 6. Region: StoreRegion / X-User-Region

Enums (`userInfo.js` + `bootService/common/constant.js`):

```js
(function(t){t.USTTP="usttp",t.ROW="row",t.CN="cn"})(co||(co={}))            // userTag
(function(t){t.CN="CN",t.SG="SG",t.US="US",t.BOE="BOE",t.BOEI18N="BOEI18N"})(ac||(ac={}))   // quality-region
(function(t){t.US="US",t.CN="CN",t.SG="SG",t.USTTP="USTTP",t.UNKNOWN="UNKNOWN"})(It||(It={})) // storeRegion
```

Header injection for every trae/cloudide request through the webRequest interceptor
(excluding the three auth endpoints, which are called directly from main):

```js
const d=async()=>{const p=await r.getAuthUserInfo(),w=await n.getStoreRegion(),m={Authorization:`Cloud-IDE-JWT ${p?.token||""}`,"X-User-Region":w.region||""},y=i.getValue("ai_assistant.request.env"),_=i.getValue("ai_assistant.request.ppe");return y==="ppe"&&_&&(m["x-tt-env"]=_,m["x-use-ppe"]="1"),y==="boe"&&_&&(m["x-use-boe"]="1",m["x-tt-env"]=_),m},
u=["/cloudide/api/v3/trae/GetUserInfo","/trae/api/v3/oauth/ExchangeToken","/cloudide/api/v3/trae/CheckLogin"];
```

→ **`Authorization: Cloud-IDE-JWT {access token}` + `X-User-Region: {storeRegion}`**
(lowercase value from `getStoreRegion().region`; for a fresh CN login this is `cn`/`CN`
per the `It`/`b9e` maps — value ultimately comes from TnC country + account).

`getStoreRegion` decision (StoreRegion service, abbreviated verbatim):

```js
async _getStoreRegion(){await this.iCubeAuthManagementService.waitReady.wait();const e=this.iCubeAuthManagementService.cacheUserInfo,i=e?.account?.scope,r=this.tncRegionMainService.getTncRegion();
if(e?.account?.scope===Dt.BYTEDANCE&&e?.account?.loginScope===gi.USDS){const n={...r,region:It.USTTP,countryCode:"us",countryCodeSrc:"uid"};return ...n}
return e?.account?.scope===Dt.BYTEDANCE||this.productService.provider===Bi.YINLI?e?{...r,region:Rg(e)}:{...r,region:this.getRegionByDid(r),countryCodeSrc:r.countryCodeSrc||"did"}:(...,i===Dt.MARSCODE?!e?.account?.storeCountryCode||!e?.account?.userTag?(this.iCubeAuthManagementService.refreshStoreCountryCode(e),...{...r,region:It.UNKNOWN}):this.buildStoreRegionByUid(e.userId,r...))}
```

Region effects:
* `apiHost` selection for ExchangeToken/CheckLogin/GetUserInfo (`setApiHostByUserInfo`,
  §1.5) and for `GenerateTempToken`:
  `const n=(r===It.USTTP?i.USTTP:r===It.SG||r===It.US?i.SG:void 0)||i.normal`.
* `migrateToSG` (from GetUserInfo `Result.MigrateToSG` / CheckLogin
  `Result.MigrateToSG`) flips the stored account and re-fires
  `onStoreRegionChange` (TnC listener above).
* `Rg(t)` region inference: `function Rg(t){return t?.userRegion?._aiRegion||t?.account?.uidRegion||t?.aiRegion}`.

---

## 7. Confidence & Gaps

**High confidence (verbatim excerpted):**
- ExchangeToken request bodies, ECDSA P-256 signature message format, DeviceInfo fields,
  `x-cloudide-token` header, `Result` field names (`Token`, `RefreshToken`,
  `TokenExpireAt`, `TokenExpireDuration`, `RefreshExpireAt`).
- Persistence: encrypted blob at state key `iCubeAuthInfo://icube.cloudide` in
  `state.vscdb` (`%USERPROFILE%\.trae-cn\`), plus plaintext temp JWT at
  `%USERPROFILE%\.trae-cn\trae-jwt-token`; device keypair at
  `iCubeAuthInfo://icube-dc:{deviceId}`. No `auth.json`.
- Callback server paths `/authorize`, `/login-confirm` (+`IDEUserToken`),
  `/login-success`; `/authorize` receives the raw query parsed by `qs` with
  `authCodeInfo` (JSON with `AuthCode`), optional `userInfo`, `error_code`;
  `codeVerifier` comes from local PKCE state, not the URL.
- Logout codes `["20324","20101","20315","20125","20126","20401","20403"]` and
  `Result.IsLogin===!1`; refresh cadence (≤24 h to expiry or 1/3 lifetime;
  temp-token at 50% remaining, min 60 s).
- Default bootConfig hosts (product.json): consoleHost `https://www.trae.cn`,
  account/ug `https://api.trae.cn`, agent/remote/ckg/cue/hub
  `https://trae-api-cn.mchost.guru`, ws `wss://trae-ws-cn.mchost.guru/custom_model`,
  iCube/market/asr `https://api.trae.com.cn`, SG maps
  (`copilot-sg-og.byteintl.net`, `copilot-sg.byteintl.net`).
- Device ID source = native `ahaDeviceService` (`electron/main` builtin), 40 s timeout,
  fallback `localDeviceId`/`"0"`; no HTTP RegisterDevice call.

**Medium confidence / inferred:**
- Exact file paths of state storage (`%USERPROFILE%\.trae-cn\state.vscdb`) inferred from
  VS Code `stateService` + `dataFolderName: ".trae-cn"`; not read from disk in this session.
- The exact AES-GCM key derivation for `H1`/`b2` (two hard-coded Uint8Arrays at offset
  ~1743600) was located but not cryptographically reconstructed.
- Host passed to `exchangeTokenByRefreshToken` = `YM.apiHost` (= `account.trae.normal`
  for CN) inferred from `get apiHost()` + `refreshToken()` call site; the truncated
  call `const r=await this.request.exchangeTokenByRefr...` did not show the first arg.
- SG/US account API host (`account.trae.SG` / `.USTTP`) is expected from
  `setApiHostByUserInfo` but those literals are not in the CN product.json (server
  `HostInfo` supplies them at runtime).

**Gaps / not found:**
- No `"aigw"`, `"mono-cn"`, `"ibytedtos"`, `"RegisterDevice"`, `"aha_kit"`,
  `"doctor_sdk"`, `"storageService.store"`, `"login_channel"` (URL uses
  `login_channel` param but the JS identifier count was 0 due to minification)
  strings in the bundle.
- `m9`'s `gr(t)` helper (userinfo sanity check) not dumped; behavior obvious from context.
- The `/login-confirm` page HTML builder `Koe(...)` internals not extracted
  (only its invocation).
- Product.json SG-region `bootConfig` (this is the CN build; SG build would carry
  `trae.sg`-style defaults — not present here).
