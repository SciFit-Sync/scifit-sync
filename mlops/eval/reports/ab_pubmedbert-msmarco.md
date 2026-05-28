# RAG Retrieval 평가 리포트 (2026-05-27)

- 골드셋: `mlops/eval/goldset.jsonl` (n=71)
- Retriever: `inmem+shard+pubmedbert-msmarco`
- 생성 시각 (UTC): 2026-05-27T03:55:35+00:00

## 전체 지표

| recall@5 | recall@10 | MRR |
| --- | --- | --- |
| 0.153 | 0.192 | 0.288 |

## 카테고리별 지표

| 카테고리 | n | recall@5 | recall@10 | MRR |
| --- | --- | --- | --- | --- |
| endurance | 8 | 0.062 | 0.146 | 0.263 |
| exercise_selection | 7 | 0.190 | 0.214 | 0.508 |
| form_technique | 2 | 0.375 | 0.375 | 0.667 |
| frequency_split | 7 | 0.060 | 0.060 | 0.076 |
| hypertrophy | 6 | 0.083 | 0.167 | 0.111 |
| muscle_specific | 18 | 0.215 | 0.257 | 0.340 |
| progressive_overload | 6 | 0.153 | 0.153 | 0.306 |
| recovery | 2 | 0.500 | 0.500 | 0.750 |
| special_populations | 1 | 0.000 | 0.000 | 0.000 |
| strength | 9 | 0.176 | 0.194 | 0.297 |
| weight_loss | 5 | 0.000 | 0.100 | 0.025 |
