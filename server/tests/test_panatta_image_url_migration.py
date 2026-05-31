"""20260529_fix_panatta_image_url 마이그레이션과 equipments_seed.csv 의 일관성 검증.

DB·외부 API 없이 순수 데이터 검증만 수행한다(CI-safe). 목적:
- 마이그레이션의 IMAGE_URL_FIXES(31건)가 형식적으로 유효한지.
- seed CSV가 마이그레이션의 대체 URL과 동기화돼 있는지(둘 사이 drift 방지).
  신규 환경: seed 가 새 URL을 INSERT → 마이그레이션 UPDATE 도 동일 값 → 수렴.
  기존 환경: seed 는 ON CONFLICT skip → 마이그레이션이 새 URL로 UPDATE → 수렴.
"""

import csv
import importlib.util
import uuid
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_MIGRATION = _REPO / "server" / "alembic" / "versions" / "20260529_fix_panatta_image_url.py"
_SEED = _REPO / "mlops" / "data" / "equipments_seed.csv"
_PANATTA = _REPO / "mlops" / "data" / "panatta_equipments.csv"  # 원본 per-brand import 소스 (cp949)
_DEAD_DOMAIN = "panattasport.com"  # 404로 깨진 도메인


def _load_fixes() -> list[dict[str, str]]:
    spec = importlib.util.spec_from_file_location("_fix_panatta_image_url", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.IMAGE_URL_FIXES


def _seed_image_by_id() -> dict[str, str]:
    with _SEED.open(encoding="utf-8") as f:
        return {r["id"]: (r["image_url"] or "").strip() for r in csv.DictReader(f)}


def test_revision_id_within_varchar32():
    """alembic_version.version_num 은 VARCHAR(32) — revision id 길이 제약."""
    spec = importlib.util.spec_from_file_location("_fix_panatta_image_url_rev", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert len(module.revision) <= 32
    assert module.down_revision == "009"  # develop 현재 head 위에 적층


def test_fixes_are_wellformed():
    fixes = _load_fixes()
    assert len(fixes) == 31

    ids = [f["id"] for f in fixes]
    assert len(ids) == len(set(ids)), "중복 equipment_id"
    for f in fixes:
        uuid.UUID(f["id"])  # 유효 UUID v4 문자열
        assert f["new"].strip(), f"빈 new url: {f['id']}"
        assert "panattasport.com" not in f["new"], f"new가 여전히 깨진 도메인: {f['id']}"
        assert "panattasport.com" in f["old"], f"old가 알려진 깨진 URL이 아님: {f['id']}"


def test_seed_csv_synced_with_migration():
    """seed CSV의 image_url 이 마이그레이션 대체 URL과 일치(drift 방지)."""
    fixes = _load_fixes()
    seed = _seed_image_by_id()
    for f in fixes:
        assert f["id"] in seed, f"seed에 없는 equipment_id: {f['id']}"
        assert seed[f["id"]] == f["new"], (
            f"seed image_url 가 마이그레이션과 불일치: id={f['id']}\n"
            f"  seed={seed[f['id']]!r}\n  migration.new={f['new']!r}"
        )


def test_seed_sources_have_no_dead_domain():
    """두 시드 소스에 깨진 panattasport.com URL이 남아 있지 않아야 한다(회귀 방지)."""
    seed_text = _SEED.read_text(encoding="utf-8")
    assert _DEAD_DOMAIN not in seed_text, "equipments_seed.csv 에 깨진 panattasport.com URL 잔존"

    panatta_text = _PANATTA.read_text(encoding="cp949")  # 원본은 cp949 인코딩
    assert _DEAD_DOMAIN not in panatta_text, "panatta_equipments.csv 에 깨진 panattasport.com URL 잔존"
