# RAG Retrieval 평가 리포트

`mlops/eval/run_eval.py` 실행 시 생성되는 Markdown 리포트가 이 디렉토리에 누적된다.

- 파일명 규칙: `YYYY-MM-DD.md` (예: `2026-05-19.md`)
- 각 리포트는 골드셋, retriever 식별자, 전체 지표(recall@5/10, MRR), 카테고리별 지표를 포함한다.
- 첫 베이스라인 리포트는 골드셋 + ChromaDB 데이터가 모두 준비된 뒤 생성한다.

생성 명령 예시:

```bash
python -m mlops.eval.run_eval \
    --goldset mlops/eval/gold_set.jsonl \
    --output  mlops/eval/reports/2026-05-19.md
```
