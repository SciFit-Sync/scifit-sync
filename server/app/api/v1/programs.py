"""프로그램 도메인 엔드포인트."""

import logging
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundError, ValidationError
from app.core.limiter import rate_limit
from app.models import Program, ProgramRoutine, User, WorkoutRoutine
from app.schemas.common import SuccessResponse
from app.schemas.programs import (
    CreateProgramRequest,
    DeleteProgramData,
    ProgramItem,
    ProgramListData,
    ProgramRoutineItem,
    UpdateProgramRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/programs", tags=["programs"])


def _parse_uuid(v: str, name: str) -> uuid.UUID:
    try:
        return uuid.UUID(v)
    except ValueError as e:
        raise ValidationError(message=f"잘못된 {name} 형식입니다.") from e


async def _program_to_dto(program: Program, db: AsyncSession) -> ProgramItem:
    routine_ids = [pr.routine_id for pr in sorted(program.program_routines, key=lambda x: x.order_index)]
    routines = []
    if routine_ids:
        rows = (await db.execute(select(WorkoutRoutine).where(WorkoutRoutine.id.in_(routine_ids)))).scalars().all()
        routine_map = {r.id: r for r in rows}
        for pr in sorted(program.program_routines, key=lambda x: x.order_index):
            r = routine_map.get(pr.routine_id)
            if r:
                routines.append(
                    ProgramRoutineItem(
                        routine_id=str(r.id),
                        name=r.name,
                        gym_name=None,
                        order_index=pr.order_index,
                    )
                )
    return ProgramItem(
        program_id=str(program.id),
        name=program.name,
        description=program.description,
        created_at=program.created_at,
        routines=routines,
    )


# ── GET /programs ─────────────────────────────────────────────────────────────
@rate_limit("60/minute")
@router.get("", response_model=SuccessResponse[ProgramListData], summary="프로그램 목록 조회")
async def list_programs(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    programs = (
        (
            await db.execute(
                select(Program)
                .where(Program.user_id == current_user.id)
                .options(selectinload(Program.program_routines))
                .order_by(Program.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    items = [await _program_to_dto(p, db) for p in programs]
    return SuccessResponse(data=ProgramListData(items=items))


# ── POST /programs ────────────────────────────────────────────────────────────
@rate_limit("60/minute")
@router.post("", response_model=SuccessResponse[ProgramItem], status_code=201, summary="프로그램 생성")
async def create_program(
    request: Request,
    body: CreateProgramRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    routine_uuids = [_parse_uuid(rid, "routine_id") for rid in body.routine_ids]

    valid = (
        (
            await db.execute(
                select(WorkoutRoutine.id).where(
                    WorkoutRoutine.id.in_(routine_uuids),
                    WorkoutRoutine.user_id == current_user.id,
                    WorkoutRoutine.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )

    if len(valid) != len(routine_uuids):
        raise ValidationError(message="존재하지 않거나 접근 권한이 없는 루틴이 포함되어 있습니다.")

    program = Program(
        user_id=current_user.id,
        name=body.name,
        description=body.description,
    )
    db.add(program)
    await db.flush()

    for idx, rid in enumerate(routine_uuids):
        db.add(ProgramRoutine(program_id=program.id, routine_id=rid, order_index=idx))

    await db.commit()
    await db.refresh(program)

    program_with_routines = (
        await db.execute(
            select(Program).where(Program.id == program.id).options(selectinload(Program.program_routines))
        )
    ).scalar_one()

    logger.info("Program %s created by user %s", program.id, current_user.id)
    return SuccessResponse(data=await _program_to_dto(program_with_routines, db))


# ── GET /programs/{id} ────────────────────────────────────────────────────────
@rate_limit("60/minute")
@router.get("/{program_id}", response_model=SuccessResponse[ProgramItem], summary="프로그램 상세 조회")
async def get_program(
    request: Request,
    program_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pid = _parse_uuid(program_id, "program_id")
    program = (
        await db.execute(
            select(Program)
            .where(Program.id == pid, Program.user_id == current_user.id)
            .options(selectinload(Program.program_routines))
        )
    ).scalar_one_or_none()

    if program is None:
        raise NotFoundError(message="프로그램을 찾을 수 없습니다.")

    return SuccessResponse(data=await _program_to_dto(program, db))


# ── PATCH /programs/{id} ─────────────────────────────────────────────────────
@rate_limit("60/minute")
@router.patch("/{program_id}", response_model=SuccessResponse[ProgramItem], summary="프로그램 수정")
async def update_program(
    request: Request,
    program_id: str,
    body: UpdateProgramRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pid = _parse_uuid(program_id, "program_id")
    program = (
        await db.execute(
            select(Program)
            .where(Program.id == pid, Program.user_id == current_user.id)
            .options(selectinload(Program.program_routines))
        )
    ).scalar_one_or_none()

    if program is None:
        raise NotFoundError(message="프로그램을 찾을 수 없습니다.")

    program.name = body.name
    program.description = body.description
    await db.commit()
    await db.refresh(program)

    return SuccessResponse(data=await _program_to_dto(program, db))


# ── DELETE /programs/{id} ─────────────────────────────────────────────────────
@rate_limit("60/minute")
@router.delete("/{program_id}", response_model=SuccessResponse[DeleteProgramData], summary="프로그램 삭제")
async def delete_program(
    request: Request,
    program_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pid = _parse_uuid(program_id, "program_id")
    program = (
        await db.execute(select(Program).where(Program.id == pid, Program.user_id == current_user.id))
    ).scalar_one_or_none()

    if program is None:
        raise NotFoundError(message="프로그램을 찾을 수 없습니다.")

    await db.delete(program)
    await db.commit()

    logger.info("Program %s deleted by user %s", pid, current_user.id)
    return SuccessResponse(data=DeleteProgramData(message="프로그램이 삭제되었습니다."))
