# RAG Retrieval 평가 리포트 (2026-05-27)

- 골드셋: `mlops/eval/goldset.jsonl` (n=71)
- Retriever: `inmem+shard+bge-base`
- 생성 시각 (UTC): 2026-05-27T03:52:03+00:00

## 전체 지표

| recall@5 | recall@10 | MRR |
| --- | --- | --- |
| 0.203 | 0.248 | 0.374 |

## 카테고리별 지표

| 카테고리 | n | recall@5 | recall@10 | MRR |
| --- | --- | --- | --- | --- |
| endurance | 8 | 0.094 | 0.115 | 0.301 |
| exercise_selection | 7 | 0.333 | 0.333 | 0.690 |
| form_technique | 2 | 0.500 | 0.500 | 0.750 |
| frequency_split | 7 | 0.095 | 0.167 | 0.127 |
| hypertrophy | 6 | 0.083 | 0.208 | 0.125 |
| muscle_specific | 18 | 0.264 | 0.278 | 0.413 |
| progressive_overload | 6 | 0.153 | 0.194 | 0.292 |
| recovery | 2 | 0.500 | 0.500 | 1.000 |
| special_populations | 1 | 0.000 | 0.000 | 0.000 |
| strength | 9 | 0.194 | 0.222 | 0.415 |
| weight_loss | 5 | 0.150 | 0.350 | 0.257 |
