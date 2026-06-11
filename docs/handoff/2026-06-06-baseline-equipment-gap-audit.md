# 🔎 generic 8기구 제거 → 재시드 기본주입 명세 공백 감사

> 작성 2026-06-06 · 트리거: 사용자 한글 채움 `equipments 1.xlsx`(140행) ↔ 정리본 `equipments.csv`(132행) 대조에서 **xlsx에만 있고 csv에서 빠진 8개 generic 기구** 발견.
> 질문: "이 8개를 재시드 때 기본으로 넣어주려면 어딘가 기억(기록)돼 있어야 하잖아 — 어디에 기록됐나?"
> 방법: 멀티에이전트 워크플로우(finder 5 + verify 12). finding 35건 / gap 의심 12 / **확정 9**.

---

## 0. 한 줄 결론

**generic 8행을 부활시키는 건 답이 아니다(D2/D4 위반).** 프리웨이트 6종은 기록 완비(✅), 머신 2종은 실물 대체본이 csv에 이미 있으나(✅) **그 실물로 "흡수"하는 연결이 미기록 + Smith 실물이 gym 미등록 + load_calc 잠복 버그** 3건이 진짜 공백이다.

---

## 1. 제거된 8개 generic (전부 brand_id=NULL, csv 132에서 ABSENT)

| # | name_en | 한글 | generic id | 물리분류 | 재시드 기본주입 명세 | 공백? |
|---|---|---|---|---|---|---|
| 1 | Bodyweight | 맨몸 | 57d1b189 | 프리웨이트 | `freeweight_load_modes.csv` bodyweight (풀업바·딥스대 포함) | ✅ 없음 |
| 2 | Barbell | 바벨 | f970fcc9 | 프리웨이트 | barbell 20kg | ✅ 없음 |
| 3 | Dumbbell | 덤벨 | a0b9376d | 프리웨이트 | dumbbell 증분 | ✅ 없음 |
| 4 | Pull-up Bar | 풀업바 | fd80d7e6 | 프리웨이트(맨몸 흡수) | bodyweight 흡수 | ✅ 없음 |
| 5 | Dip Bar | 딥스바 | d7631d75 | 프리웨이트(맨몸 흡수) | bodyweight 흡수 | ✅ 없음 |
| 6 | EZ Bar | EZ 바 | 32f43f66 | 프리웨이트(별도 load_mode) | ez_barbell 10kg (D8) | ✅ 없음 |
| 7 | **Smith machine** | 스미스 머신 | fe005947 | **머신** | **없음** — generic 부활 불요지만 실물 흡수 매핑 미기록 | 🔴 **공백** |
| 8 | **Assisted Pull-up Machine** | 어시스티드 풀업 머신 | c323aec6 | **머신** | **없음** — 동일 | 🔴 **공백** |

→ 프리웨이트 6종(1~6)은 `docs/handoff/workoutx-raw/freeweight_load_modes.csv`에 baseline으로 **완전히 기억돼 있음**. equipment 행이 아니라 `exercises.load_mode` + load_calc 상수로 주입(D2). 사용자 우려와 달리 손실 없음.

---

## 2. 머신 2종 실물 대체본 (csv 132에 이미 존재 — 직접 확인)

| 운동군 | 실물 행 | brand | type | has_weight_assist | bar/stack | **gym_equipments 등록** |
|---|---|---|---|---|---|---|
| Smith | `f6fe186b` Smith machine | Panatta | machine | FALSE | bar 15kg / stack 0~300kg / pulley 1 | 🔴 **미등록** |
| 어시스티드 딥/친 | `2ca108c5` Assisted Dip/Chin | Newtech | machine | **TRUE** | stack 5~90kg | ✅ 등록(더찬스짐) |
| (추가) | `91dd2f21` Hammer Strength Select Assist Dip/Chin | — | machine | FALSE | — | 미등록 |

- `has_weight_assist=TRUE` 머신은 csv 전체에서 **단 1개**(Assisted Dip/Chin)뿐.
- generic 제거는 핸드오프 line 59 "generic 프리웨이트·Assisted placeholder·Smith 중복 제거 완료"로 **의도된 dedup**이 맞음.

---

## 3. 🔴 확정 공백 4건 (사용자 직관이 맞았던 부분)

### G1 (P0) — ✅ 해결(2026-06-06) — Smith 실물이 어느 gym에도 미등록 → Smith 운동 48개 증발
> **처리됨**: 유저 확인 "더찬스짐에 스미스 머신 실재" → `gym_equipments.csv`에 `f6fe186b`(Smith machine) 더찬스짐(`ecdd073b`) 등록 완료(32→33행, orphan 0). Smith 48운동 가용성 복구.
- WorkoutX `exercises.json`에서 `equipment="Smith Machine"` = **48운동**. SOT §6에서 `Smith→load_mode=machine`.
- D4 가용성 규칙: 머신은 `exercise_equipment ⋈ gym_equipments`로만 노출. 그런데 Smith 실물(f6fe186b)이 gym_equipments 0건 → 테스트 gym(더찬스짐)에서 **M'=0 전량 제외 = 48운동 증발**.
- **조치**: 더찬스짐에 스미스 머신이 실재하면 `gym_equipments.csv`에 f6fe186b 등록. (현실 사실 = 사용자 확인 필요)

### G2 (P0) — ✅ 해결(2026-06-07) — generic→실물 머신 "흡수" 매핑(정션 산출물)이 미작성
> **처리됨**: 마이그레이션 `20260607_seed_junction`이 machine/cable 운동↔실물 기구 정션(`junction_seed.csv`)을 적재.
- 머신-클래스 운동 = Leverage 81 + Smith 48 + Sled 15 + Assisted 14 + Hammer 1 + towel 1 = **160운동**.
- 이들을 어느 실물 `equipments` 행에 붙일지의 **검증된 `exercise_equipment` 정션 내용**이 어떤 파일에도 없음. SOT §7-3e는 "Gemini 매핑 검증본 적재"라는 **메커니즘만** 명시, **내용은 미작성**. SOT §10 미결로만 플래그됨.
- 정션이 비면 160운동 전부 M'=0 런타임 침묵 제외.
- **조치**: Phase 7 Gemini N:M 산출 시, 머신-클래스 160운동 → 실물 행(f6fe186b/2ca108c5/91dd2f21 등) 매핑을 **명시 산출 → 사용자 검증 → 적재**. §9 게이트 "머신 정션 없는 machine/cable 운동 = 0" 검증.

### G3 (P1) — ✅ 해결 — `load_calc.py` machine 분기가 has_weight_assist 미반영 (잠복 버그)
> **처리됨**: 커밋 `a7b5b66`(load_calc load_mode 11종 전환 + 어시스티드 머신 부호반대 수정)에서 machine 분기에 has_weight_assist 처리 반영.
- 현 `load_calc.py` machine 분기: `stack/pulley_ratio + bar_weight`. **has_weight_assist 미참조**. 어시스트 로직(`body_weight - stack`)은 bodyweight 분기에만 존재.
- Assisted Dip/Chin(has_weight_assist=TRUE)을 `load_mode=machine`으로 분류하면 → 어시스트 무게를 **실효부하로 오계산(부호 반대 폭탄)**.
- SOT §4 line 100은 "machine이 has_weight_assist 사용"이라 적었으나 현 구현 미반영 = **스펙↔코드 갭**.
- **조치**: Phase 4 load_calc 재작성 시 machine 분기에 has_weight_assist 처리 추가.

### G4 (P1) — ✅ 해결(2026-06-07) — WorkoutX "Assisted" 15운동 대부분이 파트너 스트레치 → machine 오분류 위험
> **처리됨**: 마이그레이션 `20260607_g4_stretch_bw`가 assisted 스트레치/맨몸 15운동의 load_mode를 machine→bodyweight로 정정.
- `equipment="Assisted"` 15운동(Assisted Lying Glutes Stretch, Assisted Hanging Knee Raise 등)은 외부 부하 없는 **스트레치/맨몸**. 실제 어시스트 부하 머신은 has_weight_assist=TRUE 1행뿐.
- SOT §6 룩업대로 일괄 `Assisted→machine` 하면 부하 없는 스트레치가 실물 머신 정션을 강제 요구 → 게이트 탈락.
- SOT §6 룩업에 "초안 후 사용자 검토" 단서 있음.
- **조치**: Assisted 15운동을 bodyweight 등으로 재분류(machine 제외). Phase 1/7 Gemini 룩업 검토 시 반영.

---

## 4. 처리 정책 결론

1. **generic 머신 2종 부활 금지** — D2/D4 위반. 실물 흡수가 정답.
2. **Smith는 Panatta 실물(f6fe186b)로 일원화** + gym 등록(G1).
3. **머신-클래스 160운동의 실물 정션 산출물을 Phase 7에서 반드시 작성**(G2) — 이게 "기억해둬야 할" 핵심 누락분.
4. **load_calc machine 분기 has_weight_assist 추가**(G3) + Assisted 스트레치 재분류(G4).

---

## 5. 핸드오프 실행 플랜 반영점
- Phase 1(기구 시드): equipments.csv 132 + 한글 머지 완료. Smith gym 등록 여부(G1) 선결.
- Phase 4(load_calc): G3 버그 수정 항목 추가.
- Phase 7(Gemini N:M): G2(머신 160 정션 명시)·G4(Assisted 재분류)를 산출물 요구사항에 포함.
