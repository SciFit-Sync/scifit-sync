"""redesign schema — full ER diagram update

Revision ID: 003
Revises: 002
Create Date: 2026-05-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


# Helper: pre-created enum type reference (no auto-create on table create)
def _e(name, *values):
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    # ── 1. Drop all existing tables (leaf → root) ─────────────────────────────
    op.drop_table("workout_log_sets")
    op.drop_table("routine_papers")
    op.drop_table("routine_exercises")
    op.drop_table("chat_messages")
    op.drop_table("workout_logs")
    op.drop_table("routine_days")
    op.drop_table("user_exercise_1rm")
    op.drop_table("workout_routines")
    op.drop_table("equipment_reports")
    op.drop_table("user_gyms")
    op.drop_table("user_stats")
    op.drop_table("notifications")
    op.drop_table("paper_chunks")
    op.drop_table("chat_sessions")
    op.drop_table("exercise_muscles")
    op.drop_table("exercise_equipment_map")
    op.drop_table("user_equipment_selections")
    op.drop_table("gym_equipments")
    op.drop_table("equipments")
    op.drop_table("refresh_tokens")
    op.drop_table("user_body_measurements")
    op.drop_table("user_profiles")
    op.drop_table("papers")
    op.drop_table("gyms")
    op.drop_table("exercises")
    op.drop_table("muscle_groups")
    op.drop_table("equipment_brands")
    op.drop_table("users")

    # ── 2. Drop old / changed enum types (IF EXISTS 로 부분 실패 재실행 안전) ──
    op.execute("DROP TYPE IF EXISTS fitnessgoal")
    op.execute("DROP TYPE IF EXISTS careerlevel")
    op.execute("DROP TYPE IF EXISTS equipmentcategory")
    # 이전 실패 실행에서 생성된 타입 잔재 정리
    op.execute("DROP TYPE IF EXISTS gender")
    op.execute("DROP TYPE IF EXISTS provider")
    op.execute("DROP TYPE IF EXISTS onermsource")
    op.execute("DROP TYPE IF EXISTS equipmentbodycategory")
    op.execute("DROP TYPE IF EXISTS equipmenttype")
    op.execute("DROP TYPE IF EXISTS equipmentreportstatus")
    op.execute("DROP TYPE IF EXISTS generatedby")
    op.execute("DROP TYPE IF EXISTS routinestatus")
    op.execute("DROP TYPE IF EXISTS splittype")
    op.execute("DROP TYPE IF EXISTS workoutstatus")
    op.execute("DROP TYPE IF EXISTS notificationtype")

    # ── 3. Create new enum types ──────────────────────────────────────────────
    op.execute("CREATE TYPE gender AS ENUM ('male', 'female')")
    op.execute("CREATE TYPE provider AS ENUM ('local', 'kakao')")
    op.execute("CREATE TYPE careerlevel AS ENUM ('beginner', 'novice', 'intermediate', 'advanced')")
    op.execute("CREATE TYPE onermsource AS ENUM ('manual', 'epley')")
    op.execute("CREATE TYPE equipmentbodycategory AS ENUM ('chest', 'back', 'shoulders', 'arms', 'core', 'legs')")
    op.execute("CREATE TYPE equipmenttype AS ENUM ('cable', 'machine', 'barbell', 'dumbbell', 'bodyweight')")
    op.execute("CREATE TYPE equipmentreportstatus AS ENUM ('pending', 'reviewed', 'resolved')")
    op.execute("CREATE TYPE generatedby AS ENUM ('user', 'ai')")
    op.execute("CREATE TYPE routinestatus AS ENUM ('active', 'archived')")
    op.execute("CREATE TYPE splittype AS ENUM ('2split', '3split', '4split', '5split')")
    op.execute("CREATE TYPE workoutstatus AS ENUM ('in_progress', 'completed')")
    op.execute(
        "CREATE TYPE notificationtype AS ENUM ('workout_reminder', 'motivation', 'po_suggestion', 'skip_warning', 'system')"
    )

    # ── 4. Recreate all tables ────────────────────────────────────────────────

    # users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("provider", _e("provider", "local", "kakao"), server_default=sa.text("'local'"), nullable=False),
        sa.Column("provider_id", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_username", "users", ["username"])

    # equipment_brands
    op.create_table(
        "equipment_brands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("logo_url", sa.String(500), nullable=True),
        sa.UniqueConstraint("name", name="uq_equipment_brands_name"),
    )

    # muscle_groups
    op.create_table(
        "muscle_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_ko", sa.String(100), nullable=False),
        sa.Column("body_region", sa.String(50), nullable=False),
        sa.UniqueConstraint("name", name="uq_muscle_groups_name"),
        sa.UniqueConstraint("name_ko", name="uq_muscle_groups_name_ko"),
    )

    # exercises
    op.create_table(
        "exercises",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_en", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(50), nullable=False),
        sa.UniqueConstraint("name_en", name="uq_exercises_name_en"),
    )

    # gyms
    op.create_table(
        "gyms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("kakao_place_id", sa.String(50), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.String(500), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.UniqueConstraint("kakao_place_id", name="uq_gyms_kakao_place_id"),
    )

    # papers
    op.create_table(
        "papers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("doi", sa.String(200), nullable=True),
        sa.Column("pmid", sa.String(20), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("authors", sa.Text(), nullable=False),
        sa.Column("journal", sa.String(300), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.UniqueConstraint("doi", name="uq_papers_doi"),
        sa.UniqueConstraint("pmid", name="uq_papers_pmid"),
    )

    # user_profiles — user_id is PK
    op.create_table(
        "user_profiles",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("gender", _e("gender", "male", "female"), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=False),
        sa.Column("height_cm", sa.Float(), nullable=False),
        sa.Column("default_goals", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("career_level", _e("careerlevel", "beginner", "novice", "intermediate", "advanced"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )

    # user_body_measurements
    op.create_table(
        "user_body_measurements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("skeletal_muscle_kg", sa.Float(), nullable=True),
        sa.Column("body_fat_pct", sa.Float(), nullable=True),
        sa.Column("measured_at", sa.Date(), nullable=False),
    )
    op.create_index("ix_user_body_measurements_user_id", "user_body_measurements", ["user_id"])

    # refresh_tokens
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column(
            "replaced_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("refresh_tokens.id"),
            nullable=True,
        ),
        sa.Column("device_info", sa.String(255), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])

    # equipments
    op.create_table(
        "equipments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "brand_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("equipment_brands.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_en", sa.String(200), nullable=True),
        sa.Column(
            "category", _e("equipmentbodycategory", "chest", "back", "shoulders", "arms", "core", "legs"), nullable=True
        ),
        sa.Column(
            "equipment_type",
            _e("equipmenttype", "cable", "machine", "barbell", "dumbbell", "bodyweight"),
            nullable=False,
        ),
        sa.Column("pulley_ratio", sa.Float(), server_default=sa.text("1.0"), nullable=False),
        sa.Column("bar_weight_kg", sa.Float(), nullable=True),
        sa.Column("has_weight_assist", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("min_stack_kg", sa.Float(), nullable=True),
        sa.Column("max_stack_kg", sa.Float(), nullable=True),
        sa.Column("stack_weight_kg", sa.Float(), nullable=True),
        sa.Column("image_url", sa.String(500), nullable=True),
    )

    # user_gyms — composite PK
    op.create_table(
        "user_gyms",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "gym_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("gyms.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )

    # gym_equipments — composite PK
    op.create_table(
        "gym_equipments",
        sa.Column(
            "gym_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("gyms.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "equipment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("equipments.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("quantity", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )

    # exercise_equipment_map — composite PK
    op.create_table(
        "exercise_equipment_map",
        sa.Column(
            "exercise_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exercises.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "equipment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("equipments.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    # exercise_muscles — composite PK
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
        sa.Column("involvement", _e("muscleinvolvement", "primary", "secondary", "stabilizer"), nullable=False),
        sa.Column("activation_pct", sa.Integer(), nullable=True),
    )

    # equipment_muscles — composite PK (new)
    op.create_table(
        "equipment_muscles",
        sa.Column(
            "equipment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("equipments.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "muscle_group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("muscle_groups.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("involvement", sa.String(20), nullable=False),
    )

    # chat_sessions
    op.create_table(
        "chat_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(300), nullable=False),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])

    # paper_chunks
    op.create_table(
        "paper_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
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
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("chroma_id", sa.String(100), nullable=False),
    )
    op.create_index("ix_paper_chunks_paper_id", "paper_chunks", ["paper_id"])

    # notifications
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "type",
            _e("notificationtype", "workout_reminder", "motivation", "po_suggestion", "skip_warning", "system"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("data_json", postgresql.JSON(), nullable=True),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])

    # equipment_reports
    op.create_table(
        "equipment_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "gym_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("gyms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "equipment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("equipments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("report_type", sa.String(50), nullable=False),
        sa.Column(
            "status",
            _e("equipmentreportstatus", "pending", "reviewed", "resolved"),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_index("ix_equipment_reports_user_id", "equipment_reports", ["user_id"])

    # workout_routines
    op.create_table(
        "workout_routines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "gym_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("gyms.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("fitness_goals", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("target_muscle_group_ids", postgresql.JSONB(), nullable=True),
        sa.Column("session_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("split_type", _e("splittype", "2split", "3split", "4split", "5split"), nullable=True),
        sa.Column("generated_by", _e("generatedby", "user", "ai"), server_default=sa.text("'user'"), nullable=False),
        sa.Column(
            "status", _e("routinestatus", "active", "archived"), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column("ai_reasoning", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_workout_routines_user_id", "workout_routines", ["user_id"])
    op.create_index("ix_workout_routines_deleted_at", "workout_routines", ["deleted_at"])

    # user_exercise_1rm
    op.create_table(
        "user_exercise_1rm",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "exercise_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exercises.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("source", _e("onermsource", "manual", "epley"), server_default=sa.text("'manual'"), nullable=False),
        sa.Column("estimated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_user_exercise_1rm_user_id", "user_exercise_1rm", ["user_id"])

    # routine_days
    op.create_table(
        "routine_days",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "routine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workout_routines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day_number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
    )
    op.create_index("ix_routine_days_routine_id", "routine_days", ["routine_id"])

    # workout_logs
    op.create_table(
        "workout_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "routine_day_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("routine_days.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "gym_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("gyms.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("started_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column(
            "status",
            _e("workoutstatus", "in_progress", "completed"),
            server_default=sa.text("'in_progress'"),
            nullable=False,
        ),
    )
    op.create_index("ix_workout_logs_user_id", "workout_logs", ["user_id"])

    # chat_messages
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
        sa.Column("role", _e("chatrole", "user", "assistant"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("paper_ids", postgresql.JSONB(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])

    # routine_exercises
    op.create_table(
        "routine_exercises",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "routine_day_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("routine_days.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "exercise_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exercises.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "equipment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("equipments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("order_index", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("sets", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("reps_min", sa.Integer(), nullable=True),
        sa.Column("reps_max", sa.Integer(), nullable=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("rest_seconds", sa.Integer(), server_default=sa.text("60"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("ix_routine_exercises_routine_day_id", "routine_exercises", ["routine_day_id"])

    # routine_papers
    op.create_table(
        "routine_papers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "routine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workout_routines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "routine_exercise_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("routine_exercises.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "paper_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("papers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relevance_summary", sa.Text(), nullable=True),
    )
    op.create_index("ix_routine_papers_routine_id", "routine_papers", ["routine_id"])

    # workout_log_sets
    op.create_table(
        "workout_log_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "workout_log_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workout_logs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "exercise_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exercises.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "routine_exercise_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("routine_exercises.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("set_number", sa.Integer(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("rpe", sa.Float(), nullable=True),
        sa.Column("is_completed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("performed_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_workout_log_sets_workout_log_id", "workout_log_sets", ["workout_log_id"])

    # programs (new)
    op.create_table(
        "programs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_index("ix_programs_user_id", "programs", ["user_id"])

    # program_routines (new) — composite PK
    op.create_table(
        "program_routines",
        sa.Column(
            "program_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("programs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "routine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workout_routines.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("order_index", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("program_routines")
    op.drop_table("programs")
    op.drop_table("workout_log_sets")
    op.drop_table("routine_papers")
    op.drop_table("routine_exercises")
    op.drop_table("chat_messages")
    op.drop_table("workout_logs")
    op.drop_table("routine_days")
    op.drop_table("user_exercise_1rm")
    op.drop_table("workout_routines")
    op.drop_table("equipment_reports")
    op.drop_table("equipment_muscles")
    op.drop_table("user_gyms")
    op.drop_table("notifications")
    op.drop_table("paper_chunks")
    op.drop_table("chat_sessions")
    op.drop_table("exercise_muscles")
    op.drop_table("exercise_equipment_map")
    op.drop_table("gym_equipments")
    op.drop_table("equipments")
    op.drop_table("refresh_tokens")
    op.drop_table("user_body_measurements")
    op.drop_table("user_profiles")
    op.drop_table("papers")
    op.drop_table("gyms")
    op.drop_table("exercises")
    op.drop_table("muscle_groups")
    op.drop_table("equipment_brands")
    op.drop_table("users")

    op.execute("DROP TYPE IF EXISTS notificationtype")
    op.execute("DROP TYPE IF EXISTS workoutstatus")
    op.execute("DROP TYPE IF EXISTS splittype")
    op.execute("DROP TYPE IF EXISTS routinestatus")
