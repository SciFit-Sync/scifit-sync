"""
Equipment CSV → PostgreSQL import script.
Alembic 008 마이그레이션 적용 후 실행.

Run from server/ directory:
    python import_equipment_csv.py [--dry-run]

Idempotent: (brand_id, name) 조합이 이미 있으면 건너뜀.
"""

import argparse
import asyncio
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import select  # noqa: E402

from app.core.database import async_session_factory  # noqa: E402
from app.models.gym import Equipment, EquipmentBrand, WeightUnit  # noqa: E402

DATA_DIR = Path(__file__).parent.parent / "mlops" / "data"

BRAND_CONFIGS: dict[str, dict] = {
    "hammer_strength_equipments.csv": {
        "name": "Hammer Strength",
        "default_bar_unit": WeightUnit.LB,
        "default_stack_unit": WeightUnit.LB,
    },
    "newtech_equipments.csv": {
        "name": "Newtech",
        "default_bar_unit": WeightUnit.KG,
        "default_stack_unit": WeightUnit.KG,
    },
    "panatta_equipments.csv": {
        "name": "Panatta",
        "default_bar_unit": WeightUnit.KG,
        "default_stack_unit": WeightUnit.KG,
    },
}


def _parse_weight_str(s: str) -> tuple[float | None, str | None]:
    """'5kg', '10lb', '120', 'null', '?' → (value, unit). 인식 불가 시 (None, None)."""
    s = (s or "").strip()
    if not s or s.lower() in ("null", "?"):
        return None, None
    m = re.match(r"^(\d+(?:\.\d+)?)(kg|lb)?$", s, re.IGNORECASE)
    if m:
        return float(m.group(1)), m.group(2).lower() if m.group(2) else None
    return None, None


def _parse_pattern(s: str, default_unit: str) -> tuple[dict | None, str | None]:
    """'10lb*5, 15lb*10' → ({"pattern": [...]}, unit). 파싱 실패 시 (None, None)."""
    pattern: list[dict] = []
    unit: str | None = None
    current_from = 1

    for seg in s.split(","):
        m = re.match(r"^(\d+(?:\.\d+)?)(kg|lb)?\*(\d+)$", seg.strip(), re.IGNORECASE)
        if not m:
            return None, None
        val = float(m.group(1))
        seg_unit = m.group(2).lower() if m.group(2) else default_unit
        count = int(m.group(3))
        if count < 1:
            return None, None
        if unit is None:
            unit = seg_unit
        pattern.append({"from": current_from, "to": current_from + count - 1, "value": val})
        current_from += count

    return {"pattern": pattern}, unit


def _parse_stack_weight(s: str, default_unit: str) -> tuple[dict | None, str | None]:
    """stack_weight_kg 컬럼 값 → (JSONB dict | None, unit | None)."""
    s = (s or "").strip()
    if not s or s.lower() in ("null", "?"):
        return None, None
    if "*" in s:
        return _parse_pattern(s, default_unit)
    val, unit = _parse_weight_str(s)
    if val is not None:
        return {"value": val}, unit
    return None, None


def _parse_row(row: dict, brand_cfg: dict) -> dict | None:
    """CSV 행 → Equipment 필드 dict. 삽입 불가 행은 None 반환."""
    name = (row.get("name") or "").strip()
    if not name:
        return None

    eq_type = (row.get("equipment_type") or "").strip().lower()
    if not eq_type or eq_type == "null":
        return None  # NOT NULL 컬럼

    pr_str = (row.get("pulley_ratio") or "").strip()
    try:
        pulley_ratio = float(pr_str) if pr_str and pr_str.lower() != "null" else 1.0
    except ValueError:
        pulley_ratio = 1.0

    bar_val, bar_unit_from_val = _parse_weight_str(row.get("bar_weight_kg") or "")
    bar_weight_unit: str | None = None
    if bar_val is not None:
        bar_weight_unit = bar_unit_from_val or brand_cfg["default_bar_unit"].value

    min_val, min_unit = _parse_weight_str(row.get("min_stack_kg") or "")
    max_val, max_unit = _parse_weight_str(row.get("max_stack_kg") or "")
    sw_jsonb, sw_unit = _parse_stack_weight(row.get("stack_weight_kg") or "", brand_cfg["default_stack_unit"].value)

    explicit_units = [u for u in (min_unit, max_unit, sw_unit) if u]
    if explicit_units:
        stack_unit: str | None = explicit_units[0]
    elif any(v is not None for v in (min_val, max_val, sw_jsonb)):
        stack_unit = brand_cfg["default_stack_unit"].value
    else:
        stack_unit = None

    return {
        "name": name,
        "name_en": None,
        "sub_category": (row.get("sub_category") or "").strip() or None,
        "category": (row.get("category") or "").strip() or None,
        "equipment_type": eq_type,
        "pulley_ratio": pulley_ratio,
        "bar_weight": bar_val,
        "bar_weight_unit": bar_weight_unit,
        "has_weight_assist": False,
        "min_stack": min_val,
        "max_stack": max_val,
        "stack_weight": sw_jsonb,
        "stack_unit": stack_unit,
        "image_url": (row.get("image_url") or "").strip() or None,
    }


async def _import_file(session, filename: str, brand_cfg: dict, dry_run: bool) -> tuple[int, int]:
    path = DATA_DIR / filename
    if not path.exists():
        print(f"  [SKIP] 파일 없음: {path}")
        return 0, 0

    brand_name = brand_cfg["name"]
    inserted = skipped = 0

    if not dry_run:
        result = await session.execute(select(EquipmentBrand).where(EquipmentBrand.name == brand_name))
        brand = result.scalar_one_or_none()
        if brand is None:
            brand = EquipmentBrand(
                name=brand_name,
                default_bar_unit=brand_cfg["default_bar_unit"],
                default_stack_unit=brand_cfg["default_stack_unit"],
            )
            session.add(brand)
            await session.flush()
            print(f"  [CREATE] brand: {brand_name}")
        else:
            print(f"  [EXIST]  brand: {brand_name}")
        brand_id = brand.id
    else:
        brand_id = None
        print(f"  [DRY]    brand: {brand_name}")

    with path.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            parsed = _parse_row(row, brand_cfg)
            if parsed is None:
                name_hint = (row.get("name") or "").strip() or "(빈 행)"
                print(f"  [SKIP]   {name_hint!r} — equipment_type 없음")
                skipped += 1
                continue

            if not dry_run:
                dup = await session.execute(
                    select(Equipment).where(
                        Equipment.brand_id == brand_id,
                        Equipment.name == parsed["name"],
                    )
                )
                if dup.scalar_one_or_none():
                    skipped += 1
                    continue
                session.add(Equipment(brand_id=brand_id, **parsed))

            inserted += 1
            sw = parsed["stack_weight"]
            sw_display = "pattern" if sw and "pattern" in sw else (str(sw) if sw else "null")
            print(
                f"  {'[DRY]  ' if dry_run else '[INSERT]'} {parsed['name']!r}"
                f"  stack_unit={parsed['stack_unit']}  stack_weight={sw_display}"
            )

    return inserted, skipped


async def main(dry_run: bool) -> None:
    prefix = "[DRY RUN] " if dry_run else ""
    print(f"{prefix}기구 CSV import 시작\n")

    async with async_session_factory() as session, session.begin():
        for filename, brand_cfg in BRAND_CONFIGS.items():
            print(f"── {filename}")
            ins, skp = await _import_file(session, filename, brand_cfg, dry_run)
            print(f"  → {ins}개 {'(예정)' if dry_run else '삽입'}, {skp}개 건너뜀\n")

    print("완료.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Equipment CSV → PostgreSQL")
    ap.add_argument("--dry-run", action="store_true", help="파싱만 확인, DB 변경 없음")
    args = ap.parse_args()
    asyncio.run(main(args.dry_run))
