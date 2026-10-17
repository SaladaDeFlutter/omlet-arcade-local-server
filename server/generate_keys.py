#!/usr/bin/env python3
"""Generate the local server X25519 keypair used by the Omlet test server.

The private key is written to server/keys.json and must never be committed.
The public key is the one patched into the APK by scripts/patch-apk.sh.
"""

import argparse
import base64
import json
import os
import sys

from cryptography.hazmat.primitives import serialization as ser
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "keys.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing keys.json",
    )
    args = parser.parse_args()

    if os.path.exists(OUT) and not args.force:
        print(f"{OUT} already exists; use --force to overwrite.", file=sys.stderr)
        return 1

    private_key = X25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        ser.Encoding.Raw, ser.PrivateFormat.Raw, ser.NoEncryption()
    )
    public_bytes = private_key.public_key().public_bytes(
        ser.Encoding.Raw, ser.PublicFormat.Raw
    )

    data = {
        "private_b64": base64.b64encode(private_bytes).decode("ascii"),
        "public_b64": base64.b64encode(public_bytes).decode("ascii"),
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")

    print(f"Wrote {OUT}")
    print(f"Public key: {data['public_b64']}")
    print("")
    print("Keep the private key secret. Next step:")
    print("  scripts/patch-apk.sh /path/to/omlet-arcade.apk")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
