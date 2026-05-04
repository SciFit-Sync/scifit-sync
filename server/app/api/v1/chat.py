"""챗봇 도메인 엔드포인트.

CLAUDE.md / api-endpoints.md #37-39.

⚠️ POST /chat/messages 의 RAG 파이프라인은 현재 SSE 스켈레톤만 제공.
실제 ChromaDB + LLM 연동은 별도 구현 필요.
"""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.models import ChatMessage, ChatRole, ChatSession, User
from app.schemas.chat import (
    ChatMessageItem,
    ChatMessageListData,
    RecommendedRoutineItem,
    RecommendedRoutinesData,
    SendChatMessageRequest,
)
from app.schemas.common import SuccessResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


def _parse_uuid(v: str, name: str) -> uuid.UUID:
    try:
        return uuid.UUID(v)
    except ValueError as e:
        raise ValidationError(message=f"잘못된 {name} 형식입니다.") from e


# ── POST /chat/messages (SSE) ─────────────────────────────────────────────────
@router.post("/messages", summary="챗봇 메시지 전송 (SSE)")
async def send_chat_message(
    body: SendChatMessageRequest,
    current_user: User = Depends(get_current_user),
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
        # ⚠️ TODO: 실제 RAG 파이프라인 (한→영 번역 → ChromaDB 검색 → LLM 스트리밍)
        # CLAUDE.md §6 RAG 파이프라인 참고
        yield (f"id: evt_001\ndata: {json.dumps({'type': 'session', 'session_id': session_id_str})}\n\n")
        await asyncio.sleep(0)
        yield (f"id: evt_002\ndata: {json.dumps({'type': 'chunk', 'content': 'RAG 챗봇 미구현 — TODO'})}\n\n")
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── GET /chat/messages ────────────────────────────────────────────────────────
@router.get("/messages", response_model=SuccessResponse[ChatMessageListData], summary="챗봇 히스토리")
async def list_chat_messages(
    session_id: str = Query(...),
    current_user: User = Depends(get_current_user),
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
            role=m.role.value if m.role else "user",
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
    current_user: User = Depends(get_current_user),
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
