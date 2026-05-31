"""exercise_muscles.activation_pct 일괄 시딩 스크립트.

Gemini에게 운동별 근육 EMG 활성도를 묻고, exercise_muscles.activation_pct를 채운다.
한 번만 실행하면 되는 일회성 스크립트.

사전 준비:
    mlops/.env에 아래 두 값이 있어야 한다.
        GEMINI_API_KEY=...
        DATABASE_URL=postgresql://user:password@host:port/db

실행:
    scifit-sync/ 루트에서
    python mlops/scripts/seed_activation_pct.py
"""

import asyncio
import json
import logging
import os
from collections import defaultdict
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
from google import genai

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / "mlops" / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
DATABASE_URL = os.getenv("DATABASE_URL", "")

_PROMPT = """\
You are a sports science expert. Provide estimated EMG muscle activation percentages \
for the exercise "{exercise}" based on published research.

Muscles:
{muscles}

Return ONLY a JSON array, no markdown, no explanation:
[{{"muscle_slug": "<slug>", "activation_pct": <integer 0-100>}}, ...]

Guidelines by involvement:
- primary: 65-100%
- secondary: 30-60%
- stabilizer: 10-29%
"""


async def main() -> None:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY가 mlops/.env에 없습니다.")
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL이 mlops/.env에 없습니다.\n"
            "예) DATABASE_URL=postgresql://postgres:postgres@localhost:5432/scifiitsync"
        )

    client = genai.Client(api_key=GEMINI_API_KEY)
    dsn = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn=dsn, ssl=False, statement_cache_size=0)

    try:
        rows = await conn.fetch("""
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

        if not rows:
            logger.info("모든 activation_pct가 이미 채워져 있습니다.")
            return

        exercises: dict[str, list] = defaultdict(list)
        for r in rows:
            exercises[r["name_en"]].append(dict(r))

        logger.info("처리할 운동: %d개 (%d개 근육 매핑)", len(exercises), len(rows))

        total_updated = 0

        for exercise_name, muscle_rows in exercises.items():
            muscle_lines = "\n".join(
                f"- {r['muscle_slug']} ({r['involvement']})" for r in muscle_rows
            )
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
                for r in muscle_rows:
                    if r["muscle_slug"] == slug:
                        await conn.execute(
                            "UPDATE exercise_muscles "
                            "SET activation_pct = $1 "
                            "WHERE exercise_id = $2 AND muscle_group_id = $3",
                            int(pct),
                            r["exercise_id"],
                            r["muscle_group_id"],
                        )
                        updated += 1
                        break

            total_updated += updated
            logger.info("✓ %-35s %d/%d 근육 업데이트", exercise_name, updated, len(muscle_rows))

        logger.info("완료 — 총 %d개 행 업데이트", total_updated)

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
