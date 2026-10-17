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
STATE_PATH = os.path.join(BASE, "state.json")

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
LOCAL_POST_ID = "local-post-1"
LOCAL_COMMUNITY_ID = "local-community"
LOCAL_CHANNEL_ID = "local-community-general"
POSTS = {}
CHANNELS = {}


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


def empty_post_state():
    return {"liked": False, "count": 0, "comments": []}


def load_state():
    global POSTS, CHANNELS
    POSTS = {}
    CHANNELS = {}
    if not os.path.exists(STATE_PATH):
        return
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        posts = data.get("posts", {})
        if isinstance(posts, dict):
            for post_id, post_state in posts.items():
                if not isinstance(post_state, dict):
                    continue
                comments = post_state.get("comments", [])
                POSTS[post_id] = {
                    "liked": bool(post_state.get("liked", False)),
                    "count": max(0, int(post_state.get("count", 0))),
                    "comments": comments if isinstance(comments, list) else [],
                }
        channels = data.get("channels", {})
        if isinstance(channels, dict):
            for channel_id, channel_state in channels.items():
                if (
                    isinstance(channel_state, dict)
                    and isinstance(channel_state.get("messages"), list)
                ):
                    CHANNELS[channel_id] = {
                        "messages": channel_state["messages"]
                    }
    except Exception as exc:
        LOG.error("could not load state.json: %r", exc)
        POSTS = {}
        CHANNELS = {}


def save_state():
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(
            {"posts": POSTS, "channels": CHANNELS},
            fh,
            indent=2,
            ensure_ascii=False,
        )
        fh.write("\n")
    os.replace(tmp, STATE_PATH)


def get_post_state(post_id=LOCAL_POST_ID):
    post_state = POSTS.get(post_id)
    if post_state is None:
        post_state = empty_post_state()
        POSTS[post_id] = post_state
    return post_state


def empty_channel_state():
    return {"messages": []}


def get_channel_state(channel_id=LOCAL_CHANNEL_ID):
    channel_state = CHANNELS.get(channel_id)
    if channel_state is None:
        channel_state = empty_channel_state()
        CHANNELS[channel_id] = channel_state
    return channel_state


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


def local_channel_eo():
    return {"a": LOCAL_CHANNEL_ID, "k": b64e(b"omlet-local-channel")}


def local_community_info():
    return {
        "cid": {"ct": "Managed", "cid": LOCAL_COMMUNITY_ID, "p": "Android"},
        "n": "Comunidade Local",
        "i": AVATAR_HTTP_URL,
        "ll": [],
        "sq": False,
    }


def local_channel_feed():
    now = int(time.time() * 1000)
    return {
        "f": local_channel_eo(),
        "n": "geral",
        "a": "Yes",
        "mc": 1,
        "fc": local_community_info(),
        "lrt": now,
        "ibt": "CommunityFeedChannels",
    }


def make_channel_message(record, text):
    now = int(time.time() * 1000000)
    body = json.dumps(
        {"text": text, "profileVersion": 0}, ensure_ascii=False
    ).encode("utf-8")
    return {
        "i": {"t": "text", "i": b64e(os.urandom(32))},
        "t": now,
        "s": record.get("account_id", ""),
        "b": b64e(body),
        "f": local_channel_eo(),
        "d": False,
        "rn": now,
    }


def local_community_ee():
    now = int(time.time() * 1000)
    return {
        "cci": {"ct": "Managed", "cid": LOCAL_COMMUNITY_ID, "p": "Android"},
        "c": 1,
        "p": 1,
        "l": 0,
        "im": False,
        "m": {
            "dn": "Comunidade Local",
            "ci": AVATAR_HTTP_URL,
            "b": COVER_HTTP_URL,
        },
        "t": now,
    }


def make_feed_post(record, post_state):
    now = int(time.time() * 1000)
    return {
        "i": LOCAL_POST_ID,
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
                    "id": b64e(record.get("account_id", "").encode("utf-8")),
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
                "cc": len(post_state["comments"]),
                "l": post_state["count"],
                "yl": post_state["liked"],
                "vd": False,
            }
        },
        "ls": {"t": str(now)},
        "ofc": 0,
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
                post_state = get_post_state()
                response["w"] = {"gcvv": {"C": post_state["comments"]}}
                LOG.info(
                    "COMMENTS_LIST path=%s count=%d",
                    path,
                    len(post_state["comments"]),
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
                post_state = get_post_state()
                post_state["comments"].append(make_comment(record, text))
                save_state()
                response["="] = {"v": True}
                LOG.info(
                    "COMMENT_ADD path=%s text=%r count=%d",
                    path,
                    text,
                    len(post_state["comments"]),
                )
            elif isinstance(q.get("w"), dict) and "l" in q["w"]:
                like_req = q["w"]["l"] or {}
                liked = bool(like_req.get("l", False)) if isinstance(like_req, dict) else False
                post_state = get_post_state()
                if liked != post_state["liked"]:
                    post_state["count"] = max(
                        0, post_state["count"] + (1 if liked else -1)
                    )
                    post_state["liked"] = liked
                    save_state()
                response["="] = {"v": True}
                LOG.info(
                    "LIKE path=%s liked=%s count=%s",
                    path,
                    liked,
                    post_state["count"],
                )
            elif isinstance(q.get("m"), dict) and "o" in q["m"]:
                op = q["m"]["o"] or {}
                message_id = op.get("i") or {}
                message_type = (
                    message_id.get("t")
                    if isinstance(message_id, dict)
                    else None
                )
                raw_body = op.get("b")
                if message_type == "text" and raw_body:
                    record = find_account(
                        client_pub=state.get("client_pub")
                    )
                    if record is None:
                        record = get_or_create_record(
                            state.get("client_pub", ""),
                            state.get("api", ""),
                            None,
                        )
                    channel_state = get_channel_state()
                    encoded_id = message_id.get("i")
                    is_duplicate = any(
                        item.get("i", {}).get("i") == encoded_id
                        for item in channel_state["messages"]
                    )
                    if not is_duplicate:
                        now = int(time.time() * 1000000)
                        channel_state["messages"].append(
                            {
                                "i": message_id,
                                "t": now,
                                "s": record.get("account_id", ""),
                                "b": raw_body,
                                "f": op.get("f") or local_channel_eo(),
                                "d": False,
                                "rn": now,
                            }
                        )
                        save_state()
                    text = ""
                    try:
                        text = json.loads(b64d(raw_body)).get("text", "")
                    except Exception:
                        pass
                    LOG.info(
                        "CHANNEL_SEND path=%s type=%s text=%r count=%d",
                        path,
                        message_type,
                        text,
                        len(channel_state["messages"]),
                    )
                else:
                    LOG.info(
                        "CHANNEL_ACTIVITY path=%s type=%s",
                        path,
                        message_type,
                    )
                response["="] = {"v": True}
            elif isinstance(q.get("m"), dict) and "gmfc" in q["m"]:
                record = find_account(client_pub=state.get("client_pub"))
                if record is None:
                    record = get_or_create_record(
                        state.get("client_pub", ""),
                        state.get("api", ""),
                        None,
                    )
                channel_state = get_channel_state()
                if not channel_state["messages"]:
                    channel_state["messages"].append(
                        make_channel_message(
                            record,
                            "Bem-vindo ao canal geral da Comunidade Local!",
                        )
                    )
                    save_state()
                response["m"] = {
                    "wd": {
                        "c": channel_state["messages"],
                        "p": False,
                        "s": {
                            record.get("account_id", ""): comment_author(record)
                        },
                        "fd": local_channel_feed(),
                    }
                }
                LOG.info(
                    "CHANNEL_MESSAGES path=%s channel=%s count=%d",
                    path,
                    LOCAL_CHANNEL_ID,
                    len(channel_state["messages"]),
                )
            elif isinstance(q.get("i"), dict) and "f" in q["i"]:
                feed_req = q["i"].get("f")
                item_type = (
                    feed_req.get("ibt") if isinstance(feed_req, dict) else None
                )
                if item_type == "CommunityFeedChannels":
                    response["i"] = {"f": {"f": [local_channel_feed()]}}
                    LOG.info("CHANNELS path=%s count=1", path)
                else:
                    response["i"] = {"f": {"f": []}}
                    LOG.info(
                        "FEED_DETAILS path=%s ibt=%s count=0",
                        path,
                        item_type,
                    )
            elif isinstance(q.get("w"), dict) and "gcfr" in q["w"]:
                record = find_account(client_pub=state.get("client_pub"))
                if record is None:
                    record = get_or_create_record(
                        state.get("client_pub", ""),
                        state.get("api", ""),
                        None,
                    )
                post_state = get_post_state()
                post = make_feed_post(record, post_state)
                header = {
                    "i": "my-communities",
                    "c": [local_community_ee()],
                }
                response["w"] = {"ghp": {"p": [header, post]}}
                LOG.info("COMMUNITY_FEED path=%s count=2", path)
            elif isinstance(q.get("w"), dict) and "licu" in q["w"]:
                response["w"] = {"gcm": {"c": [], "p": 0}}
                LOG.info("COMMUNITIES path=%s count=0", path)
            elif isinstance(q.get("w"), dict) and "ghp" in q["w"]:
                record = find_account(client_pub=state.get("client_pub"))
                if record is None:
                    record = get_or_create_record(
                        state.get("client_pub", ""),
                        state.get("api", ""),
                        None,
                    )
                post_state = get_post_state()
                post = make_feed_post(record, post_state)
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
    load_state()
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
