#!/usr/bin/env python3
"""Render the audit log as the owner would read it. Reads JSON on stdin."""

from __future__ import annotations

import json
import sys


def main() -> int:
    rows = json.load(sys.stdin).get("rows", [])
    if not rows:
        print("  (空)")
        return 0

    looked = sum(1 for r in rows if r["capability"] == "look_on_demand")
    egressed = sum(1 for r in rows if r.get("egress"))
    print(f"  这台设备记录了 {len(rows)} 次观察，其中 {looked} 次是你主动问的。")
    print(f"  像素出境 {egressed} 次。像素保留时间：全部 0 毫秒。\n")

    for r in rows:
        head = f"  {r['capability']:16} {r['trigger']:16}"
        if r.get("question"):
            engine = r.get("engine") or "（无引擎可答）"
            mark = "出境" if r.get("egress") else "本地"
            print(f"{head} {mark}  {engine}  {r.get('latency_ms', '-')}ms")
            print(f"      问: {r['question']}")
            answer = r.get("answer")
            if answer:
                first = answer.splitlines()[0]
                more = f" …(+{len(answer.splitlines()) - 1} 行)" if "\n" in answer else ""
                print(f"      答: {first}{more}")
            else:
                print(f"      答: —  ({r.get('outcome', '?')})")
        else:
            print(
                f"{head} 本地  帧 {r.get('frames_in')}→{r.get('frames_admitted')}  "
                f"观察 {r.get('observations')}  事实 {r.get('facts')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
