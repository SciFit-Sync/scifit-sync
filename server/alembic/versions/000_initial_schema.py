"""initial schema — 28 tables

Revision ID: 000
Revises:
Create Date: 2026-04-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "000"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL ENUM types — created before first use
    op.execute("CREATE TYPE fitnessgoal AS ENUM ('hypertrophy', 'strength', 'endurance', 'rehabilitation')")
    op.execute("CREATE TYPE careerlevel AS ENUM ('beginner', 'intermediate', 'advanced')")
    op.execute("CREATE TYPE equipmentcategory AS ENUM ('cable', 'machine', 'barbell', 'dumbbell', 'bodyweight')")
    op.execute("CREATE TYPE muscleinvolvement AS ENUM ('primary', 'secondary', 'stabilizer')")
    op.execute("CREATE TYPE chatrole AS ENUM ('user', 'assistant')")

    # ── users ──────────────────────────────────────────────────────────────────
    # NOTE: name/phone added by 001, kakao_id added by 002, password_hash made nullable by 002
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("failed_login_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_username", "users", ["username"])

    # ── equipment_brands ───────────────────────────────────────────────────────
    op.create_table(
        "equipment_brands",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.UniqueConstraint("name", name="uq_equipment_brands_name"),
    )

    # ── muscle_groups ─────────────────────────────────────────────────────────
    op.create_table(
        "muscle_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_en", sa.String(100), nullable=True),
        sa.Column("body_region", sa.String(50), nullable=True),
    )

    # ── exercises ─────────────────────────────────────────────────────────────
    op.create_table(
        "exercises",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_en", sa.String(200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(50), nullable=True),
    )

    # ── gyms ──────────────────────────────────────────────────────────────────
    op.create_table(
        "gyms",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("kakao_place_id", sa.String(50), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.UniqueConstraint("kakao_place_id", name="uq_gyms_kakao_place_id"),
    )

    # ── papers ────────────────────────────────────────────────────────────────
    op.create_table(
        "papers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
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

    # ── user_profiles ─────────────────────────────────────────────────────────
    op.create_table(
        "user_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("gender", sa.String(10), nullable=True),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column(
            "fitness_goal",
            postgresql.ENUM(
                "hypertrophy", "strength", "endurance", "rehabilitation", name="fitnessgoal", create_type=False
            ),
            nullable=True,
        ),
        sa.Column(
            "career_level",
            postgresql.ENUM("beginner", "intermediate", "advanced", name="careerlevel", create_type=False),
            nullable=True,
        ),
        sa.Column("workout_days_per_week", sa.Integer(), nullable=True),
        sa.UniqueConstraint("user_id", name="uq_user_profiles_user_id"),
    )

    # ── user_body_measurements ────────────────────────────────────────────────
    op.create_table(
        "user_body_measurements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("height_cm", sa.Float(), nullable=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("body_fat_pct", sa.Float(), nullable=True),
        sa.Column("skeletal_muscle_kg", sa.Float(), nullable=True),
        sa.Column("measured_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_user_body_measurements_user_id", "user_body_measurements", ["user_id"])

    # ── refresh_tokens ────────────────────────────────────────────────────────
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
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
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])

    # ── equipments ────────────────────────────────────────────────────────────
    op.create_table(
        "equipments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_en", sa.String(200), nullable=True),
        sa.Column(
            "category",
            postgresql.ENUM(
                "cable", "machine", "barbell", "dumbbell", "bodyweight", name="equipmentcategory", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("brand_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("equipment_brands.id"), nullable=True),
        sa.Column("pulley_ratio", sa.Float(), server_default=sa.text("1.0"), nullable=False),
        sa.Column("bar_weight_kg", sa.Float(), nullable=True),
        sa.Column("has_weight_assist", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("max_stack_kg", sa.Float(), nullable=True),
        sa.Column("weight_increment_kg", sa.Float(), nullable=True),
    )

    # ── gym_equipments ────────────────────────────────────────────────────────
    op.create_table(
        "gym_equipments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
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
        sa.Column("quantity", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.UniqueConstraint("gym_id", "equipment_id", name="uq_gym_equipment"),
    )
    op.create_index("ix_gym_equipments_gym_id", "gym_equipments", ["gym_id"])

    # ── exercise_equipment_map ────────────────────────────────────────────────
    op.create_table(
        "exercise_equipment_map",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "exercise_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exercises.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "equipment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("equipments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("exercise_id", "equipment_id", name="uq_exercise_equipment_map"),
    )
    op.create_index("ix_exercise_equipment_map_exercise_id", "exercise_equipment_map", ["exercise_id"])

    # ── exercise_muscles ──────────────────────────────────────────────────────
    op.create_table(
        "exercise_muscles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "exercise_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exercises.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "muscle_group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("muscle_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "involvement",
            postgresql.ENUM("primary", "secondary", "stabilizer", name="muscleinvolvement", create_type=False),
            nullable=False,
        ),
        sa.UniqueConstraint("exercise_id", "muscle_group_id", name="uq_exercise_muscle"),
    )
    op.create_index("ix_exercise_muscles_exercise_id", "exercise_muscles", ["exercise_id"])

    # ── chat_sessions ─────────────────────────────────────────────────────────
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
        sa.Column("title", sa.String(300), nullable=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])

    # ── paper_chunks ──────────────────────────────────────────────────────────
    op.create_table(
        "paper_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
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

    # ── notifications ─────────────────────────────────────────────────────────
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("is_read", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("data_json", postgresql.JSON(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])

    # ── user_stats ────────────────────────────────────────────────────────────
    op.create_table(
        "user_stats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("total_workouts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_volume_kg", sa.Float(), server_default=sa.text("0.0"), nullable=False),
        sa.Column("current_streak", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("longest_streak", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_workout_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", name="uq_user_stats_user_id"),
    )

    # ── user_gyms ─────────────────────────────────────────────────────────────
    op.create_table(
        "user_gyms",
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
            sa.ForeignKey("gyms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.UniqueConstraint("user_id", "gym_id", name="uq_user_gym"),
    )
    op.create_index("ix_user_gyms_user_id", "user_gyms", ["user_id"])

    # ── equipment_reports ─────────────────────────────────────────────────────
    op.create_table(
        "equipment_reports",
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
            "gym_equipment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("gym_equipments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("report_type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_equipment_reports_user_id", "equipment_reports", ["user_id"])

    # ── workout_routines ──────────────────────────────────────────────────────
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
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("fitness_goal", sa.String(50), nullable=True),
        sa.Column("generated_by", sa.String(100), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_workout_routines_user_id", "workout_routines", ["user_id"])
    op.create_index("ix_workout_routines_deleted_at", "workout_routines", ["deleted_at"])

    # ── user_exercise_1rm ─────────────────────────────────────────────────────
    op.create_table(
        "user_exercise_1rm",
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
            "exercise_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exercises.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("estimated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("user_id", "exercise_id", name="uq_user_exercise_1rm"),
    )
    op.create_index("ix_user_exercise_1rm_user_id", "user_exercise_1rm", ["user_id"])

    # ── user_equipment_selections ─────────────────────────────────────────────
    op.create_table(
        "user_equipment_selections",
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
            "gym_equipment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("gym_equipments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "gym_equipment_id", name="uq_user_gym_equipment_selection"),
    )
    op.create_index("ix_user_equipment_selections_user_id", "user_equipment_selections", ["user_id"])

    # ── routine_days ──────────────────────────────────────────────────────────
    op.create_table(
        "routine_days",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "routine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workout_routines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
    )
    op.create_index("ix_routine_days_routine_id", "routine_days", ["routine_id"])

    # ── workout_logs ──────────────────────────────────────────────────────────
    op.create_table(
        "workout_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("routine_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workout_routines.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_workout_logs_user_id", "workout_logs", ["user_id"])

    # ── chat_messages ─────────────────────────────────────────────────────────
    op.create_table(
        "chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
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
        sa.Column("message_type", sa.String(50), server_default=sa.text("'text'"), nullable=False),
        sa.Column("routine_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workout_routines.id"), nullable=True),
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("papers.id"), nullable=True),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])

    # ── routine_exercises ─────────────────────────────────────────────────────
    op.create_table(
        "routine_exercises",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "routine_day_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("routine_days.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "exercise_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exercises.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("equipment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("equipments.id"), nullable=True),
        sa.Column("order_index", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("sets", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("reps", sa.Integer(), server_default=sa.text("10"), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("rest_seconds", sa.Integer(), server_default=sa.text("60"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_routine_exercises_routine_day_id", "routine_exercises", ["routine_day_id"])

    # ── routine_papers ────────────────────────────────────────────────────────
    op.create_table(
        "routine_papers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "routine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workout_routines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "routine_exercise_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("routine_exercises.id", ondelete="CASCADE"),
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

    # ── workout_log_sets ──────────────────────────────────────────────────────
    op.create_table(
        "workout_log_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "workout_log_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workout_logs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "exercise_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exercises.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("equipment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("equipments.id"), nullable=True),
        sa.Column("set_number", sa.Integer(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("is_completed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("rpe", sa.Float(), nullable=True),
    )
    op.create_index("ix_workout_log_sets_workout_log_id", "workout_log_sets", ["workout_log_id"])


def downgrade() -> None:
    # Drop leaf tables first, then work up the dependency tree
    op.drop_table("workout_log_sets")
    op.drop_table("routine_papers")
    op.drop_table("routine_exercises")
    op.drop_table("chat_messages")
    op.drop_table("workout_logs")
    op.drop_table("routine_days")
    op.drop_table("user_equipment_selections")
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

    # Drop enum types after all tables using them are gone
    op.execute("DROP TYPE IF EXISTS chatrole")
    op.execute("DROP TYPE IF EXISTS muscleinvolvement")
    op.execute("DROP TYPE IF EXISTS equipmentcategory")
    op.execute("DROP TYPE IF EXISTS careerlevel")
    op.execute("DROP TYPE IF EXISTS fitnessgoal")
