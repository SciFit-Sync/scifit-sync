"""Admin API — MLOps 파이프라인 연동용.

GitHub Actions에서 실행된 논문 임베딩 결과를 서버 ChromaDB로 수신하는 엔드포인트.
ADMIN_API_TOKEN으로 인증.
"""

from fastapi import APIRouter, Header

from app.core.exceptions import ForbiddenError, InternalError

router = APIRouter(prefix="/admin", tags=["admin"])


async def _verify_admin_token(x_admin_token: str = Header(...)) -> None:
    """Admin 토큰 검증 (GitHub Actions secrets 연동)."""
    from app.core.config import get_settings

    settings = get_settings()
    # TODO: ADMIN_API_TOKEN 환경변수 추가 후 활성화
    if not settings.GEMINI_API_KEY:  # placeholder — 실제로는 ADMIN_API_TOKEN 비교
        raise ForbiddenError(message="Admin 인증이 필요합니다")


@router.post("/rag/ingest")
async def ingest_papers():
    """MLOps 파이프라인에서 처리된 논문 청크+임베딩을 ChromaDB에 수신한다.

    TODO (BE-6에서 구현):
    - Request Body: chunks + embeddings 배열
    - ChromaDB upsert 로직
    - Admin 토큰 인증
    """
    raise InternalError(message="아직 구현되지 않았습니다. BE-6 단계에서 구현 예정.")
