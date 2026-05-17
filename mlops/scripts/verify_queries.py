"""쿼리 후보를 PubMed에서 실제 검색해서 효용성을 평가하는 일회성 검증 스크립트.

각 후보 쿼리를 strict 필터(RCT/메타분석/시스템 리뷰 + free full text)와 함께 실행하고,
hit count를 출력한다. 채택 기준:
  - strict=True: 최소 30건 (RAG 청크 다양성 확보를 위한 하한)
  - strict=False: 최소 10건 (개인화/추천시스템 등 본질적으로 논문 수가 적은 영역)
  - 상한 50,000건 (지나치게 광범위 → relevance 정렬이 무의미)

사용:
    python -m mlops.scripts.verify_queries
"""

from __future__ import annotations

import logging
import sys
import time

import requests
from mlops.pipeline.config import NCBI_API_KEY, NCBI_BASE_URL, NCBI_RATE_LIMIT
from mlops.pipeline.crawler import COMMON_PUBLICATION_FILTER

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)


CANDIDATE_QUERIES: list[tuple[str, str, bool]] = [
    # ── 기존 29개 ──
    (
        "volume",
        '("resistance training") AND '
        '("training volume" OR "volume load" OR "sets per muscle group" OR "weekly sets") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "intensity",
        '("resistance training") AND '
        '("training intensity" OR "%1RM" OR "high load" OR "low load") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "frequency",
        '("resistance training") AND '
        '("training frequency" OR "weekly frequency" OR "sessions per week") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "hypertrophy_strength",
        '("resistance training" OR "strength training") AND '
        '("muscle hypertrophy" OR "muscle thickness" OR "cross-sectional area" '
        'OR "muscle strength" OR "maximal strength" OR "1RM") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "trained_status",
        '("resistance training") AND '
        '("trained individuals" OR "resistance-trained" OR "experienced lifters" '
        'OR "untrained individuals" OR "beginners" OR "novice") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "rest_interval",
        '("resistance training") AND '
        '("rest interval" OR "inter-set rest") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "performance") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "failure_rir",
        '("resistance training") AND '
        '("training to failure" OR "muscular failure" OR "repetitions in reserve" OR "RIR") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "fatigue") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "exercise_order",
        '("resistance training") AND '
        '("exercise order" OR "exercise sequence") AND '
        '("muscle strength" OR "muscle hypertrophy" OR "performance") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "recommendation_system",
        '("exercise recommendation system" OR "fitness recommendation system" '
        'OR "workout recommendation system") AND '
        '("personalized" OR "machine learning" OR "user profile")',
        False,
    ),
    (
        "personalized_prescription",
        '("personalized exercise prescription" OR "individualized exercise program") AND '
        '("resistance training" OR "strength training") AND '
        '("humans" OR "adults")',
        False,
    ),
    (
        "machine_vs_freeweight",
        '("resistance training") AND '
        '("machine" OR "free weight" OR "exercise machine" OR "selectorized" OR "plate loaded") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "biomechanics" OR "muscle activation") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "emg_activation",
        '("resistance training" OR "strength training") AND '
        '("electromyography" OR "EMG" OR "muscle activation" OR "neural drive") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "periodization",
        '("resistance training") AND '
        '("periodization" OR "linear periodization" OR "undulating periodization" '
        'OR "block periodization") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "deload_recovery",
        '("resistance training") AND '
        '("deload" OR "recovery week" OR "training cycle" OR "tapering") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "fatigue" OR "performance") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "doms_recovery",
        '("resistance training") AND '
        '("delayed onset muscle soreness" OR "DOMS" OR "muscle damage" OR "exercise-induced muscle damage") AND '
        '("recovery" OR "muscle hypertrophy" OR "performance") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "older_adults",
        '("resistance training" OR "strength training") AND '
        '("older adults" OR "elderly" OR "sarcopenia" OR "aging") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "physical function") AND '
        '("humans")',
        True,
    ),
    (
        "women_resistance",
        '("resistance training" OR "strength training") AND '
        '("women" OR "female" OR "sex differences" OR "menstrual cycle") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "injury_prevention",
        '("resistance training") AND '
        '("injury prevention" OR "lower back pain" OR "shoulder impingement" '
        'OR "rotator cuff" OR "knee injury" OR "musculoskeletal injury") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "range_of_motion",
        '("resistance training") AND '
        '("range of motion" OR "ROM" OR "full range" OR "partial range" OR "lengthened position") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "tempo_tut",
        '("resistance training") AND '
        '("tempo" OR "time under tension" OR "lifting cadence" OR "movement velocity") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "contraction_mode",
        '("resistance training") AND '
        '("eccentric" OR "concentric" OR "isometric" OR "contraction mode") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "compound_isolation",
        '("resistance training") AND '
        '("compound exercise" OR "multi-joint" OR "single-joint" OR "isolation exercise") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "chest_training",
        '("resistance training") AND '
        '("bench press" OR "pectoral" OR "chest" OR "pectoralis major") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "back_training",
        '("resistance training") AND '
        '("row" OR "pull-down" OR "latissimus" OR "back exercise" OR "pull-up") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "legs_training",
        '("resistance training") AND '
        '("squat" OR "deadlift" OR "leg press" OR "quadriceps" OR "hamstring" OR "gluteus") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "shoulders_training",
        '("resistance training") AND '
        '("shoulder press" OR "overhead press" OR "deltoid" OR "lateral raise" OR "shoulder exercise") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "arms_training",
        '("resistance training") AND '
        '("biceps curl" OR "triceps extension" OR "elbow flexion" OR "elbow extension" OR "arm exercise") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "core_training",
        '("resistance training" OR "core training") AND '
        '("abdominal" OR "trunk stability" OR "core stability" OR "rectus abdominis") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "load_progression",
        '("resistance training") AND '
        '("progressive overload" OR "load progression" OR "training progression") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    # ── 최근 추가된 3개 (S2691) ──
    (
        "muscular_endurance",
        '("resistance training") AND '
        '("muscular endurance" OR "local muscular endurance" OR "muscle endurance") AND '
        '("muscle strength" OR "performance" OR "fatigue resistance") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "concurrent_training",
        '("resistance training") AND '
        '("concurrent training" OR "aerobic training" OR "interference effect" OR "combined training") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "exercise_rehabilitation",
        '("resistance training" OR "exercise therapy") AND '
        '("rehabilitation" OR "physical therapy" OR "post-injury" OR "return to sport") AND '
        '("muscle strength" OR "muscle hypertrophy" OR "physical function") AND '
        '("humans" OR "adults")',
        True,
    ),
    # ── Consensus / Perplexity 추천 신규 ──
    (
        "warm_up_cool_down",
        '("resistance training") AND '
        '("warm-up" OR "warm up" OR "cool-down" OR "cool down" OR "dynamic stretching" OR "preparatory exercise") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "performance") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "exercise_variation",
        '("resistance training") AND '
        '("exercise variation" OR "variation" OR "different exercises" OR "exercise diversity") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "blood_flow_restriction",
        '("resistance training") AND '
        '("blood flow restriction" OR "BFR" OR "occlusion training" OR "KAATSU") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "explosive_power_speed",
        '("resistance training") AND '
        '("explosive power" OR "rate of force development" OR "ballistic training" OR "sprint performance") AND '
        '("muscle strength" OR "athletic performance") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "instability_training",
        '("resistance training") AND '
        '("instability training" OR "unstable surface" OR "balance training" OR "stability ball" OR "BOSU") AND '
        '("muscle strength" OR "muscle activation" OR "core stability") AND '
        '("humans" OR "adults")',
        True,
    ),
    # ── 추가 (운동 루틴 생성에 유용) ──
    (
        "training_split",
        '("resistance training") AND '
        '("training split" OR "split routine" OR "push pull legs" OR "upper lower split" OR "full body training") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "advanced_techniques",
        '("resistance training") AND '
        '("drop set" OR "superset" OR "rest-pause" OR "cluster set" OR "pre-exhaustion") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "minimum_effective_dose",
        '("resistance training") AND '
        '("minimum effective dose" OR "low volume" OR "minimal training" OR "time-efficient") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "plyometric_training",
        '("plyometric training" OR "plyometrics" OR "jump training") AND '
        '("muscle strength" OR "athletic performance" OR "power output") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "detraining",
        '("resistance training") AND '
        '("detraining" OR "training cessation" OR "muscle atrophy" OR "strength loss") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "protein_nutrition",
        '("resistance training") AND '
        '("protein intake" OR "protein supplementation" OR "amino acids" OR "dietary protein") AND '
        '("muscle hypertrophy" OR "muscle protein synthesis" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "sleep_recovery",
        '("resistance training" OR "strength training") AND '
        '("sleep" OR "sleep deprivation" OR "sleep quality") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "recovery" OR "performance") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "bodyweight_training",
        '("bodyweight exercise" OR "calisthenics" OR "bodyweight training") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "unilateral_training",
        '("resistance training") AND '
        '("unilateral training" OR "single-leg" OR "single-arm" OR "bilateral deficit") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "mind_muscle_connection",
        '("resistance training") AND '
        '("attentional focus" OR "internal focus" OR "external focus" OR "mind muscle connection") AND '
        '("muscle activation" OR "muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "mechanical_tension",
        '("resistance training") AND '
        '("mechanical tension" OR "metabolic stress" OR "muscle damage hypothesis") AND '
        '("muscle hypertrophy" OR "muscle protein synthesis") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "individual_response",
        '("resistance training") AND '
        '("individual response" OR "responders" OR "non-responders" OR "inter-individual variability") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "resistance_band",
        '("resistance band" OR "elastic band" OR "elastic resistance") AND '
        '("muscle strength" OR "muscle activation" OR "muscle hypertrophy") AND '
        '("humans" OR "adults")',
        True,
    ),
]


def count_query(query: str) -> int | None:
    """esearch에서 hit count만 가져온다 (retmax=0 → idlist 비우고 count만 반환)."""
    params: dict = {
        "db": "pubmed",
        "term": query,
        "retmax": 0,
        "retmode": "json",
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY

    try:
        resp = requests.get(f"{NCBI_BASE_URL}/esearch.fcgi", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return int(data.get("esearchresult", {}).get("count", 0))
    except Exception as e:
        logger.warning("쿼리 실패 err=%s", e)
        return None


def classify(strict: bool, count: int | None) -> str:
    """채택 / 보류 / 폐기 판정."""
    if count is None:
        return "ERROR"
    if strict:
        if count < 30:
            return "DROP   "
        if count > 50_000:
            return "BROAD  "
        return "KEEP   "
    else:
        if count < 10:
            return "DROP   "
        if count > 50_000:
            return "BROAD  "
        return "KEEP   "


def main() -> int:
    print(f"NCBI_API_KEY present: {bool(NCBI_API_KEY)} (rate_limit={NCBI_RATE_LIMIT}s)")
    print("strict 기준: 30 ≤ count ≤ 50,000 | non-strict 기준: 10 ≤ count ≤ 50,000")
    print("-" * 95)
    print(f"{'idx':>3}  {'category':<26}  {'strict':<6}  {'count':>8}  {'verdict':<7}")
    print("-" * 95)

    results: list[tuple[str, str, bool, int | None, str]] = []
    for i, (name, query, strict) in enumerate(CANDIDATE_QUERIES, 1):
        full_query = query + (COMMON_PUBLICATION_FILTER if strict else "")
        time.sleep(NCBI_RATE_LIMIT)
        count = count_query(full_query)
        verdict = classify(strict, count)
        count_str = f"{count:>8,}" if count is not None else "     N/A"
        print(f"{i:>3}  {name:<26}  {str(strict):<6}  {count_str}  {verdict}")
        results.append((name, query, strict, count, verdict))

    print("-" * 95)
    keep = [r for r in results if r[4].strip() == "KEEP"]
    drop = [r for r in results if r[4].strip() == "DROP"]
    broad = [r for r in results if r[4].strip() == "BROAD"]
    err = [r for r in results if r[4].strip() == "ERROR"]
    print(f"\n요약: KEEP={len(keep)}  DROP={len(drop)}  BROAD={len(broad)}  ERROR={len(err)}")

    if drop:
        print("\n[DROP] 채택 기준 미달 — 쿼리 어휘 부족/너무 좁음:")
        for r in drop:
            print(f"  - {r[0]:<26} count={r[3]}")
    if broad:
        print("\n[BROAD] 너무 광범위 — 필터 강화 권장:")
        for r in broad:
            print(f"  - {r[0]:<26} count={r[3]:,}")
    if err:
        print("\n[ERROR] API 호출 실패 — 재실행 필요:")
        for r in err:
            print(f"  - {r[0]}")

    print("\n[KEEP] 최종 채택 카테고리:")
    for r in keep:
        print(f"  - {r[0]:<26} count={r[3]:,}  (strict={r[2]})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
