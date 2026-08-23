#!/usr/bin/env python3
"""Demo 3: the decoupling criterion, executed.

Moves each capability package aside in turn, reruns the suite, and puts it back.
A capability that cannot be removed without breaking something else is not a
capability — it is a load-bearing part of the framework wearing a directory.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

CAPS = Path("eidolon_vision/capabilities")


def run_suite() -> str:
    out = subprocess.run(
        ["uv", "run", "pytest", "-q"], capture_output=True, text=True, check=False
    )
    tail = [ln for ln in out.stdout.splitlines() if re.search(r"passed|failed|error", ln)]
    return tail[-1] if tail else "(no summary)"


def main() -> int:
    names = sorted(p.name for p in CAPS.iterdir() if p.is_dir() and not p.name.startswith("_"))
    print(f"  基线（{len(names)} 个能力：{', '.join(names)}）")
    print(f"    -> {run_suite()}")

    with tempfile.TemporaryDirectory() as tmp:
        removed = []
        for name in names:
            src = CAPS / name
            if not src.is_dir():
                continue
            shutil.move(str(src), str(Path(tmp) / name))
            removed.append(name)
            print(f"  rm -rf capabilities/{name}/")
            print(f"    -> {run_suite()}")
        for name in removed:
            shutil.move(str(Path(tmp) / name), str(CAPS / name))

    print("  全部恢复")
    print(f"    -> {run_suite()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
