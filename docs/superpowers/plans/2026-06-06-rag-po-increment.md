# RAG 기반 자동 중량 증가 제안 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ChromaDB에 수집된 Progressive Overload 논문에서 LLM이 % 증가량을 추출하고 사용자 1RM 기반 kg로 변환하여 세션 완료 시 알림에 적용한다. 논문/LLM 실패 시 기존 하드코딩 fallback.

**Architecture:** `po_rag.py` 신규 서비스가 RAG 검색 + LLM 추출 + 24h 인메모리 캐시를 담당. `po.py`에 `increment_override` 파라미터 추가. `sessions.py`의 `_check_and_create_po_notifications()`에 1RM 조회 + `rag_po_increment()` 호출 삽입.

**Tech Stack:** Python 3.11, FastAPI async, ChromaDB (`rag.py`의 `search_chunks`), Gemini/GPT-4o-mini (`llm.py`의 `generate`), SQLAlchemy 2.0 async, pytest, pytest-asyncio

---

## 파일 구조

| 파일 | 변경 |
|---|---|
| `server/app/services/po_rag.py` | **신규** — RAG 검색·LLM 추출·캐시 |
| `server/app/services/po.py` | **수정** — `calculate_increase()`에 `increment_override` 추가 |
| `server/app/api/v1/sessions.py` | **수정** — `_check_and_create_po_notifications()` 내 1RM 조회 + `rag_po_increment()` 호출 |
| `server/tests/test_po_rag.py` | **신규** — `po_rag.py` 단위 테스트 |
| `server/tests/test_po.py` | **수정** — `increment_override` 케이스 추가 |
| `server/requirements.txt` | **수정** — `pytest-asyncio` 추가 |

---

## Task 1: 브랜치 생성

**Files:** 없음

- [ ] **Step 1: develop 최신화 후 브랜치 생성**

```bash
git fetch --prune
git checkout develop
git pull origin develop
git checkout -b feature/taehyun/rag-po-increment
```

---

## Task 2: `po.py`에 `increment_override` 추가 (TDD)

**Files:**
- Modify: `server/app/services/po.py:72-110`
- Modify: `server/tests/test_po.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_po.py`의 `TestCalculateIncrease` 클래스 끝에 추가:

```python
def test_increment_override_used(self):
    result = calculate_increase("cable", "hypertrophy", 50.0, 3, increment_override=3.0)
    assert result["new_weight"] == 53.0
    assert result["new_sets"] == 3
    assert result["overflow"] is False

def test_increment_override_none_uses_hardcoded(self):
    result = calculate_increase("cable", "hypertrophy", 50.0, 3, increment_override=None)
    assert result["new_weight"] == 52.5

def test_increment_override_with_max_stack_overflow(self):
    result = calculate_increase("cable", "hypertrophy", 49.0, 3, max_stack=50.0, increment_override=3.0)
    assert result["new_weight"] == 50.0
    assert result["overflow"] is True
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
cd server && pytest tests/test_po.py::TestCalculateIncrease::test_increment_override_used -v
```

Expected: `FAILED` — `TypeError: calculate_increase() got an unexpected keyword argument 'increment_override'`

- [ ] **Step 3: `po.py` 수정**

`server/app/services/po.py:72` 의 `calculate_increase` 시그니처와 첫 번째 increment 계산 줄을 다음으로 교체:

```python
def calculate_increase(
    category: str,
    goal: str,
    current_weight: float,
    current_sets: int,
    max_stack: float | None = None,
    increment_override: float | None = None,
) -> dict:
    """PO 트리거 시 증가량을 계산한다.

    Returns:
        {
            "new_weight": float,
            "new_sets": int,
            "overflow": bool,
            "message": str | None,
        }
    """
    goal_map = INCREASE.get(goal, INCREASE["endurance"])
    increment = increment_override if increment_override is not None else goal_map.get(category, 1.25)
```

나머지 함수 본문(`new_weight = current_weight + increment` 이하)은 변경 없음.

- [ ] **Step 4: 테스트 통과 확인**

```bash
cd server && pytest tests/test_po.py -v
```

Expected: 전체 PASS (기존 테스트 포함)

- [ ] **Step 5: 커밋**

```bash
git add server/app/services/po.py server/tests/test_po.py
git commit -m "feat: add increment_override param to po.calculate_increase"
```

---

## Task 3: `po_rag.py` 신규 서비스 작성 (TDD)

**Files:**
- Create: `server/app/services/po_rag.py`
- Create: `server/tests/test_po_rag.py`
- Modify: `server/requirements.txt`

- [ ] **Step 1: pytest-asyncio 추가**

`server/requirements.txt`에 다음 줄 추가 (기존 pytest 줄 아래):

```
pytest-asyncio>=0.23.0
```

- [ ] **Step 2: 테스트 파일 작성**

`server/tests/test_po_rag.py` 신규 생성:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

SAMPLE_CHUNKS = [
    {"document": "Studies show 5% load increment per session improves strength.", "similarity": 0.85, "score": 0.85}
]


@pytest.fixture(autouse=True)
def clear_cache():
    from app.services import po_rag
    po_rag._cache.clear()
    yield
    po_rag._cache.clear()


class TestConvertToKg:
    def test_basic_conversion(self):
        from app.services.po_rag import _convert_to_kg
        assert _convert_to_kg(5.0, 100.0) == 5.0

    def test_rounds_to_nearest_2_5(self):
        from app.services.po_rag import _convert_to_kg
        assert _convert_to_kg(3.0, 100.0) == 2.5

    def test_min_clamp(self):
        from app.services.po_rag import _convert_to_kg
        assert _convert_to_kg(0.1, 10.0) == 1.25

    def test_max_clamp(self):
        from app.services.po_rag import _convert_to_kg
        assert _convert_to_kg(50.0, 100.0) == 10.0


class TestRagPoIncrement:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_returns_none_when_no_chunks(self):
        from app.services.po_rag import rag_po_increment
        with patch("app.services.po_rag._call_search_async", new=AsyncMock(return_value=[])):
            result = self._run(rag_po_increment("hypertrophy", "cable", 100.0))
        assert result is None

    def test_returns_none_when_llm_returns_null(self):
        from app.services.po_rag import rag_po_increment
        with patch("app.services.po_rag._call_search_async", new=AsyncMock(return_value=SAMPLE_CHUNKS)), \
             patch("app.services.po_rag._call_llm_async", new=AsyncMock(return_value='{"increment_percent": null}')):
            result = self._run(rag_po_increment("hypertrophy", "cable", 100.0))
        assert result is None

    def test_converts_percent_to_kg(self):
        from app.services.po_rag import rag_po_increment
        with patch("app.services.po_rag._call_search_async", new=AsyncMock(return_value=SAMPLE_CHUNKS)), \
             patch("app.services.po_rag._call_llm_async", new=AsyncMock(return_value='{"increment_percent": 5}')):
            result = self._run(rag_po_increment("hypertrophy", "cable", 100.0))
        assert result == 5.0

    def test_returns_none_when_1rm_is_none(self):
        from app.services.po_rag import rag_po_increment
        with patch("app.services.po_rag._call_search_async", new=AsyncMock(return_value=SAMPLE_CHUNKS)), \
             patch("app.services.po_rag._call_llm_async", new=AsyncMock(return_value='{"increment_percent": 5}')):
            result = self._run(rag_po_increment("hypertrophy", "cable", None))
        assert result is None

    def test_cache_hit_skips_rag_and_llm(self):
        from app.services.po_rag import rag_po_increment, _cache_set
        _cache_set("hypertrophy", "cable", 5.0)
        with patch("app.services.po_rag._call_search_async", new=AsyncMock()) as mock_search, \
             patch("app.services.po_rag._call_llm_async", new=AsyncMock()) as mock_llm:
            result = self._run(rag_po_increment("hypertrophy", "cable", 100.0))
            mock_search.assert_not_called()
            mock_llm.assert_not_called()
        assert result == 5.0

    def test_cache_hit_with_none_pct_returns_none(self):
        from app.services.po_rag import rag_po_increment, _cache_set
        _cache_set("hypertrophy", "cable", None)
        with patch("app.services.po_rag._call_search_async", new=AsyncMock()) as mock_search:
            result = self._run(rag_po_increment("hypertrophy", "cable", 100.0))
            mock_search.assert_not_called()
        assert result is None

    def test_chroma_exception_returns_none(self):
        from app.services.po_rag import rag_po_increment
        with patch("app.services.po_rag._call_search_async", new=AsyncMock(side_effect=RuntimeError("chroma down"))):
            result = self._run(rag_po_increment("hypertrophy", "cable", 100.0))
        assert result is None

    def test_invalid_json_returns_none(self):
        from app.services.po_rag import rag_po_increment
        with patch("app.services.po_rag._call_search_async", new=AsyncMock(return_value=SAMPLE_CHUNKS)), \
             patch("app.services.po_rag._call_llm_async", new=AsyncMock(return_value="not valid json")):
            result = self._run(rag_po_increment("hypertrophy", "cable", 100.0))
        assert result is None

    def test_non_numeric_pct_returns_none(self):
        from app.services.po_rag import rag_po_increment
        with patch("app.services.po_rag._call_search_async", new=AsyncMock(return_value=SAMPLE_CHUNKS)), \
             patch("app.services.po_rag._call_llm_async", new=AsyncMock(return_value='{"increment_percent": "five"}')):
            result = self._run(rag_po_increment("hypertrophy", "cable", 100.0))
        assert result is None
```

- [ ] **Step 3: 테스트 실패 확인**

```bash
cd server && pytest tests/test_po_rag.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.po_rag'`

- [ ] **Step 4: `po_rag.py` 구현**

`server/app/services/po_rag.py` 신규 생성:

```python
"""RAG 기반 Progressive Overload 증가량 추출 서비스.

ChromaDB에서 load_progression 논문 청크를 검색하고,
LLM이 % 증가량을 추출한 뒤 사용자 1RM 기반 kg로 변환한다.

실패(논문 없음, LLM 오류, 1RM 없음 등) 시 None 반환 → po.py 하드코딩 fallback.
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# llm.py 동일 디렉터리 직접 import (rag.py 동일 패턴)
_SERVICES_DIR = Path(__file__).resolve().parent
if str(_SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICES_DIR))
from llm import generate as _llm_generate  # noqa: E402

# (goal, equipment_type) → (increment_percent_or_none, expires_at_monotonic)
_cache: dict[tuple[str, str], tuple[float | None, float]] = {}
_CACHE_TTL = 86400.0  # 24h


# ── 캐시 헬퍼 ─────────────────────────────────────────────────────────────────

def _cache_get(goal: str, equipment_type: str) -> tuple[bool, float | None]:
    entry = _cache.get((goal, equipment_type))
    if entry is None:
        return False, None
    value, expires_at = entry
    if time.monotonic() > expires_at:
        del _cache[(goal, equipment_type)]
        return False, None
    return True, value


def _cache_set(goal: str, equipment_type: str, value: float | None) -> None:
    _cache[(goal, equipment_type)] = (value, time.monotonic() + _CACHE_TTL)


# ── 변환 헬퍼 ─────────────────────────────────────────────────────────────────

def _convert_to_kg(increment_percent: float, user_1rm_kg: float) -> float:
    """% → 2.5kg 단위 반올림, [1.25, 10.0] kg 클램핑."""
    raw = user_1rm_kg * (increment_percent / 100.0)
    rounded = round(raw / 2.5) * 2.5
    return max(1.25, min(10.0, rounded))


def _build_prompt(goal: str, equipment_type: str, chunks: list[dict]) -> str:
    excerpts = "\n---\n".join(c.get("document", "") for c in chunks[:3])
    return (
        "<system>\n"
        "You are a sports science expert. Based ONLY on the provided paper excerpts, "
        'return a single JSON object with one key: "increment_percent" (number or null). '
        "This represents the recommended per-session weight increase as a percentage of "
        f"current working weight for {goal} training. "
        "If the papers do not contain enough evidence, "
        'return {"increment_percent": null}.\n'
        "</system>\n\n"
        "<paper_excerpts>\n"
        f"{excerpts}\n"
        "</paper_excerpts>\n\n"
        "<user_query>\n"
        f"Equipment type: {equipment_type}\n"
        f"Training goal: {goal}\n"
        "What percentage weight increase per session do these papers support?\n"
        "</user_query>"
    )


# ── 비동기 래퍼 (테스트 모킹 포인트) ─────────────────────────────────────────

async def _call_search_async(query: str, top_k: int) -> list[dict]:
    from app.services.rag import search_chunks
    return await asyncio.to_thread(search_chunks, query, top_k)


async def _call_llm_async(prompt: str) -> str:
    return await asyncio.to_thread(_llm_generate, prompt)


# ── 공개 API ──────────────────────────────────────────────────────────────────

async def rag_po_increment(
    goal: str,
    equipment_type: str,
    user_1rm_kg: float | None,
) -> float | None:
    """논문 기반 세션당 증가량(kg) 반환. 실패·논문 없음·1RM 없음 시 None."""
    hit, cached_pct = _cache_get(goal, equipment_type)
    if hit:
        if cached_pct is None or user_1rm_kg is None:
            return None
        return _convert_to_kg(cached_pct, user_1rm_kg)

    try:
        query = (
            f"{goal} resistance training progressive overload "
            "weight increment recommendation"
        )
        chunks = await _call_search_async(query, 3)

        if not chunks:
            _cache_set(goal, equipment_type, None)
            return None

        prompt = _build_prompt(goal, equipment_type, chunks)
        raw = await _call_llm_async(prompt)

        parsed = json.loads(raw.strip())
        pct = parsed.get("increment_percent")

        if pct is None or not isinstance(pct, (int, float)):
            _cache_set(goal, equipment_type, None)
            return None

        pct_float = float(pct)
        _cache_set(goal, equipment_type, pct_float)

        if user_1rm_kg is None:
            return None
        return _convert_to_kg(pct_float, user_1rm_kg)

    except Exception:
        logger.warning(
            "rag_po_increment failed for goal=%s equipment_type=%s",
            goal,
            equipment_type,
        )
        return None
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
cd server && pip install pytest-asyncio && pytest tests/test_po_rag.py -v
```

Expected: 전체 PASS

- [ ] **Step 6: 커밋**

```bash
git add server/app/services/po_rag.py server/tests/test_po_rag.py server/requirements.txt
git commit -m "feat: add po_rag service for RAG-based PO increment extraction"
```

---

## Task 4: `sessions.py` 연결

**Files:**
- Modify: `server/app/api/v1/sessions.py`

- [ ] **Step 1: import 2개 추가**

`server/app/api/v1/sessions.py`의 기존 import 블록을 수정:

```python
# 기존 (sessions.py:18-34)
from app.models import (
    Equipment,
    Exercise,
    ExerciseMuscle,
    Gym,
    MuscleGroup,
    Notification,
    NotificationType,
    RoutineDay,
    RoutineExercise,
    User,
    UserBodyMeasurement,
    WorkoutLog,
    WorkoutLogSet,
    WorkoutRoutine,
    WorkoutStatus,
)
```

→ `UserExercise1RM` 추가:

```python
from app.models import (
    Equipment,
    Exercise,
    ExerciseMuscle,
    Gym,
    MuscleGroup,
    Notification,
    NotificationType,
    RoutineDay,
    RoutineExercise,
    User,
    UserBodyMeasurement,
    UserExercise1RM,
    WorkoutLog,
    WorkoutLogSet,
    WorkoutRoutine,
    WorkoutStatus,
)
```

그리고 `sessions.py:56` 기존 줄 아래에 추가:

```python
from app.services import po
from app.services import po_rag  # 추가
```

- [ ] **Step 2: `_check_and_create_po_notifications()` 내 루프 수정**

`sessions.py:517-537` 의 기존 코드:

```python
        equipment_type = "barbell"
        max_stack = None
        if rex.equipment_id:
            equip = equip_map.get(rex.equipment_id)
            if equip:
                equipment_type = str(equip.equipment_type)
                max_stack = equip.max_stack

        result = po.calculate_increase(
            category=equipment_type,
            goal=goal,
            current_weight=float(cur_max_weight or 0),
            current_sets=int(set_count),
            max_stack=max_stack,
        )
```

→ 다음으로 교체:

```python
        equipment_type = "barbell"
        max_stack = None
        if rex.equipment_id:
            equip = equip_map.get(rex.equipment_id)
            if equip:
                equipment_type = str(equip.equipment_type)
                max_stack = equip.max_stack

        user_1rm_row = (
            await db.execute(
                select(UserExercise1RM.weight_kg)
                .where(
                    UserExercise1RM.user_id == user.id,
                    UserExercise1RM.exercise_id == rex.exercise_id,
                )
                .order_by(UserExercise1RM.estimated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        user_1rm_kg = float(user_1rm_row) if user_1rm_row is not None else None

        increment_override = await po_rag.rag_po_increment(goal, equipment_type, user_1rm_kg)

        result = po.calculate_increase(
            category=equipment_type,
            goal=goal,
            current_weight=float(cur_max_weight or 0),
            current_sets=int(set_count),
            max_stack=max_stack,
            increment_override=increment_override,
        )
```

- [ ] **Step 3: 기존 테스트 통과 확인**

```bash
cd server && pytest tests/test_sessions.py -v
```

Expected: 전체 PASS (기존 테스트 영향 없음)

- [ ] **Step 4: 전체 테스트 실행**

```bash
cd server && pytest tests/ -v
```

Expected: 전체 PASS

- [ ] **Step 5: 커밋**

```bash
git add server/app/api/v1/sessions.py
git commit -m "feat: wire rag_po_increment into session finish PO notification flow"
```

---

## Task 5: PR 생성

**Files:** 없음

- [ ] **Step 1: develop 기준 최신화 확인**

```bash
git fetch --prune
git log --oneline origin/develop..HEAD
```

Expected: Task 2~4의 3개 커밋이 보임

- [ ] **Step 2: PR 생성**

```bash
gh pr create \
  --base develop \
  --title "feat: RAG 기반 PO 자동 증량 제안" \
  --body "$(cat <<'EOF'
## Summary
- `po_rag.py` 신규 서비스: ChromaDB 논문 검색 → LLM % 추출 → 사용자 1RM 기반 kg 변환
- `po.py`: `calculate_increase()`에 `increment_override` 파라미터 추가
- `sessions.py`: 세션 완료 시 `rag_po_increment()` 호출 후 논문 기반 증가량 적용 (fallback: 기존 하드코딩)
- (goal, equipment_type) 조합 24h 인메모리 캐시로 반복 LLM 호출 방지

## Test plan
- [ ] `pytest tests/test_po.py` — increment_override 케이스 포함 전체 통과
- [ ] `pytest tests/test_po_rag.py` — 캐시 히트/미스, fallback, 클램핑 전체 통과
- [ ] `pytest tests/test_sessions.py` — 기존 세션 테스트 회귀 없음
- [ ] Swagger에서 `PATCH /sessions/{id}/finish` 호출 후 notifications 테이블에 PO 알림 생성 확인

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## 자체 검토

**스펙 커버리지:**
- ✅ RAG 검색 (ChromaDB, top_k=3, threshold 기존 동일) → `_call_search_async`
- ✅ LLM 추출 (`increment_percent` JSON) → `_call_llm_async`
- ✅ % → kg 변환, 2.5kg 단위 반올림, [1.25, 10.0] 클램핑 → `_convert_to_kg`
- ✅ 캐시 (goal, equipment_type) 키, TTL 24h
- ✅ Fallback (None 반환 → po.py 하드코딩)
- ✅ 세션 종료 시 1RM 조회 → `UserExercise1RM`
- ✅ `po.py` `increment_override` 파라미터

**타입 일관성:**
- `rag_po_increment() -> float | None` → `increment_override: float | None` → `po.calculate_increase()` ✅
- `_cache_set(goal, equipment_type, pct_float)` — `pct_float`는 `float` ✅
- `_convert_to_kg(pct_float, user_1rm_kg)` — 둘 다 `float` ✅
