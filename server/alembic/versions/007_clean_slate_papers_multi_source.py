"""clean slate papers and paper_chunks for multi-source ingestion

Phase 1 다중 소스 + evidence_weight 도입 (Task 12).

변경 사항:
- papers: DOI를 primary lookup으로 전환 (NOT NULL UNIQUE).
  - 신규 컬럼: pmcid, openalex_id, publication_types(text[]),
              evidence_weight(numeric 3,2), fulltext_source, search_categories(text[]).
  - published_year 인덱스 추가, pmid는 nullable(UNIQUE 제거) + 일반 인덱스.
  - publication_types / search_categories GIN 인덱스.
- paper_chunks: evidence_weight, publication_types 컬럼 추가, chroma_id 제거.
  - (paper_id, chunk_index) UNIQUE 보장.
- 기존 데이터는 mlops 파이프라인이 재수집하므로 DROP CASCADE (사용자 합의).
- chat_messages / routine_papers의 paper_id FK는 papers.id 그대로 유지.

Revision ID: 007
Revises: 006
Create Date: 2026-05-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1) chat_messages / routine_papers의 papers FK 제거 (CASCADE drop 전 해제) ──
    # papers를 DROP CASCADE 하면 FK도 같이 사라지지만, 명시적으로 잡아 둔다.
    # → 굳이 명시할 필요 없으므로 CASCADE에 위임.

    # ── 2) 기존 테이블 DROP (clean slate 정책) ──
    op.execute("DROP TABLE IF EXISTS paper_chunks CASCADE")
    op.execute("DROP TABLE IF EXISTS papers CASCADE")

    # ── 3) papers 신규 schema ──
    op.create_table(
        "papers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        # 식별자
        sa.Column("doi", sa.String(255), nullable=False),
        sa.Column("pmid", sa.String(20), nullable=True),
        sa.Column("pmcid", sa.String(20), nullable=True),
        sa.Column("openalex_id", sa.String(20), nullable=True),
        # 메타데이터
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("authors", sa.Text(), nullable=True),
        sa.Column("journal", sa.String(300), nullable=True),
        sa.Column("published_year", sa.Integer(), nullable=True),
        sa.Column("abstract", sa.Text(), nullable=True),
        # 근거 가중치
        sa.Column(
            "publication_types",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "evidence_weight",
            sa.Numeric(3, 2),
            nullable=False,
            server_default=sa.text("0.50"),
        ),
        # 본문 출처
        sa.Column("fulltext_source", sa.String(20), nullable=False),
        # 카테고리
        sa.Column(
            "search_categories",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.UniqueConstraint("doi", name="uq_papers_doi"),
    )
    # 인덱스: 단일 컬럼
    op.create_index("ix_papers_pmid", "papers", ["pmid"])
    op.create_index("ix_papers_openalex_id", "papers", ["openalex_id"])
    op.create_index("ix_papers_published_year", "papers", ["published_year"])
    # 인덱스: GIN (배열 컬럼)
    op.create_index(
        "ix_papers_publication_types",
        "papers",
        ["publication_types"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_papers_search_categories",
        "papers",
        ["search_categories"],
        postgresql_using="gin",
    )

    # ── 4) paper_chunks 신규 schema ──
    op.create_table(
        "paper_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "paper_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("papers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("section_name", sa.String(100), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        # 신규
        sa.Column("evidence_weight", sa.Numeric(3, 2), nullable=True),
        sa.Column("publication_types", postgresql.ARRAY(sa.String()), nullable=True),
    )
    op.create_index("ix_paper_chunks_paper_id", "paper_chunks", ["paper_id"])
    op.create_index(
        "uq_paper_chunks_paper_id_chunk_index",
        "paper_chunks",
        ["paper_id", "chunk_index"],
        unique=True,
    )


def downgrade() -> None:
    # 데이터 복구 불가 — 스키마만 000 마이그레이션 시점으로 복원한다.
    op.drop_index("uq_paper_chunks_paper_id_chunk_index", table_name="paper_chunks")
    op.drop_index("ix_paper_chunks_paper_id", table_name="paper_chunks")
    op.drop_table("paper_chunks")

    op.drop_index("ix_papers_search_categories", table_name="papers")
    op.drop_index("ix_papers_publication_types", table_name="papers")
    op.drop_index("ix_papers_published_year", table_name="papers")
    op.drop_index("ix_papers_openalex_id", table_name="papers")
    op.drop_index("ix_papers_pmid", table_name="papers")
    op.drop_table("papers")

    # 000 시점의 papers / paper_chunks 복원 (chat_messages.paper_id, routine_papers.paper_id FK 회복).
    op.create_table(
        "papers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("doi", sa.String(200), nullable=True),
        sa.Column("pmid", sa.String(20), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("authors", sa.Text(), nullable=True),
        sa.Column("journal", sa.String(300), nullable=True),
        sa.Column("published_year", sa.Integer(), nullable=True),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.UniqueConstraint("doi", name="uq_papers_doi"),
        sa.UniqueConstraint("pmid", name="uq_papers_pmid"),
    )
    op.create_table(
        "paper_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "paper_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("papers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("section_name", sa.String(100), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
    )
    op.create_index("ix_paper_chunks_paper_id", "paper_chunks", ["paper_id"])
