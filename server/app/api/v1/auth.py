import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    verify_password,
    verify_token,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import ConflictError, EmailDuplicateError, UnauthorizedError
from app.models.user import CareerLevel, FitnessGoal, RefreshToken, User, UserBodyMeasurement, UserProfile
from app.schemas.auth import LoginData, LoginRequest, LogoutRequest, RegisterData, RegisterRequest
from app.schemas.common import SuccessResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/login", response_model=SuccessResponse[LoginData], summary="로그인")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise UnauthorizedError(message="아이디 또는 비밀번호가 올바르지 않습니다.")

    if not user.is_active:
        raise UnauthorizedError(message="비활성화된 계정입니다")

    now = datetime.now(timezone.utc)
    settings = get_settings()
    family_id = uuid.uuid4()
    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id, family_id=family_id)

    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=_hash_token(refresh_token),
            family_id=family_id,
            expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
    )
    await db.commit()

    logger.info("User %s logged in", user.id)

    return SuccessResponse(
        data=LoginData(
            accessToken=access_token,
            refreshToken=refresh_token,
            userId=str(user.id),
            username=user.username,
        )
    )


@router.post("/logout", response_model=SuccessResponse[None], summary="로그아웃")
async def logout(
    body: LogoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    payload = verify_token(body.refreshToken, expected_type="refresh")

    if payload.get("sub") != str(current_user.id):
        raise UnauthorizedError()

    token_hash = _hash_token(body.refreshToken)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.user_id == current_user.id,
            RefreshToken.revoked_at.is_(None),
        )
    )
    token_record = result.scalar_one_or_none()

    if token_record:
        token_record.revoked_at = datetime.now(timezone.utc)
        await db.commit()

    logger.info("User %s logged out", current_user.id)

    return SuccessResponse(data=None)


@router.post("/register", response_model=SuccessResponse[RegisterData], status_code=201, summary="회원가입")
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # 이메일 중복 확인
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise EmailDuplicateError(message="이미 사용 중인 이메일입니다.")

    # 아이디 중복 확인
    result = await db.execute(select(User).where(User.username == body.username))
    if result.scalar_one_or_none():
        raise ConflictError(message="이미 사용 중인 아이디입니다.")

    user = User(
        email=body.email,
        username=body.username,
        password_hash=hash_password(body.password),
        name=body.name,
        phone=body.phone,
    )
    db.add(user)
    await db.flush()  # user.id 확보

    # 프로필 생성
    fitness_goal = FitnessGoal(body.goals[0]) if body.goals else None
    career_level = CareerLevel(body.careerLevel) if body.careerLevel else None

    db.add(
        UserProfile(
            user_id=user.id,
            gender=body.gender,
            age=body.age,
            fitness_goal=fitness_goal,
            career_level=career_level,
        )
    )

    # 신체 정보 생성
    if body.height is not None or body.weight is not None:
        db.add(
            UserBodyMeasurement(
                user_id=user.id,
                height_cm=body.height,
                weight_kg=body.weight,
            )
        )

    await db.commit()

    logger.info("User %s registered", user.id)

    return SuccessResponse(
        data=RegisterData(
            userId=str(user.id),
            username=user.username,
        )
    )
