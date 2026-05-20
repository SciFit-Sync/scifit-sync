"""fix enum type values to lowercase

Revision ID: 004
Revises: 003
Create Date: 2026-05-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # muscleinvolvement — drop table, drop type, recreate both with confirmed lowercase values
    op.drop_table("exercise_muscles")
    op.execute("DROP TYPE IF EXISTS muscleinvolvement")
    op.execute("CREATE TYPE muscleinvolvement AS ENUM ('primary', 'secondary', 'stabilizer')")
    op.create_table(
        "exercise_muscles",
        sa.Column(
            "exercise_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exercises.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "muscle_group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("muscle_groups.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "involvement",
            postgresql.ENUM("primary", "secondary", "stabilizer", name="muscleinvolvement", create_type=False),
            nullable=False,
        ),
        sa.Column("activation_pct", sa.Integer(), nullable=True),
    )

    # chatrole — same precaution
    op.drop_table("chat_messages")
    op.execute("DROP TYPE IF EXISTS chatrole")
    op.execute("CREATE TYPE chatrole AS ENUM ('user', 'assistant')")
    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            postgresql.ENUM("user", "assistant", name="chatrole", create_type=False),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("paper_ids", postgresql.JSONB(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("exercise_muscles")
    op.execute("DROP TYPE IF EXISTS chatrole")
    op.execute("DROP TYPE IF EXISTS muscleinvolvement")
