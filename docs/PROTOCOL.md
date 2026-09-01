# Hisense RemoteNOW MQTT Protocol

Reverse engineered from the official **RemoteNOW** app
(`com.universal.remote.ms`, version 5.01.011) via JADX decompilation and cross
checked against [Krazy998/mqtt-hisensetv](https://github.com/Krazy998/mqtt-hisensetv)
and [sehaas/ha_hisense_tv](https://github.com/sehaas/ha_hisense_tv).

## 1. Transport & credentials

| Property | Value |
|---|---|
| Transport | **MQTT 3.1** (`MQIsdp`, protocol level 3). Verified live: a 3.1.1 CONNECT is answered with CONNACK `0x05` (not authorized) or the TV closes the socket outright - always pin protocol version 3.1 |
| Port | **36669** (advertised per device as `mqttport=`) |
| TLS | `ssl://` when the advertised `transport_protocol >= 1001` (APK `MqttConnectManager`: `i2 >= 1001`); self-signed server cert  verify off / TOFU. Live finding: some firmwares run this port **TLS-only** - a plain CONNECT is answered with an immediate TCP RST, while the TLS handshake completes normally |
| Mutual TLS | Some models (A71 series) *require* client certificates. The app bundles `res/raw/remoteclientmobile.p12` + `remoteca.bks`; p12 password is **`multiscreen123`** (`ConfigureUtils.e()`), CA store password empty |
| Username | `hisenseservice` (`ConfigureUtils.c()`, double base64 `YUdselpXNXpaWE5sY25acFkyVT0=`) |
| Password | `multimqttservice` (`ConfigureUtils.d()`, double base64 `YlhWc2RHbHRjWFIwYzJWeWRtbGpaUT09`) |
| Client ID | `<phone MAC>$normal` (+ `e` suffix for OEM builds). Any unique string works; it must be identical in CONNECT and topics |
| Options | clean session false, keepalive 45 s, connect timeout 5 s, max inflight 100, LWT `/mobile/<uuid>` (empty, retained) |

## 2. Topics

Commands (phone → TV):

```
/remoteapp/tv/<service>/<clientId>/actions/<action>
```

Feedback (TV → phone), subscribe to both:

```
/remoteapp/mobile/broadcast/#
/remoteapp/mobile/<clientId>/#
```

Topic segments when split by `/`: `[3]`=clientId-or-broadcast, `[4]`=service,
`[5]`=functionType (e.g. `state`, `data`, `actions`), `[6]`=function.

### Services and actions

| Service | Actions (from TopicTo*Service classes) |
|---|---|
| `remote_service` | `sendkey`, `mouse`, `input` |
| `ui_service` | `timeseek`, `launchapp`, `playvideo`, `uninstallapp`, `changetvname`, `changechannel`, `changesource`, `appversion`, `applist`, `applisticon`, `sourcelist`, `defaultnext`, `defaultprevious`, `gettvstate`, `dlnastop`, `authenticationcode`, `authenticationcodeclose`, `capability`, `picturesetting` |
| `platform_service` | `channellist`, `curallprogram`, `channelepg`, `programinfo`, `add/edit/deletebooking`, `getbookinglist`, `getbookingconflict`, `apply/cancelbookingconflict`, `changevolume`, `getvolume`, `getchannellistinfo`, `gettvinfo`, `getdeviceinfo`, `picturesetting`, `screencapture` |
| `avs_service` | `voicestart`, `voicedata`, `voicestop` |

## 3. Payloads (verified)

| Action | Payload |
|---|---|
| `sendkey` | raw key name, e.g. `KEY_POWER` (plain text, no JSON) |
| `changevolume` | **plain number string** `"0"`…`"100"` (`RemoteVolumeView: ""+volume`). `101`/`102` = AMP-mode volume down/up. NOT JSON |
| `changesource` | JSON; only `{"sourceid":"4"}` is required (Krazy998: sourcename optional, no spaces) |
| `launchapp` | `{"name":"YouTube","urlType":37,"storeType":0,"url":"youtube"}` |
| `authenticationcode` | `{"authNum":"1234"}` (SecurityActivity builds 4 digits from inputs) |
| `authenticationcodeclose` | empty |
| `gettvstate` / `sourcelist` / `getvolume` / `capability` / `appversion` | empty payload |

## 4. Feedback functions (last topic segment)

| Function | Model | Notes |
|---|---|---|
| `/state` | `{statetype, sourceid?, sourcename?, displayname?, is_signal?, is_lock?, hotel_mode?}` | statetype ∈ `sourceswitch, voicestate, livetv, mediadmp, tshift, app, input, mouse, fake_sleep_0, fake_sleep_1, mediadlna` |
| `/volume` or `/volumechange` or `/getvolume` | `{volume_type, volume_value}` | type 0/1 = level 0-100; type 2 = mute flag (value 1 muted). Firmware-dependent naming — subscribe broadly |
| `/data/sourcelist` | array of `{sourceid, sourcename, displayname, is_signal, is_lock, hotel_mode}` | response to `sourcelist` |
| `/data/applist` | app list JSON | response to `applist` |
| `/authentication` | – | **TV requests pairing** (triggers PIN display on the TV screen) |
| `/authenticationcode` | `{result: 0|1, info}` | result of a PIN submission. `{"result":1,"info":""}` = accepted; `{"result":100,"info":"Wrong authNum!!"}` = wrong or expired code |
| `/authenticationcodetoast` | – | **NOT a success signal!** App string `authen_toast` (German locale): *"Das verbundene Gerät ist besetzt, verbinden Sie ein anderes Gerät"* (= "The connected device is busy, connect a different device"). The TV sends this when the remote slot is already occupied by another client (e.g. the phone app is running). Pairing cannot proceed until that client disconnects |
| `/authenticationcodeclose` | – | pairing dialog dismissed; also pushed by the TV itself after the code expires (~30 s) |
| `/capability` | CapabilityTvInfo | brand, deviceid, featurecode, capability, tuner_num, fake_sleep(+state), audio/screen_capture_supported |
| `/appversion` | version string | firmware/app enrichment |

## 5. First pairing sequence (= RemoteNOW behaviour)

```
connect MQTT ──► subscribe broadcast/# + own cid/#
             ──► probe: publish gettvstate
TV unknown? ──► push function "/authentication"
             ──► app shows PIN entry; TV shows 4-digit code (~30 s validity!)
user enters ──► publish {"authNum":"NNNN"} to ui_service/<cid>/actions/authenticationcode
TV checks   ──► push "/authenticationcode" {"result":1}        -> done (paired)
                push {"result":100,"info":"Wrong authNum!!"}   -> wrong/expired code, retry
                push "/authenticationcodetoast"               -> remote slot busy, abort
                push "/authenticationcodeclose"               -> dialog closed/expired
cancel      ──► publish to .../actions/authenticationcodeclose
old firmware ─► no "/authentication" within timeout -> no pairing needed
```

### 5.1 Live-verified pairing behaviour (2026-08, MSD6886 / 65A6101EE)

Findings from a packet-level session against a real TV (65A6101EE, VIDAA,
board `MSD6886`, software `V0001.01.00a.P0219`), including a full capture of
the official app pairing fresh:

* **Client ID format**: the app connects as `<MAC>$normal` (e.g.
  `9f:b3:a4:e0:4a:d7$normal`), where the prefix looks like the phone's WLAN
  MAC. Any unique string is accepted by the broker; MAC-style IDs are the
  safest choice because some firmwares appear to treat unknown ID shapes
  differently.
* **Connect burst**: right after subscribing, the app publishes one burst:
  `ui_service/gettvstate`, `ui_service/capability`,
  `platform_service/gettvinfo`, `platform_service/getchannellistinfo`,
  `ui_service/appversion`, `ui_service/sourcelist` (all empty payloads).
  The TV answers each on `/remoteapp/mobile/<cid>/<service>/data/<function>`.
* **PIN display trigger**: the TV shows the 4-digit code on screen only in
  response to the `/authentication` push that follows `gettvstate` from an
  unknown client. The code **expires after roughly 30 seconds** - after that
  the TV pushes `/authenticationcodeclose` and a new request generates a new
  code. Re-sending `gettvstate` re-opens the dialog with a fresh code.
* **Single remote slot**: only one client may control the TV at a time. While
  another client is connected/paired (e.g. the phone app running in the
  background), the TV still pushes `/authentication` but does *not* render
  the code; it sends `/authenticationcodetoast` ("device busy") instead.
  Close/kill other remote apps before pairing.
* **Overlay rendering**: system overlays (e.g. the auto-standby countdown)
  can cover the PIN. Dismiss them before reading the code.
* **Already paired clients** get real data responses (`state`, `sourcelist`,
  ...) instead of `/authentication`; broadcast `state` messages (e.g.
  `voicestate`) can arrive at any time and must not be mistaken for proof of
  a successful auth probe.

## 6. Discovery

The app uses a native UPnP stack (`libmbldlna.so`). Equivalent pure-Python
flow:

1. SSDP M-SEARCH (`ssdp:all`, `MediaRenderer`) to `239.255.255.250:1900`.
2. HTTP GET each LOCATION URL.
3. Parse `<device><modelDescription>` — newline separated key=value block:

```
transport_protocol=2100   # >=1001 -> TLS
platform=1
region=6
country=DEU
model_name=65A71FS
tv_version=V0000.01.00a.N0821
language=deu
macWifi=AABBCCDDEEFF
macEthernet=001122334455
voice=1
mqttport=36669
```

Filter: accept only devices whose modelDescription contains `mqttport=` or
`transport_protocol=` (manufacturer alone matches non-Vidaa sets).
Unique ID: `macWifi || macEthernet || UDN`.

## 7. Wake-on-LAN

`WakeupManager` sends the standard magic packet (FF×6 + MAC×16)
**5 times, 100 ms apart**, to UDP port **33129**, broadcast address
`255.255.255.255`. Preferred MAC: wifi, fallback ethernet.

## 8. Keys (RemoteKeyBase)

`KEY_HOME KEY_MUTE KEY_CHANNELUP KEY_CHANNELDOWN KEY_VOLUMEDOWN KEY_VOLUMEUP
KEY_RETURNS KEY_MENU KEY_DOWN KEY_LEFT KEY_RIGHT KEY_UP KEY_OK KEY_POWER
KEY_EXIT KEY_PLAY KEY_PAUSE KEY_STOP KEY_BACKS KEY_FORWARDS KEY_PREVIOUS
KEY_NEXT KEY_SOURCES KEY_TVS KEY_INFO KEY_EPG KEY_SUBTITLE KEY_AUDIO KEY_RED
KEY_GREEN KEY_YELLOW KEY_BLUE KEY_0..KEY_9 KEY_ZOOMIN KEY_ZOOMOUT …`

Note: `KEY_RETURNS` = back, `KEY_BACKS` = rewind. Community docs mentioning
`KEY_BACK` refer to nothing in this firmware generation; we alias it.

Keyboard map (`KeyBoardBase`, for the `input` action): `KEY_A..KEY_Z`,
`KEY_ENTER`, `KEY_BACKSPACE`, `KEY_SPACE`, punctuation keys plus `*UP`
release variants.

## 9. Discrepancies between sources

| Item | APK | Krazy998 | sehaas |
|---|---|---|---|
| changevolume payload | plain number | plain number (`-m 50`) | n/a |
| mute | `KEY_MUTE` key | `KEY_MUTE` | n/a |
| KEY_BACK | does not exist (`KEY_BACKS`/`KEY_RETURNS`) | lists `KEY_BACK` | – |
| gettvstate response | parsed as StateType{statetype} | rich JSON incl. source fields | A71 returns no state, used as auth probe only |
| client certs | bundled, password `multiscreen123`/empty(BKS) | not mentioned | mandatory on A71, user-provided |
| architecture | direct connection | mosquitto_pub/sub examples | Mosquitto bridge into HA's single broker |

This integration connects **directly** (aiomqtt inside HA) - no bridge needed.
