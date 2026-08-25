#!/usr/bin/env python3
"""Demo 1 driver: sign a local token, ask about an image, report the number.

Self-contained — no Hub, no device, no network beyond localhost. The Hub is
"faked" by generating a keypair here and signing with it; `runtime/auth.py` is
untouched, because verification never cared who signed.

Usage:
    uv run python scripts/demo_look.py --image samples/note.jpg \
        --question "这上面写的什么？" [--repeat 5] [--allow-egress]

Prints per-run latency and a p50/p95 summary. On a Pi that summary is the P0
criterion; on a dev laptop it is not evidence of anything.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

AUDIENCE = "eidolon_vision"


def _keypair(key_file: Path) -> tuple[str, str]:
    """Load, or create and persist, the demo signing key.

    Persisted because the server needs the public half at startup and the client
    needs the private half per request — a fresh key each run would fail to
    verify, which is the correct behaviour and a useless demo.
    """
    if key_file.is_file():
        key = serialization.load_pem_private_key(key_file.read_bytes(), password=None)
    else:
        key = ed25519.Ed25519PrivateKey.generate()
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        key_file.chmod(0o600)

    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def issue_token(
    *, key_file: Path, device_id: str, owner_id: str, triggers: list[str], ttl_s: int = 600
):
    """Stand in for the Hub. Returns (token, public_key_pem)."""
    private_pem, public_pem = _keypair(key_file)
    token = jwt.encode(
        {
            "sub": device_id,
            "owner": owner_id,
            "aud": AUDIENCE,
            "triggers": triggers,
            "exp": int(time.time()) + ttl_s,
        },
        private_pem,
        algorithm="EdDSA",
    )
    return token, public_pem


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, type=Path)
    ap.add_argument("--question", default="这上面写的什么？")
    ap.add_argument("--base-url", default="http://127.0.0.1:18085")
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--allow-egress", action="store_true")
    ap.add_argument("--print-key", action="store_true", help="emit the PEM the server needs")
    ap.add_argument("--key-file", type=Path, default=Path("var/demo_signing_key.pem"))
    args = ap.parse_args()

    token, public_pem = issue_token(
        key_file=args.key_file,
        device_id="demo-device",
        owner_id="demo-owner",
        triggers=["user_look", "presence_sample", "fatigue_sample"],
    )
    if args.print_key:
        print(public_pem)
        return 0

    if not args.image.is_file():
        print(f"no such image: {args.image}", file=sys.stderr)
        return 2
    payload = args.image.read_bytes()

    latencies: list[float] = []
    with httpx.Client(base_url=args.base_url, timeout=120.0) as client:
        for i in range(args.repeat):
            started = time.perf_counter()
            resp = client.post(
                "/v1/look",
                headers={"Authorization": f"Bearer {token}"},
                data={
                    "question": args.question,
                    "correlation_id": f"demo-{i}",
                    "allow_egress": str(args.allow_egress).lower(),
                },
                files={"image": (args.image.name, payload, "image/jpeg")},
            )
            wall = (time.perf_counter() - started) * 1000
            if resp.status_code == 428:
                print(f"[{i}] egress refused (expected without --allow-egress)")
                continue
            if resp.status_code != 200:
                print(f"[{i}] HTTP {resp.status_code}: {resp.text}", file=sys.stderr)
                continue
            body = resp.json()
            latencies.append(wall)
            print(
                f"[{i}] {wall:7.0f}ms wall  engine={body['engine']}  "
                f"egress={body['egress']}\n     {body['answer'][:160]!r}"
            )

    if latencies:
        print(
            f"\nn={len(latencies)}  p50={statistics.median(latencies):.0f}ms  "
            f"max={max(latencies):.0f}ms  "
            f"(P0 criterion: p50 < 3000ms, measured on the host that ships)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
