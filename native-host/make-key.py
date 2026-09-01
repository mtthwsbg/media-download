r"""
make-key.py - gives the extension a permanent ID. Run once, ever.

Normally Chrome invents an extension's ID from the folder it was loaded from,
so the ID is different on every machine and in every folder - which is why the
first version of install.ps1 had to ask for it. Putting a public key in
manifest.json instead makes Chrome derive the ID from the key, so it is the
same ID for everybody, forever, and the installer can just know it.

Writes the key into chrome-extension/manifest.json and prints the ID.
The matching private key is only needed to publish a packed .crx; it is saved
next to this file and is not shipped to anyone.

    ..\.venv\Scripts\python.exe make-key.py
"""

import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

HERE = Path(__file__).resolve().parent
MANIFEST = HERE.parent / "chrome-extension" / "manifest.json"
PRIVATE_KEY = HERE / "extension-private-key.pem"


def extension_id(der_public_key):
    """Chrome's rule: sha256 the key, take 16 bytes, and map 0-f onto a-p."""
    digest = hashlib.sha256(der_public_key).digest()[:16]
    return "".join("abcdefghijklmnop"[byte >> 4] + "abcdefghijklmnop"[byte & 15] for byte in digest)


def main():
    if PRIVATE_KEY.exists():
        # Never silently mint a new key: it would change the ID and break every
        # install that already exists, including everyone you shared the zip with.
        print(f"A key already exists at {PRIVATE_KEY} - reusing it.")
        private = serialization.load_pem_private_key(PRIVATE_KEY.read_bytes(), password=None)
    else:
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        PRIVATE_KEY.write_bytes(
            private.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        print(f"New private key written to {PRIVATE_KEY} (keep it, don't share it)")

    der = private.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["key"] = base64.b64encode(der).decode("ascii")
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"manifest.json updated")
    print(f"EXTENSION_ID={extension_id(der)}")


if __name__ == "__main__":
    main()
