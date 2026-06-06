# RAG 기반 자동 중량 증가 제안 설계

**날짜**: 2026-06-06  
**상태**: 승인됨  
**관련 파일**: `server/app/services/po.py`, `server/app/services/po_rag.py` (신규), `server/app/api/v1/sessions.py`

---

## 1. 목적

현재 `po.py`의 증가량(2.5kg, 5.0kg 등)은 하드코딩된 운동생리학 기준값이다.  
ChromaDB에 수집된 Progressive Overload 관련 논문(`load_progression` 쿼리 수집분)을 활용해  
세션 종료 시 LLM이 논문 청크에서 구체적인 % 증가 권장값을 추출하고, 이를 사용자 1RM 기반 kg로 변환한다.  
논문 미발견·LLM 실패 등 모든 예외는 기존 하드코딩 값으로 fallback한다.

---

## 2. 아키텍처 개요

### 신규/변경 파일

| 파일 | 변경 유형 | 내용 |
|---|---|---|
| `server/app/services/po_rag.py` | 신규 | RAG 기반 증가량 추출 서비스 |
| `server/app/services/po.py` | 수정 | `calculate_increase()`에 `increment_override` 파라미터 추가 |
| `server/app/api/v1/sessions.py` | 수정 | `_check_and_create_po_notifications()`에 `rag_po_increment()` 호출 삽입 |

### 변경 없는 범위

- `po.py`의 `check_po_trigger()`, `INCREASE`, `REP_UPPER_BOUNDS`
- `_create_po_notifications()` (exercise_id 기반 첫 번째 PO 함수)
- 알림 메시지 포맷 및 `NotificationType.PO_SUGGESTION`

---

## 3. 세션 종료 시 흐름

```
PATCH /sessions/{session_id}/finish
    └─ _check_and_create_po_notifications()
            ├─ po.check_po_trigger([prev_max_reps, cur_max_reps], goal)
            │       └─ False → continue (기존 동일)
            ├─ rag_po_increment(goal, equipment_type, user_1rm_kg, ...)   ← 신규
            │       ├─ ChromaDB 검색 (top_k=3, threshold=0.70)
            │       │   query: "{goal} resistance training progressive overload weight increment recommendation"
            │       ├─ top-3 청크 → LLM 호출 → increment_percent 추출
            │       ├─ % → kg 변환 (user_1rm_kg 기반, 2.5kg 단위 반올림)
            │       └─ 실패 시 None 반환
            └─ po.calculate_increase(..., increment_override=논문기반값 or None)
                    └─ override=None이면 기존 INCREASE 하드코딩값 사용
```

---

## 4. `po_rag.py` 상세 설계

### 캐시

`(goal, equipment_type)` 조합을 키로 서버 인메모리 dict 캐시, TTL 24시간.  
같은 목표+기구 조합은 매번 LLM을 호출하지 않는다.

```python
_cache: dict[tuple[str, str], tuple[float | None, float]] = {}
# key: (goal, equipment_type)
# value: (increment_kg | None, expires_at_timestamp)
```

### 함수 시그니처

```python
async def rag_po_increment(
    goal: str,
    equipment_type: str,
    user_1rm_kg: float | None,
    chroma_client,
    llm_client,
) -> float | None:
    """논문 기반 세션당 증가량(kg) 반환. 실패·논문 없음·1RM 없음 시 None."""
```

### LLM 프롬프트

```
<system>
You are a sports science expert. Based ONLY on the provided paper excerpts,
return a single JSON object with one key: "increment_percent" (number or null).
This represents the recommended per-session weight increase as a percentage of
current working weight for {goal} training.
If the papers do not contain enough evidence, return {"increment_percent": null}.
</system>

<paper_excerpts>
{chunk_1_text}
---
{chunk_2_text}
---
{chunk_3_text}
</paper_excerpts>

<user_query>
Equipment type: {equipment_type}
Training goal: {goal}
What percentage weight increase per session do these papers support?
</user_query>
```

### % → kg 변환

```python
increment_kg = user_1rm_kg * (increment_percent / 100)
increment_kg = round(increment_kg / 2.5) * 2.5      # 2.5kg 단위 반올림
increment_kg = max(1.25, min(10.0, increment_kg))   # 클램핑 [1.25, 10.0]
```

- `user_1rm_kg`가 None이면 변환 불가 → None 반환 → fallback

### 에러 처리

모든 예외(ChromaDB 연결 실패, LLM 타임아웃, JSON 파싱 오류 등)는 `logger.warning` 후 `None` 반환.  
세션 종료 API 응답에는 영향 없음.

---

## 5. `po.py` 변경

`calculate_increase()`에 `increment_override: float | None = None` 파라미터 추가.

```python
def calculate_increase(
    category: str,
    goal: str,
    current_weight: float,
    current_sets: int,
    max_stack: float | None = None,
    increment_override: float | None = None,  # 신규
) -> dict:
    goal_map = INCREASE.get(goal, INCREASE["endurance"])
    increment = increment_override if increment_override is not None else goal_map.get(category, 1.25)
    # 이하 기존 로직 동일
```

기존 `INCREASE` 테이블, `REP_UPPER_BOUNDS`, `check_po_trigger()` 변경 없음.

---

## 6. `sessions.py` 변경

`_check_and_create_po_notifications()` 내부에서 PO 트리거 확인 후 `rag_po_increment()` 호출.

```python
# PO 트리거 확인 후
user_1rm = await _get_user_1rm(user.id, rex.exercise_id, db)  # 기존 1RM 테이블 조회
increment = await rag_po_increment(goal, equipment_type, user_1rm, chroma_client, llm_client)
result = po.calculate_increase(
    category=equipment_type,
    goal=goal,
    current_weight=float(cur_max_weight or 0),
    current_sets=int(set_count),
    max_stack=max_stack,
    increment_override=increment,
)
```

---

## 7. 테스트 전략

- `po_rag.py` 단위 테스트: ChromaDB mock, LLM mock, 캐시 히트/미스, fallback 경로
- `po.py` 기존 테스트: `increment_override` 추가에 따른 케이스 보완
- `sessions.py` 통합 테스트: `rag_po_increment` mock → 기존 PO 알림 생성 흐름 유지 확인

---

## 8. 미결정 사항

- `user_exercise_1rm` 테이블에서 1RM 조회 헬퍼 함수 신규 작성 필요 여부 확인
- LLM 클라이언트 주입 방식 (기존 `llm.py` 재사용 vs 직접 호출) 확정
- ChromaDB 클라이언트를 `sessions.py`로 주입하는 방식 확정 (DI vs 전역 인스턴스)
