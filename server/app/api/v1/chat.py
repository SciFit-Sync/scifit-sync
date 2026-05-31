"""챗봇 도메인 엔드포인트.

CLAUDE.md / api-endpoints.md #37-39.
"""

import asyncio
import json
import logging
import threading
import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_required_profile
from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.core.limiter import rate_limit
from app.models import ChatMessage, ChatRole, ChatSession, User
from app.schemas.chat import (
    ChatMessageItem,
    ChatMessageListData,
    RecommendedRoutineItem,
    RecommendedRoutinesData,
    SendChatMessageRequest,
)
from app.schemas.common import SuccessResponse
from app.services.rag import chat_rag_stream

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


def _parse_uuid(v: str, name: str) -> uuid.UUID:
    try:
        return uuid.UUID(v)
    except ValueError as e:
        raise ValidationError(message=f"잘못된 {name} 형식입니다.") from e


async def _async_iter_sync_gen(make_gen):
    """블로킹 sync generator를 백그라운드 스레드에서 돌리고 async iterator로 노출."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    sentinel = object()

    def producer():
        try:
            for item in make_gen():
                loop.call_soon_threadsafe(queue.put_nowait, item)
        except Exception as e:  # noqa: BLE001
            logger.exception("챗봇 RAG 생성 중 예외")
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "message": f"RAG 파이프라인 오류: {e}"},
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, sentinel)

    threading.Thread(target=producer, daemon=True).start()

    while True:
        item = await queue.get()
        if item is sentinel:
            return
        yield item


# ── POST /chat/messages (SSE) ─────────────────────────────────────────────────
@router.post("/messages", summary="챗봇 메시지 전송 (SSE)")
@rate_limit("5/minute")
async def send_chat_message(
    request: Request,
    body: SendChatMessageRequest,
    current_user: User = Depends(get_required_profile),
    db: AsyncSession = Depends(get_db),
):
    # 세션 확보 (없으면 신규 생성)
    if body.session_id:
        session = await _get_my_session(body.session_id, current_user, db)
    else:
        session = ChatSession(
            user_id=current_user.id,
            title=body.content[:50],
        )
        db.add(session)
        await db.flush()

    # 현재 메시지 저장 전에 이전 대화 히스토리 로드 (최근 10개 메시지 = 5턴)
    prev_msgs = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session.id)
                .order_by(ChatMessage.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    history = [{"role": str(m.role), "content": m.content} for m in reversed(prev_msgs)]

    # 사용자 메시지 저장
    user_msg = ChatMessage(
        session_id=session.id,
        role=ChatRole.USER,
        content=body.content,
    )
    db.add(user_msg)
    await db.commit()

    session_id_str = str(session.id)

    async def stream():
        full_answer_parts: list[str] = []
        source_paper_ids: list[str] = []
        seq = 0

        yield f"id: evt_{seq:03d}\ndata: {json.dumps({'type': 'session', 'session_id': session_id_str}, ensure_ascii=False)}\n\n"
        seq += 1

        try:
            async for ev in _async_iter_sync_gen(lambda: chat_rag_stream(body.content, history)):
                etype = ev.get("type")
                seq += 1

                if etype == "chunk":
                    content = ev.get("content", "")
                    full_answer_parts.append(content)
                    yield f"id: evt_{seq:03d}\ndata: {json.dumps({'type': 'chunk', 'content': content}, ensure_ascii=False)}\n\n"

                elif etype == "sources":
                    sources = ev.get("sources", [])
                    source_paper_ids = [s.get("doi") or s.get("pmid") for s in sources if s.get("doi") or s.get("pmid")]
                    yield f"id: evt_{seq:03d}\ndata: {json.dumps({'type': 'sources', 'sources': sources}, ensure_ascii=False)}\n\n"

                elif etype == "error":
                    yield f"id: evt_{seq:03d}\ndata: {json.dumps({'type': 'error', 'message': ev.get('message', '')}, ensure_ascii=False)}\n\n"

                elif etype == "done":
                    break

        except Exception:
            logger.exception("챗봇 SSE 스트리밍 오류")

        # 어시스턴트 메시지 저장
        full_answer = "".join(full_answer_parts)
        if full_answer:
            db.add(
                ChatMessage(
                    session_id=session.id,
                    role=ChatRole.ASSISTANT,
                    content=full_answer,
                    paper_ids=source_paper_ids or None,
                )
            )
            await db.commit()

        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── GET /chat/messages ────────────────────────────────────────────────────────
@router.get("/messages", response_model=SuccessResponse[ChatMessageListData], summary="챗봇 히스토리")
async def list_chat_messages(
    session_id: str = Query(...),
    current_user: User = Depends(get_required_profile),
    db: AsyncSession = Depends(get_db),
):
    session = await _get_my_session(session_id, current_user, db)

    msgs = (
        (
            await db.execute(
                select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at)
            )
        )
        .scalars()
        .all()
    )

    items = [
        ChatMessageItem(
            message_id=str(m.id),
            role=str(m.role) if m.role else "user",
            content=m.content,
            paper_ids=[str(pid) for pid in m.paper_ids] if m.paper_ids else None,
            created_at=m.created_at,
        )
        for m in msgs
    ]
    return SuccessResponse(data=ChatMessageListData(session_id=session_id, items=items))


# ── GET /chat/recommended-routines ────────────────────────────────────────────
@router.get(
    "/recommended-routines",
    response_model=SuccessResponse[RecommendedRoutinesData],
    summary="챗봇 기반 추천 루틴",
)
async def recommended_routines(
    current_user: User = Depends(get_required_profile),
):
    """⚠️ TODO: 사용자 프로필 + 최근 챗 히스토리 + RAG로 추천 생성.
    현재는 빈 목록 반환.
    """
    return SuccessResponse(data=RecommendedRoutinesData(items=[]))


async def _get_my_session(session_id: str, user: User, db: AsyncSession) -> ChatSession:
    sid = _parse_uuid(session_id, "session_id")
    s = (
        await db.execute(select(ChatSession).where(ChatSession.id == sid, ChatSession.user_id == user.id))
    ).scalar_one_or_none()
    if s is None:
        raise NotFoundError(message="챗 세션을 찾을 수 없습니다.")
    return s


# 사용 안 하는 import 정리용 placeholder
_ = RecommendedRoutineItem
