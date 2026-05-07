import hashlib
import logging
import random
import uuid
from datetime import date as date_type
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, Response
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
from app.core.exceptions import (
    ConflictError,
    EmailDuplicateError,
    ExternalServiceError,
    UnauthorizedError,
    ValidationError,
)
from app.models.user import (
    CareerLevel,
    EmailOtp,
    Gender,
    Provider,
    RefreshToken,
    User,
    UserBodyMeasurement,
    UserProfile,
)
from app.schemas.auth import (
    CheckUsernameData,
    KakaoLoginData,
    KakaoLoginRequest,
    LoginData,
    LoginRequest,
    LogoutRequest,
    PasswordResetData,
    PasswordResetEmailData,
    PasswordResetEmailRequest,
    PasswordResetRequest,
    RefreshData,
    RefreshRequest,
    RegisterData,
    RegisterRequest,
    ResendOtpData,
    ResendOtpRequest,
    VerifyEmailData,
    VerifyEmailRequest,
    WithdrawData,
)
from app.schemas.common import SuccessResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/login", response_model=SuccessResponse[LoginData], summary="로그인")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()

    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise UnauthorizedError(message="아이디 또는 비밀번호가 올바르지 않습니다.")

    if not user.is_active:
        raise UnauthorizedError(message="비활성화된 계정입니다")

    if not user.is_email_verified:
        raise UnauthorizedError(message="이메일 인증이 완료되지 않았습니다. 이메일을 확인해주세요.")

    now = datetime.utcnow()
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
            access_token=access_token,
            refresh_token=refresh_token,
            user_id=str(user.id),
            username=user.username,
        )
    )


@router.post("/logout", response_model=SuccessResponse[None], summary="로그아웃")
async def logout(
    body: LogoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    payload = verify_token(body.refresh_token, expected_type="refresh")

    if payload.get("sub") != str(current_user.id):
        raise UnauthorizedError()

    token_hash = _hash_token(body.refresh_token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.user_id == current_user.id,
            RefreshToken.revoked_at.is_(None),
        )
    )
    token_record = result.scalar_one_or_none()

    if token_record:
        token_record.revoked_at = datetime.utcnow()
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
    )
    db.add(user)
    await db.flush()  # user.id 확보

    # 프로필 생성 — 신규 스키마: gender/birth_date/height_cm/career_level은 NOT NULL.
    # 모두 제공된 경우에만 생성하고, 그렇지 않으면 온보딩 단계에서 채우도록 둔다.
    if (
        body.gender is not None
        and body.birth_date is not None
        and body.height is not None
        and body.career_level is not None
    ):
        db.add(
            UserProfile(
                user_id=user.id,
                gender=Gender(body.gender),
                birth_date=body.birth_date,
                height_cm=body.height,
                default_goals=body.goals or None,
                career_level=CareerLevel(body.career_level),
            )
        )

    # 체중이 입력된 경우 초기 측정 기록 생성
    if body.weight is not None:
        db.add(
            UserBodyMeasurement(
                user_id=user.id,
                weight_kg=body.weight,
                measured_at=date_type.today(),
            )
        )

    # OTP 생성 및 저장
    otp_code = f"{random.randint(0, 999999):06d}"
    db.add(
        EmailOtp(
            email=body.email,
            code=otp_code,
            expires_at=datetime.utcnow() + timedelta(minutes=10),
        )
    )
    await db.commit()

    # ⚠️ TODO: 실제 이메일 발송 (SendGrid / AWS SES)
    # 현재는 로그로 대체 (개발 환경)
    logger.info("OTP for %s: %s", body.email, otp_code)

    return SuccessResponse(
        data=RegisterData(
            user_id=str(user.id),
            username=user.username,
        )
    )


@router.post("/kakao", response_model=SuccessResponse[KakaoLoginData], summary="카카오 소셜 로그인")
async def kakao_login(
    body: KakaoLoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    # 카카오 사용자 정보 조회
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            kakao_resp = await client.get(
                "https://kapi.kakao.com/v2/user/me",
                headers={"Authorization": f"Bearer {body.access_token}"},
            )
    except httpx.RequestError as e:
        raise ExternalServiceError(message="카카오 API가 일시적으로 사용할 수 없습니다.") from e

    if kakao_resp.status_code in (400, 401):
        raise ValidationError(message="유효하지 않은 카카오 토큰입니다.")
    if not kakao_resp.is_success:
        raise ExternalServiceError(message="카카오 API가 일시적으로 사용할 수 없습니다.")

    kakao_data = kakao_resp.json()
    kakao_id = str(kakao_data["id"])
    kakao_account = kakao_data.get("kakao_account", {})
    kakao_email = kakao_account.get("email")
    kakao_nickname = (kakao_account.get("profile") or {}).get("nickname")

    # kakao_id(provider_id)로 기존 사용자 조회
    result = await db.execute(select(User).where(User.provider == Provider.KAKAO, User.provider_id == kakao_id))
    user = result.scalar_one_or_none()
    is_new_user = user is None

    if is_new_user:
        email = kakao_email or f"kakao_{kakao_id}@noemail.local"

        # 이메일 중복 확인
        if kakao_email:
            dup = await db.execute(select(User).where(User.email == kakao_email))
            if dup.scalar_one_or_none():
                raise ConflictError(message="이미 해당 이메일로 가입된 계정이 있습니다.", code="EMAIL_DUPLICATE")

        user = User(
            email=email,
            username=f"kakao_{kakao_id}",
            provider=Provider.KAKAO,
            provider_id=kakao_id,
            name=kakao_nickname or "사용자",
        )
        db.add(user)
        await db.flush()

        # UserProfile은 온보딩 단계에서 생성 — 필수 필드(gender/birth_date/height_cm/career_level)가
        # 카카오 응답만으로는 채워지지 않으므로 여기서는 생성하지 않는다.
        await db.commit()

        logger.info("Kakao user %s registered (user_id=%s)", kakao_id, user.id)

    # JWT 발급
    now = datetime.utcnow()
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

    logger.info("Kakao user %s logged in (user_id=%s)", kakao_id, user.id)

    if is_new_user:
        response.status_code = 201

    return SuccessResponse(
        data=KakaoLoginData(
            access_token=access_token,
            refresh_token=refresh_token,
            is_new_user=is_new_user,
            message="온보딩을 완료해주세요." if is_new_user else None,
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# 추가 엔드포인트: #5 #6 #7 #8 #42
# ─────────────────────────────────────────────────────────────────────────────


@router.get(
    "/check-username",
    response_model=SuccessResponse[CheckUsernameData],
    summary="아이디 사용 가능 여부 확인",
)
async def check_username(username: str, db: AsyncSession = Depends(get_db)):
    if len(username) < 2 or len(username) > 20:
        raise ValidationError(message="사용자명은 2~20자여야 합니다.")
    existing = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    return SuccessResponse(data=CheckUsernameData(username=username, available=existing is None))


@router.post(
    "/password/reset-email",
    response_model=SuccessResponse[PasswordResetEmailData],
    summary="비밀번호 재설정 메일 발송",
)
async def password_reset_email(body: PasswordResetEmailRequest, db: AsyncSession = Depends(get_db)):
    """⚠️ TODO: 메일 발송 인프라 연동 필요. 현재는 스텁."""
    user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    # 보안상 사용자 존재 여부에 무관하게 동일 응답
    logger.info("Password reset email requested for %s (exists=%s)", body.email, user is not None)
    return SuccessResponse(data=PasswordResetEmailData(sent=True, message="비밀번호 재설정 메일이 발송되었습니다."))


@router.patch(
    "/password/reset",
    response_model=SuccessResponse[PasswordResetData],
    summary="비밀번호 재설정",
)
async def password_reset(body: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    """비밀번호 재설정 토큰을 검증하고 새 비밀번호로 갱신한다."""
    payload = verify_token(body.token, expected_type="reset")
    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedError(message="유효하지 않은 토큰입니다.")

    if len(body.new_password) < 8:
        raise ValidationError(message="비밀번호는 8자 이상이어야 합니다.")

    user = (await db.execute(select(User).where(User.id == uuid.UUID(user_id)))).scalar_one_or_none()
    if user is None:
        raise UnauthorizedError(message="사용자를 찾을 수 없습니다.")

    user.password_hash = hash_password(body.new_password)
    await db.commit()
    return SuccessResponse(data=PasswordResetData(success=True))


@router.delete("/withdraw", response_model=SuccessResponse[WithdrawData], summary="회원 탈퇴")
async def withdraw(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current_user.is_active = False
    # 모든 refresh token 무효화
    refresh_tokens = (
        (await db.execute(select(RefreshToken).where(RefreshToken.user_id == current_user.id))).scalars().all()
    )
    now_utc = datetime.utcnow()
    for rt in refresh_tokens:
        rt.revoked_at = now_utc
    await db.commit()
    return SuccessResponse(data=WithdrawData(user_id=str(current_user.id), success=True))


@router.post("/verify-email", response_model=SuccessResponse[VerifyEmailData], summary="이메일 OTP 인증")
async def verify_email(body: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    now = datetime.utcnow()
    otp = (
        await db.execute(
            select(EmailOtp).where(
                EmailOtp.email == body.email,
                EmailOtp.code == body.otp,
                EmailOtp.used_at.is_(None),
                EmailOtp.expires_at > now,
            )
        )
    ).scalar_one_or_none()

    if otp is None:
        raise ValidationError(message="OTP가 유효하지 않거나 만료되었습니다.")

    otp.used_at = now

    user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if user is None:
        raise ValidationError(message="사용자를 찾을 수 없습니다.")

    user.is_email_verified = True
    await db.commit()

    logger.info("Email verified for %s", body.email)
    return SuccessResponse(data=VerifyEmailData(verified=True, message="이메일 인증이 완료되었습니다."))


@router.post("/resend-otp", response_model=SuccessResponse[ResendOtpData], summary="OTP 재발송")
async def resend_otp(body: ResendOtpRequest, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    # 보안상 사용자 존재 여부에 무관하게 동일 응답
    if user and not user.is_email_verified:
        otp_code = f"{random.randint(0, 999999):06d}"
        db.add(
            EmailOtp(
                email=body.email,
                code=otp_code,
                expires_at=datetime.utcnow() + timedelta(minutes=10),
            )
        )
        await db.commit()
        # ⚠️ TODO: 실제 이메일 발송 (SendGrid / AWS SES)
        logger.info("OTP resent for %s: %s", body.email, otp_code)

    return SuccessResponse(data=ResendOtpData(sent=True, message="인증 코드가 재발송되었습니다."))


@router.post("/refresh", response_model=SuccessResponse[RefreshData], summary="액세스 토큰 갱신")
async def refresh_token_endpoint(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Refresh Token Rotation — Grace Period 10초 + family revoke."""
    payload = verify_token(body.refresh_token, expected_type="refresh")
    user_id_str = payload.get("sub")
    family_id_str = payload.get("family_id")
    if not user_id_str or not family_id_str:
        raise UnauthorizedError(message="유효하지 않은 토큰입니다.")

    token_hash = _hash_token(body.refresh_token)
    rec = (await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))).scalar_one_or_none()
    if rec is None:
        raise UnauthorizedError(message="유효하지 않은 토큰입니다.")

    now_utc = datetime.utcnow()

    # 이미 revoke된 토큰이면서 grace period(10초)도 지났다면 family 전체를 revoke (재사용 공격 방지)
    if rec.revoked_at is not None and (now_utc - rec.revoked_at).total_seconds() > 10:
        family = (await db.execute(select(RefreshToken).where(RefreshToken.family_id == rec.family_id))).scalars().all()
        for t in family:
            if t.revoked_at is None:
                t.revoked_at = now_utc
        await db.commit()
        raise UnauthorizedError(message="토큰 재사용이 감지되었습니다.")

    # 새 토큰 발급 + 기존 토큰 revoke
    rec.revoked_at = now_utc
    new_access = create_access_token(uuid.UUID(user_id_str))
    new_refresh = create_refresh_token(uuid.UUID(user_id_str), family_id=rec.family_id)
    db.add(
        RefreshToken(
            user_id=rec.user_id,
            token_hash=_hash_token(new_refresh),
            family_id=rec.family_id,
            expires_at=now_utc + timedelta(days=get_settings().REFRESH_TOKEN_EXPIRE_DAYS),
        )
    )
    await db.commit()

    return SuccessResponse(data=RefreshData(access_token=new_access, refresh_token=new_refresh))
