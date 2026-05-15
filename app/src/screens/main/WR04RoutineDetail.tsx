import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Modal,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  deleteRoutine,
  getRoutineDetail,
  renameRoutine,
  type RoutineDayItem,
  type RoutineExerciseItem,
} from '../../services/routines';
import { useAuthStore } from '../../stores/authStore';

const GOAL_LABEL: Record<string, string> = {
  hypertrophy: '근비대',
  strength: '근력',
  endurance: '근지구력',
  rehabilitation: '재활',
  weight_loss: '체중 감량',
};

function ExerciseRow({ item }: { item: RoutineExerciseItem }) {
  const reps =
    item.reps_min != null && item.reps_max != null
      ? item.reps_min === item.reps_max
        ? `${item.reps_min}회`
        : `${item.reps_min}~${item.reps_max}회`
      : null;
  const weight = item.weight_kg != null ? `${item.weight_kg}kg` : null;

  return (
    <View style={styles.exerciseRow}>
      <View style={styles.exerciseIndex}>
        <Text style={styles.exerciseIndexText}>{item.order_index}</Text>
      </View>
      <View style={styles.exerciseBody}>
        <Text style={styles.exerciseName}>{item.exercise_name}</Text>
        {item.equipment_name && (
          <Text style={styles.exerciseMeta}>{item.equipment_name}</Text>
        )}
      </View>
      <View style={styles.exerciseSets}>
        <Text style={styles.exerciseSetsText}>{item.sets}세트</Text>
        {reps && <Text style={styles.exerciseMeta}>{reps}</Text>}
        {weight && <Text style={styles.exerciseMeta}>{weight}</Text>}
      </View>
    </View>
  );
}

function DayCard({ day }: { day: RoutineDayItem }) {
  return (
    <View style={styles.dayCard}>
      <View style={styles.dayHeader}>
        <Text style={styles.dayNumber}>Day {day.day_number}</Text>
        <Text style={styles.dayLabel}>{day.label}</Text>
      </View>
      {day.exercises.map((ex) => (
        <ExerciseRow key={ex.routine_exercise_id} item={ex} />
      ))}
      {day.exercises.length === 0 && (
        <Text style={styles.emptyText}>운동 없음</Text>
      )}
    </View>
  );
}

export default function WR04RoutineDetail({ navigation, route }: { navigation: any; route: any }) {
  const { routine_id } = route.params as { routine_id: string };
  const token = useAuthStore((s) => s.accessToken) ?? '';
  const queryClient = useQueryClient();
  const [renameVisible, set_renameVisible] = useState(false);
  const [nameInput, set_nameInput] = useState('');

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['routine', routine_id],
    queryFn: () => getRoutineDetail(token, routine_id),
    enabled: !!token,
  });

  const { mutate: doDelete, isPending: isDeleting } = useMutation({
    mutationFn: () => deleteRoutine(token, routine_id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['routines'] });
      navigation.goBack();
    },
    onError: () => Alert.alert('오류', '삭제에 실패했습니다.'),
  });

  const { mutate: doRename, isPending: isRenaming } = useMutation({
    mutationFn: (name: string) => renameRoutine(token, routine_id, name),
    onSuccess: (updated) => {
      queryClient.setQueryData(['routine', routine_id], (old: typeof data) =>
        old ? { ...old, name: updated.name } : old,
      );
      queryClient.invalidateQueries({ queryKey: ['routines'] });
      set_renameVisible(false);
    },
    onError: () => Alert.alert('오류', '이름 변경에 실패했습니다.'),
  });

  function handleDeletePress() {
    Alert.alert('루틴 삭제', '이 루틴을 삭제하시겠습니까? 되돌릴 수 없습니다.', [
      { text: '취소', style: 'cancel' },
      { text: '삭제', style: 'destructive', onPress: () => doDelete() },
    ]);
  }

  function handleRenameOpen() {
    set_nameInput(data?.name ?? '');
    set_renameVisible(true);
  }

  function handleRenameSubmit() {
    const trimmed = nameInput.trim();
    if (!trimmed) return;
    doRename(trimmed);
  }

  function handleOptionsPress() {
    Alert.alert(data?.name ?? '루틴', undefined, [
      { text: '이름 변경', onPress: handleRenameOpen },
      { text: '삭제', style: 'destructive', onPress: handleDeletePress },
      { text: '취소', style: 'cancel' },
    ]);
  }

  if (isLoading) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.center}>
          <ActivityIndicator color="#fff" size="large" />
        </View>
      </SafeAreaView>
    );
  }

  if (isError || !data) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()} style={styles.headerBtn}>
            <Text style={styles.backText}>←</Text>
          </TouchableOpacity>
          <View style={styles.headerBtn} />
        </View>
        <View style={styles.center}>
          <Text style={styles.emptyText}>루틴을 불러오지 못했습니다.</Text>
          <TouchableOpacity onPress={() => refetch()} style={styles.retryButton}>
            <Text style={styles.retryText}>다시 시도</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  const goals = data.fitness_goals?.map((g) => GOAL_LABEL[g] ?? g) ?? [];

  return (
    <SafeAreaView style={styles.container}>
      {/* 헤더 */}
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.headerBtn}>
          <Text style={styles.backText}>←</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle} numberOfLines={1}>
          {data.name}
        </Text>
        <TouchableOpacity
          onPress={handleOptionsPress}
          style={styles.headerBtn}
          disabled={isDeleting}
        >
          <Text style={styles.optionsText}>⋯</Text>
        </TouchableOpacity>
      </View>

      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        {/* 메타 정보 */}
        <View style={styles.metaCard}>
          {goals.length > 0 && (
            <View style={styles.metaRow}>
              <Text style={styles.metaLabel}>목표</Text>
              <Text style={styles.metaValue}>{goals.join(' · ')}</Text>
            </View>
          )}
          {data.split_type && (
            <View style={styles.metaRow}>
              <Text style={styles.metaLabel}>분할</Text>
              <Text style={styles.metaValue}>{data.split_type}</Text>
            </View>
          )}
          {data.session_duration_minutes && (
            <View style={styles.metaRow}>
              <Text style={styles.metaLabel}>세션 시간</Text>
              <Text style={styles.metaValue}>{data.session_duration_minutes}분</Text>
            </View>
          )}
          <View style={styles.metaRow}>
            <Text style={styles.metaLabel}>생성</Text>
            <Text style={styles.metaValue}>{data.generated_by === 'ai' ? 'AI 생성' : '직접 생성'}</Text>
          </View>
        </View>

        {/* AI 추론 */}
        {data.ai_reasoning && (
          <View style={styles.reasoningCard}>
            <Text style={styles.reasoningTitle}>AI 분석</Text>
            <Text style={styles.reasoningText}>{data.ai_reasoning}</Text>
          </View>
        )}

        {/* 일자별 운동 */}
        <Text style={styles.sectionTitle}>운동 구성 ({data.days.length}일)</Text>
        {data.days.map((day) => (
          <DayCard key={day.routine_day_id} day={day} />
        ))}
        {data.days.length === 0 && (
          <Text style={styles.emptyText}>운동 일정이 없습니다.</Text>
        )}
      </ScrollView>

      {/* 이름 변경 모달 */}
      <Modal
        visible={renameVisible}
        transparent
        animationType="fade"
        onRequestClose={() => set_renameVisible(false)}
      >
        <TouchableOpacity
          style={styles.modalOverlay}
          activeOpacity={1}
          onPress={() => set_renameVisible(false)}
        >
          <TouchableOpacity activeOpacity={1} style={styles.modalBox}>
            <Text style={styles.modalTitle}>이름 변경</Text>
            <TextInput
              style={styles.modalInput}
              value={nameInput}
              onChangeText={set_nameInput}
              placeholder="루틴 이름"
              placeholderTextColor="#555"
              autoFocus
              maxLength={200}
            />
            <View style={styles.modalActions}>
              <TouchableOpacity
                style={styles.modalCancel}
                onPress={() => set_renameVisible(false)}
                disabled={isRenaming}
              >
                <Text style={styles.modalCancelText}>취소</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.modalConfirm, !nameInput.trim() && styles.modalConfirmDisabled]}
                onPress={handleRenameSubmit}
                disabled={isRenaming || !nameInput.trim()}
              >
                {isRenaming ? (
                  <ActivityIndicator color="#000" size="small" />
                ) : (
                  <Text style={styles.modalConfirmText}>변경</Text>
                )}
              </TouchableOpacity>
            </View>
          </TouchableOpacity>
        </TouchableOpacity>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 16 },

  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  headerBtn: { width: 40 },
  backText: { color: '#fff', fontSize: 22 },
  headerTitle: { flex: 1, color: '#fff', fontSize: 17, fontWeight: '700', textAlign: 'center' },
  optionsText: { color: '#fff', fontSize: 22, textAlign: 'right' },

  content: { paddingHorizontal: 16, paddingBottom: 40, gap: 12 },

  metaCard: {
    backgroundColor: '#111',
    borderRadius: 12,
    padding: 16,
    gap: 10,
  },
  metaRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  metaLabel: { color: '#666', fontSize: 13 },
  metaValue: { color: '#fff', fontSize: 13, fontWeight: '600', flexShrink: 1, textAlign: 'right', marginLeft: 16 },

  reasoningCard: {
    backgroundColor: '#0d0d1a',
    borderRadius: 12,
    padding: 16,
    borderWidth: 1,
    borderColor: '#2a2a4a',
    gap: 8,
  },
  reasoningTitle: { color: '#8888ff', fontSize: 12, fontWeight: '700', letterSpacing: 0.5 },
  reasoningText: { color: '#bbb', fontSize: 13, lineHeight: 20 },

  sectionTitle: { color: '#888', fontSize: 13, fontWeight: '600', marginTop: 4 },

  dayCard: {
    backgroundColor: '#111',
    borderRadius: 12,
    padding: 16,
    gap: 10,
  },
  dayHeader: { flexDirection: 'row', alignItems: 'center', gap: 10, marginBottom: 4 },
  dayNumber: { color: '#fff', fontSize: 13, fontWeight: '800' },
  dayLabel: { color: '#aaa', fontSize: 13 },

  exerciseRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  exerciseIndex: {
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: '#222',
    alignItems: 'center',
    justifyContent: 'center',
  },
  exerciseIndexText: { color: '#888', fontSize: 11, fontWeight: '700' },
  exerciseBody: { flex: 1, gap: 2 },
  exerciseName: { color: '#fff', fontSize: 14, fontWeight: '600' },
  exerciseMeta: { color: '#666', fontSize: 12 },
  exerciseSets: { alignItems: 'flex-end', gap: 2 },
  exerciseSetsText: { color: '#fff', fontSize: 13, fontWeight: '700' },

  emptyText: { color: '#555', fontSize: 13, textAlign: 'center', paddingVertical: 8 },
  retryButton: { backgroundColor: '#222', paddingVertical: 10, paddingHorizontal: 24, borderRadius: 8 },
  retryText: { color: '#fff', fontSize: 14 },

  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  modalBox: {
    width: '100%',
    backgroundColor: '#1a1a1a',
    borderRadius: 16,
    padding: 24,
    gap: 16,
  },
  modalTitle: { color: '#fff', fontSize: 16, fontWeight: '700' },
  modalInput: {
    backgroundColor: '#2a2a2a',
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: '#fff',
    fontSize: 15,
    borderWidth: 1,
    borderColor: '#333',
  },
  modalActions: { flexDirection: 'row', gap: 10 },
  modalCancel: {
    flex: 1,
    backgroundColor: '#2a2a2a',
    borderRadius: 8,
    paddingVertical: 12,
    alignItems: 'center',
  },
  modalCancelText: { color: '#aaa', fontSize: 14, fontWeight: '600' },
  modalConfirm: {
    flex: 1,
    backgroundColor: '#fff',
    borderRadius: 8,
    paddingVertical: 12,
    alignItems: 'center',
  },
  modalConfirmDisabled: { opacity: 0.4 },
  modalConfirmText: { color: '#000', fontSize: 14, fontWeight: '700' },
});
