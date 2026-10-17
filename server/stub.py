import asyncio
import gzip
import logging
import sys

import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
    force=True,
)
LOG = logging.getLogger("stub")


def safe_decode(data):
    if isinstance(data, str):
        return data
    if isinstance(data, (bytes, bytearray)):
        raw = bytes(data)
        try:
            return gzip.decompress(raw).decode("utf-8", "replace")
        except Exception:
            pass
        try:
            return raw.decode("utf-8", "replace")
        except Exception:
            return raw.hex()
    return repr(data)


async def handler(ws, *args):
    path = None
    try:
        path = ws.request.path
    except Exception:
        path = args[0] if args else None

    headers = {}
    try:
        headers = dict(ws.request.headers)
    except Exception:
        pass

    LOG.info("CONNECT path=%r headers=%s", path, headers)
    try:
        async for msg in ws:
            LOG.info(
                "MSG path=%r len=%d data=%s",
                path,
                len(msg),
                safe_decode(msg)[:4000],
            )
    except Exception as exc:
        LOG.info("DISCONNECT path=%r err=%r", path, exc)


async def main():
    async with websockets.serve(handler, "0.0.0.0", 8080, max_size=None):
        LOG.info("stub listening on 0.0.0.0:8080")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
