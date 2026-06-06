"""Admin API — MLOps 파이프라인 연동용.

GitHub Actions에서 실행된 논문 임베딩 결과를 서버 ChromaDB로 수신하는 엔드포인트.
ADMIN_API_TOKEN으로 인증.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import chromadb
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import ForbiddenError
from app.models.exercise import Exercise, ExerciseEquipment
from app.models.gym import Equipment
from app.models.paper import Paper
from app.schemas.rag import RagIngestRequest
from app.services import rag as rag_svc
from app.services.workoutx import list_all_exercises

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_chroma_client = None


def _close_chroma_writer() -> None:
    """Lifespan shutdown에서 호출 — admin writer client 참조를 해제한다.

    B2 fix: main.py lifespan shutdown이 rag._client(reader)만 정리하고
    admin._chroma_client(writer)를 누락하던 문제를 해결한다.
    ChromaDB PersistentClient는 명시적 close API가 없지만, 참조를 끊으면
    GC finalizer가 sqlite WAL을 flush하므로 HNSW partial-write 위험이 감소한다.
    """
    global _chroma_client
    _chroma_client = None


def _get_collection() -> chromadb.Collection:
    global _chroma_client
    settings = get_settings()
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_PATH)
    return _chroma_client.get_or_create_collection(
        name=settings.CHROMA_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


async def _verify_admin_token(x_admin_token: str = Header(...)) -> None:
    settings = get_settings()
    if not settings.ADMIN_API_TOKEN or x_admin_token != settings.ADMIN_API_TOKEN:
        raise ForbiddenError(message="Admin 인증이 필요합니다")


def _safe_doc_id(doi: str, chunk_index: int) -> str:
    """DOI에 포함된 슬래시/점을 ChromaDB id-safe 문자로 치환."""
    doi_safe = doi.replace("/", "_").replace(".", "-")
    return f"{doi_safe}_{chunk_index}"


# ChromaDB는 collection.get(include=["metadatas"]) 시 내부적으로 SQLite IN 절을 쓰는데
# 한 번에 ~18~30k row를 넘기면 "too many SQL variables" InternalError로 깨진다.
# 페이지당 1000 row(SQLite 한계 32766 대비 충분한 여유)로 잘라 가져온다.
_GET_PAGE_SIZE = 1000


def _fetch_all_metadatas_paged(collection: chromadb.Collection) -> tuple[list[str], list[dict]]:
    """collection.get(include=["metadatas"])를 limit/offset로 페이지네이션해 누적.

    동기 호출 — 호출부에서 asyncio.to_thread로 워커 스레드 오프로드.
    """
    all_ids: list[str] = []
    all_metas: list[dict] = []
    offset = 0
    while True:
        page = collection.get(include=["metadatas"], limit=_GET_PAGE_SIZE, offset=offset)
        ids = page.get("ids") or []
        if not ids:
            break
        metas = page.get("metadatas") or [{} for _ in ids]
        all_ids.extend(ids)
        all_metas.extend(metas)
        if len(ids) < _GET_PAGE_SIZE:
            break
        offset += _GET_PAGE_SIZE
    return all_ids, all_metas


def _get_or_create_named_collection(name: str) -> chromadb.Collection:
    """명시적 collection 이름으로 get_or_create. alias 무시."""
    global _chroma_client
    settings = get_settings()
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_PATH)
    return _chroma_client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def _ingest_chunks_to_chroma(
    chunks: list, batch_size: int = 100, collection_name: str | None = None
) -> tuple[int, int]:
    """ChromaDB에 청크를 배치 upsert하고 (적재 수, 전체 컬렉션 수)를 반환한다.

    upsert/count는 모두 동기 블로킹 호출이라 async 핸들러에서 직접 부르면 이벤트 루프가
    멈춘다(0.5 vCPU 단일 태스크에서 대량 적재 시 /health 타임아웃 → ECS가 태스크 kill).
    이 함수를 통째로 워커 스레드에서 실행하기 위해 분리한다.

    Args:
        chunks: 적재할 ChunkIngestPayload 리스트.
        batch_size: ChromaDB upsert 배치 크기.
        collection_name: 명시 시 alias 무시하고 해당 컬렉션에 직접 적재.
            None이면 _get_collection()(alias-aware 기본값) 사용.
    """
    if collection_name and collection_name.strip():
        collection = _get_or_create_named_collection(collection_name.strip())
    else:
        collection = _get_collection()
    total = 0
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        collection.upsert(
            ids=[_safe_doc_id(c.paper_doi, c.chunk_index) for c in batch],
            documents=[c.content for c in batch],
            embeddings=[c.embedding for c in batch],
            metadatas=[
                {
                    "paper_doi": c.paper_doi,
                    "paper_pmid": c.paper_pmid or "",
                    "paper_title": c.paper_title,
                    "section_name": c.section_name,
                    "chunk_index": c.chunk_index,
                    "token_count": c.token_count or 0,
                    "search_categories": ",".join(c.search_categories),
                    "publication_types": ",".join(c.publication_types),
                    "evidence_weight": float(c.evidence_weight),
                    "fulltext_source": c.fulltext_source or "",
                    "published_year": c.published_year or 0,
                }
                for c in batch
            ],
        )
        total += len(batch)
        logger.info("ChromaDB upsert: %d/%d", total, len(chunks))
    return total, collection.count()


@router.post("/rag/ingest")
async def ingest_papers(
    body: RagIngestRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_admin_token),
) -> dict:
    """MLOps 파이프라인에서 처리된 논문 청크+임베딩을 적재한다.

    1) papers UPSERT (DOI ON CONFLICT) — Postgres
    2) ChromaDB chunk upsert (확장 metadata 포함)
    """
    if not body.chunks:
        return {"success": True, "data": {"upserted": 0}}

    # ── 1) Papers UPSERT (DOI 기준 그룹화) ────────────────────
    # 같은 DOI는 첫 청크의 메타로 한 번만 적재한다.
    papers_by_doi: dict[str, dict] = {}
    for c in body.chunks:
        if c.paper_doi and c.paper_doi not in papers_by_doi:
            papers_by_doi[c.paper_doi] = {
                "doi": c.paper_doi,
                "pmid": c.paper_pmid or None,
                "title": c.paper_title,
                "publication_types": c.publication_types,
                "evidence_weight": c.evidence_weight,
                "fulltext_source": c.fulltext_source or "unknown",
                "search_categories": c.search_categories,
                "published_year": c.published_year if c.published_year else None,
            }

    if papers_by_doi:
        stmt = pg_insert(Paper).values(list(papers_by_doi.values()))
        stmt = stmt.on_conflict_do_update(
            index_elements=["doi"],
            set_={
                "pmid": stmt.excluded.pmid,
                "title": stmt.excluded.title,
                "publication_types": stmt.excluded.publication_types,
                "evidence_weight": stmt.excluded.evidence_weight,
                "fulltext_source": stmt.excluded.fulltext_source,
                "search_categories": stmt.excluded.search_categories,
                "published_year": stmt.excluded.published_year,
                "updated_at": func.now(),
            },
        )
        await db.execute(stmt)
        await db.commit()
        logger.info("papers UPSERT 완료: %d편", len(papers_by_doi))

    # ── 2) ChromaDB chunk upsert (확장 메타) ─────────────────
    # ChromaDB 호출(upsert/count)은 동기 블로킹이라 이벤트 루프를 멈춘다 → 대량 적재 시
    # /health 타임아웃으로 ECS가 태스크를 kill한다. 워커 스레드로 오프로드해 루프를 비운다.
    # body.collection이 명시되면 alias 무시하고 해당 컬렉션에 직접 적재 (Phase 2 papers_v2용).
    target_collection = (body.collection or "").strip() or None
    total, total_collection = await asyncio.to_thread(_ingest_chunks_to_chroma, body.chunks, 100, target_collection)

    logger.info("ingest 완료: %d청크 (collection 전체: %d)", total, total_collection)
    return {
        "success": True,
        "data": {
            "upserted": total,
            "papers_upserted": len(papers_by_doi),
            "total_collection": total_collection,
        },
    }


@router.get("/rag/dois")
async def list_dois(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_admin_token),
) -> dict:
    """papers 테이블에 적재된 모든 paper의 DOI 목록.

    MLOps 파이프라인이 ingest 시작 시 호출해 `existing_dois`를 초기화한다 —
    manifest는 GitHub Actions runner의 임시 디스크에 저장되어 매 cron마다 손실되므로
    서버를 dedup의 primary source로 두고 manifest는 보조 (paper별 tried_sources 같은
    부가 정보 보존)로 둔다.
    """
    result = await db.execute(select(Paper.doi).order_by(Paper.doi))
    dois = [row[0] for row in result.all()]
    return {"success": True, "data": {"dois": dois, "count": len(dois)}}


@router.get("/rag/pmids")
async def list_pmids(
    limit: int = 100,
    offset: int = 0,
    _: None = Depends(_verify_admin_token),
) -> dict:
    """ChromaDB에 적재된 unique paper_pmid 목록을 페이지네이션하여 반환한다.

    카테고리 메타 동기화 스크립트(`refresh_search_categories`)가 호출하여
    어떤 PMID에 대해 카테고리 재계산을 적용할지 결정한다.

    신규 MAJOR 픽스: 이전 구현은 chunk row 기준 limit/offset이어서 페이지 경계에서
    같은 PMID의 청크가 분리되면 중복 또는 누락이 발생했다.
    현재 구현은 collection 전체 metadata를 배치로 수집 → unique PMID 집계 → sort → slice하여
    PMID 단위 페이지네이션을 보장한다. `limit`/`offset`은 unique PMID 목록 기준.

    NOTE: 응답이 `dict`인 것은 기존 `ingest_papers` 엔드포인트와의 일관성 때문이다
    (모든 admin 엔드포인트가 `{success, data}` 평문 dict 패턴). OpenAPI 모델화는
    admin 모든 엔드포인트를 한 번에 변환하는 별도 PR에서 다룬다.
    """
    if limit <= 0 or limit > 100000:
        raise HTTPException(status_code=400, detail="limit must be in (0, 100000]")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")

    collection = _get_collection()
    # PR #176 헬퍼로 전체 metadata 안전 수집 (내부 페이지네이션, SQLite 변수 한계 회피)
    _ids, metas = await asyncio.to_thread(_fetch_all_metadatas_paged, collection)
    total_chunks = len(metas)

    # unique PMID 집계 → sort → slice (PMID 단위 페이지네이션, 페이지 경계 중복/누락 방지)
    all_pmids = sorted({m["paper_pmid"] for m in metas if m and m.get("paper_pmid")})
    total_pmids = len(all_pmids)
    page = all_pmids[offset : offset + limit]

    return {
        "success": True,
        "data": {
            "pmids": page,
            "total": total_pmids,  # unique PMID 수 (페이지네이션 기준)
            "limit": limit,
            "offset": offset,
            "has_next": offset + limit < total_pmids,
            # 하위 호환: 기존 MLOps 스크립트가 count/total_chunks를 읽는 경우 대비 보존
            "count": len(page),
            "total_chunks": total_chunks,
        },
    }


class RefreshCategoriesRequest(BaseModel):
    mapping: dict[str, list[str]]  # paper_pmid -> categories list


@router.post("/rag/refresh-categories")
async def refresh_categories(
    body: RefreshCategoriesRequest,
    _: None = Depends(_verify_admin_token),
) -> dict:
    """PMID → 카테고리 리스트 매핑을 받아 ChromaDB 청크 메타의 search_categories만 갱신한다.

    임베딩/문서 본문은 건드리지 않으므로 매우 빠르다. SEARCH_QUERY_CATEGORIES가
    변경된 후 RAG 검색 가중치를 동기화하는 용도.
    """
    collection = _get_collection()
    # 페이지네이션으로 전체 메타 누적 (대용량 컬렉션에서 SQLite "too many SQL variables" 회피)
    ids, metas = await asyncio.to_thread(_fetch_all_metadatas_paged, collection)

    update_ids: list[str] = []
    update_metas: list[dict] = []
    for cid, meta in zip(ids, metas, strict=True):
        if not meta:
            continue
        pmid = meta.get("paper_pmid")
        if pmid not in body.mapping:
            continue
        new_cats = sorted(set(body.mapping[pmid]))
        old_raw = meta.get("search_categories", "") or ""
        old_cats = sorted(c for c in old_raw.split(",") if c)
        if new_cats == old_cats:
            continue
        update_ids.append(cid)
        update_metas.append({**meta, "search_categories": ",".join(new_cats)})

    if update_ids:
        batch_size = 500
        for i in range(0, len(update_ids), batch_size):
            await asyncio.to_thread(
                collection.update,
                ids=update_ids[i : i + batch_size],
                metadatas=update_metas[i : i + batch_size],
            )

    logger.info(
        "refresh-categories: 갱신 %d청크 (전체 %d, 매핑 PMID %d)",
        len(update_ids),
        len(ids),
        len(body.mapping),
    )
    return {
        "success": True,
        "data": {
            "updated_chunks": len(update_ids),
            "total_chunks": len(ids),
            "total_pmids_in_mapping": len(body.mapping),
        },
    }


# WorkoutX equipment 문자열 → load_mode 매핑 (SOT: docs/handoff workoutx-raw/freeweight_load_modes.csv)
# cardio(Elliptical/Bike)는 FREEWEIGHT_MODES/MACHINE_MODES 어디에도 없어 루틴 후보 제외.
_WX_LOAD_MODE: dict[str, str] = {
    "barbell": "barbell",
    "olympic barbell": "barbell",
    "ez barbell": "ez_barbell",
    "trap bar": "trap_bar",
    "dumbbell": "dumbbell",
    "body weight": "bodyweight",
    "bodyweight": "bodyweight",
    "weighted": "weighted",
    "kettlebell": "kettlebell",
    "band": "band",
    "cable": "cable",
    "machine": "machine",
    "leverage machine": "machine",
    "smith machine": "machine",
    "assisted": "machine",
}


@router.post("/exercises/seed-workoutx")
async def seed_exercises_from_workoutx(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_admin_token),
) -> dict:
    """WorkoutX API에서 전체 운동 목록을 가져와 exercises 테이블을 채운다.

    멱등 처리 (name_en ON CONFLICT DO UPDATE). 여러 번 실행해도 안전.

    Phase 4 재설계:
    - load_mode 컬럼 채움 (_WX_LOAD_MODE 매핑).
    - 머신/케이블 운동(MACHINE_MODES)만 exercise_equipment junction 행 upsert.
      프리웨이트는 routine_exercises.equipment_id=NULL 경로이므로 junction 불필요.
    - exercise UPSERT 배치 커밋 후 name_en→id 룩업으로 junction 구성
      (미커밋 참조 방지).

    전제조건: Phase-1 스키마 마이그레이션(load_mode 컬럼 + exercise_equipment 테이블)
    적용 후 실행해야 한다.
    """
    from app.services.load_calc import MACHINE_MODES

    wx_exercises = await list_all_exercises()
    if not wx_exercises:
        return {
            "success": True,
            "data": {"upserted": 0, "junction": 0, "message": "WorkoutX에서 운동 목록을 가져오지 못했습니다."},
        }

    # 머신/케이블 junction용: equipment_type IN ('cable','machine') 기구 목록
    # equipment_type 컬럼은 Equipment 모델에 여전히 존재 (Equipment.is_freeweight 제거됨)
    machine_eq_rows = (
        await db.execute(
            select(Equipment.id, Equipment.equipment_type, Equipment.name_en)
            .where(Equipment.equipment_type.in_(["cable", "machine"]))
            .order_by(Equipment.equipment_type, Equipment.id)
        )
    ).all()
    # load_mode(cable/machine) → 후보 equipment id 리스트 (첫 번째 = 대표)
    eq_by_load_mode: dict[str, list[uuid.UUID]] = {}
    for eq_id, eq_type, _eq_name in machine_eq_rows:
        eq_by_load_mode.setdefault(str(eq_type), []).append(eq_id)

    upserted = 0
    errors = 0
    _BATCH = 50
    # 머신 junction용: name_en → load_mode 수집 (exercise commit 후 id 룩업)
    machine_name_to_load_mode: dict[str, str] = {}

    for i, item in enumerate(wx_exercises):
        name_en: str = (item.get("name") or "").strip()
        if not name_en:
            continue

        body_part: str = (item.get("bodyPart") or "").strip()
        gif_url: str | None = item.get("gifUrl")
        wx_equipment: str = (item.get("equipment") or "").strip().lower()
        load_mode: str | None = _WX_LOAD_MODE.get(wx_equipment)

        # Exercise.category NOT NULL 가드: bodyPart 빈 문자열/None 방어
        if not body_part:
            logger.warning("운동 '%s' bodyPart 없음, 스킵", name_en)
            errors += 1
            continue

        try:
            values: dict = {
                "name": name_en,
                "name_en": name_en,
                "category": body_part,  # SOT: raw bodyPart 그대로 (소문자 변환 없음)
                "gif_url": gif_url,
                "load_mode": load_mode,
            }
            set_: dict = {
                "gif_url": gif_url,
                "category": body_part,
                "load_mode": load_mode,
            }

            stmt = pg_insert(Exercise).values(**values).on_conflict_do_update(index_elements=["name_en"], set_=set_)
            await db.execute(stmt)
            upserted += 1

            if load_mode in MACHINE_MODES:
                machine_name_to_load_mode[name_en] = load_mode

            # 배치 단위로 커밋 (긴 트랜잭션 방지)
            if (i + 1) % _BATCH == 0:
                await db.commit()

        except Exception as e:
            logger.warning("운동 '%s' 처리 실패, 스킵: %s", name_en, e)
            await db.rollback()
            errors += 1

    await db.commit()

    # ── junction upsert (머신/케이블만) ──────────────────────────────────────
    # exercise UPSERT 커밋 완료 후 name_en→id 룩업 (미커밋 참조 방지)
    junction_count = 0
    if machine_name_to_load_mode and eq_by_load_mode:
        name_list = list(machine_name_to_load_mode.keys())
        id_rows = (await db.execute(select(Exercise.id, Exercise.name_en).where(Exercise.name_en.in_(name_list)))).all()
        name_to_id: dict[str, uuid.UUID] = {row.name_en: row.id for row in id_rows}

        junction_values: list[dict] = []
        for ex_name, lm in machine_name_to_load_mode.items():
            ex_id = name_to_id.get(ex_name)
            candidates = eq_by_load_mode.get(lm, [])
            if ex_id is None or not candidates:
                continue
            # M>=1 후보 중 첫 번째 equipment를 대표로 junction 삽입 (D14: M>=2 LLM택1은 루틴생성 시)
            junction_values.append({"exercise_id": ex_id, "equipment_id": candidates[0], "source": "seed"})

        if junction_values:
            junc_stmt = (
                pg_insert(ExerciseEquipment)
                .values(junction_values)
                .on_conflict_do_nothing(index_elements=["exercise_id", "equipment_id"])
            )
            await db.execute(junc_stmt)
            await db.commit()
            junction_count = len(junction_values)

    # 2nd pass: gif_url이 NULL인 기존 운동에 WorkoutX gif 퍼지 매칭
    wx_by_name_lc = {(item.get("name") or "").strip().lower(): item for item in wx_exercises if item.get("name")}
    null_gif_rows = (
        await db.execute(
            select(Exercise.id, Exercise.name_en).where(Exercise.gif_url.is_(None), Exercise.name_en.isnot(None))
        )
    ).all()

    gif_updated = 0
    for ex_id, ex_name_en in null_gif_rows:
        name_lc = ex_name_en.strip().lower()
        wx = wx_by_name_lc.get(name_lc)
        if not wx:
            for wx_name, wx_item in wx_by_name_lc.items():
                if name_lc in wx_name or wx_name in name_lc:
                    wx = wx_item
                    break
        if wx and wx.get("gifUrl"):
            await db.execute(sa_update(Exercise).where(Exercise.id == ex_id).values(gif_url=wx.get("gifUrl")))
            gif_updated += 1

    if gif_updated:
        await db.commit()

    logger.info(
        "seed-workoutx 완료: exercises=%d, exercise_equipment=%d, gif_updated=%d, errors=%d",
        upserted,
        junction_count,
        gif_updated,
        errors,
    )
    return {
        "success": True,
        "data": {"upserted": upserted, "junction": junction_count, "gif_updated": gif_updated, "errors": errors},
    }


class CollectionSwapRequest(BaseModel):
    to: str


@router.post("/rag/collection-swap")
async def swap_collection(
    body: CollectionSwapRequest,
    _: None = Depends(_verify_admin_token),
) -> dict:
    """`current_alias.json`의 `current`를 새 collection 이름으로 atomic write.

    PR-δ §2.3 alias-swap 패턴 — body `{"to": "papers_v2"}`로 호출하면 EFS의 alias 파일을
    교체하고 rag 서비스의 keyed cache를 clear 한다. 다음 검색 요청부터 새 collection을
    사용하므로 zero-downtime swap이 가능하다. 롤백은 동일 endpoint에 이전 이름으로 재호출.

    F1 fix: alias 파일 쓰기 전에 target collection이 ChromaDB에 실제로 존재하는지 검증.
    오타(papers_v22 등) 한 번에 검색 500 회귀 가능성 차단 → 존재하지 않으면 404 반환.
    """
    target = body.to.strip()
    if not target:
        raise HTTPException(status_code=400, detail="`to` 필드는 비어있을 수 없습니다")

    # F1 fix: target collection 존재 검증 — alias 파일 쓰기 전에 ChromaDB에서 확인
    global _chroma_client
    settings = get_settings()
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_PATH)
    existing = [c.name for c in _chroma_client.list_collections()]
    if target not in existing:
        raise HTTPException(
            status_code=404,
            detail=f"collection {target!r} not found. Available: {existing}",
        )

    alias_path: Path = rag_svc.ALIAS_FILE
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    swapped_at = datetime.now(timezone.utc).isoformat()

    # POSIX atomic: tmp write → rename. 동일 디렉토리에서 .replace는 atomic이 보장된다.
    # M3 잔여 픽스: uuid4 suffix — pid+ms timestamp는 동일 프로세스 동시 요청에서 같은 ms 충돌 가능
    tmp = alias_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    tmp.write_text(
        json.dumps({"current": target, "swapped_at": swapped_at}),
        encoding="utf-8",
    )
    tmp.replace(alias_path)

    # 다음 _get_collection 호출부터 새 alias가 즉시 반영되도록 keyed cache 비움.
    rag_svc._collection_cache.clear()

    logger.info("collection-swap: alias '%s'로 갱신 (at=%s)", target, swapped_at)
    return {"success": True, "data": {"current": target, "swapped_at": swapped_at}}
