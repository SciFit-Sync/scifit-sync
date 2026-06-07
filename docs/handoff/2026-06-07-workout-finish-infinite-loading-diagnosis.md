# 버그 진단 보고서 — 운동 완료 무한 로딩 + "이미 종료된 세션" / "세트 기록 실패"

- **작성일**: 2026-06-07
- **상태**: 진단 완료 + Codex 독립 2차 검증 완료 (코드 수정 미착수 — 보고서까지만)
- **검증**: 3대 근본 원인 모두 Codex가 코드 대조로 확인(RC-1 조건부, RC-2·RC-3 확정). 추가로 RC-4 외 3건 발견 → §7 참조
- **영향 화면**: `WR04RoutineDetail.tsx` (루틴 상세 = 운동 진행 화면)
- **영향 API**: `PATCH /sessions/{id}/finish`, `POST /sessions/{id}/sets`
- **심각도**: 🔴 High — 세션을 정상 종료할 수 없고, 한 번 막히면 해당 세션이 영구적으로 잠김(409 연쇄)

---

## 1. 증상 (사용자 보고 / 재현 시나리오)

1. LLM이 생성한 루틴의 중량·횟수를 수정한다.
2. 세트를 체크하며 운동을 진행한다.
3. **"운동 완료"를 누르면 무한 로딩**에 빠진다 (스피너가 멈추지 않음).
4. 뒤로 가기로 화면을 나갔다가 다시 들어와 "운동 완료"를 누르면 **"이미 종료된 세션"** 에러가 뜨고 아무것도 안 된다.
5. 세트를 다시 체크하면 **"세트 기록 실패 — 세트가 서버에 저장되지 않았습니다. 네트워크 연결을 확인해주세요."** 알림이 뜬다.

> 핵심: 위 5개는 **별개 버그가 아니라 하나의 인과 체인**이다. (3)이 원인이고 (4)(5)는 그 후유증이다.

---

## 2. 근본 원인 (3계층)

### 🔴 RC-1 (Primary) — `finish_session`이 COMPLETED 커밋 후 RAG/LLM을 **동기 블로킹**으로 실행, 클라이언트엔 **요청 타임아웃이 없음** → 무한 로딩

`PATCH /sessions/{id}/finish` 핸들러는 다음 순서로 동작한다
(`server/app/api/v1/sessions.py:508-563`):

```python
s.finished_at = candidate
s.status = WorkoutStatus.COMPLETED
await db.commit()                       # ← 여기서 세션은 이미 '완료'로 확정 (line 525-526)
await db.refresh(s)
...                                      # total_sets / completed_exercises / body_weight 집계
await _check_and_create_po_notifications(s, current_user, db)   # ← line 561 (무거운 작업)
return SuccessResponse(data=dto)
```

`_check_and_create_po_notifications`는 PO(Progressive Overload) 트리거가 성립한
운동마다 `po_rag.rag_po_increment(...)`를 **루프 안에서 순차 await** 한다
(`sessions.py:453`, 루프는 `sessions.py:406`):

```python
increment_override = await po_rag.rag_po_increment(goal, category, user_1rm_kg)  # line 453
```

`po_rag.rag_po_increment`는 **ChromaDB 검색 + LLM 호출**을 수행한다
(`server/app/services/po_rag.py:107-130`):

```python
chunks = await _call_search_async(query, 3)   # ChromaDB (asyncio.to_thread)  line 109
...
raw = await _call_llm_async(prompt)           # LLM 생성 (asyncio.to_thread)  line 116
```

그리고 LLM 호출에는 **타임아웃이 전혀 없다** (`server/app/services/llm.py:68-94`).
게다가 기본 provider인 Gemini가 실패하면 **OpenAI로 순차 fallback** 하므로 최악의 경우
한 번의 `generate()`가 **2회 연속 네트워크 블로킹**이 된다:

```python
def generate(prompt: str) -> str:
    ...
    try:
        client = _get_gemini()
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)  # timeout 없음
        return response.text.strip()
    except Exception as e:
        logger.warning("Gemini 실패 (%s), GPT-4o-mini fallback 시도", e)
        client = _get_openai()
        response = client.chat.completions.create(...)   # 또 timeout 없음
        return response.choices[0].message.content.strip()
```

클라이언트의 `apiFetch`는 `fetch()`를 **AbortController/타임아웃 없이** 호출한다
(`app/src/services/api.ts:56-59`). 따라서 서버 응답이 수십 초~수 분 걸리거나 LLM이 멈추면
프론트는 **무한정 대기**하고, "운동 완료" 버튼은 `is_finishing=true` 상태로 영원히 스피너를 돈다
(`WR04RoutineDetail.tsx:705`, 버튼 스피너 `:1130`).

> **결정적 포인트**: 세션 상태는 `db.commit()`(line 526)에서 **이미 COMPLETED로 확정**된다.
> 응답이 도착하지 않아 클라이언트는 "아직 완료 안 됐다"고 믿지만, 서버 DB에서는 이미 끝난 세션이다.
> 이 불일치가 RC-2의 출발점이다.

### 🔴 RC-2 (State) — 완료 확정 후에도 클라이언트가 **같은 session_id를 영속 보관** → 재시도 시 409 연쇄

진행 중 세션은 Zustand + AsyncStorage(`workoutSessionStore.ts`)에 영속화되며,
**`clear()`는 오직 finishSession이 성공 응답을 반환한 직후에만 호출**된다
(`WR04RoutineDetail.tsx:722` `ws_clear()`).

RC-1로 인해 finish 응답이 끝내 도착하지 않으면 `ws_clear()`가 실행되지 않아
스토어에 `session_id`(=이미 COMPLETED된 SID)가 그대로 남는다.

사용자가 화면을 나갔다 재진입하면 복원 effect가 그 SID를 다시 `session_id_ref`에 올린다
(`WR04RoutineDetail.tsx:222-237`):

```js
if (ws_routine_id === routine_id) {
  if (ws_session_id) {
    session_id_ref.current = ws_session_id;   // ← 이미 완료된 세션 ID를 재사용
    set_session_started(true);
  }
  ...
}
```

이 상태에서 다시 "운동 완료"를 누르면 `do_finish` → `finishSession(SID)` →
백엔드가 `s.status == COMPLETED`를 보고 **409 ConflictError "이미 종료된 세션입니다."**를 던진다
(`sessions.py:516-517`). 이 경로는 RAG를 타지 않으므로 **즉시** 반환된다 →
사용자에겐 "이미 종료된 세션" 알림이 바로 뜬다. (증상 4)

```python
# sessions.py:515-517 (finish_session)
s = await _get_my_session(session_id, current_user, db)
if s.status == WorkoutStatus.COMPLETED:
    raise ConflictError(message="이미 종료된 세션입니다.")
```

마찬가지로 세트를 다시 체크하면 `logSet(SID, ...)` →
백엔드가 동일하게 **409 "이미 종료된 세션에는 세트를 추가할 수 없습니다."**를 던진다
(`sessions.py:260-261`):

```python
# sessions.py:259-261 (log_set)
s = await _get_my_session(session_id, current_user, db)
if s.status == WorkoutStatus.COMPLETED:
    raise ConflictError(message="이미 종료된 세션에는 세트를 추가할 수 없습니다.")
```

### 🟠 RC-3 (UX / 오진단) — 세트 기록은 fire-and-forget 이고, 409 상태 충돌을 "네트워크 오류"로 잘못 표기

세트 체크 시 `toggle_set_done`은 세트 기록을 **fire-and-forget**(await 없이 `.then/.catch`)으로 보낸다
(`WR04RoutineDetail.tsx:324-354`). 실패하면 원인과 무관하게 동일한 메시지를 띄운다
(`WR04RoutineDetail.tsx:347-352`):

```js
.catch(() => {
  Alert.alert(
    "세트 기록 실패",
    "세트가 서버에 저장되지 않았습니다.\n네트워크 연결을 확인해주세요.",
  );
});
```

실제 원인은 **409 상태 충돌**(이미 완료된 세션)인데 메시지는 "네트워크 연결을 확인해주세요"라고 안내해
사용자·디버깅을 오도한다. (증상 5 — 네트워크 문제가 아님)

---

## 3. 전체 인과 체인 (타임라인)

```
[1] 사용자가 중량·횟수 수정 (update_set — 로컬 state만 변경, 서버 전송 X)
[2] 세트 체크 → ensure_session() → POST /sessions → SID 발급, 스토어에 SID 저장
       → logSet(SID, ...) 201 OK  (정상)
[3] "운동 완료" 탭 → do_finish → set_is_finishing(true)
       → PATCH /sessions/SID/finish
            서버: status=COMPLETED 커밋 (DB 확정)  ← 이 시점에 세션은 이미 끝남
            서버: _check_and_create_po_notifications → rag_po_increment → ChromaDB + LLM(타임아웃 X)
            ⟶ 응답이 수십 초~무한 지연
       클라이언트: apiFetch 타임아웃 없음 → 무한 await → 버튼 스피너 영구 회전   ▶ 증상 3
[4] 사용자 뒤로 가기 → 화면 언마운트 (in-flight finish 요청은 고아가 됨, ws_clear 미실행)
[5] 재진입 → 복원 effect가 스토어의 SID(=완료된 세션)를 session_id_ref에 복원
[6] "운동 완료" 재탭 → finishSession(SID) → 서버 status==COMPLETED → 409 즉시 반환
       → Alert "오류: 이미 종료된 세션입니다."                                  ▶ 증상 4
[7] 세트 재체크 → logSet(SID) → 서버 status==COMPLETED → 409
       → Alert "세트 기록 실패 / 네트워크 연결을 확인해주세요"  (실제론 상태충돌)  ▶ 증상 5
```

---

## 4. 트리거 조건 — "수정"이 정말 원인인가?

- **중량·횟수 수정 자체는 직접 원인이 아니다.** `update_set`은 로컬 React state만 바꾸며 서버를 호출하지 않는다
  (`WR04RoutineDetail.tsx:362-380`).
- 다만 **횟수를 목표 rep 상단까지 올려 입력**하면 PO 트리거(`po.check_po_trigger`, 연속 2세션 목표 달성)가
  성립하기 쉬워지고, 그 결과 RC-1의 RAG/LLM 경로가 실행된다. 즉 수정은 **유발 확률을 높이는 정황**이지
  버그의 본질이 아니다.
- **선행 조건**: RAG 경로가 돌려면 동일 `routine_exercise`에 대해 **이전 완료 세션이 1건 이상** 있어야 한다
  (`sessions.py:341-379`의 직전 세션 reps 조회 → `:410` 트리거 판정). 최초 1회 세션만 있으면
  `prev_reps_map`이 비어 트리거가 안 되고 finish는 빠르게 끝난다.
  반복 테스트 중이라면 이 조건은 쉽게 충족된다.
- 참고: `rag_po_increment`는 `user_1rm_kg`가 없어도 **ChromaDB 검색 + LLM 호출을 먼저 수행**한 뒤
  마지막에 None을 반환한다(`po_rag.py:107-130`). 즉 1RM 유무와 무관하게 트리거만 성립하면 무거운 작업이 돈다.

---

## 5. 수정 방향 (제안 — 미구현)

> 아래는 권고안일 뿐이며, 사용자 요청에 따라 **코드는 수정하지 않았다.**

> 🚫 **불가침 제약 (사용자 지시, 2026-06-07)**: **루틴 생성·논문 검색(챗봇 RAG)을 절대 막거나 저하시키지 말 것.**
> 루틴 생성은 `rag.routine_rag_stream`(`routines.py:1408`), 논문 검색은 `search_chunks`(`rag.py:272/625/701/783`),
> LLM은 `generate`/`generate_stream` — 모두 finish 경로와 **별개 코드 경로**지만 `generate`/`generate_stream`/`search_chunks`와
> 캐시 클라이언트(`_get_gemini`/`_get_openai`)는 **공유 자원**이다. 따라서:
> - ❌ **금지**: 공유 `generate`/`generate_stream`/`search_chunks` 또는 캐시 클라이언트에 **전역 `timeout=` 추가** (루틴/챗봇이 잘림).
> - ✅ **허용**: 수정은 `sessions.py` finish 한 곳만(아래 1·3번). 타임아웃이 필요하면 **PO 경로 한정**으로만 scoped.
> - 검증: 수정 후 루틴 생성·챗봇 스트리밍이 정상 동작함을 반드시 확인.

1. **[RC-1 핵심] PO를 "쪼개서" — 빠른 부분은 동기 유지, 느린 RAG만 백그라운드** ⭐ (권장 표준안)
   > ⚠️ PO를 **통째로 백그라운드로 옮기면 안 됨**: `_check_and_create_po_notifications`는 `rex.weight_kg/sets`를
   > 갱신해(`sessions.py:466-467`) "다음에 같은 운동 진입 시 올라간 중량 표시"를 책임진다. 통째 백그라운드화하면
   > ① 직후 재진입 시 옛 중량이 보이는 staleness 창, ② 두 세션 연속 종료 시 같은 rex에 이중 PO 쓰는 레이스가 생긴다.
   - **느린 건 오직 `rag_po_increment`(ChromaDB+LLM) 하나**이고, 그건 증가량 **%의 정밀화**만 담당한다.
     트리거 판정(`po.check_po_trigger`)·기본 증가량(`po.py` 하드코딩)·rex bump·알림 생성은 전부 **순수 계산/DB라 즉시** 끝난다.
   - **동기 (finish 안, 빠름 — 이번 세션 정확성 보장)**: 트리거 판정 → `calculate_increase`(RAG **캐시 히트면 논문값,
     미스면 하드코딩값**) → `rex.weight_kg/sets` 반영 + 알림 생성 → 커밋·반환. **RAG를 절대 기다리지 않는다.**
   - **백그라운드 (느림 — 캐시 미스일 때만, 이번 세션과 무관)**: 미스였던 `(goal, equipment_type)`의
     `rag_po_increment`를 백그라운드로 호출해 **인메모리 캐시만 데움** → **다음 finish부터** 논문 기반 증가량 적용.
     (캐시는 7일 TTL·~20조합·ECS 단일 프로세스 → 워밍 후 네트워크 0회)
   - 효과: 무한 로딩 제거 + PO 즉시 반영(누락·레이스 없음) + 논문 정밀도는 "다음다음 세션"에서 점진 적용.
2. **[RC-1 보강] 타임아웃은 PO 경로 한정으로만 (공유 코드·클라이언트 전역 금지 — §5 불가침 제약)**
   - ❌ `llm.generate()`/`generate_stream`/캐시 클라이언트(`_get_gemini`/`_get_openai`)에 전역 `timeout=` 금지
     → 루틴 생성·챗봇 스트리밍이 잘린다.
   - ✅ 백그라운드 캐시워밍 내부에서 **PO 전용** scoped 상한만(예: `asyncio.wait_for`). 단 `to_thread`는 스레드를
     강제 취소 못 하므로(스레드 누수) 실제 차단은 SDK-레벨 timeout이 정석. 백그라운드라 사용자 영향은 0.
   - ✅ `apiFetch`에 `AbortController` 기반 클라 타임아웃(예: 20~30초)을 **2차 안전망**으로 추가(단독 해법 아님 — 세션은
     이미 COMPLETED 커밋되므로 RC-2 멱등화와 병행 필수).
3. **[RC-2 핵심] finish 멱등화 + 클라이언트 복구 경로**
   - 서버: 이미 COMPLETED인 세션에 finish를 다시 호출하면 409 대신 **현재 완료 상태를 그대로 200으로 반환**(멱등).
   - 클라이언트: finish가 "이미 완료/409"로 오면 이를 **성공으로 간주**해 `ws_clear()` + 화면 종료로 복구.
   - 또는 재진입 시 `GET /sessions/active`(이미 존재, `sessions.py:1075`)로 진행 중 세션 유무를 확인해
     완료된 SID를 스토어에서 제거.
4. **[RC-3] 에러 메시지 정확화 + 세트 기록 신뢰성**
   - 409(상태 충돌)와 네트워크 오류를 구분해 메시지를 다르게 노출.
   - fire-and-forget 세트 기록에 재시도/큐 또는 완료 시 일괄 동기화 보강 검토.
5. **[RC-1 동반/프론트] finish 후 `["routine", routine_id]` 캐시 무효화 추가**
   - 현재 `do_finish`는 sessions/stats/volume/notifications만 invalidate하고 **루틴 상세는 무효화하지 않는다**
     (`WR04RoutineDetail.tsx:723-727`). 동기로 `rex.weight_kg`를 올려도 React Query가 옛 루틴 캐시를 보여줄 수 있다.
   - finish 성공 시 `query_client.invalidateQueries({ queryKey: ["routine", routine_id] })`를 추가해야
     "다음 진입 시 올라간 중량" 정책(`sessions.py:465` 주석)이 실제로 보인다.
6. **[부수] 성공 경로 `is_finishing` 정리**
   - `do_finish` 성공 시 `set_is_finishing(false)`가 없다(`WR04RoutineDetail.tsx:717-728`).
     `navigation.goBack()`로 언마운트되면 가려지지만, 언마운트되지 않는 내비게이션 구성에선 잠재적 스피너 잔존.
     `finally`로 정리하는 편이 안전.

---

## 6. 증거 파일·라인 인덱스

| 항목 | 위치 |
|---|---|
| finish: COMPLETED 커밋 | `server/app/api/v1/sessions.py:525-526` |
| finish: 동기 PO/RAG 호출 | `server/app/api/v1/sessions.py:561` |
| finish: "이미 종료된 세션입니다" 409 | `server/app/api/v1/sessions.py:516-517` |
| log_set: "이미 종료된 세션…" 409 | `server/app/api/v1/sessions.py:260-261` |
| PO 루프 내 RAG await | `server/app/api/v1/sessions.py:406, 453` |
| RAG: ChromaDB + LLM | `server/app/services/po_rag.py:109, 116` |
| LLM: 타임아웃 부재 + Gemini→OpenAI fallback | `server/app/services/llm.py:68-94` |
| 클라: apiFetch 타임아웃 부재 | `app/src/services/api.ts:56-59` |
| 클라: do_finish (await finish, ws_clear) | `app/src/screens/main/WR04RoutineDetail.tsx:702-735` |
| 클라: 세트 기록 fire-and-forget + 오진단 메시지 | `app/src/screens/main/WR04RoutineDetail.tsx:324-354` |
| 클라: 수정은 로컬 state만 변경 | `app/src/screens/main/WR04RoutineDetail.tsx:362-380` |
| 클라: 재진입 시 완료 SID 복원 | `app/src/screens/main/WR04RoutineDetail.tsx:222-237` |
| 스토어: clear는 finish 성공 시에만 | `app/src/stores/workoutSessionStore.ts:62-71` + `WR04RoutineDetail.tsx:722` |

---

## 7. Codex 독립 2차 검증 결과 (2026-06-07)

`codex exec -s read-only`로 본 보고서를 코드와 대조 검증. 요지: **메인 인과 체인은 근본적으로 정확**.

### 7.1 3대 근본 원인 판정

| 항목 | 판정 | 근거 |
|---|---|---|
| RC-1 | **부분 확인** | 메커니즘은 사실(`sessions.py:524-526` 커밋 → `:561` PO/RAG, `api.ts:56-59` 타임아웃 없음). 단 RAG/LLM은 **PO 트리거 시에만** 실행되므로 "모든 재현에서 발생"은 과장. §4가 이 조건을 정직하게 밝힌 점은 타당. RAG 경로의 느린 부분은 LLM뿐 아니라 **ChromaDB 검색+임베딩**(`po_rag.py:109` → `rag.py:194-205`)도 타임아웃이 없음 |
| RC-2 | **확정** | `WR04RoutineDetail.tsx:717-723`(성공 시에만 clear), `:222-225`(재진입 복원), `sessions.py:516-517`·`260-261`(409) |
| RC-3 | **확정** | fire-and-forget(`:325-339`) + 동일 alert(`:347-352`). `apiFetch`는 409 메시지를 보존하는데(`api.ts:91-95`) catch가 뭉갬 |

### 7.2 보고서가 놓친 추가 결함 (Codex 발견)

- **🔴 RC-4 — finish가 진행 중 세트 기록을 기다리지 않는 별도 레이스**:
  `do_finish`는 미완료 `logSet` 프로미스를 await하지 않고 즉시 `finishSession`을 호출
  (`WR04RoutineDetail.tsx:702-722`). 따라서 **뒤로 가기/재진입 없이도** 마지막 세트의 늦은 logSet이
  완료된 세션에 도달해 409 → "세트 기록 실패"가 발생할 수 있다. 증상 5의 더 흔한 경로.
- **🟠 체크 해제가 서버 기록을 되돌리지 않음 + 중복 적재 가능**:
  uncheck는 로컬 타이머만 정지(`:355-359`)하고 서버엔 반영 안 됨. `log_set`은 항상 새 행을 insert
  (`sessions.py:266-277`)하며 `(workout_log_id, routine_exercise_id, set_number)` 유니크 제약이 없다
  (`workout.py:44-62`) → 같은 세트 재체크 시 **중복 행**.
- **🟠 낙관적 스토어가 거짓말**: `ws_toggle_set`는 서버 ack 전에 실행(`:317`)되고 실패해도
  롤백하지 않아(catch는 alert만), 저장 안 된 세트가 체크된 채 남는다.
- **순수 클라이언트발 무한 스피너는 없음** 확인: 성공 경로 `is_finishing` 누수(§5.5)는 실재하나
  단독으로 "hang"을 설명하진 못함 → RC-1(서버 지연)이 무한 로딩의 주원인이라는 점 재확인.

### 7.3 수정안 보강 (Codex)

- PO/RAG를 동기 경로에서 분리할 때 **요청 스코프 `db`를 응답 이후 재사용 금지** → 새 DB 세션/잡 큐 사용.
- 서버 타임아웃은 **ChromaDB·임베딩 검색과 LLM 호출 양쪽** 모두 감싸야 함. 클라 타임아웃만으로는
  세션이 이미 COMPLETED 커밋된 상태라 불충분.
- `/sessions/active` 기반 복구는 한계가 있음 — **`start_session`이 멱등이 아니라**
  항상 새 `WorkoutLog`를 insert(`sessions.py:223-231`)하고 `/active`는 최신 1건만 반환(`:1087-1096`)하므로
  활성 세션이 여러 개 생길 수 있다.
- RC-3 최선책: 단순 재시도/큐보다 **pending set-log 프로미스를 추적해 finish가 끝날 때까지 await**.

---

## 8. 멀티에이전트 적대적 감사 (ultracode workflow, 2026-06-07)

6개 차원 병렬 리뷰 → high/critical 적대적 검증 → 종합. **제안 6요소 설계가 실제 코드에서 만들 새 문제**를 탐색.
총 35건 발견, high/critical 9건 검증(확인 4 / 부분확인 4 / 반증 1).

### 8.1 총평
설계 방향은 건전(무한로딩·409연쇄 해결됨). 단 **구현 전 반드시 막아야 할 항목**이 있고, 특히
"타임아웃/멱등화를 따로 떼면 고아 세션이 오히려 재발"하는 결합 의존성이 확인됐다.

### 8.2 🔴 구현 전 필수 (confirmed / partial-confirmed)

| ID | 차원 | 판정 | 무엇이 깨지나 | 처방 |
|---|---|---|---|---|
| **po-no-readonly-entrypoint** | PO분해 | ✅확인(high) | `po_rag` 공개함수는 `rag_po_increment` 하나뿐 — 캐시 미스 시 **무조건 ChromaDB+LLM 실행**(po_rag.py:95-130). 동기 경로가 이걸 부르면 분해해도 **그대로 블로킹** | 캐시-읽기 전용 진입점 신설(`_cache_get`+`_convert_to_kg` 래퍼). 동기는 그것만, 미스면 하드코딩+백그라운드 워밍 |
| **abort-aborted-finish-orphan-after-commit** | apiFetch | ✅확인(med) | apiFetch 타임아웃이 finish를 끊어도 서버는 이미 COMPLETED 커밋 → 클라가 실패로 오인 → `ws_clear` 미실행 → **고아 세션 재발**(WR04:717-722 vs sessions.py:525-526) | 타임아웃/abort/409를 **"완료 가능성"으로 간주** → `/sessions/active` 확인 or 멱등 finish 재호출로 복구. 타임아웃은 멱등화와 **반드시 묶어서** |
| **rc4-dropped-logset-409-alert** | RC-4 | ✅확인(med) | bounded await로 **버린** logSet이 완료 세션에 409 → 무조건 Alert(WR04:347-353)가 언마운트 후 뜸 → 증상5 부분 재현 | logSet `.catch`가 409/abort/언마운트를 구분해 alert 억제. 또는 logSet에 mount-guard/abort |
| **be-already-completed-200-dto-recompute** | 멱등화 | ◑부분(med) | 멱등 200 반환 시 `_session_to_dto`는 total_sets/completed_exercises/calories를 **안 채움**(None 디폴트, sessions.py:102-121) → 빈 DTO or PO 재실행 위험 | 멱등 경로에 DTO 집계 재계산 전용 분기. PO는 절대 재실행 안 함 |
| **be-double-po-race-same-rex** | 멱등화 | ✅확인(med) | 원자 전이는 **같은 session_id**만 디둡. 서로 다른 세션 A·B를 연속 종료하면 각자 PO 실행 → 같은 rex 이중 bump(sessions.py:343-358,466-467) | rex bump를 prev-session 기준 멱등 계산 or 짧은 시간 내 동일 rex 재-PO 가드 |

### 8.3 🟠 사용자가 직접 지목한 두 프론트 변경 — 판정

- **`invalidate(["routine", routine_id])` (요소6 전반)** → ◑ **대체로 무해하나 의도대로 작동 안 함**.
  WR04는 native-stack 별도 화면이라 `goBack()`이 언마운트하고, `["routine", routine_id]`의 active observer는
  WR04 자신뿐이다(fe-invalidate-routine-no-active-observer, low). 언마운트 후 invalidate는 **즉시 refetch를
  유발하지 않고 캐시만 stale 표시** → "완료 후 신선한 detail" 효과 없음. 무서워한 체크풀림 플리커는 **안 남**
  (언마운트라 useEffect 재실행 불가). → 굳이 invalidate 안 해도 **재진입 시 staleTime에 따라 자연 refetch**되므로,
  깔끔하려면 invalidate 대신 **재진입 refetch에 맡기거나** 루틴 캐시를 낙관적 업데이트.
- **`is_finishing` finally 정리 (요소6 후반)** → 🔴 **진짜 새 회귀**(fe-finally-setstate-after-unmount, med).
  성공 경로는 try 안에서 `goBack()` 후 finally가 `set_is_finishing(false)` 호출 → **언마운트된 컴포넌트에 setState
  경고**. 게다가 goBack 지연 구성에선 버튼이 잠깐 재활성 → 이중 finish 탭(→409). → finally 무지성 추가 금지.
  `isMountedRef` 가드 or "성공 시 reset 안 함(이탈), 에러 시만 reset"(현행 catch 유지)이 안전.

### 8.4 🟠 기타 주의 (비-blocking)
- `be-returning-orm-stale-instance`(med): RETURNING UPDATE 후 ORM 인스턴스 status/finished_at refresh 필요.
- `be-po-second-commit-partial-failure`(med): 원자 전이 commit + PO line-501 commit 분리 → PO 예외 시 부분 적용.
- `po-cache-reset-per-deploy`(med): 인메모리 캐시는 배포마다 리셋 → "다음 finish부터 논문값" 실효성↓. 시작 시/크론 프리워밍 권장.
- `po-mixed-source-same-session`(med): 같은 세션 내 논문값/하드코딩값 혼용 → 증가량 비일관·비단조 가능.
- `uniqueness-gap-untouched`(med): uncheck 미반영 + 유니크 제약 부재 → 중복 세트 행 → 볼륨/통계/PO 집계 부풀림(이번 수정 범위 밖, 별도 트랙).
- `optimistic-store-no-rollback`(med): RC-3는 메시지만 분기, 낙관적 스토어 실패 롤백은 여전히 누락.
- `abort-ocr-inbody-false-cut`(med): InBody Vision OCR(`ocrInbody`)도 **apiFetch 경유** → 전역 타임아웃이 OCR을 오탐 abort 가능. 타임아웃 값/예외 처리 시 OCR 고려.
- `rc4-ensure-session-not-awaited`(med): 마지막 세트 직후 즉시 완료 시 `session_promise_ref` in-flight 미대기로 no-op 가능.

### 8.5 ⚪ 반증된 발견
- `be-rex-bump-zero-notif-not-committed`: rex bump 후 if/else **양쪽 모두** Notification을 append하므로 항상 커밋됨 → "중량 미반영" 주장 성립 안 함.

### 8.6 ✅ 안전 구현 체크리스트 (순서)
1. **po_rag에 캐시-읽기 전용 진입점 신설** → 동기 경로는 절대 네트워크 안 탐.
2. **원자 전이 + 멱등화 + DTO 재계산 분기** 한 묶음으로(부분 적용·stale ORM·이중 PO 가드 포함).
3. **apiFetch 타임아웃은 멱등화와 함께** + abort를 "완료 가능성"으로 복구(고아 재발 방지) + OCR 예외 고려.
4. **logSet `.catch` 409/abort/언마운트 구분** (RC-4 bounded await만으론 부족).
5. **프론트**: `is_finishing`는 `isMountedRef` 가드(무지성 finally 금지). `["routine"]`은 재진입 refetch에 위임 or 낙관적 업데이트.
6. 별도 트랙(이번 핫픽스 밖): 중복 세트 행 유니크 제약 + uncheck 반영, 낙관적 스토어 롤백.

---

## 7-bis. (참고) §7.4 Codex 결론
### 7.4 최종 결론 (Codex)

> 진단은 핵심 "고아 세션" 체인에 대해 근본적으로 정확하다. 가장 큰 과장은 RC-1의 도달성(RAG/LLM은 PO 트리거 조건부).
> **단일 최우선 수정**: `PATCH /sessions/{id}/finish`가 완료 커밋 직후 즉시 반환하고
> `_check_and_create_po_notifications`를 요청 경로 밖으로 빼거나 짧게 바운드할 것.
> 그다음 **finish 멱등화** — 클라 타임아웃/재시도만으로는 동일한 고아-완료 세션 상태가 계속 재발한다.

---

## 9. 확정 설계 (hardened — §8 감사 발견 전부 반영)

> 설계 원칙: **finish 엔드포인트는 "상태 전이(원자·멱등)"만 책임진다.** DTO는 항상 재계산(read),
> PO는 전이 선점자만 동기·논블로킹으로, 느린 RAG는 캐시 워밍으로 분리.

### 9.1 백엔드 finish 재구성 (원자 claim + 멱등 + 조건부 PO)
```python
async def finish_session(...):
    s0 = await _get_my_session(session_id, current_user, db)      # 404 게이트(소유권) + started_at 확보
    candidate = _resolve_finished_at(body.finished_at, s0.started_at)  # started_at<= 보정 선반영
    claimed = (await db.execute(
        update(WorkoutLog)
        .where(WorkoutLog.id == s0.id,
               WorkoutLog.user_id == current_user.id,
               WorkoutLog.status == WorkoutStatus.IN_PROGRESS)      # ← 원자 전이: 선점자만 1행
        .values(status=WorkoutStatus.COMPLETED, finished_at=candidate)
        .returning(WorkoutLog.id)
    )).scalar_one_or_none()
    await db.commit()                                              # COMPLETED 먼저 durable (PO 실패와 무관)

    s = await _get_my_session(session_id, current_user, db)        # stale ORM 방지: 신선 재로드
    dto = await _build_finish_dto(s, current_user, db)             # total_sets/calories 항상 재계산(멱등 200 경로 포함)

    if claimed is not None:                                        # 전이 선점자만 PO (재-finish 시 이중 PO 차단)
        try:
            warm_keys = await _apply_po_sync(s, current_user, db)  # 캐시-읽기 전용 증가량 + rex bump + 알림 dedup
            await db.commit()
        except Exception:
            logger.warning("PO 후처리 실패 (세션은 이미 COMPLETED)", ...)  # best-effort
        for (goal, lm) in warm_keys:
            background_tasks.add_task(po_rag.warm_po_cache, goal, lm)  # 느린 RAG는 응답 후 캐시만 워밍(DB 미사용)
    return SuccessResponse(data=dto)
```
- **해결**: be-already-completed-200-dto(항상 재계산), be-returning-orm-stale(재로드), be-po-second-commit-partial(COMPLETED 선커밋·PO best-effort), TOCTOU 더블탭(원자 claim).

### 9.2 po_rag — 캐시-읽기 전용 진입점 + 프리워밍 (po-no-readonly-entrypoint)
```python
def po_increment_cached(goal, equipment_type, user_1rm_kg) -> tuple[float|None, bool]:
    """동기·논블로킹. (kg|None, cache_warm). 네트워크 절대 안 탐."""
    hit, pct = _cache_get(goal, equipment_type)
    if not hit: return None, False                 # 미스 → 호출자는 po.py 하드코딩
    if pct is None or user_1rm_kg is None: return None, True
    return _convert_to_kg(pct, user_1rm_kg), True

_warming: set[tuple[str,str]] = set()
async def warm_po_cache(goal, equipment_type):     # 백그라운드 전용, DB 미사용, 예외 자체 처리
    key=(goal,equipment_type)
    if _cache_get(*key)[0] or key in _warming: return   # in-flight dedup
    _warming.add(key)
    try: await rag_po_increment(goal, equipment_type, None)  # 캐시만 채움
    finally: _warming.discard(key)
```
- **시작 시 프리워밍**(FastAPI lifespan에서 `create_task`로 모든 goal×load_mode 조합 워밍) → 배포 직후/요청 경로에서 RAG를 사실상 0회. **해결**: po-cache-reset-per-deploy, po-mixed-source-same-session(워밍 후 일관), po-bg-warm-dedup.

### 9.3 PO 멱등성·이중 알림 (be-double-po-race 재평가)
- rex bump는 `result["new_weight"] = 세션 로그 max_weight + 증가량`으로 **세션 자체 기록값 기반**(sessions.py:324,459) → 같은 무게로 수행한 두 세션이 동시 트리거해도 **동일 값 set = 비복합(idempotent)**. ⇒ 중량 손상은 없음, 잔여는 **중복 PO 알림**뿐.
- **처방**: 동일 rex에 대해 **미확인(unread) PO 알림이 이미 있으면 새로 만들지 않음**(또는 짧은 윈도우 dedup). → be-double-po-race를 중복알림 제거로 종결.

### 9.4 apiFetch — 타입드 에러 + per-request 타임아웃 + abort 복구 (abort-* 군)
- `ApiError extends Error { status:number; code?:string; aborted?:boolean }` 도입 → 호출자가 409/네트워크/abort 분기 가능(RC-3·RC-4 동시 해결).
- `AbortController` 타임아웃을 **per-request 옵션**(`timeoutMs`)으로. 기본 30s, **OCR(`ocrInbody`)은 60s/예외**(abort-ocr-inbody), **SSE(루틴생성·챗봇)는 apiFetch 미경유라 무영향**(확인됨).
- **401 refresh 재시도 시 새 컨트롤러/타이머**로 예산 재설정(abort-401-budget).
- **do_finish 복구**: abort/타임아웃/`409 이미 종료`는 **"완료됐을 가능성"으로 간주** → 멱등 finish 1회 재시도(→200) 또는 `GET /sessions/active`로 확인 → 완료 확인 시 `ws_clear()`+goBack. **해결**: abort-aborted-finish-orphan(고아 재발 차단).

### 9.5 세트 기록 — 추적·bounded await·409/abort 구분·낙관적 롤백 (rc4-*, RC-3)
- toggle_set_done이 logSet 프로미스를 `pending_logsets` ref에 push, `.finally`로 제거(누수 방지).
- **finish 시작 시 신규 세트 체크 차단**(`finishing` 플래그) → 스냅샷 이후 늦은 logSet 없음(rc4-snapshot-race).
- do_finish는 `ensure_session()`의 in-flight를 **await**(703 조기반환 대신)(rc4-ensure-session) → `Promise.allSettled(pending)` + 3~5s 상한 → finishSession.
- logSet `.catch`는 `ApiError.status`로 분기: **409/abort/언마운트 → alert 억제**, **진짜 네트워크 오류만 alert + `ws_toggle_set(set_id,false)` 롤백**(optimistic-store-no-rollback). **해결**: rc4-dropped-logset-409, RC-3.

### 9.6 프론트 — is_finishing·["routine"] (사용자 지목 2건)
- `isMountedRef`(언마운트 cleanup에서 false) 가드. **무지성 finally 금지** — 성공은 이탈(리셋 불필요), 에러만 `if(isMountedRef.current) set_is_finishing(false)`. **해결**: fe-finally-setstate-after-unmount + 이중탭 윈도우.
- `["routine", routine_id]` invalidate는 **유지**: 언마운트 후 즉시 refetch는 없지만 **stale 표시 → 재진입 mount 시 refetch**되어 올라간 중량이 보임(의도 충족). 관찰자는 WR04뿐이라 타 화면 플리커 없음.

### 9.7 별도 트랙 (이번 핫픽스 밖, 데이터 정합성)
- `UNIQUE(workout_log_id, routine_exercise_id, set_number)` 추가(Alembic) + log_set을 **UPSERT**로 + **uncheck → DELETE/PATCH** 엔드포인트. → 중복 행·볼륨/통계/PO 집계 오염·낙관적 스토어 진실성 일괄 해결(uniqueness-gap, po-sync-duplicate-pollution).

### 9.8 감사 발견 → 처방 매핑
| 발견 | 처방(§) |
|---|---|
| po-no-readonly-entrypoint (high✅) | 9.2 캐시-읽기 진입점 |
| abort-aborted-finish-orphan (med✅) | 9.4 abort 복구 + 9.1 멱등 |
| rc4-dropped-logset-409 (med✅) | 9.5 ApiError 분기 |
| be-already-completed-200-dto (med◑) | 9.1 DTO 항상 재계산 |
| be-double-po-race (med✅) | 9.3 비복합 + 알림 dedup |
| fe-finally-setstate (med) | 9.6 isMountedRef |
| be-returning-orm-stale / partial-commit | 9.1 재로드 / 선커밋 |
| po-cache-reset / mixed-source | 9.2 시작 프리워밍 |
| abort-ocr / abort-401 | 9.4 per-request·새 컨트롤러 |
| uniqueness-gap / optimistic-rollback / duplicate-pollution | 9.5 롤백 + 9.7 UPSERT |
| be-rex-bump-zero-notif (반증) | 조치 불요 |

### 9.9 변경 파일 범위 (불가침 제약 재확인)
- 백엔드: `sessions.py`(finish/PO), `po_rag.py`(진입점·워밍), `app/main.py`(lifespan 프리워밍), (별도) Alembic + `workout.py`.
- 프론트: `WR04RoutineDetail.tsx`, `services/api.ts`(ApiError·timeout), `services/sessions.ts`.
- **불변**: `llm.py`/`rag.py`(`generate`·`generate_stream`·`search_chunks`)·캐시 클라이언트·루틴생성/챗봇 경로 — 한 줄도 안 건드림.
