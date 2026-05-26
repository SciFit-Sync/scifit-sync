"""백엔드 통합 테스트 스크립트.

루틴 생성(SSE)과 챗봇 SSE가 실제 백엔드와 올바르게 연동되는지 확인한다.

사용법:
    # 1. 먼저 액세스 토큰 발급
    python scripts/integration_test.py login --email <이메일> --password <비밀번호> --base-url http://localhost:8000

    # 2. 챗봇 SSE 확인
    python scripts/integration_test.py chat --token <TOKEN> --base-url http://localhost:8000

    # 3. 루틴 생성 SSE 확인 (gym_id 없이 — AI 헬스장 등록 필요 시 --gym-id 추가)
    python scripts/integration_test.py routine --token <TOKEN> --base-url http://localhost:8000

    # 4. 생성된 루틴 DB 저장 확인
    python scripts/integration_test.py check --token <TOKEN> --routine-id <UUID> --base-url http://localhost:8000
"""

import argparse
import json
import sys


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _print_sse(line: str) -> dict | None:
    """SSE data 라인을 파싱해서 출력. 이벤트 dict 반환."""
    if not line.startswith("data:"):
        return None
    raw = line[5:].strip()
    if raw == "[DONE]":
        print("  ── [DONE] ──────────────────────────")
        return None
    try:
        ev = json.loads(raw)
        etype = ev.get("type", "?")

        if etype == "chunk":
            print(ev.get("content", ""), end="", flush=True)
        elif etype == "session":
            print(f"\n[session] session_id={ev.get('session_id')}")
        elif etype == "started":
            print(f"[started] routine_id={ev.get('routine_id')}  goals={ev.get('goals')}")
        elif etype == "day_complete":
            day_data = ev.get("data", {})
            exs = day_data.get("exercises", [])
            print(
                f"\n[day_complete] Day {ev.get('day')}  "
                f"routine_day_id={day_data.get('routine_day_id')}  "
                f"exercises={len(exs)}개"
            )
            for ex in exs:
                print(
                    f"  └ exercise_id={ex.get('exercise_id')}  "
                    f"routine_exercise_id={ex.get('routine_exercise_id')}  "
                    f"{ex.get('sets')}세트×{ex.get('reps_min')}-{ex.get('reps_max')}회"
                )
            if not exs:
                print("  ⚠ exercises 없음 → _resolve_exercise_id 매칭 전부 실패했을 가능성")
        elif etype == "sources":
            sources = ev.get("sources", [])
            print(f"\n[sources] {len(sources)}개 논문")
            for s in sources:
                print(f"  └ PMID={s.get('pmid')}  {s.get('title', '')[:50]}")
        elif etype == "papers":
            sources = ev.get("sources", [])
            print(f"\n[papers] DB 저장={ev.get('count')}개  논문={len(sources)}개")
            for s in sources:
                print(f"  └ PMID={s.get('pmid')}  {s.get('title', '')[:50]}")
        elif etype == "done":
            print(f"\n[done] routine_id={ev.get('routine_id')}")
        elif etype == "error":
            print(f"\n[ERROR] {ev.get('message')}")
        else:
            print(f"\n[{etype}] {raw[:120]}")
        return ev
    except json.JSONDecodeError:
        print(f"  (non-JSON) {raw[:80]}")
        return None


def cmd_login(args):
    import urllib.request

    payload = json.dumps({"email": args.email, "password": args.password}).encode()
    req = urllib.request.Request(
        f"{args.base_url}/api/v1/auth/login",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        body = json.loads(resp.read())
    token = body.get("data", {}).get("access_token")
    if token:
        print(f"access_token={token}")
    else:
        print("로그인 실패:", body)


def cmd_chat(args):
    import urllib.request

    question = args.question or "벤치프레스 근비대에 최적인 세트×반복수는 얼마인가요?"
    payload = json.dumps({"content": question}).encode()
    req = urllib.request.Request(
        f"{args.base_url}/api/v1/chat/messages",
        data=payload,
        headers=_headers(args.token),
        method="POST",
    )

    print("\n=== 챗봇 SSE 테스트 ===")
    print(f"질문: {question}\n")
    events = []
    with urllib.request.urlopen(req) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").rstrip("\n\r")
            ev = _print_sse(line)
            if ev:
                events.append(ev)

    print("\n\n=== 결과 요약 ===")
    chunks = [e for e in events if e.get("type") == "chunk"]
    sources_ev = next((e for e in events if e.get("type") == "sources"), None)
    print(f"chunk 이벤트: {len(chunks)}개")
    print(
        f"sources 이벤트: {'있음 (' + str(len(sources_ev.get('sources', []))) + '개 논문)' if sources_ev else '없음'}"
    )
    if not chunks:
        print("⚠ chunk가 없음 → LLM 응답이 오지 않았거나 에러 발생")
    if not sources_ev:
        print("⚠ sources 없음 → 논문 DB가 비어 있거나 ChromaDB 검색 실패")


def cmd_routine(args):
    import urllib.request

    payload_dict = {
        "goals": ["hypertrophy"],
        "target_muscle_group_ids": ["chest", "triceps"],
        "split_type": "three",
        "session_minutes": 60,
    }
    if args.gym_id:
        payload_dict["gym_id"] = args.gym_id

    payload = json.dumps(payload_dict).encode()
    req = urllib.request.Request(
        f"{args.base_url}/api/v1/routines/generate",
        data=payload,
        headers=_headers(args.token),
        method="POST",
    )

    print("\n=== 루틴 생성 SSE 테스트 ===")
    print(f"payload: {json.dumps(payload_dict, ensure_ascii=False)}\n")

    events = []
    with urllib.request.urlopen(req) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").rstrip("\n\r")
            ev = _print_sse(line)
            if ev:
                events.append(ev)

    print("\n\n=== 결과 요약 ===")
    started = next((e for e in events if e.get("type") == "started"), None)
    day_completes = [e for e in events if e.get("type") == "day_complete"]
    papers_ev = next((e for e in events if e.get("type") == "papers"), None)
    done_ev = next((e for e in events if e.get("type") == "done"), None)
    errors = [e for e in events if e.get("type") == "error"]

    routine_id = (started or done_ev or {}).get("routine_id") or (done_ev or {}).get("routine_id")
    print(f"routine_id: {routine_id}")
    print(f"day_complete 이벤트: {len(day_completes)}개")
    for dc in day_completes:
        exs = dc.get("data", {}).get("exercises", [])
        print(
            f"  Day {dc.get('day')}: exercises {len(exs)}개  routine_day_id={dc.get('data', {}).get('routine_day_id')}"
        )
        if not exs:
            print("    ⚠ exercises 없음 → _resolve_exercise_id 매칭 실패 (exercises 테이블 확인 필요)")
    print(
        f"papers 이벤트: {'있음 (DB 저장=' + str((papers_ev or {}).get('count', 0)) + '개)' if papers_ev else '없음'}"
    )
    if errors:
        for e in errors:
            print(f"⚠ ERROR: {e.get('message')}")

    if routine_id:
        print("\n다음 명령으로 DB 저장 확인:")
        print(
            f"  python scripts/integration_test.py check --token <TOKEN> --routine-id {routine_id} --base-url {args.base_url}"
        )


def cmd_check(args):
    import urllib.request

    if not args.routine_id:
        print("--routine-id 필요")
        sys.exit(1)

    req = urllib.request.Request(
        f"{args.base_url}/api/v1/routines/{args.routine_id}",
        headers=_headers(args.token),
        method="GET",
    )

    print("\n=== 루틴 DB 저장 확인 ===")
    with urllib.request.urlopen(req) as resp:
        body = json.loads(resp.read())

    data = body.get("data", {})
    print(f"routine_id: {data.get('routine_id')}")
    print(f"name: {data.get('name')}")
    print(f"status: {data.get('status')}")
    days = data.get("days", [])
    print(f"\ndays: {len(days)}개")
    for day in days:
        exs = day.get("exercises", [])
        print(f"  Day {day.get('day_number')} — {day.get('label')}: exercises {len(exs)}개")
        for ex in exs:
            has_paper = ex.get("has_paper", False)
            print(
                f"    └ {ex.get('exercise_name')}  "
                f"{ex.get('sets')}×{ex.get('reps_min')}-{ex.get('reps_max')}  "
                f"weight={ex.get('weight_kg')}kg  "
                f"{'📄 논문 있음' if has_paper else '논문 없음'}"
            )
        if not exs:
            print("    ⚠ exercises 없음 → 운동명 매칭 실패로 저장 누락")

    if not days:
        print("⚠ days 없음 → routine 생성 자체가 실패했거나 day_complete 이벤트 처리 오류")


def main():
    parser = argparse.ArgumentParser(description="SciFit-Sync 백엔드 통합 테스트")
    parser.add_argument("--base-url", default="http://localhost:8000", help="백엔드 base URL")
    sub = parser.add_subparsers(dest="cmd")

    p_login = sub.add_parser("login", help="로그인 → access_token 출력")
    p_login.add_argument("--email", required=True)
    p_login.add_argument("--password", required=True)

    p_chat = sub.add_parser("chat", help="챗봇 SSE 테스트")
    p_chat.add_argument("--token", required=True)
    p_chat.add_argument("--question", default=None)

    p_routine = sub.add_parser("routine", help="루틴 생성 SSE 테스트")
    p_routine.add_argument("--token", required=True)
    p_routine.add_argument("--gym-id", default=None, help="gym_id (없으면 생략)")

    p_check = sub.add_parser("check", help="생성된 루틴 DB 저장 확인")
    p_check.add_argument("--token", required=True)
    p_check.add_argument("--routine-id", required=True)

    args = parser.parse_args()
    if args.cmd == "login":
        cmd_login(args)
    elif args.cmd == "chat":
        cmd_chat(args)
    elif args.cmd == "routine":
        cmd_routine(args)
    elif args.cmd == "check":
        cmd_check(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
