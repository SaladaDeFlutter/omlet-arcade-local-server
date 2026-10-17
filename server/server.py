import asyncio
import base64
import gzip
import hashlib
import http.server
import json
import logging
import os
import sys
import threading
import time
import uuid

import websockets
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)

BASE = os.path.dirname(os.path.abspath(__file__))
KEYS_PATH = os.path.join(BASE, "keys.json")
ACCOUNTS_PATH = os.path.join(BASE, "accounts.json")

with open(KEYS_PATH, "r", encoding="utf-8") as fh:
    KEYS = json.load(fh)

SERVER_PRIVATE = X25519PrivateKey.from_private_bytes(
    base64.b64decode(KEYS["private_b64"])
)
SERVER_PUBLIC_B64 = KEYS["public_b64"]

AVATAR_PATH = os.path.join(BASE, "avatar.png")
COVER_PATH = os.path.join(BASE, "cover.png")
PUBLIC_HOST = os.environ.get("PUBLIC_HOST", "192.168.240.1")
AVATAR_HTTP_URL = f"http://{PUBLIC_HOST}:8081/avatar.png"
COVER_HTTP_URL = f"http://{PUBLIC_HOST}:8081/cover.png"
BLOB_BASE = f"http://{PUBLIC_HOST}:8081/blob/"


def file_blob_url(name, path):
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as fh:
        digest = hashlib.md5(fh.read()).digest()
    encoded = base64.b64encode(digest).decode("ascii")
    encoded = encoded.replace("/", "_").replace("+", "-").replace("=", ".")
    return f"longdan://{name}/" + encoded


AVATAR_BLOB_URL = file_blob_url("avatar", AVATAR_PATH)
COVER_BLOB_URL = file_blob_url("cover", COVER_PATH)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
    force=True,
)
LOG = logging.getLogger("omlet")

ACCOUNTS = []
POST_STATE = {"liked": False, "count": 0}
COMMENTS = []


def b64d(value):
    return base64.b64decode(value)


def b64e(value):
    return base64.b64encode(value).decode("ascii")


def decode_message(message):
    if isinstance(message, bytes):
        raw = bytes(message)
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
        return json.loads(raw.decode("utf-8", "replace"))
    return json.loads(message)


def load_accounts():
    global ACCOUNTS
    if not os.path.exists(ACCOUNTS_PATH):
        ACCOUNTS = []
        return
    try:
        with open(ACCOUNTS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        ACCOUNTS = data.get("records", [])
    except Exception as exc:
        LOG.error("could not load accounts.json: %r", exc)
        ACCOUNTS = []


def save_accounts():
    tmp = ACCOUNTS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"records": ACCOUNTS}, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, ACCOUNTS_PATH)


def find_account(client_pub=None, account_id=None):
    if account_id:
        for record in ACCOUNTS:
            if record.get("account_id") == account_id:
                return record
    if client_pub:
        for record in ACCOUNTS:
            if record.get("client_pub") == client_pub:
                return record
    return None


def upsert_account(record):
    for index, existing in enumerate(ACCOUNTS):
        if (
            existing.get("client_pub") == record.get("client_pub")
            or existing.get("account_id") == record.get("account_id")
        ):
            ACCOUNTS[index] = record
            save_accounts()
            return record
    ACCOUNTS.append(record)
    save_accounts()
    return record


def build_account(client_pub, api_key, account_id, omlet_id, scopes, created_ms=None):
    now = created_ms or int(time.time() * 1000)
    seed = (client_pub + api_key + "appid").encode()
    app_id = hashlib.sha256(seed).digest()
    profile = {
        "a": account_id,
        "c": "ONE",
        "d": "GUEST",
        "i": [{"p": omlet_id, "t": "omlet"}],
        "p": omlet_id,
        "s": now,
    }
    account = {
        "a": profile,
        "S": scopes,
        "i": b64e(app_id),
        "e": False,
        "p": False,
    }
    return account, now


def make_record(client_pub, api_key, account_id, omlet_id, scopes):
    account, created_ms = build_account(
        client_pub, api_key, account_id, omlet_id, scopes
    )
    return {
        "client_pub": client_pub,
        "account_id": account_id,
        "omlet_id": omlet_id,
        "scopes": scopes,
        "created_ms": created_ms,
        "z": account,
    }


def profile_about(record):
    now = int(time.time() * 1000)
    omlet_id = record.get("omlet_id", "omletplayer")
    community = {
        "m": {"ci": AVATAR_BLOB_URL, "dn": omlet_id},
        "cci": {"p": omlet_id, "cid": omlet_id, "ct": "App"},
        "uci": [],
        "c": 0,
        "p": 0,
        "l": 0,
        "im": False,
    }
    return {
        "a": omlet_id,
        "al": record.get("created_ms", now),
        "lm": now,
        "bg": COVER_BLOB_URL,
        "fc": community,
        "g": "Unknown",
        "p": [],
        "s": "Omlet Arcade guest",
        "tfs": False,
        "p2pfc": 0,
        "p2popb": 0,
    }


def get_or_create_record(client_pub, api_key, account_id=None):
    record = find_account(client_pub=client_pub, account_id=account_id)
    if record:
        return record
    account_id = account_id or client_pub or uuid.uuid4().hex
    record = make_record(
        client_pub,
        api_key,
        account_id,
        "omletplayer",
        ["PublicProfile", "Arcade"],
    )
    return upsert_account(record)


def profile_detail(record):
    omlet_id = record.get("omlet_id", "omletplayer")
    return {
        "v": 0,
        "pu": omlet_id,
        "i": [{"p": omlet_id, "t": "omlet"}],
        "n": omlet_id,
        "p": AVATAR_BLOB_URL,
        "au": AVATAR_HTTP_URL,
    }


def comment_author(record):
    return {
        "a": record.get("account_id", ""),
        "n": record.get("omlet_id", "omletplayer"),
        "p": AVATAR_BLOB_URL,
        "vfs": [],
    }


def comment_subject(record):
    return {
        "a": record.get("account_id", ""),
        "t": "Message",
        "id": b64e(record.get("account_id", "").encode("utf-8")),
    }


def make_comment(record, text):
    return {
        "i": b64e(os.urandom(8)),
        "T": "TEXT",
        "b": b64e(text.encode("utf-8")),
        "t": int(time.time() * 1000),
        "u": comment_author(record),
        "p": comment_subject(record),
    }


async def handler(ws, *args):
    try:
        path = ws.request.path
    except Exception:
        path = args[0] if args else "?"

    LOG.info("CONNECT path=%s", path)
    state = {}
    try:
        async for raw in ws:
            try:
                request = decode_message(raw)
            except Exception as exc:
                LOG.error("bad message path=%s err=%r", path, exc)
                continue

            LOG.info("REQ path=%s %s", path, json.dumps(request)[:3000])
            q = request.get("q") or {}
            request_id = q.get("#")
            response = {"#": request_id}

            if "*" in q:
                hello = q["*"]
                state["client_pub"] = hello.get("k", "")
                state["api"] = hello.get("a", "")
                try:
                    client_public = X25519PublicKey.from_public_bytes(
                        b64d(hello["k"])
                    )
                    shared = SERVER_PRIVATE.exchange(client_public)
                    server_nonce = os.urandom(32)
                    digest = hashlib.sha256(
                        b"\x01" + shared + b64d(hello["c"])
                    ).digest()
                    response["*"] = {
                        "c": b64e(server_nonce),
                        "r": b64e(digest),
                    }
                    LOG.info(
                        "HANDSHAKE path=%s api=%s",
                        path,
                        hello.get("a"),
                    )
                except Exception as exc:
                    LOG.exception("handshake failed path=%s", path)
                    response["!"] = "HandshakeFailed"
                    response["!!"] = str(exc)
            elif "-" in q:
                response["-"] = {"t": int(time.time() * 1000)}
            elif "+" in q:
                LOG.info("HELLO path=%s %s", path, json.dumps(q["+"])[:2000])
                response["+"] = {"l": "ONE"}
            elif isinstance(q.get("a"), dict) and "l" in q["a"]:
                qb = q["a"]["l"] or {}
                account_id = qb.get("p") if isinstance(qb, dict) else None
                record = find_account(
                    client_pub=state.get("client_pub"),
                    account_id=account_id,
                )
                if record:
                    response["a"] = {"a": record["z"]}
                    LOG.info(
                        "QB_RESUME path=%s account=%s omlet_id=%s",
                        path,
                        record.get("account_id"),
                        record.get("omlet_id"),
                    )
                else:
                    response["!"] = "NotSignedIn"
                    LOG.info(
                        "QB_NO_ACCOUNT path=%s client_pub=%s",
                        path,
                        state.get("client_pub"),
                    )
            elif isinstance(q.get("a"), dict) and "ci" in q["a"]:
                LOG.info("CHECK_ID path=%s %s", path, json.dumps(q["a"]["ci"])[:2000])
                response["="] = {"v": True}
            elif isinstance(q.get("a"), dict) and "sc" in q["a"]:
                sc = q["a"]["sc"]
                omlet_id = sc.get("s") or "omletplayer"
                account_id = sc.get("a") or uuid.uuid4().hex
                scopes = sc.get("S") or ["PublicProfile", "Arcade"]
                record = make_record(
                    state.get("client_pub", ""),
                    state.get("api", ""),
                    account_id,
                    omlet_id,
                    scopes,
                )
                upsert_account(record)
                response["a"] = {"sc": {"s": "GUEST", "a": record["z"]}}
                LOG.info(
                    "CREATE_ACCOUNT path=%s account=%s omlet_id=%s scopes=%s",
                    path,
                    account_id,
                    omlet_id,
                    scopes,
                )
            elif isinstance(q.get("p"), dict) and "gpa" in q["p"]:
                gpa = q["p"]["gpa"] or {}
                account_id = (
                    gpa.get("c") or gpa.get("a")
                    if isinstance(gpa, dict)
                    else None
                )
                record = get_or_create_record(
                    state.get("client_pub", ""),
                    state.get("api", ""),
                    account_id,
                )
                response["p"] = {"pa": {"p": profile_about(record), "us": {}}}
                LOG.info(
                    "PROFILE path=%s account=%s omlet_id=%s",
                    path,
                    record.get("account_id"),
                    record.get("omlet_id"),
                )
            elif isinstance(q.get("p"), dict) and "c" in q["p"]:
                pc = q["p"]["c"] or {}
                account_id = pc.get("c") if isinstance(pc, dict) else None
                record = get_or_create_record(
                    state.get("client_pub", ""),
                    state.get("api", ""),
                    account_id,
                )
                response["p"] = {"c": {"p": profile_detail(record)}}
                LOG.info(
                    "PROFILE_DETAIL path=%s account=%s omlet_id=%s",
                    path,
                    record.get("account_id"),
                    record.get("omlet_id"),
                )
            elif isinstance(q.get("w"), dict) and any(
                key in q["w"] for key in ("gfc", "gafc", "guwc")
            ):
                response["="] = {"v": 0}
                LOG.info(
                    "COUNT path=%s keys=%s",
                    path,
                    list(q["w"].keys()),
                )
            elif isinstance(q.get("w"), dict) and "gcvv" in q["w"]:
                response["w"] = {"gcvv": {"C": COMMENTS}}
                LOG.info(
                    "COMMENTS_LIST path=%s count=%d", path, len(COMMENTS)
                )
            elif isinstance(q.get("w"), dict) and "ac" in q["w"]:
                add_req = q["w"]["ac"] or {}
                text = ""
                if isinstance(add_req, dict):
                    raw_text = add_req.get("b")
                    if raw_text:
                        text = b64d(raw_text).decode("utf-8", "replace")
                record = find_account(client_pub=state.get("client_pub"))
                if record is None:
                    record = get_or_create_record(
                        state.get("client_pub", ""),
                        state.get("api", ""),
                        None,
                    )
                COMMENTS.append(make_comment(record, text))
                response["="] = {"v": True}
                LOG.info(
                    "COMMENT_ADD path=%s text=%r count=%d",
                    path,
                    text,
                    len(COMMENTS),
                )
            elif isinstance(q.get("w"), dict) and "l" in q["w"]:
                like_req = q["w"]["l"] or {}
                liked = bool(like_req.get("l", False)) if isinstance(like_req, dict) else False
                if liked != POST_STATE["liked"]:
                    POST_STATE["count"] = max(
                        0, POST_STATE["count"] + (1 if liked else -1)
                    )
                    POST_STATE["liked"] = liked
                response["="] = {"v": True}
                LOG.info(
                    "LIKE path=%s liked=%s count=%s",
                    path,
                    liked,
                    POST_STATE["count"],
                )
            elif isinstance(q.get("w"), dict) and "ghp" in q["w"]:
                record = find_account(client_pub=state.get("client_pub"))
                if record is None:
                    record = get_or_create_record(
                        state.get("client_pub", ""),
                        state.get("api", ""),
                        None,
                    )
                now = int(time.time() * 1000)
                post = {
                    "i": "local-post-1",
                    "a": profile_about(record),
                    "P": {
                        "m": {
                            "u": "Hello from the local Omlet server!",
                            "t": "Hello from the local Omlet server!",
                            "d": "Posted via the local server",
                            "P": "https://omlet.gg",
                            "Q": "Hello from the local Omlet server!",
                            "U": "Local server test post",
                            "oi": {
                                "p": record.get("omlet_id", "omletplayer"),
                                "t": "omlet",
                            },
                            "un": record.get("omlet_id", "omletplayer"),
                            "id": {
                                "a": record.get("account_id", ""),
                                "t": "Message",
                                "id": b64e(
                                    record.get("account_id", "").encode("utf-8")
                                ),
                            },
                            "usr": {
                                "a": record.get("account_id", ""),
                                "n": record.get("omlet_id", "omletplayer"),
                                "p": AVATAR_BLOB_URL,
                                "vfs": [],
                            },
                            "gn": [],
                            "gi": [],
                            "g": [],
                            "ct": now,
                            "cc": len(COMMENTS),
                            "l": POST_STATE["count"],
                            "yl": POST_STATE["liked"],
                            "vd": False,
                        }
                    },
                    "ls": {"t": str(now)},
                    "ofc": 0,
                }
                response["w"] = {"ghp": {"p": [post]}}
                LOG.info("FEED path=%s post=%s", path, post["i"])
            elif isinstance(q.get("p"), dict) and "gui" in q["p"]:
                response["p"] = {"gui": {"ii": {}}}
                LOG.info("SHARDS path=%s", path)
            elif isinstance(q.get("ca"), dict) and "g" in q["ca"]:
                response["ca"] = {
                    "g": {"d": [], "l": [], "m": [], "u": [], "w": []}
                }
                LOG.info("TOP_SUPPORTERS path=%s", path)
            elif isinstance(q.get("b"), dict) and "dt" in q["b"]:
                dt = q["b"].get("dt")
                source = dt.get("l", "") if isinstance(dt, dict) else ""
                url = COVER_HTTP_URL if "/cover/" in source else AVATAR_HTTP_URL
                response["b"] = {
                    "dt": {
                        "dt": {"u": url, "h": {}},
                        "pp": BLOB_BASE,
                    }
                }
                LOG.info("BLOB_TICKET path=%s source=%s", path, source)
            else:
                LOG.info(
                    "UNKNOWN path=%s keys=%s payload=%s",
                    path,
                    list(q.keys()),
                    json.dumps(q)[:2000],
                )
                response["!"] = "NotImplemented"

            await ws.send(json.dumps({"r": response}))
    except websockets.ConnectionClosed:
        LOG.info("DISCONNECT path=%s", path)
    except Exception:
        LOG.exception("handler error path=%s", path)


class AvatarHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/cover"):
            path = COVER_PATH
        elif self.path.startswith("/avatar") or self.path.startswith("/blob/"):
            path = AVATAR_PATH
        else:
            self.send_error(404)
            return
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        LOG.info("HTTP " + fmt, *args)


def start_avatar_server():
    server = http.server.ThreadingHTTPServer(("0.0.0.0", 8081), AvatarHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    LOG.info("avatar HTTP server listening on 0.0.0.0:8081")
    LOG.info("avatar URL: %s", AVATAR_HTTP_URL)


async def main():
    load_accounts()
    start_avatar_server()
    async with websockets.serve(
        handler,
        "0.0.0.0",
        8080,
        max_size=None,
        compression=None,
    ):
        LOG.info("Omlet local server listening on 0.0.0.0:8080")
        LOG.info("server public key: %s", SERVER_PUBLIC_B64)
        LOG.info("accounts loaded: %d", len(ACCOUNTS))
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
