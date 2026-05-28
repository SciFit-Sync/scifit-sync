"""Admin API — MLOps 파이프라인 연동용.

GitHub Actions에서 실행된 논문 임베딩 결과를 서버 ChromaDB로 수신하는 엔드포인트.
ADMIN_API_TOKEN으로 인증.
"""

import asyncio
import logging

import chromadb
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import ForbiddenError
from app.models.exercise import Exercise, ExerciseEquipmentMap
from app.models.gym import Equipment, EquipmentType
from app.models.paper import Paper
from app.schemas.rag import RagIngestRequest
from app.services.workoutx import list_all_exercises

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

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


def _ingest_chunks_to_chroma(chunks: list, batch_size: int = 100) -> tuple[int, int]:
    """ChromaDB에 청크를 배치 upsert하고 (적재 수, 전체 컬렉션 수)를 반환한다.

    upsert/count는 모두 동기 블로킹 호출이라 async 핸들러에서 직접 부르면 이벤트 루프가
    멈춘다(0.5 vCPU 단일 태스크에서 대량 적재 시 /health 타임아웃 → ECS가 태스크 kill).
    이 함수를 통째로 워커 스레드에서 실행하기 위해 분리한다.
    """
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
    total, total_collection = await asyncio.to_thread(_ingest_chunks_to_chroma, body.chunks)

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
async def list_pmids(_: None = Depends(_verify_admin_token)) -> dict:
    """ChromaDB에 적재된 모든 unique paper_pmid 목록을 반환한다.

    카테고리 메타 동기화 스크립트(`refresh_search_categories`)가 호출하여
    어떤 PMID에 대해 카테고리 재계산을 적용할지 결정한다.

    NOTE: 응답이 `dict`인 것은 기존 `ingest_papers` 엔드포인트와의 일관성 때문이다
    (모든 admin 엔드포인트가 `{success, data}` 평문 dict 패턴). OpenAPI 모델화는
    admin 모든 엔드포인트를 한 번에 변환하는 별도 PR에서 다룬다.
    """
    collection = _get_collection()
    # ChromaDB get()은 동기 블로킹 → 이벤트 루프 비차단 위해 워커 스레드로 오프로드
    data = await asyncio.to_thread(collection.get, include=["metadatas"])
    metas = data.get("metadatas") or []
    pmids = sorted({m["paper_pmid"] for m in metas if m and m.get("paper_pmid")})
    return {"success": True, "data": {"pmids": pmids, "count": len(pmids), "total_chunks": len(metas)}}


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
    # ChromaDB get()/update()는 동기 블로킹 → 워커 스레드로 오프로드
    data = await asyncio.to_thread(collection.get, include=["metadatas"])
    ids = data.get("ids") or []
    metas = data.get("metadatas") or []

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


# WorkoutX equipment 문자열 → EquipmentType 매핑
_WX_EQUIPMENT_TYPE: dict[str, str] = {
    "barbell": EquipmentType.BARBELL,
    "dumbbell": EquipmentType.DUMBBELL,
    "cable": EquipmentType.CABLE,
    "machine": EquipmentType.MACHINE,
    "leverage machine": EquipmentType.MACHINE,
    "smith machine": EquipmentType.MACHINE,
    "assisted": EquipmentType.MACHINE,
    "body weight": EquipmentType.BODYWEIGHT,
    "bodyweight": EquipmentType.BODYWEIGHT,
    "band": EquipmentType.BODYWEIGHT,
    "ez barbell": EquipmentType.BARBELL,
    "olympic barbell": EquipmentType.BARBELL,
}


@router.post("/exercises/seed-workoutx")
async def seed_exercises_from_workoutx(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_admin_token),
) -> dict:
    """WorkoutX API에서 전체 운동 목록을 가져와 exercises + exercise_equipment_map 테이블을 채운다.

    멱등 처리 (name_en ON CONFLICT DO NOTHING). 여러 번 실행해도 안전.
    """
    wx_exercises = await list_all_exercises()
    if not wx_exercises:
        return {"success": True, "data": {"upserted": 0, "mapped": 0, "message": "WorkoutX에서 운동 목록을 가져오지 못했습니다."}}

    # DB 기구 목록 미리 로드: equipment_type → [equipment_id, ...]
    eq_rows = (await db.execute(select(Equipment.id, Equipment.equipment_type))).all()
    equipment_by_type: dict[str, list] = {}
    for eq_id, eq_type in eq_rows:
        equipment_by_type.setdefault(eq_type, []).append(eq_id)

    upserted = 0
    mapped = 0

    for item in wx_exercises:
        name_en: str = (item.get("name") or "").strip()
        if not name_en:
            continue

        body_part: str = (item.get("bodyPart") or "").strip().lower()
        gif_url: str | None = item.get("gifUrl")
        wx_equipment: str = (item.get("equipment") or "").strip().lower()

        # exercises upsert (name_en unique)
        stmt = pg_insert(Exercise).values(
            name=name_en,
            name_en=name_en,
            category=body_part or "unknown",
            gif_url=gif_url,
        ).on_conflict_do_update(
            index_elements=["name_en"],
            set_={"gif_url": gif_url, "category": body_part or "unknown"},
        ).returning(Exercise.id)
        result = await db.execute(stmt)
        exercise_id = result.scalar_one()
        upserted += 1

        # exercise_equipment_map: 매핑 타입의 모든 기구와 연결
        eq_type = _WX_EQUIPMENT_TYPE.get(wx_equipment)
        if eq_type:
            for eq_id in equipment_by_type.get(eq_type, []):
                map_stmt = pg_insert(ExerciseEquipmentMap).values(
                    exercise_id=exercise_id,
                    equipment_id=eq_id,
                ).on_conflict_do_nothing()
                await db.execute(map_stmt)
                mapped += 1

    await db.commit()
    logger.info("seed-workoutx 완료: exercises=%d, equipment_map=%d", upserted, mapped)
    return {"success": True, "data": {"upserted": upserted, "mapped": mapped}}
