# WorkoutX 근육 정규화 맵 (확정 2026-06-06)

> 실 API 1324운동 실측 기반. muscle_groups 캐노니컬 = WorkoutX `target` 19 + `Hip Flexors` = **20종**.
> `target`(primary)은 번역 0. `secondaryMuscles`(40종)만 아래 맵으로 20종에 흡수, 5종 drop.

## 캐노니컬 muscle_groups (20)

`Abs, Pectorals, Biceps, Glutes, Delts, Triceps, Upper Back, Lats, Calves, Quads, Forearms, Cardiovascular System, Hamstrings, Spine, Traps, Adductors, Serratus Anterior, Abductors, Levator Scapulae, Hip Flexors`

(name_ko는 Gemini 일괄 번역 → 파일 검증 예정)

## bodyPart (10) → exercises.category (그대로)

`Back, Cardio, Chest, Lower Arms, Lower Legs, Neck, Shoulders, Upper Arms, Upper Legs, Waist`

## secondaryMuscles 40 → canon 정규화 맵

| secondary (count) | → canon |
|---|---|
| Shoulders (400) | Delts |
| Hamstrings (289) | Hamstrings |
| Forearms (277) | Forearms |
| Triceps (268) | Triceps |
| Biceps (194) | Biceps |
| Quadriceps (161) | Quads |
| Calves (147) | Calves |
| Glutes (136) | Glutes |
| Core (94) | Abs |
| Chest (91) | Pectorals |
| Hip Flexors (77) | **Hip Flexors** (유지) |
| Obliques (72) | Abs |
| Lower Back (71) | Spine |
| Rhomboids (54) | Upper Back |
| Trapezius (47) | Traps |
| Upper Back (37) | Upper Back |
| Traps (33) | Traps |
| Deltoids (28) | Delts |
| Rear Deltoids (20) | Delts |
| Brachialis (14) | Biceps |
| Back (11) | **Spine** (자세안정화 다수) |
| Rotator Cuff (6) | Delts |
| Latissimus Dorsi (5) | Lats |
| Soleus (4) | Calves |
| Upper Chest (3) | Pectorals |
| Wrists (3) | Forearms |
| Wrist Extensors (2) | Forearms |
| Wrist Flexors (2) | Forearms |
| Sternocleidomastoid (2) | Levator Scapulae |
| Abdominals (2) | Abs |
| Grip Muscles (1) | Forearms |
| Lower Abs (1) | Abs |
| Inner Thighs (1) | Adductors |
| Groin (1) | Adductors |
| Lats (1) | Lats |

## DROP (근육 아님/잡값, 5종)

`Ankles (11), Feet (8), Ankle Stabilizers (4), Hands (2), Shins (1)`

## 적용 규칙
- `exercise_muscles` primary = `target` (1:1, 무번역)
- `exercise_muscles` secondary = `secondaryMuscles` 각 원소 → 위 맵. drop 5종은 제외.
- 한 운동에서 정규화 후 primary와 secondary가 같은 canon이면 primary 우선(secondary 무시).
- activation% = `muscle_activation_seed.csv`(해부학 26) → 병합 맵(reconciliation §2.1)으로 충당, 없으면 NULL.
