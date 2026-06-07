# 운동 완료(finish) 버그 핫픽스 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "운동 완료" 무한 로딩 / "이미 종료된 세션" / "세트 기록 실패" 버그를 근본 해결한다 — finish를 원자·멱등 상태 전이로 바꾸고, 느린 PO/RAG를 동기 경로에서 분리하며, 클라이언트에 타임아웃·복구·에러 구분을 추가한다.

**Architecture:** finish 엔드포인트는 상태 전이(원자 UPDATE...RETURNING)만 동기로 책임지고 즉시 반환한다. PO 중량 bump는 캐시-읽기 전용 증가량으로 동기 커밋(다음 세션 정확성 보장), 느린 RAG는 응답 후 BackgroundTask로 캐시만 워밍한다. 클라이언트는 `ApiError`로 409/abort/네트워크를 구분해 멱등 재시도로 고아 세션을 차단한다.

**Tech Stack:** FastAPI / SQLAlchemy 2.0 async / pytest(+pytest-asyncio, httpx ASGI mock-db) · React Native + Expo / TanStack Query / Zustand / jest-expo + @testing-library/react-native

**스펙:** `docs/superpowers/specs/2026-06-07-workout-finish-fix-design.md` (rev2)
**불가침 제약:** `llm.py`/`rag.py`(`generate`/`generate_stream`/`search_chunks`)·캐시 클라이언트·루틴생성·챗봇 경로는 한 줄도 변경 금지.

**테스트 실행 명령(정확히 이대로)**:
- 서버: `cd server && .venv-test/bin/python -m pytest tests/<file>::<test> -v`
- 앱: `cd app && npx jest src/<path> --silent=false`

---

## 파일 구조 (책임 맵)

| 파일 | 책임 | 변경 |
|---|---|---|
| `server/app/services/po_rag.py` | PO 증가량 캐시 — **동기 캐시-읽기**(`po_increment_cached`) + **백그라운드 워밍**(`warm_po_cache`) | 함수 3개 추가 |
| `server/app/api/v1/sessions.py` | finish 원자·멱등 전이 + DTO 재계산 + 조건부 PO + 알림 dedup | finish 재구성, 헬퍼 추출, 409 가드 삭제 |
| `server/tests/test_po_rag.py` | po_rag 단위 테스트 | 추가 |
| `server/tests/test_sessions.py` | finish 단위 테스트 | 추가/수정 |
| `app/src/services/api.ts` | `ApiError` + per-request 타임아웃 + 401 새 컨트롤러 | 재구성 |
| `app/src/services/users.ts` | `ocrInbody`에 60s 타임아웃 캡슐화 | 1줄 |
| `app/src/screens/main/WR04RoutineDetail.tsx` | handle_finish 게이트·do_finish 복구·pending/finishing/mounted ref·logSet 분기 | 재구성 |
| `app/src/services/__tests__/api.test.ts` | apiFetch/ApiError/타임아웃 단위 테스트 | 신규 |
| `app/src/services/__tests__/users.test.ts` | ocrInbody 타임아웃 전달 테스트 | 신규 |

---

## Task 1: `po_rag.po_increment_cached` — 동기 캐시-읽기 진입점

**Files:**
- Modify: `server/app/services/po_rag.py` (공개 함수 추가, `rag_po_increment` 위)
- Test: `server/tests/test_po_rag.py`

- [ ] **Step 1: 실패 테스트 작성** — `server/tests/test_po_rag.py` 끝에 클래스 추가

```python
class TestPoIncrementCached:
    def test_miss_returns_none_false(self):
        from app.services.po_rag import po_increment_cached
        assert po_increment_cached("hypertrophy", "cable", 100.0) == (None, False)

    def test_hit_returns_kg_true(self):
        from app.services.po_rag import _cache_set, po_increment_cached
        _cache_set("hypertrophy", "cable", 5.0)
        assert po_increment_cached("hypertrophy", "cable", 100.0) == (5.0, True)

    def test_hit_none_pct_returns_none_true(self):
        from app.services.po_rag import _cache_set, po_increment_cached
        _cache_set("hypertrophy", "cable", None)
        assert po_increment_cached("hypertrophy", "cable", 100.0) == (None, True)

    def test_hit_but_no_1rm_returns_none_true(self):
        from app.services.po_rag import _cache_set, po_increment_cached
        _cache_set("hypertrophy", "cable", 5.0)
        assert po_increment_cached("hypertrophy", "cable", None) == (None, True)

    def test_never_calls_network(self):
        from app.services.po_rag import po_increment_cached
        with patch("app.services.po_rag._call_search_async", new=AsyncMock()) as ms, \
             patch("app.services.po_rag._call_llm_async", new=AsyncMock()) as ml:
            po_increment_cached("hypertrophy", "cable", 100.0)  # miss
            ms.assert_not_called()
            ml.assert_not_called()
```

- [ ] **Step 2: 실패 확인**

Run: `cd server && .venv-test/bin/python -m pytest tests/test_po_rag.py::TestPoIncrementCached -v`
Expected: FAIL — `ImportError: cannot import name 'po_increment_cached'`

- [ ] **Step 3: 구현** — `po_rag.py`의 `rag_po_increment` 정의 **직전**에 추가

```python
def po_increment_cached(
    goal: str,
    equipment_type: str,
    user_1rm_kg: float | None,
) -> tuple[float | None, bool]:
    """동기·논블로킹 PO 증가량 조회. (kg|None, cache_warm) 반환.

    캐시 히트만 사용하며 ChromaDB/LLM을 절대 호출하지 않는다.
    미스 시 (None, False) → 호출자는 하드코딩 fallback + 백그라운드 워밍.
    """
    hit, pct = _cache_get(goal, equipment_type)
    if not hit:
        return None, False
    if pct is None or user_1rm_kg is None:
        return None, True
    return _convert_to_kg(pct, user_1rm_kg), True
```

- [ ] **Step 4: 통과 확인**

Run: `cd server && .venv-test/bin/python -m pytest tests/test_po_rag.py::TestPoIncrementCached -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 커밋**

```bash
git add server/app/services/po_rag.py server/tests/test_po_rag.py
git commit -m "feat: po_rag 동기 캐시-읽기 진입점 po_increment_cached 추가"
```

---

## Task 2: `po_rag.warm_po_cache` — 백그라운드 캐시 워밍 + dedup

**Files:**
- Modify: `server/app/services/po_rag.py`
- Test: `server/tests/test_po_rag.py`

- [ ] **Step 1: 실패 테스트 작성** — `test_po_rag.py`에 추가

```python
class TestWarmPoCache:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_warm_populates_cache(self):
        from app.services import po_rag
        with patch("app.services.po_rag._call_search_async", new=AsyncMock(return_value=SAMPLE_CHUNKS)), \
             patch("app.services.po_rag._call_llm_async", new=AsyncMock(return_value='{"increment_percent": 5}')):
            self._run(po_rag.warm_po_cache("hypertrophy", "cable"))
        hit, pct = po_rag._cache_get("hypertrophy", "cable")
        assert hit is True and pct == 5.0

    def test_warm_skips_when_already_cached(self):
        from app.services import po_rag
        po_rag._cache_set("hypertrophy", "cable", 5.0)
        with patch("app.services.po_rag._call_search_async", new=AsyncMock()) as ms:
            self._run(po_rag.warm_po_cache("hypertrophy", "cable"))
            ms.assert_not_called()

    def test_warm_swallows_exception(self):
        from app.services import po_rag
        with patch("app.services.po_rag._call_search_async", new=AsyncMock(side_effect=RuntimeError("down"))):
            self._run(po_rag.warm_po_cache("hypertrophy", "cable"))  # 예외 안 던짐
        assert po_rag._cache_get("hypertrophy", "cable")[0] is False
```

- [ ] **Step 2: 실패 확인**

Run: `cd server && .venv-test/bin/python -m pytest tests/test_po_rag.py::TestWarmPoCache -v`
Expected: FAIL — `AttributeError: module 'app.services.po_rag' has no attribute 'warm_po_cache'`

- [ ] **Step 3: 구현** — `po_rag.py`의 `_cache` 정의 아래에 `_warming` 추가, `po_increment_cached` 아래에 함수 추가

```python
# 파일 상단 _cache 선언 근처에 추가:
_warming: set[tuple[str, str]] = set()
```
```python
# po_increment_cached 아래에 추가:
async def warm_po_cache(goal: str, equipment_type: str) -> None:
    """백그라운드 전용. 캐시 미스 시 ChromaDB+LLM으로 캐시만 채운다.

    DB 미사용. 예외는 rag_po_increment 내부에서 흡수. 동일 키 in-flight dedup.
    """
    key = (goal, equipment_type)
    if _cache_get(*key)[0] or key in _warming:
        return
    _warming.add(key)
    try:
        await rag_po_increment(goal, equipment_type, None)  # _cache_set만 채움, 반환값 무시
    finally:
        _warming.discard(key)
```

- [ ] **Step 4: 통과 확인**

Run: `cd server && .venv-test/bin/python -m pytest tests/test_po_rag.py -v`
Expected: PASS (전체 po_rag 테스트 green)

- [ ] **Step 5: 커밋**

```bash
git add server/app/services/po_rag.py server/tests/test_po_rag.py
git commit -m "feat: po_rag 백그라운드 캐시 워밍 warm_po_cache + dedup 추가"
```

---

## Task 3: `sessions.py` 헬퍼 추출 (`_resolve_finished_at`, `_build_finish_dto`)

순수 리팩토링 — 동작 변화 없음. 기존 finish 테스트가 green으로 유지돼야 한다.

**Files:**
- Modify: `server/app/api/v1/sessions.py`
- Test: `server/tests/test_sessions.py` (기존 `TestFinishSession` 재실행)

- [ ] **Step 1: 기존 finish 테스트 baseline 확인**

Run: `cd server && .venv-test/bin/python -m pytest tests/test_sessions.py -k finish -v`
Expected: PASS (현재 통과 상태 기록 — 리팩토링 후 동일해야 함)

- [ ] **Step 2: `_resolve_finished_at` 추출** — `sessions.py`의 `_strip_tz` 헬퍼 아래에 추가

```python
def _resolve_finished_at(finished_at: datetime | None, started_at: datetime | None) -> datetime:
    """클라가 보낸 finished_at을 naive UTC로 정규화. started_at 이하이면 서버 시간으로 대체."""
    dt = finished_at or datetime.now(timezone.utc)
    candidate = dt.replace(tzinfo=None)
    if started_at and candidate <= _strip_tz(started_at):
        candidate = datetime.now(timezone.utc).replace(tzinfo=None)
    return candidate
```

- [ ] **Step 3: `_build_finish_dto` 추출** — `finish_session` 위에 추가 (기존 529-559 로직 이전)

```python
async def _build_finish_dto(s: WorkoutLog, user: User, db: AsyncSession) -> SessionData:
    """완료된 세션의 응답 DTO를 집계 쿼리로 재계산한다. PO를 호출하지 않는다(멱등 200 경로 공용)."""
    total_sets = int(
        (await db.execute(select(func.count(WorkoutLogSet.id)).where(WorkoutLogSet.workout_log_id == s.id))).scalar_one()
    )
    completed_exercises = int(
        (
            await db.execute(
                select(func.count(func.distinct(WorkoutLogSet.exercise_id))).where(
                    WorkoutLogSet.workout_log_id == s.id,
                    WorkoutLogSet.is_completed.is_(True),
                )
            )
        ).scalar_one()
    )
    latest_measurement = (
        await db.execute(
            select(UserBodyMeasurement)
            .where(UserBodyMeasurement.user_id == user.id)
            .order_by(UserBodyMeasurement.measured_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    body_weight = latest_measurement.weight_kg if latest_measurement else 70.0

    dto = _session_to_dto(s)
    dto.total_sets = total_sets
    dto.completed_exercises = completed_exercises
    dto.total_calories = round(5.0 * body_weight * dto.duration_minutes / 60) if dto.duration_minutes else None
    return dto
```

- [ ] **Step 4: `finish_session` 본문에서 위 두 블록을 헬퍼 호출로 교체**

`finish_session` 내부의 `dt = body.finished_at or ...` ~ `s.finished_at = candidate`(519-524)를 `candidate = _resolve_finished_at(body.finished_at, s.started_at)` + `s.finished_at = candidate`로, 그리고 `total_sets = ...` ~ `dto.total_calories = ...`(529-559)를 `dto = await _build_finish_dto(s, current_user, db)`로 교체. **이 단계는 동작 동일** (Task 5에서 원자 전이로 재구성).

- [ ] **Step 5: 리팩토링 후 동일 통과 확인**

Run: `cd server && .venv-test/bin/python -m pytest tests/test_sessions.py -k finish -v`
Expected: PASS (Step 1과 동일 결과)

- [ ] **Step 6: 커밋**

```bash
git add server/app/api/v1/sessions.py
git commit -m "refactor: finish_session에서 _resolve_finished_at/_build_finish_dto 헬퍼 추출"
```

---

## Task 4: `sessions.py` `_apply_po` — 캐시-읽기 전환 + commit 분리 + 알림 dedup

**Files:**
- Modify: `server/app/api/v1/sessions.py` (`_check_and_create_po_notifications` → `_apply_po`)
- Test: `server/tests/test_sessions.py`

- [ ] **Step 1: 실패 테스트 작성** — `test_sessions.py`에 추가 (mock-db 패턴)

```python
class TestApplyPo:
    @pytest.mark.asyncio
    async def test_returns_warm_keys_on_cache_miss_and_no_internal_commit(self, monkeypatch):
        from app.api.v1 import sessions as sess
        # po_increment_cached가 캐시 미스(None, False) → warm_keys에 (goal, load_mode) 적재
        monkeypatch.setattr(sess.po_rag, "po_increment_cached", lambda g, e, r: (None, False))
        # _apply_po가 트리거 1건을 만들도록 최소 모킹 — 실제로는 기존 finish 테스트의 mock-db 시퀀스를 재사용.
        # 핵심 단언: 반환 타입이 set이고, db.commit이 _apply_po 내부에서 호출되지 않는다.
        ...
        # (구현자 주: 기존 TestFinishSession의 PO 모킹 시퀀스를 복제해 session/set_rows/rex를 구성)
```

> 구현자 주: `_apply_po`는 mock-db 시퀀스 의존도가 높다. 기존 `test_sessions.py`의 PO 관련 테스트(있다면)를 복제해 (a) 반환값이 `set[tuple]`인지, (b) `_apply_po` 내부에서 `db.commit()`이 호출되지 않는지(`db.commit.assert_not_called()` 후 호출부에서만 commit), (c) `po_increment_cached`가 호출되고 `rag_po_increment`(동기 네트워크)는 호출되지 않는지 단언한다.

- [ ] **Step 2: 실패 확인**

Run: `cd server && .venv-test/bin/python -m pytest tests/test_sessions.py::TestApplyPo -v`
Expected: FAIL — `_apply_po` 미정의 / 반환값 None

- [ ] **Step 3: 구현** — `_check_and_create_po_notifications`를 `_apply_po`로 개편

변경점:
1. 함수명 `_check_and_create_po_notifications` → `_apply_po`, 반환 타입 `-> set[tuple[str, str]]`.
2. 함수 시작에 `warm_keys: set[tuple[str, str]] = set()`.
3. 루프 내 `increment_override = await po_rag.rag_po_increment(goal, category, user_1rm_kg)` 줄을 교체:
```python
        increment_override, cache_warm = po_rag.po_increment_cached(goal, category, user_1rm_kg)
        if not cache_warm:
            warm_keys.add((goal, category))
        po_source = "논문 기반" if increment_override is not None else "기본값"
```
4. 루프 **진입 전** 미확인 PO 알림 rex 집합 조회(dedup):
```python
    existing_unread = {
        str(r[0])
        for r in (
            await db.execute(
                select(Notification.data_json["routine_exercise_id"].astext)
                .where(
                    Notification.user_id == user.id,
                    Notification.type == NotificationType.PO_SUGGESTION,
                    Notification.is_read.is_(False),
                )
            )
        ).all()
        if r[0] is not None
    }
```
   그리고 `new_notifications.append(...)` 두 곳을 `if str(rex_id) not in existing_unread:` 가드로 감싼다.
5. 함수 끝 `if new_notifications: db.add_all(...); await db.commit()` 에서 **`await db.commit()` 제거** — `db.add_all(new_notifications)`만 수행(커밋은 호출부 Task 5). rex bump는 ORM dirty 상태로 호출부 커밋에 포함.
6. `return warm_keys`.

- [ ] **Step 4: 통과 확인**

Run: `cd server && .venv-test/bin/python -m pytest tests/test_sessions.py::TestApplyPo -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add server/app/api/v1/sessions.py server/tests/test_sessions.py
git commit -m "refactor: _check_and_create_po_notifications를 _apply_po로 — 캐시-읽기 전환, commit 분리, 알림 dedup"
```

---

## Task 5: `sessions.py` `finish_session` 원자 전이 + 멱등 + 조건부 PO

**Files:**
- Modify: `server/app/api/v1/sessions.py` (import에 `BackgroundTasks`, `update`; finish 본문 재구성; 409 가드 삭제)
- Test: `server/tests/test_sessions.py`

- [ ] **Step 1: 실패 테스트 작성** — `test_sessions.py`에 추가

```python
class TestFinishIdempotent:
    @pytest.mark.asyncio
    async def test_already_completed_returns_200_no_po(self, client, monkeypatch):
        from app.api.v1 import sessions as sess
        called = {"po": False}
        async def _spy_po(*a, **k):
            called["po"] = True
            return set()
        monkeypatch.setattr(sess, "_apply_po", _spy_po)
        # db.execute 시퀀스: s0 조회 → UPDATE RETURNING(claimed=None: 이미 COMPLETED) → 재로드 → DTO 집계 3건
        s_completed = _mock_session(status=WorkoutStatus.COMPLETED)
        s_completed.finished_at = _NOW
        db = _make_db(
            _exec_scalar(s_completed),       # s0 = _get_my_session
            _exec_scalar(None),              # UPDATE...RETURNING → claimed None (전이 실패=이미 완료)
            _exec_scalar(s_completed),       # 재로드 s
            _exec_scalar_one(2),             # total_sets
            _exec_scalar_one(1),             # completed_exercises
            _exec_scalar(None),              # latest_measurement
        )
        app.dependency_overrides[get_db] = _db_override(db)
        resp = await client.patch(f"/api/v1/sessions/{_SESSION_ID}/finish", json={})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert called["po"] is False          # 멱등 재호출은 PO 미실행
```

- [ ] **Step 2: 실패 확인**

Run: `cd server && .venv-test/bin/python -m pytest tests/test_sessions.py::TestFinishIdempotent -v`
Expected: FAIL (현재는 409 ConflictError 반환 → status 409)

- [ ] **Step 3: import 추가** — `sessions.py` 상단

```python
from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from sqlalchemy import func, select, text, update
```

- [ ] **Step 4: `finish_session` 재구성** — 기존 506-563 전체를 교체

```python
@router.patch("/{session_id}/finish", response_model=SuccessResponse[SessionData], summary="세션 종료")
@rate_limit("60/minute")
async def finish_session(
    request: Request,
    session_id: str,
    body: FinishSessionRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_required_profile),
    db: AsyncSession = Depends(get_db),
):
    s0 = await _get_my_session(session_id, current_user, db)   # 404 게이트 + started_at
    candidate = _resolve_finished_at(body.finished_at, s0.started_at)

    claimed = (
        await db.execute(
            update(WorkoutLog)
            .where(
                WorkoutLog.id == s0.id,
                WorkoutLog.user_id == current_user.id,
                WorkoutLog.status == WorkoutStatus.IN_PROGRESS,
            )
            .values(status=WorkoutStatus.COMPLETED, finished_at=candidate)
            .returning(WorkoutLog.id)
        )
    ).scalar_one_or_none()
    await db.commit()                                          # COMPLETED 먼저 durable

    db.expire_all()
    s = await _get_my_session(session_id, current_user, db)    # 신선 재로드
    dto = await _build_finish_dto(s, current_user, db)         # 항상 재계산

    if claimed is not None:                                    # 전이 선점자만 PO
        warm_keys: set[tuple[str, str]] = set()
        try:
            warm_keys = await _apply_po(s, current_user, db)
            await db.commit()                                 # PO bump + 알림 단일 커밋
        except Exception:
            await db.rollback()
            warm_keys = set()
            logger.warning("PO 후처리 실패 (세션은 COMPLETED) request_id=%s", getattr(request.state, "request_id", "-"))
        for goal, lm in warm_keys:
            background_tasks.add_task(po_rag.warm_po_cache, goal, lm)

    return SuccessResponse(data=dto)
```

- [ ] **Step 5: 기존 409 가드 삭제 확인**

위 교체로 기존 `s = await _get_my_session(...)` + `if s.status == WorkoutStatus.COMPLETED: raise ConflictError("이미 종료된 세션입니다.")`(515-517)가 사라졌는지 확인. `log_set`의 409(260-261)는 **그대로 유지**.

- [ ] **Step 6: 통과 확인 (신규 + 기존 회귀)**

Run: `cd server && .venv-test/bin/python -m pytest tests/test_sessions.py -v`
Expected: PASS. 기존 finish 테스트 중 "이미 종료된 세션 → 409 기대" 케이스가 있으면 **멱등 200 기대로 수정**(그 테스트는 의도적으로 변경됨을 커밋 메시지에 명시).

- [ ] **Step 7: 커밋**

```bash
git add server/app/api/v1/sessions.py server/tests/test_sessions.py
git commit -m "fix: finish_session 원자 전이+멱등화 — 409 연쇄 제거, PO 분해, 무한로딩 해소"
```

---

## Task 6: `api.ts` `ApiError` 타입드 에러

**Files:**
- Modify: `app/src/services/api.ts`
- Test: `app/src/services/__tests__/api.test.ts` (신규)

- [ ] **Step 1: 실패 테스트 작성** — `app/src/services/__tests__/api.test.ts`

```ts
import { ApiError, apiFetch } from "../api";

function mockFetchOnce(status: number, body: any) {
  (global as any).fetch = jest.fn().mockResolvedValue({
    status,
    ok: status >= 200 && status < 300,
    json: async () => body,
  });
}

describe("ApiError", () => {
  it("throws ApiError with status/code on non-success body", async () => {
    mockFetchOnce(409, { success: false, error: { code: "CONFLICT", message: "이미 종료된 세션입니다." } });
    await expect(apiFetch("/x", { token: "t" })).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      code: "CONFLICT",
    });
  });

  it("ApiError is an Error with .message", async () => {
    mockFetchOnce(409, { success: false, error: { code: "CONFLICT", message: "이미 종료된 세션입니다." } });
    const err = await apiFetch("/x", { token: "t" }).catch((e) => e);
    expect(err).toBeInstanceOf(Error);
    expect(err.message).toBe("이미 종료된 세션입니다.");
  });
});
```

- [ ] **Step 2: 실패 확인**

Run: `cd app && npx jest src/services/__tests__/api.test.ts`
Expected: FAIL — `ApiError` export 없음 / 던진 값이 일반 Error

- [ ] **Step 3: 구현** — `api.ts` 상단에 `ApiError` 추가, throw 지점 교체

```ts
export class ApiError extends Error {
  status: number;
  code?: string;
  aborted?: boolean;
  constructor(message: string, opts: { status: number; code?: string; aborted?: boolean }) {
    super(message);
    this.name = "ApiError";
    this.status = opts.status;
    this.code = opts.code;
    this.aborted = opts.aborted;
  }
}
```
그리고 기존 비-JSON throw(83-88) 및 `if (!json?.success)` throw(91-96)를 `ApiError`로 교체:
```ts
    if (res.ok) return undefined as T;
    throw new ApiError(
      res.status >= 500 ? "서버에 일시적인 문제가 발생했습니다. 잠시 후 다시 시도해주세요." : `요청을 처리할 수 없습니다. (${res.status})`,
      { status: res.status },
    );
```
```ts
  if (!json?.success) {
    const detail = json?.error?.details?.errors?.[0];
    const detail_msg = detail?.ctx?.error ?? detail?.msg;
    throw new ApiError(detail_msg ?? json?.error?.message ?? "오류가 발생했습니다.", {
      status: res.status,
      code: json?.error?.code,
    });
  }
```

- [ ] **Step 4: 통과 확인**

Run: `cd app && npx jest src/services/__tests__/api.test.ts`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add app/src/services/api.ts app/src/services/__tests__/api.test.ts
git commit -m "feat: apiFetch가 ApiError(status/code/aborted)를 던지도록 변경"
```

---

## Task 7: `api.ts` per-request 타임아웃 + 401 새 컨트롤러

**Files:**
- Modify: `app/src/services/api.ts`
- Test: `app/src/services/__tests__/api.test.ts`

- [ ] **Step 1: 실패 테스트 추가**

```ts
describe("timeout", () => {
  it("aborts after timeoutMs and throws ApiError(aborted)", async () => {
    (global as any).fetch = jest.fn((_url, opts: any) =>
      new Promise((_resolve, reject) => {
        opts.signal?.addEventListener("abort", () => reject(Object.assign(new Error("Aborted"), { name: "AbortError" })));
      }),
    );
    const p = apiFetch("/slow", { token: "t", timeoutMs: 20 });
    await expect(p).rejects.toMatchObject({ name: "ApiError", aborted: true, status: 0 });
  });
});
```

- [ ] **Step 2: 실패 확인**

Run: `cd app && npx jest src/services/__tests__/api.test.ts -t timeout`
Expected: FAIL — `timeoutMs` 미지원 / AbortError가 ApiError로 매핑 안 됨

- [ ] **Step 3: 구현** — `apiFetch` 시그니처/`send` 수정

```ts
export async function apiFetch<T>(
  path: string,
  options: RequestInit & { token?: string; timeoutMs?: number } = {},
): Promise<T> {
  const { token, headers: extraHeaders, timeoutMs = 30000, ...rest } = options;
  // ... build_headers 동일 ...
  const send = (authToken?: string) => {
    const controller = new AbortController();              // 매 시도 새 컨트롤러
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    return fetch(`${API_BASE}${path}`, { ...rest, headers: build_headers(authToken), signal: controller.signal })
      .finally(() => clearTimeout(timer));
  };

  let res: Response;
  try {
    res = await send(token);
  } catch (e: any) {
    if (e?.name === "AbortError") throw new ApiError("요청 시간이 초과되었습니다.", { status: 0, aborted: true });
    throw new ApiError("네트워크 연결을 확인해주세요.", { status: 0 });
  }
  // ... 401 분기: refreshed 후 res = await send(...) 도 동일 try/catch로 감쌈 ...
```
401 재시도(`res = await send(useAuthStore.getState().accessToken ...)`)도 위와 같은 try/catch로 감싸 abort/네트워크를 ApiError로 변환한다. (refresh 자체는 raw fetch 유지)

- [ ] **Step 4: 통과 확인**

Run: `cd app && npx jest src/services/__tests__/api.test.ts`
Expected: PASS (timeout + 기존 테스트 모두)

- [ ] **Step 5: 커밋**

```bash
git add app/src/services/api.ts app/src/services/__tests__/api.test.ts
git commit -m "feat: apiFetch per-request 타임아웃(AbortController) + 매 시도 새 컨트롤러"
```

---

## Task 8: `users.ts` `ocrInbody` 60s 타임아웃 캡슐화

**Files:**
- Modify: `app/src/services/users.ts`
- Test: `app/src/services/__tests__/users.test.ts` (신규)

- [ ] **Step 1: 실패 테스트 작성**

```ts
import * as api from "../api";
import { ocrInbody } from "../users";

it("ocrInbody passes timeoutMs 60000 to apiFetch", async () => {
  const spy = jest.spyOn(api, "apiFetch").mockResolvedValue({} as any);
  await ocrInbody("token", "base64img");   // 실제 인자 시그니처에 맞게 조정
  expect(spy).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ timeoutMs: 60000 }));
});
```

- [ ] **Step 2: 실패 확인**

Run: `cd app && npx jest src/services/__tests__/users.test.ts`
Expected: FAIL — timeoutMs 미전달

- [ ] **Step 3: 구현** — `users.ts`의 `ocrInbody` 내부 `apiFetch` 호출에 `timeoutMs: 60000` 추가

```ts
  return apiFetch<InbodyOcrData>("/api/v1/users/me/body/ocr", {
    method: "POST",
    token,
    body: JSON.stringify({ image_base64 }),
    timeoutMs: 60000,
  });
```
> 구현자 주: `ocrInbody`의 실제 경로·body 키는 현행 코드에 맞춘다. 변경은 `timeoutMs: 60000` 추가뿐.

- [ ] **Step 4: 통과 확인**

Run: `cd app && npx jest src/services/__tests__/users.test.ts`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add app/src/services/users.ts app/src/services/__tests__/users.test.ts
git commit -m "fix: ocrInbody에 60s 타임아웃 전달 — Vision OCR 오탐 abort 방지"
```

---

## Task 9: `WR04` refs + handle_finish 게이트 + finishing_ref + toggle 차단

**Files:**
- Modify: `app/src/screens/main/WR04RoutineDetail.tsx`

- [ ] **Step 1: `isMountedRef` + `finishing_ref` + `pending_logsets` 추가** — 컴포넌트 상단 ref 선언부

```ts
  const isMountedRef = useRef(true);
  const finishing_ref = useRef(false);
  const pending_logsets = useRef(new Set<Promise<unknown>>());
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      finishing_ref.current = false;
    };
  }, []);
```

- [ ] **Step 2: `toggle_set_done` 최상단 차단 가드 추가** — 함수 첫 줄

```ts
  const toggle_set_done = (exercise_id: string, set_id: string) => {
    if (finishing_ref.current) return;   // finish 진행 중 신규 체크 차단(스토어+logSet 모두)
    // ... 기존 본문 ...
```

- [ ] **Step 3: `toggle_set_done`의 logSet 체인을 pending에 추적** — `becoming_done` 분기의 `ensure_session().then(...).then(...).catch(...)` 체인을 `const p = ...`로 받아 추적

```ts
      if (ex && current_set) {
        const p = ensure_session()
          .then((sid) => { /* invalidate + logSet ... 기존 */ })
          .then(() => { /* invalidate 5종 기존 */ })
          .catch((e) => {
            if (e instanceof ApiError && (e.status === 409 || e.aborted)) return;  // 상태충돌/abort는 억제
            Alert.alert("세트 기록 실패", "세트가 서버에 저장되지 않았습니다.\n네트워크 연결을 확인해주세요.");
            ws_toggle_set(set_id, false);                                          // 낙관적 롤백(store)
            if (isMountedRef.current) {                                            // 언마운트 가드
              set_exercises((prev) => prev.map((e2) => e2.id === exercise_id
                ? { ...e2, sets: e2.sets.map((s) => (s.id === set_id ? { ...s, is_done: false } : s)) }
                : e2));
            }
          });
        pending_logsets.current.add(p);
        p.finally(() => pending_logsets.current.delete(p));
      }
```
상단 import에 `import { startSession, logSet, finishSession } from "../../services/sessions";` 옆에 `import { ApiError } from "../../services/api";` 추가.

- [ ] **Step 4: `handle_finish` 게이트 정정** — 740-745

```ts
  const handle_finish = () => {
    if (is_finishing) return;
    if (!session_id_ref.current && !session_promise_ref.current) {   // 둘 다 없을 때만 진짜 미준비
      Alert.alert("잠깐만요", "세션을 준비 중이에요. 잠시 후 다시 시도해 주세요.");
      return;
    }
    Alert.alert("운동 완료", "세션이 초기화됩니다. 완료하시겠어요?", [
      { text: "취소", style: "cancel" },
      { text: "확인", onPress: do_finish },
    ]);
  };
```

- [ ] **Step 5: 타입체크 통과 확인**

Run: `cd app && npx tsc --noEmit`
Expected: 에러 없음 (do_finish는 Task 10에서 완성 — 이 단계까지는 기존 do_finish 유지)

- [ ] **Step 6: 커밋**

```bash
git add app/src/screens/main/WR04RoutineDetail.tsx
git commit -m "feat: WR04 isMountedRef/finishing_ref/pending_logsets + handle_finish 게이트 정정 + logSet 409 억제"
```

---

## Task 10: `WR04` `do_finish` 복구 경로 + pending await

**Files:**
- Modify: `app/src/screens/main/WR04RoutineDetail.tsx`

- [ ] **Step 1: `do_finish` 재구성** — 702-735 교체

```ts
  const do_finish = async () => {
    if (is_finishing) return;
    finishing_ref.current = true;
    set_is_finishing(true);
    try {
      const sid = await ensure_session();                                  // in-flight 세션 대기
      // 진행 중 세트 기록을 bounded로 대기 (최대 4s)
      await Promise.race([
        Promise.allSettled([...pending_logsets.current]),
        new Promise((r) => setTimeout(r, 4000)),
      ]);

      let finished_at: string | undefined;
      if (ws_session_started_at) {
        const total_ms = ws_page_elapsed_ms + (Date.now() - mount_time_ref.current);
        finished_at = new Date(new Date(ws_session_started_at).getTime() + total_ms).toISOString();
      }
      await finishSession(token, sid, finished_at ? { finished_at } : undefined);
      _finish_cleanup();                                                    // ws_clear + invalidate + goBack
    } catch (e: unknown) {
      // 409(이미 완료) → success 취급
      if (e instanceof ApiError && e.status === 409) {
        _finish_cleanup();
        return;
      }
      // abort/네트워크(status 0) → 멱등 재시도 1회
      if (e instanceof ApiError && (e.aborted || e.status === 0) && session_id_ref.current) {
        try {
          await finishSession(token, session_id_ref.current, undefined);
          _finish_cleanup();
          return;
        } catch (e2: unknown) {
          if (e2 instanceof ApiError && e2.status === 409) {
            _finish_cleanup();
            return;
          }
        }
      }
      // 401은 apiFetch가 이미 clearAuth 처리 → 여기선 복구 안내만
      finishing_ref.current = false;
      if (isMountedRef.current) set_is_finishing(false);
      const msg = e instanceof Error ? e.message : "운동 완료 처리에 실패했습니다.";
      Alert.alert("오류", msg);
    }
  };

  /** 완료 성공/멱등 확정 시 단일 정리 경로 */
  const _finish_cleanup = () => {
    ws_clear();
    query_client.invalidateQueries({ queryKey: ["routine", routine_id] });
    query_client.invalidateQueries({ queryKey: ["sessions"] });
    query_client.invalidateQueries({ queryKey: ["session-stats"] });
    query_client.invalidateQueries({ queryKey: ["volume-analysis"] });
    query_client.invalidateQueries({ queryKey: ["muscle-volume"] });
    query_client.invalidateQueries({ queryKey: ["notifications", token] });
    navigation.goBack();
  };
```
> 핵심: finish 경로의 `status===409`는 **절대 Alert("이미 종료된 세션")로 노출하지 않는다** — 항상 success 취급.

- [ ] **Step 2: 타입체크**

Run: `cd app && npx tsc --noEmit`
Expected: 에러 없음

- [ ] **Step 3: 컴포넌트 테스트(복구 경로)** — `app/src/screens/main/__tests__/WR04Finish.test.tsx` (신규, 서비스 모킹)

```tsx
// finishSession 모킹: 첫 호출 ApiError(409) → do_finish가 goBack(=_finish_cleanup) 호출, Alert 미발생
jest.mock("../../../services/sessions");
// 자세한 렌더는 navigation/query/store provider 모킹 필요 — 최소한 do_finish가
// 409에서 navigation.goBack을 부르고 Alert.alert("오류", "이미 종료된 세션입니다")를 부르지 않음을 단언.
```
> 구현자 주: WR04는 navigation/QueryClient/Zustand 의존이 커서 풀 렌더가 무겁다. 최소 단위로 (a) 409→goBack·no-error-alert, (b) abort→재시도→goBack 두 시나리오만 커버. provider 모킹이 과하면 do_finish 로직을 별도 순수 함수로 추출해 단위 테스트하는 리팩토링을 우선한다.

- [ ] **Step 4: 통과 확인**

Run: `cd app && npx jest src/screens/main/__tests__/WR04Finish.test.tsx`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add app/src/screens/main/WR04RoutineDetail.tsx app/src/screens/main/__tests__/WR04Finish.test.tsx
git commit -m "fix: do_finish 멱등 복구(409=success, abort=재시도) + pending logSet bounded await + 단일 cleanup"
```

---

## Task 11: 전체 회귀 + 수동 재현 검증

**Files:** 없음 (검증 전용)

- [ ] **Step 1: 서버 전체 테스트**

Run: `cd server && .venv-test/bin/python -m pytest tests/ -v`
Expected: PASS (po_rag/sessions 포함 전체 green)

- [ ] **Step 2: 앱 테스트 + 타입체크**

Run: `cd app && npx jest && npx tsc --noEmit`
Expected: PASS, 타입 에러 0

- [ ] **Step 3: ruff (push 전 필수)**

Run: `cd server && ruff check app/ && ruff format app/`
Expected: clean

- [ ] **Step 4: 수동 재현 체크리스트** (수용 기준 §6 대조)

```
[ ] PO 트리거되는 루틴 완료 → 즉시 반환(무한로딩 없음)
[ ] "운동 완료" 두 번 탭 → 두 번째도 정상(409 노출 없음)
[ ] 완료 중 뒤로가기 → 재진입 → 완료 → "이미 종료된 세션" 안 뜸
[ ] 세트 체크 후 완료 직후 → "세트 기록 실패/네트워크" 오안내 없음
[ ] 완료 직후 같은 루틴 재진입 → 올라간 중량 표시
[ ] 챗봇·루틴생성·InBody OCR 정상 (회귀 없음)
```

- [ ] **Step 5: 최종 커밋(있으면) + PR**

```bash
git add -A && git commit -m "test: 운동 완료 핫픽스 전체 회귀 검증" --allow-empty
# PR: fix/jingyu/workout-finish-bug → develop
```

---

## Self-Review 결과 (작성자 점검)

- **스펙 커버리지**: §3.1→T3·T5, §3.2/3.3→T1·T2·T4, §3.4→T4(dedup), §4.1→T6, §4.2→T7·T8, §4.3→T10, §4.4→T9·T10, §4.5→T9·T10, §6 AC→T11. 모든 절에 대응 태스크 존재.
- **불가침 제약**: llm.py/rag.py/캐시 클라이언트/SSE 경로 변경 태스크 없음 — 준수.
- **타입 일관성**: `po_increment_cached`(T1)→사용처(T4), `warm_po_cache`(T2)→호출(T5), `ApiError`(T6)→사용(T7·T9·T10), `_apply_po`/`_build_finish_dto`/`_resolve_finished_at`(T3·T4)→호출(T5) 명칭 일치.
- **알려진 한계**: 중복 세트 행·동시 종료 PO 레이스·시작-시 프리워밍은 스펙 §8대로 범위 외(후속 PR).
