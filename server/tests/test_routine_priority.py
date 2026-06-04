"""복수 부위 선택 시 우선순위 배분(_allocate_priority_slots) + 프롬프트 반영 단위 테스트.

선택 순서를 우선순위로 보고(첫=메인) 운동 개수를 부위별로 배분하는 로직을 검증한다.
"""

import pytest

from app.services.rag import UserProfile, _allocate_priority_slots, _build_routine_prompt


class TestAllocatePrioritySlots:
    def test_empty(self):
        assert _allocate_priority_slots([], 6) == []

    def test_single_gets_all(self):
        assert _allocate_priority_slots(["arms"], 5) == [("arms", 5)]

    def test_two_main_gets_more(self):
        alloc = _allocate_priority_slots(["arms", "chest"], 6)
        assert dict(alloc) == {"arms": 4, "chest": 2}
        # 합계 보존 + 메인이 가장 큼
        assert sum(c for _, c in alloc) == 6
        assert alloc[0][1] > alloc[1][1]

    def test_three_main_weighted(self):
        alloc = _allocate_priority_slots(["a", "b", "c"], 6)
        assert sum(c for _, c in alloc) == 6
        assert alloc[0][1] >= alloc[1][1]
        assert alloc[0][1] >= alloc[2][1]
        assert all(c >= 1 for _, c in alloc)  # 각 부위 최소 1개

    def test_total_le_count_one_each(self):
        # 운동 수가 부위 수보다 적/같으면 각 1개씩 (최소 보장)
        assert _allocate_priority_slots(["a", "b", "c"], 2) == [("a", 1), ("b", 1), ("c", 1)]

    @pytest.mark.parametrize("total", [4, 5, 6, 8, 10])
    def test_sum_preserved_and_main_max(self, total):
        alloc = _allocate_priority_slots(["x", "y", "z"], total)
        assert sum(c for _, c in alloc) == total
        assert alloc[0][1] == max(c for _, c in alloc)


def _profile(**kw):
    base = dict(goals=["hypertrophy"], body_weight=70.0, fitness_career="beginner", session_minutes=60)
    base.update(kw)
    return UserProfile(**base)


class TestPromptPriorityBlock:
    def test_multi_target_includes_priority_block(self):
        prompt = _build_routine_prompt(
            _profile(target_priority=["arms", "chest"], target_muscles=["arms", "chest"]), []
        )
        assert "PRIORITY ALLOCATION" in prompt
        assert "MAIN focus" in prompt
        # 메인(arms)이 먼저 등장
        assert prompt.index("arms") < prompt.index("chest")

    def test_single_target_no_priority_block(self):
        prompt = _build_routine_prompt(_profile(target_priority=["arms"], target_muscles=["arms"]), [])
        assert "PRIORITY ALLOCATION" not in prompt

    def test_no_target_no_priority_block(self):
        prompt = _build_routine_prompt(_profile(), [])
        assert "PRIORITY ALLOCATION" not in prompt
