"""`@rate_limit` 데코레이터 순서 회귀 차단 (이슈 #188 B2).

배경
----
FastAPI의 `@router.<method>(...)` 는 데코레이트된 함수를 라우터에 등록하면서
그 함수를 **그대로** 반환한다. 따라서 `@rate_limit` 이 `@router` 보다 *위*에 오면
(= 데코레이터가 나중에 적용되면) 라우터는 rate_limit 으로 감싸지지 않은 raw 함수를
등록하고, rate limiting 이 **조용히 무효화**된다.

올바른 순서:
    @router.get(...)        # 위 — wrap 된 함수를 등록
    @rate_limit("60/minute") # 아래 — raw 함수를 먼저 감쌈
    async def handler(): ...

이 버그는 이슈 #188(users/gyms)과 PR #209(programs)에서 반복 발생했다.
런타임이 아닌 소스 AST 를 검사해 영구적으로 차단한다.
(`RATE_LIMIT_ENABLED=false` 인 테스트 환경에서도 동작하도록 AST 정적 검사로 구현.)
"""

import ast
from pathlib import Path

_API_DIR = Path(__file__).resolve().parent.parent / "app" / "api" / "v1"
_ROUTER_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def _router_decorator_index(decorators: list[ast.expr]) -> int | None:
    """`@router.<method>(...)` 데코레이터의 위치(없으면 None)."""
    for i, dec in enumerate(decorators):
        if (
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and isinstance(dec.func.value, ast.Name)
            and dec.func.value.id == "router"
            and dec.func.attr in _ROUTER_METHODS
        ):
            return i
    return None


def _rate_limit_decorator_index(decorators: list[ast.expr]) -> int | None:
    """`@rate_limit(...)` 데코레이터의 위치(없으면 None)."""
    for i, dec in enumerate(decorators):
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == "rate_limit":
            return i
    return None


def test_rate_limit_is_below_router_decorator() -> None:
    """모든 라우터 핸들러에서 `@rate_limit` 은 `@router.<method>` *아래*에 있어야 한다."""
    violations: list[str] = []
    for path in sorted(_API_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = node.decorator_list
            router_i = _router_decorator_index(decorators)
            rate_limit_i = _rate_limit_decorator_index(decorators)
            # 둘 다 존재하고 rate_limit 이 router 보다 위(작은 인덱스)면 버그.
            if router_i is not None and rate_limit_i is not None and rate_limit_i < router_i:
                violations.append(f"{path.name}::{node.name}")

    assert not violations, (
        "다음 핸들러에서 @rate_limit 이 @router 위에 있어 rate limiting 이 무효화됩니다 "
        "(이슈 #188 B2). @router 를 위로, @rate_limit 을 그 아래(def 바로 위)로 swap 하세요:\n  - "
        + "\n  - ".join(violations)
    )
