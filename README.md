# Omlet Arcade — Local Server (Study / Preservation)

Local backend and client-patching toolkit for **Omlet Arcade 1.111.9** (package
`mobisocial.arcade`), discontinued in 2023.

> **Status:** guest login and session resume work end-to-end. The patched client
> completes the WebSocket handshake, creates a guest account, persists it and
> resumes the session after a restart. The profile About screen renders the guest
> name, level, zeroed counts, bio and tabs (default avatar and empty media
> sections). Feed/chat/live are **not** implemented yet.

> **Disclaimer:** this is an unofficial reverse-engineering / preservation
> project. It is not affiliated with Omlet, Mobisocial, or any of their partners.
> No APK, proprietary source code, assets, credentials or user data are included
> in this repository. Use it only with an APK you legally own, for personal study
> and research.

---

## What works

- X25519 challenge/response handshake for the client's custom **Longdan** RPC
  protocol over WebSocket (`md0` → `nd0` → `he` → `ie`).
- Omlet ID availability check (`ci` → `pz0`).
- Guest account creation (`sc` → `nz0`/`z`) with cluster `ONE`.
- Session resume after restarting the app (`qb` → `z`) backed by a local account
  store (`server/accounts.json`, not committed).
- Client reaches the Home UI logged in as a guest and keeps the session after a
  restart.
- Session/keepalive handling (`rp0` → `sp0`).
- Profile requests:
  - `gpa` → `ir0`/`hr0` (profile About);
  - `p.c` → `z00`/`se` (profile details; the Omlet ID appears in Account
    Settings);
  - `w.gfc`, `w.gafc`, `w.guwc` → `pz0` (follower/following/posts counts);
  - `p.gui` → `ra0` (shards);
  - `ca.g` → `uu` (top supporters).
- The Profile About screen renders the guest name, level, zeroed counts, bio and
  tabs. The avatar is the default placeholder and media/post sections are empty.
- Patched APK points every embedded endpoint to a local HTTP/WS server.

Not implemented yet:

- The profile About UI still needs more `hr0`/`se` fields and remaining profile
  requests before it renders fully (currently skeleton placeholders).
- Home feed (`w.ghp` → `sx`/`td0`), follows, chat/messaging, games,
  live/streaming.
- Blobs, push notifications, billing/NFT/analytics namespaces.

---

## Architecture

The client talks to a proprietary RPC layer called **Longdan**:

- Transport: **WebSocket**, JSON payloads (server → client responses may be
  gzip-compressed; the client also gzips large requests if the server advertises
  a max size).
- Handshake: **X25519** using a per-install device key and server public keys
  embedded in the APK resource `res/raw/oml_pk.json`.
- Envelope:

```json
{"q": {"#": <request-id>, "<category>": {"<method>": { ... }}}}
{"r": {"#": <request-id>, "<category>": {"<method>": { ... }}}}
```

For the IDP/auth connection (`/device`), the request container is `jl` and the
response container is `kl` → `ml`. The message/read-only connection uses a
different container pair.

### Endpoints embedded in the APK

`res/raw/oml_pk.json` contains:

- `ClusterEndpoints` — ten regional clusters (us/sg/cn/de/in/ja/br/au/sk/use).
- `IdpEndpoints` — identity provider endpoint.
- `ReadOnlyEndpoints` — read-only content endpoint.
- `ClusterKeys`, `IdpKey`, `ReadOnlyKey` — **server public keys**.
- `DefaultCluster` — `ONE`.

The patch script replaces all of them with one local endpoint and one generated
public key.

### Handshake

The client connects to `<endpoint>/device` (or `/readonlydevice`) and sends:

```json
{"q":{"#":1,"*":{
  "a":"<omlet.apikey bytes, base64>",
  "c":"<client nonce, 32 bytes, base64>",
  "k":"<client X25519 public key, base64>",
  "s":false,
  "z":true
}}}
```

The server computes:

```text
shared = X25519(server_private, client_public)
server_nonce = random(32)
digest  = SHA256(0x01 || shared || client_nonce)
```

and replies:

```json
{"r":{"#":1,"*":{
  "c":"<server nonce, base64>",
  "r":"<digest, base64>"
}}}
```

The client verifies the digest, then sends `he` (`+`) with:

```text
SHA256(0x02 || shared || server_nonce)
```

The server replies with `ie` (`+`), which carries the closest cluster name:

```json
{"r":{"#":3,"+":{"l":"ONE"}}}
```

### Guest login

1. `ci` checks whether an Omlet ID is available. Response: `pz0` (`=`), a
   boolean stored under key `v`:

```json
{"r":{"#":7,"=":{"v":true}}}
```

2. `sc` creates/signs in the guest account. The server answers with `nz0`
   under `ml` key `sc`, inside `kl` key `a`:

```json
{"r":{"#":8,"a":{"sc":{
  "s":"GUEST",
  "a":{
    "a":{"a":"<account-id>","c":"ONE","d":"GUEST",
         "i":[{"p":"<omlet-id>","t":"omlet"}],
         "p":"<omlet-id>","s":<timestamp-ms>},
    "S":["PublicProfile","Arcade"],
    "i":"<app-id, 32 bytes, base64>",
    "e":false,
    "p":false
  }
}}}}
```

After that the client stores the account and reconnects the message channel to
the cluster endpoint.

---

## Repository layout

```text
.
├── README.md
├── LICENSE
├── .gitignore
├── server/
│   ├── server.py            # handshake, sessions and profile server
│   ├── stub.py             # raw WebSocket logger (protocol debugging)
│   ├── generate_keys.py    # creates server/keys.json
│   └── requirements.txt
└── scripts/
    └── patch-apk.sh         # decode/patch/rebuild/sign the client APK
```

At runtime the server creates `server/accounts.json` to persist guest accounts
across restarts. This file is ignored by Git.

The original APK, the decompiled tree, the rebuilt APKs, logs, the private key
and the signing keystore are intentionally **not** committed.

---

## Requirements

Tested on Arch Linux + Waydroid (LineageOS 20, x86_64). You need:

- Linux with Waydroid (or a physical Android device with ADB).
- Python 3.11+.
- `apktool`, `zipalign`, `apksigner`, `keytool` (Java).
  - On Arch, `apktool` is available from AUR; build-tools provide
    `zipalign`/`apksigner` (e.g. `/opt/android-sdk/build-tools/33.0.2`).
- The original `omlet-arcade-1-111-9.apk` (not distributed here).
- `adb` from `android-tools`.

The original APK embeds the app credentials (`omlet.apikey` and `omlet.secret`)
in the manifest. The server does not need to know them; the client sends the API
key during the handshake and the server accepts it. They are not included in this
repository.

---

## Quick start

### 1. Python environment

```bash
python3 -m venv server/venv
server/venv/bin/pip install -r server/requirements.txt
```

### 2. Generate the local server keypair

```bash
python3 server/generate_keys.py
```

This creates `server/keys.json` (private key + public key). **Never commit this
file.** The public key is the one patched into the APK.

### 3. Patch the APK

```bash
scripts/patch-apk.sh /path/to/omlet-arcade-1-111-9.apk
```

Optional second argument overrides the host/port (default
`192.168.240.1:8080`, the Waydroid host gateway):

```bash
scripts/patch-apk.sh /path/to/omlet.apk 192.168.240.1:8080
```

The script:

1. decodes resources/manifest with `apktool` (no smali changes);
2. rewrites `res/raw/oml_pk.json` to point all endpoints to your host and to
   use the public key from `server/keys.json`;
3. enables cleartext traffic for the local host;
4. enables the guest account flow (`omlet.guest=true`);
5. rebuilds, aligns and signs with `tools/debug.keystore` (generated on demand).

Output: `patched/omlet-patched-signed.apk`.

> The build is memory-hungry. Stop Waydroid and close heavy browsers before
> running it. The script uses `-j1` and `-JXmx6g` to reduce memory pressure.

### 4. Waydroid + ADB

```bash
sudo systemctl enable --now waydroid-container
waydroid session start &
waydroid show-full-ui       # unfreeze / show Android UI
waydroid adb connect        # or: adb connect 192.168.240.112:5555
adb devices
```

If ADB shows `unauthorized`, add your host key inside the container:

```bash
cat ~/.android/adbkey.pub | sudo waydroid shell -- \
  sh -c 'mkdir -p /data/misc/adb; cat > /data/misc/adb/adb_keys; \
         chmod 640 /data/misc/adb/adb_keys; chown system:shell /data/misc/adb/adb_keys'
sudo waydroid shell -- setprop ctl.restart adbd
adb kill-server && adb connect 192.168.240.112:5555
```

### 5. Install the patched APK

Unlike the original signature, the patched APK must replace the installed app:

```bash
sudo waydroid shell -- pm uninstall mobisocial.arcade
adb install -r -d patched/omlet-patched-signed.apk
```

If `waydroid app install` exits instantly without installing (known helper
issue), use `adb install` or push the APK to `/data/local/tmp` and run
`pm install` manually.

### 6. Start the server

```bash
cd server
nohup ./venv/bin/python server.py >> ../logs/server.log 2>&1 &
```

The server listens on `0.0.0.0:8080`. The client reaches the host at
`192.168.240.1:8080` from inside Waydroid.

### 7. Launch the app

```bash
adb shell am start -W -n mobisocial.arcade/.DEFAULT
```

Create a guest account:

1. tap **Create Account**;
2. enter an ID (6–20 chars, lowercase letters, digits, dot, underscore);
3. wait for the green check (`ci` succeeded);
4. tap **CONTINUE** (`sc` creates the account);
5. skip the optional gender/birthday onboarding.

You should land on the Home UI.

---

## Protocol notes

### Request/response categories

On the IDP connection:

| Key | Meaning |
| --- | --- |
| `*` | `md0` handshake request / `nd0` handshake response |
| `+` | `he` hello completion / `ie` hello response |
| `-` | `rp0` keepalive request / `sp0` keepalive response |
| `a` | auth container (`ll` request / `ml` response) |
| `=` | `pz0` generic response (used by `ci`) |

The `ci` check and `sc` sign-in live inside the `a` container:

```json
{"q":{"a":{"ci":{...}}}}
{"r":{"#":7,"=":{"v":true}}}
{"q":{"a":{"sc":{...}}}}
{"r":{"#":8,"a":{"sc":{...nz0...}}}}
```

### Keepalive

The client sends `rp0` periodically:

```json
{"q":{"#":2,"-":{"l":0,"n":28000}}}
```

Answer with the server timestamp:

```json
{"r":{"#":2,"-":{"t":<epoch-ms>}}}
```

### Debugging

`server/stub.py` is a raw WebSocket logger. It does not answer the handshake; it
just prints paths and messages (text or gzip/binary) so you can capture exactly
what the client sends.

```bash
server/venv/bin/python server/stub.py
```

---

## Known limitations / roadmap

- **Profile media/content**: the About screen renders, but the avatar is the
  default placeholder and posts/store/collections/moments are empty because media
  blobs and feed data are not implemented.
- **Home feed**: `w.ghp` → `sx`/`td0` is not implemented.
- **Chat/messaging** is not implemented.
- **Live/streaming** is not implemented; the original app relied on external
  RTMP/SRT/WebRTC and third-party platforms.
- **Blobs / push / billing / NFT / analytics** are not implemented.
- Analytics/billing calls will log errors in the client UI; they are harmless for
  the login/session/profile milestones.

---

## Troubleshooting

### Waydroid/Android graphics crash on startup

On some AMD/Mesa + Hyprland setups, starting Waydroid can crash the compositor
together with `surfaceflinger` (a Mesa/GBM abort). Updating Mesa/Hyprland/kernel
and firmware fixed it in our test. If it still happens, try software rendering:

```bash
sudo waydroid prop set persist.waydroid.software_rendering true
```

and avoid keeping the Waydroid UI open during heavy builds.

### `waydroid app install` returns success but installs nothing

This happened on Waydroid 1.6.3 with a large APK. Use ADB:

```bash
adb install -r -d patched/omlet-patched-signed.apk
```

or copy the APK to the container's `/data/local/tmp` and run:

```bash
sudo waydroid shell -- pm install -r /data/local/tmp/omlet.apk
```

### ADB `unauthorized`

Add `~/.android/adbkey.pub` to `/data/misc/adb/adb_keys` inside the container
(see step 4) and restart `adbd`.

### Client cannot reach the server

- Confirm the server is listening: `ss -ltnp | grep 8080`.
- Confirm the APK was patched with the same host as the server (default
  `192.168.240.1:8080`).
- Confirm cleartext HTTP is allowed in the patched
  `network_security_config.xml`.
- The public key in the APK must match `server/keys.json`; re-run the patch
  script after regenerating keys.

---

## Legal

Omlet Arcade, its client, protocol, trademarks and assets belong to their
respective owners. This repository contains only original code and
documentation produced for interoperability research. No APK, decompiled
proprietary source, assets, credentials or user data are distributed here.
Do not use this project to access other people's accounts or data, and do not
redistribute modified APKs.

## License

The code and documentation in this repository are released under the MIT
License (see `LICENSE`). This license does **not** grant any rights to Omlet
Arcade or third-party intellectual property.
