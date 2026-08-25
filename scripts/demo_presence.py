#!/usr/bin/env python3
"""Demo 2 driver: prove the role indirection actually decouples anything.

Posts the same `presence_sample` bursts against the same capability twice, once
with the judgement coming off the device and once computed on the host. The
capability, its aggregator, its thresholds and the fact it emits are identical
in both runs — only one line of `bootstrap.py` differs, selected by config.

    uv run python scripts/demo_presence.py --mode device
    uv run python scripts/demo_presence.py --mode host
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from demo_look import issue_token


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["device", "host"], required=True)
    ap.add_argument("--base-url", default="http://127.0.0.1:18085")
    ap.add_argument("--key-file", type=Path, default=Path("var/demo_signing_key.pem"))
    ap.add_argument("--samples", type=Path, default=Path("samples"))
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--gap-ms", type=int, default=800)
    args = ap.parse_args()

    token, _ = issue_token(
        key_file=args.key_file,
        device_id="demo-device",
        owner_id="demo-owner",
        triggers=["presence_sample"],
    )

    # The only difference between the two runs: where the judgement comes from.
    # Device mode sends a scalar and no pixels at all.
    if args.mode == "device":
        files = []
        signals = '{"person_score": 1.0}'
    else:
        files = [
            ("frames", (p.name, p.read_bytes(), "image/jpeg"))
            for p in (args.samples / "presence_a.jpg", args.samples / "presence_b.jpg")
        ]
        signals = "{}"

    with httpx.Client(base_url=args.base_url, timeout=60.0) as client:
        health = client.get("/healthz").json()
        print(f"  roles_bound={health['roles_bound']}  (mode={args.mode})")
        for i in range(args.rounds):
            now = int(time.time() * 1000)
            resp = client.post(
                "/v1/burst",
                headers={"Authorization": f"Bearer {token}"},
                data={
                    "trigger": "presence_sample",
                    "correlation_id": f"presence-{args.mode}-{i}",
                    "epoch": 1,
                    "ts_ms": now,
                    "device_signals": signals,
                },
                files=files,
            )
            if resp.status_code != 202:
                print(f"  [{i}] HTTP {resp.status_code}: {resp.text}")
                return 1
            body = resp.json()
            print(f"  [{i}] frames={body['frames']}  facts={body['facts']}")
            time.sleep(args.gap_ms / 1000)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
