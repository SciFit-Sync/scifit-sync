#!/usr/bin/env python3
"""WorkoutX API 실측 프로브 + 원본 캐시.

server/.env의 WORKOUTX_API_KEY로 전체 운동을 받아:
  1) 원본 JSON 캐시  → docs/handoff/workoutx-raw/exercises.json
  2) 분포 요약(bodyPart/target/equipment/secondaryMuscles + 필드 존재율) 출력
  3) 분포 CSV       → docs/handoff/workoutx-raw/distributions.csv

API 키는 인증에만 사용하며 출력에 노출하지 않는다.
실행: python3 docs/handoff/workoutx-raw/probe_workoutx.py
"""

import collections
import csv
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ENV = REPO / "server" / ".env"
OUT = Path(__file__).resolve().parent
BASE = "https://api.workoutxapp.com/v1"
PAGE = 100


def load_env(p: Path) -> dict:
    d = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def main() -> int:
    if not ENV.exists():
        print(f"[ERR] {ENV} 없음", file=sys.stderr)
        return 1
    key = load_env(ENV).get("WORKOUTX_API_KEY", "")
    if not key:
        print("[ERR] WORKOUTX_API_KEY 미설정 (server/.env)", file=sys.stderr)
        return 1

    items: list[dict] = []
    offset = 0
    while True:
        url = f"{BASE}/exercises?limit={PAGE}&offset={offset}"
        req = urllib.request.Request(url, headers={"X-WorkoutX-Key": key})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"[ERR] fetch offset={offset}: {type(e).__name__} {str(e)[:160]}", file=sys.stderr)
            return 1
        batch = data.get("data") if isinstance(data, dict) else data
        if not isinstance(batch, list) or not batch:
            break
        items.extend(batch)
        if len(batch) < PAGE:
            break
        offset += PAGE

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "exercises.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"총 {len(items)}개 운동 → exercises.json 캐시")

    def dist(field: str, nested: bool = False) -> collections.Counter:
        c: collections.Counter = collections.Counter()
        for ex in items:
            v = ex.get(field)
            if nested and isinstance(v, list):
                for x in v:
                    c[x] += 1
            else:
                c[v] += 1
        return c

    rows_csv: list[tuple] = []
    for field, nested in [("bodyPart", False), ("target", False), ("equipment", False), ("secondaryMuscles", True)]:
        c = dist(field, nested)
        print(f"\n=== {field} ({len(c)}종) ===")
        for k, n in c.most_common():
            print(f"  {str(k):44s}{n}")
            rows_csv.append((field, k, n))

    keys = collections.Counter()
    for ex in items:
        for k in ex:
            keys[k] += 1
    print(f"\n=== 필드 존재율 (총 {len(items)}) ===")
    for k, n in keys.most_common():
        flag = "" if n == len(items) else "  ← 일부 누락"
        print(f"  {k:24s}{n}{flag}")

    with (OUT / "distributions.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["field", "value", "count"])
        w.writerows(rows_csv)
    print("\ndistributions.csv 저장 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
