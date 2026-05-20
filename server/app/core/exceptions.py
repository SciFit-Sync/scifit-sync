class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 500,
        details: dict | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class ValidationError(AppError):
    def __init__(self, message: str = "입력값이 올바르지 않습니다", details: dict | None = None):
        super().__init__("VALIDATION_ERROR", message, 400, details)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "인증이 필요합니다", code: str = "UNAUTHORIZED"):
        super().__init__(code, message, 401)


class ForbiddenError(AppError):
    def __init__(self, message: str = "접근 권한이 없습니다", code: str = "FORBIDDEN"):
        super().__init__(code, message, 403)


class OnboardingRequiredError(AppError):
    def __init__(self, message: str = "온보딩을 완료해주세요"):
        super().__init__("ONBOARDING_REQUIRED", message, 403)


class EmailDuplicateError(AppError):
    def __init__(self, message: str = "이미 사용 중인 이메일입니다"):
        super().__init__("EMAIL_DUPLICATE", message, 409)


class NotFoundError(AppError):
    def __init__(self, message: str = "리소스를 찾을 수 없습니다"):
        super().__init__("NOT_FOUND", message, 404)


class ConflictError(AppError):
    def __init__(self, message: str = "이미 존재하는 리소스입니다", code: str = "CONFLICT"):
        super().__init__(code, message, 409)


class RateLimitedError(AppError):
    def __init__(self, message: str = "요청이 너무 많습니다. 잠시 후 다시 시도해주세요"):
        super().__init__("RATE_LIMITED", message, 429)


class InternalError(AppError):
    def __init__(self, message: str = "서버 내부 오류가 발생했습니다"):
        super().__init__("INTERNAL_ERROR", message, 500)


class ExternalServiceError(AppError):
    def __init__(
        self,
        message: str = "외부 서비스가 일시적으로 사용할 수 없습니다",
        code: str = "EXTERNAL_API_UNAVAILABLE",
    ):
        super().__init__(code, message, 503)
