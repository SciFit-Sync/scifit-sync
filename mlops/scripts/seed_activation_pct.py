"""exercise_muscles.activation_pct 일괄 시딩 스크립트.

Gemini에게 운동별 근육 EMG 활성도를 묻고, exercise_muscles.activation_pct를 채운다.
한 번만 실행하면 되는 일회성 스크립트.

사전 준비:
    server/.env에 아래 두 값이 있어야 한다.
        GEMINI_API_KEY=...
        DATABASE_URL=postgresql+asyncpg://user:password@host:port/db

실행:
    scifit-sync/ 루트에서
    python mlops/scripts/seed_activation_pct.py
"""

import asyncio
import json
import logging
import os
import platform
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "server"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_ROOT / "mlops" / ".env")
load_dotenv(_ROOT / "server" / ".env", override=True)

from google import genai  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Gemini가 반환하는 slug 이름과 DB muscle_groups.name이 다를 때 alias로 통일
_SLUG_ALIASES: dict[str, str] = {
    "anterior deltoid": "Front Deltoid",
    "front deltoid": "Front Deltoid",
    "lateral deltoid": "Side Deltoid",
    "side deltoid": "Side Deltoid",
    "posterior deltoid": "Rear Deltoid",
    "rear deltoid": "Rear Deltoid",
    "upper back": "Upper Back",
    "rhomboids": "Upper Back",
    "traps": "Upper Back",
    "trapezius": "Upper Back",
}

_PROMPT = """\
You are a sports science expert. Provide estimated EMG muscle activation percentages \
for the exercise "{exercise}" based on published research.

Muscles:
{muscles}

Return ONLY a JSON array, no markdown, no explanation.
Use muscle_slug values EXACTLY as given in the Muscles list above — do not normalize, \
translate, or change them.
[{{"muscle_slug": "<slug>", "activation_pct": <integer 0-100>}}, ...]

Guidelines by involvement:
- primary: 65-100%
- secondary: 30-60%
- stabilizer: 10-29%
"""


def _build_connect_args() -> dict:
    """asyncpg connect_args 생성. Windows 개발 환경 SSL 우회 포함.

    프로덕션(ECS Fargate + Supabase)에서는 정상 SSL 연결을 유지한다.
    """
    args: dict = {"statement_cache_size": 0}
    env = os.getenv("ENV", "development")
    if env == "development" and platform.system() == "Windows":
        args["ssl"] = False  # Windows 한글 경로 asyncpg 버그 우회
    return args


async def main() -> None:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY가 .env에 없습니다.")
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL이 .env에 없습니다.\n"
            "예) DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/scifiitsync"
        )

    client = genai.Client(api_key=GEMINI_API_KEY)
    engine = create_async_engine(DATABASE_URL, echo=False, connect_args=_build_connect_args())
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session, session.begin():
        rows = (
            (
                await session.execute(
                    text("""
                    SELECT
                        e.name_en,
                        mg.name        AS muscle_slug,
                        em.involvement,
                        em.exercise_id,
                        em.muscle_group_id
                    FROM exercise_muscles em
                    JOIN exercises     e  ON e.id  = em.exercise_id
                    JOIN muscle_groups mg ON mg.id = em.muscle_group_id
                    WHERE em.activation_pct IS NULL
                    ORDER BY e.name_en
                """)
                )
            )
            .mappings()
            .all()
        )

        if not rows:
            logger.info("모든 activation_pct가 이미 채워져 있습니다.")
            return

        exercises: dict[str, list] = defaultdict(list)
        for r in rows:
            exercises[r["name_en"]].append(dict(r))

        logger.info("처리할 운동: %d개 (%d개 근육 매핑)", len(exercises), len(rows))

        total_updated = 0

        for exercise_name, muscle_rows in exercises.items():
            muscle_lines = "\n".join(f"- {r['muscle_slug']} ({r['involvement']})" for r in muscle_rows)
            prompt = _PROMPT.format(exercise=exercise_name, muscles=muscle_lines)

            try:
                response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
                raw = response.text.strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                data: list[dict] = json.loads(raw.strip())
            except Exception as e:
                logger.warning("✗ %s — LLM 실패: %s", exercise_name, e)
                continue

            updated = 0
            for item in data:
                slug = item.get("muscle_slug")
                pct = item.get("activation_pct")
                if slug is None or pct is None:
                    continue
                try:
                    pct_int = int(pct)
                except (ValueError, TypeError):
                    logger.warning("✗ %s / %s — 정수 변환 실패: %r", exercise_name, slug, pct)
                    continue
                if not 0 <= pct_int <= 100:
                    logger.warning("✗ %s / %s — 범위 초과: %d", exercise_name, slug, pct_int)
                    continue
                # alias 변환 후 case-insensitive 매칭
                normalized = _SLUG_ALIASES.get(slug.lower(), slug)
                matched = False
                for r in muscle_rows:
                    if r["muscle_slug"].lower() == normalized.lower():
                        await session.execute(
                            text(
                                "UPDATE exercise_muscles "
                                "SET activation_pct = :pct "
                                "WHERE exercise_id = :eid AND muscle_group_id = :mgid"
                            ),
                            {"pct": pct_int, "eid": r["exercise_id"], "mgid": r["muscle_group_id"]},
                        )
                        updated += 1
                        matched = True
                        break
                if not matched:
                    logger.warning("✗ %s / %s — alias 미매칭 (DB에 없는 근육명)", exercise_name, normalized)

            total_updated += updated
            logger.info("✓ %-35s %d/%d 근육 업데이트", exercise_name, updated, len(muscle_rows))

    logger.info("완료 — 총 %d개 행 업데이트", total_updated)


if __name__ == "__main__":
    asyncio.run(main())
