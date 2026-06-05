# 큐레이션 72개 — WorkoutX 기준 매핑 변경 검토 (수동 검증용)

> 결정: 1,283 신규는 WorkoutX 자동, **72개 큐레이션은 팀 수동 검증**.

> 아래는 72개를 WorkoutX 룰로 자동 재매핑했을 때 **현재(before) → 제안(after)** 변경.

> P=primary, S=secondary. ⚠️활성도 %값은 WorkoutX에 없어 별도(Gemini) — 여기선 '근육 선택'만.


## ① WorkoutX 자동매칭 38개 — 변경 확인

| # | 운동 | 매칭 | before (현재) | after (WorkoutX 제안) | 변경점 |
|--:|---|---|---|---|---|
| 1 | Back Squat | bridge:Barbell Full Squat | 대둔근(P), 대퇴사두근(P), 종아리(S), 척추기립근(S), 햄스트링(S) | 대둔근(P), 대퇴사두근(S), 햄스트링(S), 종아리(S), 복직근(S) | +복직근(S) +대퇴사두근(S) -척추기립근(S) -대퇴사두근(P) 대퇴사두근:P→S |
| 2 | Barbell Curl | exact | 이두근(P), 전완근(S) | 이두근(P), 전완근(S) | 변경없음 |
| 3 | Barbell Lunge | exact | 대퇴사두근(P), 종아리(S), 햄스트링(S) | 대둔근(P), 대퇴사두근(S), 햄스트링(S), 종아리(S) | +대둔근(P) +대퇴사두근(S) -대퇴사두근(P) 대퇴사두근:P→S |
| 4 | Barbell Row | bridge:Barbell Bent Over Row | 광배근(P), 이두근(S), 전완근(S), 능형근(S) | 승모근(P), 이두근(S), 전완근(S) | +승모근(P) -광배근(P) -능형근(S) |
| 5 | Barbell Shrug | exact | 승모근(P) | 승모근(P), 측면 삼각근(S) | +측면 삼각근(S) |
| 6 | Bench Press | bridge:Barbell Bench Press | 대흉근(P), 전면 삼각근(S), 삼두근(S) | 대흉근(P), 삼두근(S), 측면 삼각근(S) | +측면 삼각근(S) -전면 삼각근(S) |
| 7 | Bulgarian Split Squat | bridge:Dumbbell Single Leg Split Squat | 대퇴사두근(P), 종아리(S), 대둔근(S), 햄스트링(S) | 대퇴사두근(P), 대둔근(S), 햄스트링(S), 종아리(S) | 변경없음 |
| 8 | Close Grip Bench Press | bridge:Barbell Close-grip Bench Press | 삼두근(P) | 삼두근(P), 대흉근(S), 측면 삼각근(S) | +대흉근(S) +측면 삼각근(S) |
| 9 | Conventional Deadlift | bridge:Barbell Deadlift | 척추기립근(P), 대둔근(P), 햄스트링(S), 대퇴사두근(S), 승모근(S) | 대둔근(P), 햄스트링(S), 척추기립근(S) | +척추기립근(S) -척추기립근(P) -대퇴사두근(S) -승모근(S) 척추기립근:P→S |
| 10 | Crunch | bridge:Crunch Floor | 복직근(P) | 복직근(P), 고관절굴근(S) | +고관절굴근(S) |
| 11 | Dips | bridge:Chest Dip | 대흉근(P), 삼두근(S) | 대흉근(P), 삼두근(S), 측면 삼각근(S) | +측면 삼각근(S) |
| 12 | Dumbbell Curl | bridge:Dumbbell Biceps Curl | 이두근(P), 전완근(S) | 이두근(P), 전완근(S) | 변경없음 |
| 13 | Dumbbell Fly | exact | 대흉근(P), 소흉근(S) | 대흉근(P), 측면 삼각근(S) | +측면 삼각근(S) -소흉근(S) |
| 14 | Dumbbell Hammer Curl | exact | 이두근(P), 전완근(S) | 이두근(P), 전완근(S) | 변경없음 |
| 15 | Dumbbell Shoulder Press | bridge:Dumbbell Seated Shoulder Press | 전면 삼각근(P), 측면 삼각근(S), 능형근(S), 삼두근(S) | 측면 삼각근(P), 삼두근(S), 승모근(S) | +측면 삼각근(P) +승모근(S) -전면 삼각근(P) -능형근(S) -측면 삼각근(S) 측면 삼각근:S→P |
| 16 | Dumbbell Shrug | exact | 승모근(P) | 승모근(P), 측면 삼각근(S) | +측면 삼각근(S) |
| 17 | Front Raise | bridge:Dumbbell Front Raise | 전면 삼각근(P), 이두근(S) | 전면 삼각근(P), 이두근(S), 승모근(S) | +승모근(S) |
| 18 | Front Squat | bridge:Barbell Front Squat | 대퇴사두근(P), 종아리(S), 햄스트링(S) | 대둔근(P), 대퇴사두근(S), 햄스트링(S), 종아리(S), 복직근(S) | +복직근(S) +대둔근(P) +대퇴사두근(S) -대퇴사두근(P) 대퇴사두근:P→S |
| 19 | Glute Bridge | bridge:Barbell Glute Bridge | 대둔근(P), 척추기립근(S), 햄스트링(S) | 대둔근(P), 햄스트링(S), 척추기립근(S) | 변경없음 |
| 20 | Good Morning | bridge:Barbell Good Morning | 척추기립근(P) | 햄스트링(P), 척추기립근(S) | +햄스트링(P) +척추기립근(S) -척추기립근(P) 척추기립근:P→S |
| 21 | Hip Thrust | bridge:Resistance Band Hip Thrusts On Knees (female) | 대둔근(P), 중둔근(S), 햄스트링(S) | 대둔근(P), 햄스트링(S), 대퇴사두근(S) | +대퇴사두근(S) -중둔근(S) |
| 22 | Incline Bench Press | bridge:Barbell Incline Bench Press | 대흉근(P), 전면 삼각근(S), 삼두근(S) | 대흉근(P), 측면 삼각근(S), 삼두근(S) | +측면 삼각근(S) -전면 삼각근(S) |
| 23 | One Arm Dumbbell Row | bridge:Dumbbell One Arm Bent-over Row | 광배근(P), 이두근(S), 전완근(S) | 승모근(P), 이두근(S), 전완근(S) | +승모근(P) -광배근(P) |
| 24 | Overhead Press | bridge:Barbell Seated Overhead Press | 전면 삼각근(P), 측면 삼각근(S), 능형근(S), 삼두근(S) | 측면 삼각근(P), 삼두근(S), 승모근(S) | +측면 삼각근(P) +승모근(S) -전면 삼각근(P) -능형근(S) -측면 삼각근(S) 측면 삼각근:S→P |
| 25 | Overhead Triceps Extension | bridge:Dumbbell Standing Triceps Extension | 삼두근(P) | 삼두근(P), 측면 삼각근(S) | +측면 삼각근(S) |
| 26 | Pendlay Row | bridge:Barbell Bent Over Row | 능형근(P), 이두근(S), 전완근(S) | 승모근(P), 이두근(S), 전완근(S) | +승모근(P) -능형근(P) |
| 27 | Plank | bridge:Front Plank With Twist | 복직근(P), 심부 복근(P), 복사근(S) | 복직근(P), 복사근(S), 측면 삼각근(S) | +측면 삼각근(S) -심부 복근(P) |
| 28 | Pull Up | bridge:Pull-up | 광배근(P), 이두근(S) | 광배근(P), 이두근(S), 전완근(S) | +전완근(S) |
| 29 | Rear Delt Raise | bridge:Dumbbell Rear Lateral Raise | 후면 삼각근(P), 승모근(S) | 후면 삼각근(P), 승모근(S), 능형근(S) | +능형근(S) |
| 30 | Reverse Curl | bridge:Barbell Reverse Curl | 전완근(P) | 이두근(P), 전완근(S) | +전완근(S) +이두근(P) -전완근(P) 전완근:P→S |
| 31 | Romanian Deadlift | bridge:Barbell Romanian Deadlift | 대둔근(P), 햄스트링(P), 척추기립근(S) | 대둔근(P), 햄스트링(S), 척추기립근(S) | +햄스트링(S) -햄스트링(P) 햄스트링:P→S |
| 32 | Seated Calf Raise | bridge:Barbell Seated Calf Raise | 종아리(P), 햄스트링(S) | 종아리(P), 햄스트링(S) | 변경없음 |
| 33 | Side Bend | bridge:Dumbbell Side Bend | 복사근(P) | 복직근(P), 복사근(S) | +복직근(P) +복사근(S) -복사근(P) 복사근:P→S |
| 34 | Side Lateral Raise | bridge:Dumbbell Lateral Raise | 측면 삼각근(P), 승모근(S) | 측면 삼각근(P), 승모근(S) | 변경없음 |
| 35 | Skull Crusher | bridge:Barbell Lying Triceps Extension Skull Crusher | 삼두근(P) | 삼두근(P), 측면 삼각근(S) | +측면 삼각근(S) |
| 36 | Standing Calf Raise | bridge:Barbell Standing Calf Raise | 종아리(P), 대둔근(S), 햄스트링(S) | 종아리(P), 햄스트링(S), 대둔근(S) | 변경없음 |
| 37 | Upright Row | bridge:Barbell Upright Row | 측면 삼각근(P), 이두근(S), 승모근(S) | 측면 삼각근(P), 승모근(S), 이두근(S) | 변경없음 |
| 38 | Wrist Curl | bridge:Barbell Wrist Curl | 전완근(P), 이두근(S) | 전완근(P), 이두근(S), 상완근(S) | +상완근(S) |

## ② WorkoutX 없음 34개 (머신 등) — 현재 유지 / 수동 확정

| # | 운동 | 현재 매핑 (유지) |
|--:|---|---|
| 1 | Abdominal Crunch Machine | 복직근(P) |
| 2 | Back Extension Machine | 척추기립근(P) |
| 3 | Cable Crossover | 대흉근(P) |
| 4 | Cable Crunch | 복직근(P), 복사근(S) |
| 5 | Cable Triceps Pushdown | 삼두근(P) |
| 6 | Calf Raise | 종아리(P) |
| 7 | Face Pull | 후면 삼각근(P), 승모근(S) |
| 8 | Hip Adduction Abduction Machine | 중둔근(P) |
| 9 | Hip Thrust Machine | 대둔근(P) |
| 10 | Lat Pulldown | 광배근(P), 이두근(S) |
| 11 | Leg Curl | 햄스트링(P) |
| 12 | Leg Extension | 대퇴사두근(P) |
| 13 | Leg Press | 대퇴사두근(P), 대둔근(S) |
| 14 | Machine Biceps Curl | 이두근(P) |
| 15 | Machine Chest Press | 대흉근(P) |
| 16 | Machine Decline Chest Press | 대흉근(P) |
| 17 | Machine Hack Squat | 대퇴사두근(P) |
| 18 | Machine High Row | 광배근(P) |
| 19 | Machine Incline Chest Press | 대흉근(P) |
| 20 | Machine Lat Pulldown | 광배근(P) |
| 21 | Machine Lateral Raise | 측면 삼각근(P) |
| 22 | Machine Leg Curl | 햄스트링(P) |
| 23 | Machine Leg Extension | 대퇴사두근(P) |
| 24 | Machine Leg Press | 대퇴사두근(P) |
| 25 | Machine Row | 능형근(P) |
| 26 | Machine Shoulder Press | 전면 삼각근(P) |
| 27 | Machine Triceps Extension | 삼두근(P) |
| 28 | Oblique Machine | 복직근(P) |
| 29 | Pec Deck | 대흉근(P) |
| 30 | Preacher Curl Machine | 이두근(P) |
| 31 | Pullover Machine | 광배근(P) |
| 32 | Reverse Pec Deck | 후면 삼각근(P) |
| 33 | Seated Cable Row | 광배근(P), 능형근(S) |
| 34 | Tricep Pushdown | 삼두근(P) |
