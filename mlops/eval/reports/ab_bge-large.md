# RAG Retrieval 평가 리포트 (2026-05-27)

- 골드셋: `mlops/eval/goldset.jsonl` (n=71)
- Retriever: `inmem+shard+bge-large`
- 생성 시각 (UTC): 2026-05-27T03:48:37+00:00

## 전체 지표

| recall@5 | recall@10 | MRR |
| --- | --- | --- |
| 0.249 | 0.280 | 0.405 |

## 카테고리별 지표

| 카테고리 | n | recall@5 | recall@10 | MRR |
| --- | --- | --- | --- | --- |
| endurance | 8 | 0.208 | 0.240 | 0.418 |
| exercise_selection | 7 | 0.429 | 0.429 | 0.821 |
| form_technique | 2 | 0.500 | 0.500 | 1.000 |
| frequency_split | 7 | 0.095 | 0.119 | 0.112 |
| hypertrophy | 6 | 0.125 | 0.208 | 0.225 |
| muscle_specific | 18 | 0.299 | 0.326 | 0.395 |
| progressive_overload | 6 | 0.167 | 0.167 | 0.233 |
| recovery | 2 | 0.500 | 0.500 | 0.750 |
| special_populations | 1 | 0.000 | 0.000 | 0.000 |
| strength | 9 | 0.250 | 0.278 | 0.427 |
| weight_loss | 5 | 0.200 | 0.300 | 0.339 |
