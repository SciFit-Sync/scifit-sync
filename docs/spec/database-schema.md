# 데이터 모델 (27개 테이블)

## 테이블 목록

```
사용자: users, user_profiles, user_body_measurements,
        user_exercise_1rm, refresh_tokens, user_equipment_selections

헬스장: gyms, user_gyms, equipment_brands, equipments,
        gym_equipments, equipment_reports

운동:   exercises, exercise_equipment_map, muscle_groups, exercise_muscles

루틴:   workout_routines, routine_days, routine_exercises, routine_papers

기록:   workout_logs, workout_log_sets

RAG:    chat_sessions, chat_messages, papers, paper_chunks

기타:   notifications, user_stats
```

## 주요 설계 결정

- equipment.category: cable / machine / barbell / dumbbell / bodyweight
- 중량 기록: weight_kg = 기구 표시값, 실효 부하 = weight_kg × pulley_ratio
- 루틴 삭제: soft delete (deleted_at), 복구 불가
- RAG: 임베딩은 ChromaDB만 저장 (pgvector 미사용)
- DB: Alembic 단독 관리, Supabase 대시보드 직접 수정 금지
