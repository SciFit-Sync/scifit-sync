"""DEPRECATED — Alembic 마이그레이션을 사용하세요.

원래 SQLAlchemy의 ``Base.metadata.create_all`` 으로 테이블을 만들던 스크립트이지만,
프로젝트 표준은 Alembic이며 이 파일은 머지 후 삭제 예정입니다.

대신 사용:
    cd server && alembic upgrade head
"""
