# 운동 완료(finish) 버그 핫픽스 — 설계 스펙

- **작성일**: 2026-06-07 (rev2 — 멀티에이전트 스펙 감사 blocking 7건 + nonblocking 7건 반영)
- **범위**: 핫픽스 코어 (DB 마이그레이션 없음). 중복 세트 행 정합성은 **후속 PR**로 분리.
- **진단 근거**: `docs/handoff/2026-06-07-workout-finish-infinite-loading-diagnosis.md` (§1~9, Codex 검증 + 멀티에이전트 적대적 감사)
- **불가침 제약**: 루틴 생성·논문 검색(챗봇 RAG)·OCR 외 LLM 공유 코드를 절대 막거나 저하시키지 않는다.

---

## 1. 문제 (요약)

"운동 완료"가 **무한 로딩** → 재진입 시 **"이미 종료된 세션"** → 세트 재기록 시 **"세트가 서버에 저장되지 않았습니다"**. 세 증상은 하나의 인과 체인.

**근본 원인**:
- **RC-1**: `PATCH /sessions/{id}/finish`가 `status=COMPLETED` 커밋 **후** 응답 전에 PO/RAG(ChromaDB+LLM, 타임아웃 없음)를 **동기 실행**. 클라 `apiFetch`도 타임아웃 없음 → 무한 대기.
- **RC-2**: 서버는 완료됐는데 클라가 응답을 못 받아 **완료된 session_id를 영속 보관**(`ws_clear`는 성공 응답 시에만). 재진입 시 복원 → finish/logSet **409 연쇄**.
- **RC-3/RC-4**: 세트 기록이 fire-and-forget + 409를 "네트워크 오류"로 오안내. `do_finish`가 진행 중 logSet을 기다리지 않음.

---

## 2. 설계 원칙

> **finish 엔드포인트는 "상태 전이(원자·멱등)"만 책임진다.** DTO는 항상 재계산(read), PO 부수효과는 전이 선점자만 동기·논블로킹으로, 느린 RAG는 캐시 워밍으로 분리.

확정된 미세 결정(YAGNI — **본 §2가 정본**):
- PO 캐시 워밍은 **요청 시 캐시 미스만 백그라운드 워밍**. 시작 시 전체 프리워밍·`app/main.py` lifespan 변경은 **하지 않는다**. (배포 직후 첫 miss가 "기본값" 표기되는 점은 수용 — §8)
- abort/실패 복구는 **멱등 finish 1회 재시도**로 처리. `/sessions/active` 폴링·신규 엔드포인트는 추가하지 않는다.
- **`409 = 항상 비-에러`**가 sessions 도메인 불변식: finish의 409는 "이미 완료됨"(success 취급), logSet의 409는 "완료 세션에 세트 추가 불가"(alert 억제 대상). 둘 다 사용자에게 에러로 노출하지 않는다.

---

## 3. 백엔드 설계

### 3.1 `finish_session` 재구성 — 원자 전이 + 멱등 + 조건부 PO
`server/app/api/v1/sessions.py`

```python
from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request   # BackgroundTasks 추가
from sqlalchemy import update

@router.patch("/{session_id}/finish", response_model=SuccessResponse[SessionData], summary="세션 종료")
@rate_limit("60/minute")
async def finish_session(request, session_id, body, background_tasks: BackgroundTasks,
                         current_user=Depends(get_required_profile), db=Depends(get_db)):
    s0 = await _get_my_session(session_id, current_user, db)        # 404 게이트 + started_at 확보
    candidate = _resolve_finished_at(body.finished_at, s0.started_at)

    claimed = (await db.execute(
        update(WorkoutLog)
        .where(WorkoutLog.id == s0.id,
               WorkoutLog.user_id == current_user.id,
               WorkoutLog.status == WorkoutStatus.IN_PROGRESS)       # 원자 전이: 선점자만 1행
        .values(status=WorkoutStatus.COMPLETED, finished_at=candidate)
        .returning(WorkoutLog.id)
    )).scalar_one_or_none()
    await db.commit()                                                # COMPLETED 먼저 durable

    db.expire_all()
    s = await _get_my_session(session_id, current_user, db)          # 신선 재로드(stale ORM 방지)
    dto = await _build_finish_dto(s, current_user, db)               # 항상 재계산(멱등 200 경로 포함)

    if claimed is not None:                                          # 전이 선점자만 PO
        warm_keys: set[tuple[str, str]] = set()                     # ← 선초기화(except NameError 차단)
        try:
            warm_keys = await _apply_po(s, current_user, db)        # bump+알림 ORM staged만 (commit 안 함)
            await db.commit()                                       # PO 변경을 단일 트랜잭션 커밋
        except Exception:
            await db.rollback()                                     # PO staged 전체 폐기(COMPLETED는 durable, 무영향)
            warm_keys = set()
            logger.warning("PO 후처리 실패 (세션은 이미 COMPLETED) request_id=%s", _rid(request))
        for (goal, lm) in warm_keys:
            background_tasks.add_task(po_rag.warm_po_cache, goal, lm)
    return SuccessResponse(data=dto)
```

**필수 정정 (산문 — 의사코드만 보고 구현 시 누락 위험)**:
- **기존 `sessions.py:516-517`의 `if s.status == WorkoutStatus.COMPLETED: raise ConflictError("이미 종료된 세션입니다.")` 가드를 삭제**한다. 멱등성은 원자 UPDATE의 `claimed is None` 분기로만 처리(이미 완료면 PO 건너뛰고 재계산 DTO를 200 반환). 이 가드를 남기면 멱등 재호출이 여전히 409 → AC#2/#3 깨짐.
- **`log_set`의 409(`sessions.py:260-261`)는 유지**한다 — 완료 세션 세트 추가 차단은 정상이며, 클라가 §4.4에서 억제한다.
- `finish_session`의 응답 모델/시그니처는 `background_tasks: BackgroundTasks` 파라미터 추가 외 외부 계약 불변(body=`FinishSessionRequest`, 응답=`SuccessResponse[SessionData]`).

**헬퍼 추출(기존 로직 1:1 이전)**:
- `_resolve_finished_at(finished_at, started_at)`: 기존 519-523("finished_at ≤ started_at → 서버시간 대체"). UPDATE의 SET 값으로 선반영.
- `_build_finish_dto(s, user, db)`: 기존 529-559(total_sets / completed_exercises / total_calories 집계 + duration + latest measurement). **claimed 여부 무관 항상 재계산**. PO를 **재호출하지 않음**.
- `_apply_po(s, user, db)`: 기존 `_check_and_create_po_notifications`를 리네임. **내부에서 `db.commit()`하지 않는다**(기존 498-501의 `if new_notifications:` commit 가드 제거). rex bump + 알림 ORM 추가만 수행하고 **캐시 미스였던 `(goal, load_mode)` 집합(`warm_keys`)을 반환**. 커밋은 호출부 단일 지점.

### 3.2 PO 분해 — `_apply_po` 내부 증가량 조회
`server/app/api/v1/sessions.py` (PO 루프)

기존 `increment_override = await po_rag.rag_po_increment(goal, category, user_1rm_kg)` (네트워크 블로킹)
→ 변경:
```python
increment_override, cache_warm = po_rag.po_increment_cached(goal, category, user_1rm_kg)  # 논블로킹
if not cache_warm:
    warm_keys.add((goal, category))
po_source = "논문 기반" if increment_override is not None else "기본값"
```
나머지(`po.calculate_increase`, `rex.weight_kg/sets` 반영, overflow 분기)는 동일.

### 3.3 `po_rag` 신규 진입점
`server/app/services/po_rag.py`

```python
def po_increment_cached(goal, equipment_type, user_1rm_kg) -> tuple[float | None, bool]:
    """동기·논블로킹. (kg|None, cache_warm). 네트워크 절대 안 탐. _cache_get만 호출."""
    hit, pct = _cache_get(goal, equipment_type)
    if not hit:
        return None, False                       # 미스 → 호출자는 po.py 하드코딩 + warm_keys 적재
    if pct is None or user_1rm_kg is None:
        return None, True                        # 근거 없음 OR 1RM 없음 → 하드코딩, 단 캐시는 warm
    return _convert_to_kg(pct, user_1rm_kg), True

_warming: set[tuple[str, str]] = set()

async def warm_po_cache(goal, equipment_type) -> None:
    """백그라운드 전용. DB 미사용. 예외 자체 처리. 동일 키 in-flight dedup."""
    key = (goal, equipment_type)
    if _cache_get(*key)[0] or key in _warming:
        return
    _warming.add(key)
    try:
        await rag_po_increment(goal, equipment_type, None)   # _cache_set만 채움 (반환값 무시)
    finally:
        _warming.discard(key)
```
- `(None, True)`는 두 경우(논문 근거 없음 pct=None / 1RM 미보유)를 합쳐 반환한다. 즉 **1RM 미보유 사용자는 워밍돼도 "기본값" 표기**(기존 `rag_po_increment`와 동일 동작 → 회귀 아님). AC#6은 "1RM 기록된 사용자 한정"으로 한정한다.
- 기존 `rag_po_increment`는 그대로 두되, 동기 경로(`_apply_po`)에서는 **더 이상 직접 호출하지 않는다**(워밍만 재사용).

### 3.4 PO 멱등성·이중 알림
- `rex.weight_kg = 세션 로그 max_weight + 증가량`은 **세션 자체 기록값 기반**이라, 동일 무게로 수행한 두 세션이 트리거해도 같은 값 set = **비복합(idempotent)**. 중량 손상 없음.
- 잔여(서로 다른 세션 **순차** 종료 시 중복 PO 알림): **`_apply_po` 루프 진입 전 1회 일괄 SELECT**로 이 사용자의 미확인 PO 알림 rex 집합을 구한다 — 조건 `type == PO_SUGGESTION AND is_read == False AND data_json->>'routine_exercise_id' == str(rex_id)`. append 시 그 집합에 이미 있으면 **새 알림 생성 생략**.
- **한정 명시**: 핫픽스는 **순차 종료 중복만** 제거한다. 진정한 동시 종료 레이스(SELECT-then-insert)나 부분 유니크 제약은 **후속 트랙**(§8).

---

## 4. 클라이언트 설계

### 4.1 `ApiError` 타입드 에러
`app/src/services/api.ts`
```ts
export class ApiError extends Error {
  status: number;        // HTTP 상태. abort/네트워크 단절은 0.
  code?: string;         // 서버 error.code (옵셔널, 분기 결정에는 미사용)
  aborted?: boolean;     // AbortController 타임아웃/취소
  constructor(message: string, opts: { status: number; code?: string; aborted?: boolean }) { super(message); ... }
}
```
- `apiFetch`가 실패 시 `Error` 대신 `ApiError`를 던진다. 비-JSON/네트워크/abort/HTTP 에러 모두 분류.
- **분기는 `status===409 || aborted`로만 판단**(`code` 비의존). finish/log_set의 409는 서버 default `code='CONFLICT'`라 세분 식별 불가 — 전용 code(`SESSION_COMPLETED`)는 후속 PR.
- ⚠️ **회귀 주의**: 기존 모든 `apiFetch` 호출부의 `catch (e) { e.message }` 사용이 깨지지 않도록 `ApiError extends Error`로 `.message` 호환 유지.

### 4.2 per-request 타임아웃 (AbortController)
`app/src/services/api.ts`, `app/src/services/users.ts`
- `apiFetch` 시그니처를 `RequestInit & { token?: string; timeoutMs?: number }`로 확장. `timeoutMs`(기본 30000)를 `AbortController`에 연결, 타임아웃 시 `ApiError({status:0, aborted:true})`.
- `send(authToken, signal)`로 변경 — **매 시도(원요청·refresh 후 재시도)마다 새 AbortController.signal 주입**(재사용 금지).
- **401 refresh 재시도**(api.ts 59-75)는 새 컨트롤러/타이머로 재설정(원요청 예산 소진 방지).
- **OCR**: `ocrInbody`(users.ts) 내부에서 `apiFetch<...>(..., { method:"POST", token, body, timeoutMs: 60000 })`로 60s 전달(Vision OCR 정상 지연 보호). 호출부(WA03/WP02)는 변경 불필요 — 60s가 `ocrInbody`에 캡슐화됨.
- **SSE(루틴생성·챗봇)는 apiFetch 미경유**(raw fetch/XHR) → 무영향. 코드 변경 없음.

### 4.3 `do_finish` 복구 경로
`app/src/screens/main/WR04RoutineDetail.tsx`
- 진입 가드를 **`if (is_finishing) return;`로 축소**(기존 `!session_id_ref.current` 조기반환 제거). 세션 확보는 `const sid = await ensure_session();`에 위임, `finishSession`도 `sid` 사용.
- 정상: `await finishSession(token, sid, ...)` → `ws_clear()` → invalidate(["routine"], ["sessions"]...) → goBack. **`ws_clear()`+goBack은 단일 경로에서만**.
- **복구 분기 (ApiError 기준)**:
  - `status === 409` (finish 경로) → **무조건 success 취급** → ws_clear()+goBack. **절대 `Alert("오류","이미 종료된 세션입니다")` 노출 금지.**
  - `aborted || status === 0` (timeout/네트워크) → **멱등 finishSession 1회 재시도**. 200/409면 success. 재시도도 abort/네트워크면 → `if(isMountedRef.current) set_is_finishing(false)` + "복구 가능" 메시지, **goBack 안 함**.
  - `status === 401` (세션 만료, `aborted:false`) → **복구 대상 아님**. 재로그인 유도(apiFetch가 이미 clearAuth 처리). 멱등 재시도 금지.
  - `ensure_session()` 실패(진짜 세션 생성 불가) → catch에서 사용자 안내.

### 4.4 세트 기록 신뢰성 + handle_finish 게이트
`app/src/screens/main/WR04RoutineDetail.tsx`, `app/src/services/sessions.ts`
- **handle_finish 게이트 정정(738-745)**: `if (!session_id_ref.current && !session_promise_ref.current)`일 때만 "잠깐만요" alert. 즉 **둘 다 없을 때만** 진짜 미준비. in-flight(session_promise_ref 존재) 포함 그 외에는 do_finish 진입 허용 → "마지막 세트 직후 세션 생성 in-flight" 케이스가 §4.3 복구 경로에 도달.
- **pending_logsets**: `const pending_logsets = useRef(new Set<Promise<unknown>>())`. toggle_set_done의 `ensure_session().then(logSet…)` **외곽 체인**을 push, `.finally(() => pending_logsets.current.delete(p))`로 제거(누수 방지).
- **신규 체크 차단**: 전용 `const finishing_ref = useRef(false)`. do_finish 진입 시 `true`(복구 실패/언마운트 cleanup에서 `false`). **toggle_set_done 함수 최상단** `if (finishing_ref.current) return;`로 즉시 no-op — **ws_toggle_set(스토어 기록)과 logSet 발사 모두 차단**(logSet만 막고 스토어는 기록하는 절충 금지: 잔여 거짓 체크가 COMPLETED 세션과 영구 비동기화).
- **do_finish await**: `await ensure_session()` → `await Promise.race([Promise.allSettled([...pending_logsets.current]), timeout(4000)])` → finishSession.
- **logSet `.catch(e)`**: `e instanceof ApiError && (e.status===409 || e.aborted)` → **alert 억제**. 그 외(진짜 네트워크) → alert + **낙관적 롤백**. 롤백 시 `ws_toggle_set(set_id,false)` + `if (isMountedRef.current) set_exercises(...)`(로컬 is_done=false). **모든 비동기 setState는 isMountedRef 가드**.

### 4.5 프론트 상태 정리
`app/src/screens/main/WR04RoutineDetail.tsx`
- `const isMountedRef = useRef(true)` + 언마운트 cleanup에서 `false`.
- **`is_finishing` 무지성 finally 금지**. 성공/복구-goBack 경로는 리셋 불필요(이탈), **나머지 비동기 setState(`is_finishing` 리셋, logSet catch의 `set_exercises` 롤백 포함)는 전부 `if (isMountedRef.current)` 가드**.
- `["routine", routine_id]` invalidate **유지**: 언마운트 후 즉시 refetch는 없지만 stale 표시 → **재진입 mount 시 refetch**로 올라간 중량 표시. 관찰자는 WR04뿐이라 타 화면 플리커 없음.

---

## 5. 변경 파일 범위

**변경**:
- `server/app/api/v1/sessions.py` (finish 재구성, `BackgroundTasks` import, `_resolve_finished_at`/`_build_finish_dto`/`_apply_po` 추출, 516-517 가드 삭제, PO 증가량 조회 전환, 알림 dedup)
- `server/app/services/po_rag.py` (`po_increment_cached`, `warm_po_cache`, `_warming`)
- `app/src/services/api.ts` (`ApiError`, per-request 타임아웃, 401 재시도 새 컨트롤러)
- `app/src/services/sessions.ts` (필요 시 타임아웃 옵션 전달)
- `app/src/services/users.ts` (`ocrInbody`에 `timeoutMs: 60000` 전달)
- `app/src/screens/main/WR04RoutineDetail.tsx` (handle_finish 게이트, do_finish 복구, pending/finishing ref, isMountedRef, logSet catch 분기)

**절대 불변 (불가침 제약)**:
- `server/app/services/llm.py`(`generate`/`generate_stream`), `server/app/services/rag.py`(`search_chunks`/`routine_rag_stream`), 캐시 클라이언트(`_get_gemini`/`_get_openai`), 루틴생성·챗봇 경로 — 한 줄도 변경 없음.

---

## 6. 수용 기준 (Acceptance Criteria)

1. **(측정 가능)** PO 트리거가 걸리는 finish의 **동기 경로가 `search_chunks`/LLM(`_call_search_async`/`_call_llm_async`)을 호출하지 않는다** — 모킹 호출 카운트 0. (참고 SLO: 응답 <1s, 자동 합격 기준 아님)
2. "운동 완료"를 두 번(또는 abort 후 재시도) 눌러도 **409 없이** 완료 처리(멱등). PO 부수효과(알림)는 **1회만**.
3. 뒤로 갔다 재진입 후 완료를 눌러도 **"이미 종료된 세션" 에러가 사용자에게 노출되지 않는다**(409=success 취급 + 멱등).
4. 세트 기록이 409/abort로 실패해도 **"네트워크 확인" 오안내 alert가 뜨지 않는다**(진짜 네트워크 단절만 alert + 롤백).
5. PO 중량 bump가 **동기 커밋**되어, 완료 직후 같은 루틴 재진입 시 올라간 중량이 보인다(알림 0건 엣지에서도 bump 커밋됨).
6. **(1RM 기록된 사용자 한정)** 캐시 워밍 후 다음 finish부터 PO 알림이 "논문 기반"으로 표기(캐시 미스 첫 회·1RM 미보유는 "기본값", 수용).
7. 루틴 생성·챗봇 SSE 정상. **InBody OCR이 30s를 초과해도 abort되지 않고 60s까지 대기**(모킹 응답으로 검증).

---

## 7. 테스트 계획

**pytest (`server/tests/`)**:
- finish 원자 전이: 연속/재호출 finish → PO 1회만, 두 번째 200 멱등(이중 알림 없음). 416-517 가드 삭제 회귀 테스트.
- finish DTO: 멱등 200 경로에서도 total_sets/completed_exercises/calories 정확.
- PO bump 커밋: 트리거됐으나 **알림 0건** 엣지에서 rex.weight_kg가 커밋됨.
- PO 분해: `po_increment_cached` 캐시 히트(논문값)·미스((None,False)+warm_keys)·`(None,True)`(1RM None) 경로. `warm_po_cache` dedup. **search_chunks/LLM 모킹으로 동기 경로 네트워크 0회 검증(AC#1)**.
- `po.py`/finish 커버리지 유지(CLAUDE.md §13).

**RN (`app/`)**:
- `do_finish` 복구: 409→success(no alert), abort→멱등 재시도→ws_clear+goBack, 401→재로그인(재시도 안 함).
- handle_finish 게이트: in-flight(session_promise_ref만 존재) 시 do_finish 진입 허용.
- logSet 409/abort→alert 억제, 네트워크→alert + 롤백(isMountedRef 가드).
- `isMountedRef`로 언마운트 후 setState 경고 없음(is_finishing·set_exercises 둘 다).
- apiFetch 타임아웃: 기본 30s, OCR 60s 미abort, 401 재시도 새 컨트롤러.

---

## 8. 범위 외 (후속 PR)

- **중복 세트 행 정합성**: `UNIQUE(workout_log_id, routine_exercise_id, set_number)`(Alembic) + log_set UPSERT + uncheck DELETE/PATCH. → 볼륨/통계/PO 집계 오염 + 동시 종료 PO 레이스(부분 유니크) 해소. **별도 스펙·PR**.
- **PO 캐시 시작-시 프리워밍**: 배포 직후 첫 miss "기본값" 표기 완화. 선택적 최적화. (§2 정본에 따라 이번 범위 제외)
- **logSet 전용 에러 code** `SESSION_COMPLETED` 부여(현재는 status===409로 분기).
