"""exercise_equipment junction 생성기 (Phase 7, D12/D14) — 개발 보조.

machine/cable load_mode 운동을 실물 기구(reseed_equipments)에 매핑한다.
근육 활성도는 운동 기준(exercise_muscles)이라 junction 과 무관 — junction 은 오직
"가용성(이 gym 에서 이 운동 가능?) + 중량계산(기구 pulley/bar)" 만 담당한다.

매핑 규칙 (결정론):
  1. smith machine 운동 → Smith 실물(f6fe186b) 직결. Smith 는 범용 바벨 가이드라 모든
     부위 운동 가능 → category 매핑 부적합, equipment 직결이 정확.
  2. cable 운동 → 실물 Cable 전체(category 무관, 케이블은 다부위 가능).
  3. 나머지 machine(leverage/sled/assisted/hammer/tire) → bodyPart→category 매핑 후
     동작 키워드(press/row/curl/...)가 일치하는 같은 category 머신에 매핑(confidence 0.9).
  4. 동작 매칭 실패 → LLM 정밀화 대상으로 분리(gen_junction_unmatched.csv).
  5. cardio bodyPart → skip(머신 category 없음, 근육/중량 무의미).

출력:
  - server/alembic/data/junction_seed.csv      : (exercise_name, equipment_id, source, confidence)
  - server/alembic/data/junction_unmatched.csv : LLM 정밀화 대상(exercise_name, bodyPart, category, action)

실행: python mlops/scripts/gen_junction_seed.py
"""

import csv
import json
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA = _ROOT / "server" / "alembic" / "data"
_EQUIP_CSV = _DATA / "reseed_equipments.csv"
_EX_JSON = _DATA / "reseed_exercises_workoutx.json"
_OUT_SEED = _DATA / "junction_seed.csv"
_OUT_UNMATCHED = _DATA / "junction_unmatched.csv"

# WorkoutX bodyPart → reseed_equipments.category (6종). cardio 는 매핑 없음.
_B2C = {
    "Chest": "chest",
    "Back": "back",
    "Shoulders": "shoulders",
    "Upper Arms": "arms",
    "Lower Arms": "arms",
    "Upper Legs": "legs",
    "Lower Legs": "legs",
    "Waist": "core",
}

# 동작 키워드(구체적 → 일반 순). 운동명·머신명 양쪽에서 동일 추출.
_ACTIONS = [
    "pulldown",
    "pushdown",
    "crossover",
    "preacher",
    "flye",
    "fly",
    "shrug",
    "kickback",
    "pullover",
    "adduction",
    "abduction",
    "calf",
    "crunch",
    "hack",
    "deadlift",
    "squat",
    "lunge",
    "row",
    "press",
    "curl",
    "extension",
    "raise",
    "dip",
    "chin",
    "pull",
]

_MACHINE_EQ = {
    "leverage machine",
    "smith machine",
    "assisted",
    "assisted (towel)",
    "sled machine",
    "hammer",
    "tire",
}
_CABLE_EQ = {"cable"}


def _action(name: str) -> str | None:
    n = (name or "").lower()
    for a in _ACTIONS:
        if a in n:
            return a
    return None


def _load_equipments() -> list[dict]:
    with open(_EQUIP_CSV, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _load_exercises() -> list[dict]:
    with open(_EX_JSON, encoding="utf-8") as f:
        data = json.load(f)
    items = data["data"] if isinstance(data, dict) and "data" in data else data
    # name_en dedup keep-last (reseed 와 동일)
    by_name = {}
    for ex in items:
        nm = (ex.get("name") or "").strip()
        if nm:
            by_name[nm] = ex
    return list(by_name.values())


def main() -> None:
    equipments = _load_equipments()

    def nm(r):
        return (r.get("name_en") or r.get("name") or "").strip()

    smith_id = next(r["id"] for r in equipments if "smith" in nm(r).lower())
    cable_ids = [r["id"] for r in equipments if r["equipment_type"] == "cable"]
    machines = [(r["id"], nm(r), r["category"]) for r in equipments if r["equipment_type"] == "machine"]

    exercises = _load_exercises()
    seed_rows: list[dict] = []
    unmatched: list[dict] = []
    seen = set()

    def emit(ex_name, eq_id, source, conf):
        key = (ex_name, eq_id)
        if key in seen:
            return
        seen.add(key)
        seed_rows.append({"exercise_name": ex_name, "equipment_id": eq_id, "source": source, "confidence": conf})

    stats = {"smith": 0, "cable": 0, "action": 0, "unmatched": 0, "cardio": 0}
    for ex in exercises:
        eqp = (ex.get("equipment") or "").strip().lower()
        name = (ex.get("name") or "").strip()
        if not name:
            continue
        if eqp in _CABLE_EQ:
            for cid in cable_ids:
                emit(name, cid, "seed", 0.70)
            stats["cable"] += 1
            continue
        if eqp not in _MACHINE_EQ:
            continue
        if eqp == "smith machine":
            emit(name, smith_id, "seed", 0.90)
            stats["smith"] += 1
            continue
        cat = _B2C.get(ex.get("bodyPart"))
        if cat is None:  # cardio
            unmatched.append({"exercise_name": name, "bodyPart": ex.get("bodyPart"), "category": "", "action": ""})
            stats["cardio"] += 1
            continue
        cands = [m for m in machines if m[2] == cat]
        act = _action(name)
        hits = [m for m in cands if act and _action(m[1]) == act]
        if hits:
            for m in hits:
                emit(name, m[0], "seed", 0.90)
            stats["action"] += 1
        else:
            unmatched.append(
                {"exercise_name": name, "bodyPart": ex.get("bodyPart"), "category": cat, "action": act or ""}
            )
            stats["unmatched"] += 1

    # ── 2차 LLM 정밀화(휴리스틱, source='gemini') — 동작매칭 실패분을 적합 머신에 매핑.
    #   근육 무관(가용성 목적)이라 부위·동작 휴리스틱으로 충분. 부하 없는 스트레치/유산소/
    #   기능성(타이어·해머)/맨몸(hanging) 은 매핑하지 않고 진짜 미매핑으로 남긴다(G4).
    machines_by_cat: dict[str, list] = defaultdict(list)
    for m in machines:
        machines_by_cat[m[2]].append(m)
    smith_m = [m for m in machines if "smith" in m[1].lower()]
    _SKIP_KW = (
        "stretch",
        "sledge hammer",
        "tire flip",
        "gripper hands",
        "cycle cross",
        "treadmill",
        "stationary bike",
        "hanging",
        "throw down",
    )
    still: list[dict] = []
    g_stats = {"calf": 0, "shrug/dl": 0, "pull/chin": 0, "dip": 0, "hip": 0, "core": 0, "skip": 0}
    for u in unmatched:
        name = u["exercise_name"]
        cat = u["category"]
        n = name.lower()
        if not cat or any(k in n for k in _SKIP_KW):
            still.append(u)
            g_stats["skip"] += 1
            continue
        targets: list = []
        if "calf" in n:
            targets = [m for m in machines_by_cat["legs"] if "leg press" in m[1].lower() or "hack" in m[1].lower()]
            g_stats["calf"] += 1
        elif "shrug" in n or "deadlift" in n or "good morning" in n:
            targets = smith_m
            g_stats["shrug/dl"] += 1
        elif "pull-up" in n or "pull up" in n or "chin" in n or (cat == "back" and "pull" in n):
            targets = [
                m for m in machines if "assist" in m[1].lower() and ("dip" in m[1].lower() or "chin" in m[1].lower())
            ]
            targets += [m for m in machines_by_cat["back"] if "lat pulldown" in m[1].lower()]
            g_stats["pull/chin"] += 1
        elif "dip" in n:
            targets = [m for m in machines if "dip" in m[1].lower()]
            g_stats["dip"] += 1
        elif "abduction" in n or "adduction" in n:
            targets = [
                m
                for m in machines_by_cat["legs"]
                if any(k in m[1].lower() for k in ("adduction", "abduction", "inner"))
            ]
            g_stats["hip"] += 1
        elif "sit-up" in n or "sit up" in n or "twist" in n or "crunch" in n:
            targets = machines_by_cat["core"]
            g_stats["core"] += 1
        if targets:
            for m in targets:
                emit(name, m[0], "gemini", 0.70)
        else:
            still.append(u)
            g_stats["skip"] += 1
    unmatched = still
    print(f"2차 LLM(gemini) 매핑 통계: {g_stats}")

    with open(_OUT_SEED, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["exercise_name", "equipment_id", "source", "confidence"])
        w.writeheader()
        w.writerows(seed_rows)
    with open(_OUT_UNMATCHED, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["exercise_name", "bodyPart", "category", "action"])
        w.writeheader()
        w.writerows(unmatched)

    print(f"결정론 매핑 통계: {stats}")
    print(f"junction_seed.csv 행수: {len(seed_rows)} (운동-기구 쌍)")
    print(f"junction_unmatched.csv(LLM 대상): {len(unmatched)} 운동")
    print(f"  cardio(skip): {stats['cardio']} / leverage·sled 동작실패: {stats['unmatched']}")


if __name__ == "__main__":
    main()
