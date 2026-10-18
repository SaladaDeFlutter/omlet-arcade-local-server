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

from database import Database

BASE = os.path.dirname(os.path.abspath(__file__))
KEYS_PATH = os.path.join(BASE, "keys.json")
ACCOUNTS_PATH = os.path.join(BASE, "accounts.json")
STATE_PATH = os.path.join(BASE, "state.json")
DB_PATH = os.path.join(BASE, "omlet.db")

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

LOCAL_POST_ID = "local-post-1"
LOCAL_COMMUNITY_ID = "local-community"
LOCAL_CHANNEL_ID = "local-community-general"
LOCAL_CHANNEL_KEY = base64.b64encode(b"omlet-local-channel").decode("ascii")

DB = Database(DB_PATH, default_icon=AVATAR_BLOB_URL, default_cover=COVER_BLOB_URL)


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


def find_account(client_pub=None, account_id=None):
    return DB.find_account(client_pub=client_pub, account_id=account_id)


def upsert_account(record):
    return DB.upsert_account(record)


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


def session_z(record):
    z = dict(record.get("z", {}))
    z["e"] = bool(record.get("has_email", True))
    z["p"] = False
    profile = dict(z.get("a", {}))
    profile["h"] = bool(record.get("has_password", True))
    z["a"] = profile
    return z


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


def current_record(state):
    record = find_account(client_pub=state.get("client_pub"))
    if record is None:
        record = get_or_create_record(
            state.get("client_pub", ""),
            state.get("api", ""),
            None,
        )
    return record


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


def comment_subject(record, post_id):
    return {
        "a": record.get("account_id", ""),
        "t": "Message",
        "id": b64e(post_id.encode("utf-8")),
    }


def community_info(community):
    return {
        "cid": {
            "ct": "Managed",
            "cid": community["community_id"],
            "p": "Android",
        },
        "n": community["name"],
        "i": community.get("icon") or AVATAR_BLOB_URL,
        "ll": [],
        "sq": False,
    }


def community_ee(community, account_id=None):
    members = DB.list_members(community["community_id"])
    admins = [
        member["account_id"]
        for member in members
        if member.get("role") in ("owner", "admin")
    ]
    owner_id = community.get("owner_account_id")
    if owner_id and owner_id not in admins:
        admins.append(owner_id)
    if not admins and account_id:
        admins.append(account_id)
    return {
        "cci": {
            "ct": "Managed",
            "cid": community["community_id"],
            "p": "Android",
        },
        "c": len(members),
        "p": 0,
        "l": 0,
        "im": False,
        "m": {
            "dn": community["name"],
            "ci": community.get("icon") or AVATAR_BLOB_URL,
            "b": community.get("cover") or COVER_BLOB_URL,
            "d": community.get("description") or "",
            "al": admins,
        },
        "t": int(time.time() * 1000),
    }


def channel_eo(channel):
    return {"a": channel["channel_id"], "k": channel["key_b64"]}


def channel_io(channel, community):
    members = DB.count_members(community["community_id"])
    return {
        "f": channel_eo(channel),
        "n": channel["name"],
        "ci": community_info(community),
        "mc": max(1, members),
        "td": channel.get("description") or "",
    }


def channel_feed(channel, community):
    members = DB.count_members(community["community_id"])
    return {
        "f": channel_eo(channel),
        "n": channel["name"],
        "a": "Yes",
        "mc": max(1, members),
        "fc": community_info(community),
        "lrt": int(time.time() * 1000),
        "ibt": "CommunityFeedChannels",
    }


def make_feed_post(post, author, viewer_account_id=None):
    post_id = post["post_id"]
    liked = (
        DB.is_liked(post_id, viewer_account_id)
        if viewer_account_id
        else False
    )
    like_count = DB.count_likes(post_id)
    comment_count = DB.count_comments(post_id)
    omlet_id = author.get("omlet_id", "omletplayer")
    return {
        "i": post_id,
        "a": profile_about(author),
        "P": {
            "m": {
                "u": post["title"],
                "t": post["title"],
                "d": post.get("description") or "",
                "P": "https://omlet.gg",
                "Q": post["title"],
                "U": post["title"],
                "oi": {"p": omlet_id, "t": "omlet"},
                "un": omlet_id,
                "id": {
                    "a": author.get("account_id", ""),
                    "t": "Message",
                    "id": b64e(post_id.encode("utf-8")),
                },
                "usr": {
                    "a": author.get("account_id", ""),
                    "n": omlet_id,
                    "p": AVATAR_BLOB_URL,
                    "vfs": [],
                },
                "gn": [],
                "gi": [],
                "g": [],
                "ct": post["created_ms"],
                "cc": comment_count,
                "l": like_count,
                "yl": liked,
                "vd": False,
            }
        },
        "ls": {"t": str(post["created_ms"])},
        "ofc": 0,
    }


def comment_payload(row):
    author = find_account(account_id=row["author_account_id"])
    if author is None:
        author = DB.ensure_account(
            row["author_account_id"],
            row.get("author_omlet_id") or "omletplayer",
        )
    return {
        "i": row["comment_id"],
        "T": "TEXT",
        "b": b64e(row["text"].encode("utf-8")),
        "t": row["created_ms"],
        "u": comment_author(author),
        "p": comment_subject(author, row["post_id"]),
    }


def channel_message_payload(row, channel):
    body = json.dumps(
        {"text": row["text"], "profileVersion": 0},
        ensure_ascii=False,
    ).encode("utf-8")
    return {
        "i": {"t": "text", "i": row["message_id"]},
        "t": row["created_us"],
        "s": row["author_account_id"],
        "b": b64e(body),
        "f": channel_eo(channel),
        "d": False,
        "rn": row["created_us"],
    }


def post_id_from_subject(subject):
    if isinstance(subject, dict):
        raw = subject.get("id")
        if isinstance(raw, str) and raw:
            try:
                decoded = b64d(raw).decode("utf-8", "replace")
            except Exception:
                decoded = ""
            for candidate in (decoded, raw):
                if candidate and DB.get_post(candidate):
                    return candidate
    posts = DB.list_posts(limit=1)
    return posts[0]["post_id"] if posts else LOCAL_POST_ID


def community_id_from_request(req):
    if isinstance(req, dict):
        cid = req.get("cid")
        if isinstance(cid, dict):
            value = cid.get("cid") or cid.get("a")
            if isinstance(value, str) and value:
                return value
        value = req.get("ci") or req.get("c")
        if isinstance(value, str) and value:
            return value
    return LOCAL_COMMUNITY_ID


def channel_id_from_request(req):
    if isinstance(req, dict):
        value = req.get("a") or req.get("i")
        if isinstance(value, str) and value:
            return value
    return LOCAL_CHANNEL_ID


def ensure_seed_post(record):
    posts = DB.list_posts(limit=1)
    if posts:
        return posts[0]
    DB.ensure_post(
        LOCAL_POST_ID,
        record["account_id"],
        "Hello from the local Omlet server!",
        "Posted via the local server",
    )
    return DB.get_post(LOCAL_POST_ID)


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
                    response["a"] = {"a": session_z(record)}
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
            elif isinstance(q.get("a"), dict) and "cis" in q["a"]:
                response["a"] = {"cis": {"s": "Success"}}
                LOG.info(
                    "CHECK_IDENTITY path=%s %s",
                    path,
                    json.dumps(q["a"]["cis"])[:500],
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
                keys = list(q["w"].keys())
                record = current_record(state)
                value = (
                    DB.count_posts_by_author(record["account_id"])
                    if "guwc" in keys
                    else 0
                )
                response["="] = {"v": value}
                LOG.info(
                    "COUNT path=%s keys=%s value=%s",
                    path,
                    keys,
                    value,
                )
            elif isinstance(q.get("w"), dict) and "gcvv" in q["w"]:
                request = q["w"]["gcvv"] or {}
                post_id = post_id_from_subject(
                    request.get("id") if isinstance(request, dict) else None
                )
                comments = DB.list_comments(post_id)
                response["w"] = {
                    "gcvv": {"C": [comment_payload(row) for row in comments]}
                }
                LOG.info(
                    "COMMENTS_LIST path=%s post=%s count=%d",
                    path,
                    post_id,
                    len(comments),
                )
            elif isinstance(q.get("w"), dict) and "ac" in q["w"]:
                add_req = q["w"]["ac"] or {}
                text = ""
                if isinstance(add_req, dict):
                    raw_text = add_req.get("b")
                    if raw_text:
                        text = b64d(raw_text).decode("utf-8", "replace")
                    post_id = post_id_from_subject(add_req.get("id"))
                else:
                    post_id = LOCAL_POST_ID
                record = current_record(state)
                comment = DB.add_comment(
                    post_id,
                    record["account_id"],
                    text,
                    client_id=(
                        add_req.get("i")
                        if isinstance(add_req, dict)
                        else None
                    ),
                )
                response["="] = {"v": True}
                LOG.info(
                    "COMMENT_ADD path=%s post=%s text=%r count=%d",
                    path,
                    post_id,
                    text,
                    DB.count_comments(post_id),
                )
            elif isinstance(q.get("w"), dict) and "l" in q["w"]:
                like_req = q["w"]["l"] or {}
                liked = (
                    bool(like_req.get("l", False))
                    if isinstance(like_req, dict)
                    else False
                )
                subject = like_req.get("ud") if isinstance(like_req, dict) else None
                post_id = post_id_from_subject(subject)
                record = current_record(state)
                count = DB.set_like(
                    post_id,
                    record["account_id"],
                    liked,
                )
                response["="] = {"v": True}
                LOG.info(
                    "LIKE path=%s post=%s liked=%s count=%s",
                    path,
                    post_id,
                    liked,
                    count,
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
                channel_id = channel_id_from_request(op.get("f"))
                if message_type == "text" and raw_body:
                    record = current_record(state)
                    text = ""
                    try:
                        text = json.loads(b64d(raw_body)).get("text", "")
                    except Exception:
                        pass
                    DB.add_message(
                        channel_id,
                        record["account_id"],
                        text,
                        message_id=(
                            message_id.get("i")
                            if isinstance(message_id, dict)
                            else None
                        ),
                        client_id=(
                            message_id.get("i")
                            if isinstance(message_id, dict)
                            else None
                        ),
                    )
                    LOG.info(
                        "CHANNEL_SEND path=%s channel=%s type=%s text=%r count=%d",
                        path,
                        channel_id,
                        message_type,
                        text,
                        DB.count_messages(channel_id),
                    )
                else:
                    LOG.info(
                        "CHANNEL_ACTIVITY path=%s type=%s",
                        path,
                        message_type,
                    )
                response["="] = {"v": True}
            elif isinstance(q.get("m"), dict) and "gmfc" in q["m"]:
                record = current_record(state)
                request = q["m"]["gmfc"] or {}
                channel_id = channel_id_from_request(
                    request.get("f") if isinstance(request, dict) else None
                )
                channel = DB.get_channel(channel_id)
                if channel is None:
                    channel = DB.get_channel(LOCAL_CHANNEL_ID)
                if channel is None:
                    community = DB.get_community(LOCAL_COMMUNITY_ID)
                    if community is None:
                        community = DB.insert_community(
                            LOCAL_COMMUNITY_ID,
                            "Comunidade Local",
                            "Comunidade local de testes",
                            AVATAR_BLOB_URL,
                            COVER_BLOB_URL,
                            record["account_id"],
                        )
                    channel = DB.insert_channel(
                        LOCAL_CHANNEL_ID,
                        community["community_id"],
                        "geral",
                        "Canal de texto da comunidade",
                        LOCAL_CHANNEL_KEY,
                    )
                community = DB.get_community(channel["community_id"])
                if community is None:
                    community = DB.get_community(LOCAL_COMMUNITY_ID)
                messages = DB.list_messages(channel["channel_id"])
                if not messages:
                    DB.add_message(
                        channel["channel_id"],
                        record["account_id"],
                        "Bem-vindo ao canal geral da Comunidade Local!",
                    )
                    messages = DB.list_messages(channel["channel_id"])
                senders = {}
                for message in messages:
                    sender = find_account(
                        account_id=message["author_account_id"]
                    )
                    if sender is None:
                        sender = DB.ensure_account(
                            message["author_account_id"],
                            message.get("author_omlet_id") or "omletplayer",
                        )
                    senders[sender["account_id"]] = comment_author(sender)
                response["m"] = {
                    "wd": {
                        "c": [
                            channel_message_payload(message, channel)
                            for message in messages
                        ],
                        "p": False,
                        "s": senders,
                        "fd": channel_feed(channel, community),
                    }
                }
                LOG.info(
                    "CHANNEL_MESSAGES path=%s channel=%s count=%d",
                    path,
                    channel["channel_id"],
                    len(messages),
                )
            elif isinstance(q.get("i"), dict) and "f" in q["i"]:
                feed_req = q["i"].get("f")
                item_type = (
                    feed_req.get("ibt") if isinstance(feed_req, dict) else None
                )
                if item_type == "CommunityFeedChannels":
                    record = current_record(state)
                    channels = DB.list_channels(account_id=record["account_id"])
                    if not channels:
                        channels = DB.list_channels()
                    feeds = []
                    for channel in channels:
                        community = DB.get_community(channel["community_id"])
                        if community is not None:
                            feeds.append(channel_feed(channel, community))
                    response["i"] = {"f": {"f": feeds}}
                    LOG.info("CHANNELS path=%s count=%d", path, len(feeds))
                else:
                    response["i"] = {"f": {"f": []}}
                    LOG.info(
                        "FEED_DETAILS path=%s ibt=%s count=0",
                        path,
                        item_type,
                    )
            elif isinstance(q.get("w"), dict) and any(
                key in q["w"] for key in ("grp", "gtp", "grgw")
            ):
                record = current_record(state)
                posts = DB.list_posts()
                if not posts:
                    posts = [ensure_seed_post(record)]
                response["w"] = {
                    "w": {
                        "w": {
                            "p": [
                                make_feed_post(post, find_account(account_id=post["author_account_id"]) or record, record["account_id"])["P"]
                                for post in posts
                            ]
                        }
                    }
                }
                LOG.info(
                    "COMMUNITY_POSTS path=%s keys=%s count=%d",
                    path,
                    list(q["w"].keys()),
                    len(posts),
                )
            elif isinstance(q.get("w"), dict) and "gcfr" in q["w"]:
                record = current_record(state)
                communities = DB.list_communities(account_id=record["account_id"])
                if not communities:
                    communities = DB.list_communities()
                posts = DB.list_posts()
                if not posts:
                    posts = [ensure_seed_post(record)]
                header = {
                    "i": "my-communities",
                    "c": [
                        community_ee(community, record["account_id"])
                        for community in communities
                    ],
                }
                feed_posts = [
                    make_feed_post(
                        post,
                        find_account(account_id=post["author_account_id"]) or record,
                        record["account_id"],
                    )
                    for post in posts
                ]
                response["w"] = {"ghp": {"p": [header] + feed_posts}}
                LOG.info(
                    "COMMUNITY_FEED path=%s communities=%d posts=%d",
                    path,
                    len(communities),
                    len(feed_posts),
                )
            elif isinstance(q.get("w"), dict) and "licu" in q["w"]:
                record = current_record(state)
                communities = DB.list_communities(account_id=record["account_id"])
                items = [
                    {
                        "p": {
                            "ct": "Managed",
                            "cid": community["community_id"],
                            "p": "Android",
                        },
                        "cic": community_ee(
                            community,
                            record["account_id"],
                        ),
                    }
                    for community in communities
                ]
                response["w"] = {"gcm": {"c": items, "p": len(items)}}
                LOG.info("COMMUNITIES path=%s count=%d", path, len(items))
            elif isinstance(q.get("w"), dict) and "ut" in q["w"]:
                response["w"] = {
                    "ut": {"ut": {"a": True, "l": AVATAR_BLOB_URL}}
                }
                LOG.info("BLOB_UPLOAD path=%s category=w", path)
            elif isinstance(q.get("w"), dict) and "lrcmc" in q["w"]:
                record = current_record(state)
                communities = DB.list_communities()
                response["w"] = {
                    "lrcmc": {
                        "cic": [
                            community_ee(community, record["account_id"])
                            for community in communities
                        ]
                    }
                }
                LOG.info(
                    "BROWSE_COMMUNITIES path=%s count=%d",
                    path,
                    len(communities),
                )
            elif isinstance(q.get("w"), dict) and "cmc" in q["w"]:
                create_req = q["w"]["cmc"] or {}
                record = current_record(state)
                name = "Comunidade Local"
                description = "Comunidade local de testes"
                icon = AVATAR_BLOB_URL
                cover = COVER_BLOB_URL
                if isinstance(create_req, dict):
                    requested_name = create_req.get("n")
                    if isinstance(requested_name, str) and requested_name.strip():
                        name = requested_name.strip()[:50]
                    requested_description = create_req.get("d")
                    if (
                        isinstance(requested_description, str)
                        and requested_description.strip()
                    ):
                        description = requested_description.strip()[:1500]
                    requested_icon = create_req.get("i")
                    if isinstance(requested_icon, str) and requested_icon:
                        icon = requested_icon
                    requested_cover = create_req.get("b")
                    if isinstance(requested_cover, str) and requested_cover:
                        cover = requested_cover
                community = DB.create_community(
                    name,
                    description,
                    icon,
                    cover,
                    record["account_id"],
                )
                DB.create_channel(
                    community["community_id"],
                    "geral",
                    "Canal de texto da comunidade",
                )
                response["w"] = {
                    "cmc": {
                        "cic": community_ee(
                            community,
                            record["account_id"],
                        )
                    }
                }
                LOG.info(
                    "CREATE_COMMUNITY path=%s id=%s name=%r",
                    path,
                    community["community_id"],
                    name,
                )
            elif isinstance(q.get("w"), dict) and "lmcf" in q["w"]:
                request = q["w"]["lmcf"] or {}
                community_id = community_id_from_request(request)
                channels = DB.list_channels(community_id=community_id)
                community = DB.get_community(community_id)
                feeds = []
                if community is not None:
                    feeds = [
                        channel_io(channel, community)
                        for channel in channels
                    ]
                response["w"] = {"lmcf": {"df": [], "f": feeds}}
                LOG.info(
                    "COMMUNITY_CHANNELS path=%s community=%s count=%d",
                    path,
                    community_id,
                    len(feeds),
                )
            elif isinstance(q.get("w"), dict) and "lmmc" in q["w"]:
                request = q["w"]["lmmc"] or {}
                community_id = community_id_from_request(request)
                record = current_record(state)
                members = DB.list_members(community_id)
                if not members:
                    DB.add_member(
                        community_id,
                        record["account_id"],
                        "owner",
                    )
                    members = DB.list_members(community_id)
                response["w"] = {
                    "lmmc": {
                        "f": [
                            {
                                "a": member["account_id"],
                                "n": member.get("omlet_id", "omletplayer"),
                                "p": AVATAR_BLOB_URL,
                                "vfs": [],
                                "fs": member.get("role") in ("owner", "admin"),
                            }
                            for member in members
                        ]
                    }
                }
                LOG.info(
                    "COMMUNITY_MEMBERS path=%s community=%s count=%d",
                    path,
                    community_id,
                    len(members),
                )
            elif isinstance(q.get("w"), dict) and "ghp" in q["w"]:
                record = current_record(state)
                posts = DB.list_posts()
                if not posts:
                    posts = [ensure_seed_post(record)]
                feed_posts = [
                    make_feed_post(
                        post,
                        find_account(account_id=post["author_account_id"]) or record,
                        record["account_id"],
                    )
                    for post in posts
                ]
                response["w"] = {"ghp": {"p": feed_posts}}
                LOG.info(
                    "FEED path=%s posts=%d",
                    path,
                    len(feed_posts),
                )
            elif isinstance(q.get("p"), dict) and "sab" in q["p"]:
                response["="] = {"v": True}
                LOG.info("SET_BIRTHDAY path=%s", path)
            elif isinstance(q.get("p"), dict) and "spgr" in q["p"]:
                response["="] = {"v": True}
                LOG.info("SET_GENDER path=%s", path)
            elif isinstance(q.get("p"), dict) and "gui" in q["p"]:
                response["p"] = {"gui": {"ii": {}}}
                LOG.info("SHARDS path=%s", path)
            elif isinstance(q.get("ca"), dict) and "g" in q["ca"]:
                response["ca"] = {
                    "g": {"d": [], "l": [], "m": [], "u": [], "w": []}
                }
                LOG.info("TOP_SUPPORTERS path=%s", path)
            elif isinstance(q.get("b"), dict) and "ut" in q["b"]:
                response["b"] = {
                    "ut": {"ut": {"a": True, "l": AVATAR_BLOB_URL}}
                }
                LOG.info("BLOB_UPLOAD path=%s category=b", path)
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
    DB.initialize()
    DB.migrate_json(
        ACCOUNTS_PATH,
        STATE_PATH,
        LOCAL_POST_ID,
        LOCAL_COMMUNITY_ID,
        LOCAL_CHANNEL_ID,
        LOCAL_CHANNEL_KEY,
        "Hello from the local Omlet server!",
        "Posted via the local server",
    )
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
        LOG.info("database: %s", DB_PATH)
        LOG.info("accounts loaded: %d", DB.count_accounts())
        LOG.info("posts loaded: %d", len(DB.list_posts(limit=1000)))
        LOG.info("communities loaded: %d", len(DB.list_communities()))
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
