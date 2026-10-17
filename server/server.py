import asyncio
import base64
import gzip
import hashlib
import json
import logging
import os
import sys
import time
import uuid

import websockets
from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)

BASE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE, "keys.json"), "r", encoding="utf-8") as fh:
    KEYS = json.load(fh)

SERVER_PRIVATE = X25519PrivateKey.from_private_bytes(
    base64.b64decode(KEYS["private_b64"])
)
SERVER_PUBLIC_B64 = KEYS["public_b64"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
    force=True,
)
LOG = logging.getLogger("omlet")


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
            elif isinstance(q.get("a"), dict) and "ci" in q["a"]:
                LOG.info("CHECK_ID path=%s %s", path, json.dumps(q["a"]["ci"])[:2000])
                response["="] = {"v": True}
            elif isinstance(q.get("a"), dict) and "sc" in q["a"]:
                sc = q["a"]["sc"]
                omlet_id = sc.get("s") or "omletplayer"
                account_id = sc.get("a") or uuid.uuid4().hex
                scopes = sc.get("S") or ["PublicProfile", "Arcade"]
                seed = (
                    state.get("client_pub", "")
                    + state.get("api", "")
                    + "appid"
                ).encode()
                app_id = hashlib.sha256(seed).digest()
                now = int(time.time() * 1000)
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
                response["a"] = {"sc": {"s": "GUEST", "a": account}}
                LOG.info(
                    "CREATE_ACCOUNT path=%s account=%s omlet_id=%s scopes=%s",
                    path,
                    account_id,
                    omlet_id,
                    scopes,
                )
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
    except Exception as exc:
        LOG.exception("handler error path=%s", path)


async def main():
    async with websockets.serve(
        handler,
        "0.0.0.0",
        8080,
        max_size=None,
        compression=None,
    ):
        LOG.info("Omlet local server listening on 0.0.0.0:8080")
        LOG.info("server public key: %s", SERVER_PUBLIC_B64)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
