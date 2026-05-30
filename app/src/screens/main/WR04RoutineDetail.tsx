import { useState, useEffect, useRef } from "react";
import {
  ActivityIndicator,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation, useRoute } from "@react-navigation/native";
import { Octicons } from "@expo/vector-icons";
import { useQuery } from "@tanstack/react-query";
import { colors } from "../../assets/colors/colors";
import { useAuthStore } from "../../stores/authStore";
import {
  getRoutineDetail,
  GOAL_LABELS,
  type RoutineExerciseItem,
} from "../../services/routines";

interface Set {
  id: string;
  weight: string;
  reps: string;
  is_done: boolean;
}

interface MuscleActivation {
  name: string;
  percentage: number;
}

interface Exercise {
  id: string;
  name: string;
  sets: Set[];
  is_expanded: boolean;
  muscles: MuscleActivation[];
  rest_seconds: number;
}

function api_to_exercise(item: RoutineExerciseItem): Exercise {
  const default_weight =
    item.weight_kg != null ? String(item.weight_kg) : "0";
  const default_reps =
    item.reps_max != null
      ? String(item.reps_max)
      : item.reps_min != null
        ? String(item.reps_min)
        : "10";
  const sets: Set[] = Array.from({ length: item.sets }, (_, i) => ({
    id: String(i + 1),
    weight: default_weight,
    reps: default_reps,
    is_done: false,
  }));
  return {
    id: item.routine_exercise_id,
    name: item.exercise_name,
    sets,
    is_expanded: false,
    muscles: [],
    rest_seconds: item.rest_seconds ?? 180,
  };
}

export default function WR04RoutineDetail() {
  const navigation = useNavigation();
  const route = useRoute();
  const { routine_id } = (route.params ?? {}) as { routine_id?: string };
  const token = useAuthStore((s) => s.accessToken) ?? "";

  const [selected_day_idx, set_selected_day_idx] = useState(0);
  const [exercises, set_exercises] = useState<Exercise[]>([]);
  const [editing_exercise_id, set_editing_exercise_id] = useState<
    string | null
  >(null);
  const [timer, set_timer] = useState(180);
  const [is_timer_running, set_is_timer_running] = useState(false);
  const timer_ref = useRef<ReturnType<typeof setInterval> | null>(null);

  const { data: detail, isLoading } = useQuery({
    queryKey: ["routine", routine_id],
    queryFn: () => getRoutineDetail(token, routine_id!),
    enabled: !!token && !!routine_id,
  });

  // API 데이터 → 로컬 exercises 변환 (day 인덱스 변경 시 재초기화)
  useEffect(() => {
    if (!detail) return;
    const day = detail.days[selected_day_idx];
    if (!day) {
      set_exercises([]);
      return;
    }
    const sorted = [...day.exercises].sort(
      (a, b) => a.order_index - b.order_index,
    );
    set_exercises(sorted.map(api_to_exercise));
  }, [detail, selected_day_idx]);

  useEffect(() => {
    if (is_timer_running) {
      timer_ref.current = setInterval(() => {
        set_timer((prev) => {
          if (prev <= 1) {
            set_is_timer_running(false);
            clearInterval(timer_ref.current!);
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
    } else {
      if (timer_ref.current) clearInterval(timer_ref.current);
    }
    return () => {
      if (timer_ref.current) clearInterval(timer_ref.current);
    };
  }, [is_timer_running]);

  const format_time = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  };

  const toggle_exercise = (exercise_id: string) => {
    set_exercises((prev) =>
      prev.map((ex) =>
        ex.id === exercise_id ? { ...ex, is_expanded: !ex.is_expanded } : ex,
      ),
    );
  };

  const toggle_set_done = (exercise_id: string, set_id: string) => {
    set_exercises((prev) =>
      prev.map((ex) =>
        ex.id === exercise_id
          ? {
              ...ex,
              sets: ex.sets.map((s) =>
                s.id === set_id ? { ...s, is_done: !s.is_done } : s,
              ),
            }
          : ex,
      ),
    );
    const rest =
      exercises.find((ex) => ex.id === exercise_id)?.rest_seconds ?? 180;
    set_timer(rest);
    set_is_timer_running(true);
  };

  const update_set = (
    exercise_id: string,
    set_id: string,
    field: "weight" | "reps",
    value: string,
  ) => {
    set_exercises((prev) =>
      prev.map((ex) =>
        ex.id === exercise_id
          ? {
              ...ex,
              sets: ex.sets.map((s) =>
                s.id === set_id ? { ...s, [field]: value } : s,
              ),
            }
          : ex,
      ),
    );
  };

  const add_set = (exercise_id: string) => {
    set_exercises((prev) =>
      prev.map((ex) => {
        if (ex.id !== exercise_id) return ex;
        const last_set = ex.sets[ex.sets.length - 1];
        const new_set: Set = {
          id: String(ex.sets.length + 1),
          weight: last_set?.weight ?? "0",
          reps: last_set?.reps ?? "0",
          is_done: false,
        };
        return { ...ex, sets: [...ex.sets, new_set] };
      }),
    );
  };

  const toggle_edit = (exercise_id: string) => {
    set_editing_exercise_id((prev) =>
      prev === exercise_id ? null : exercise_id,
    );
  };

  const remove_set = (exercise_id: string) => {
    set_exercises((prev) =>
      prev.map((ex) => {
        if (ex.id !== exercise_id) return ex;
        if (ex.sets.length <= 1) return ex; // 최소 1세트 유지
        return { ...ex, sets: ex.sets.slice(0, -1) };
      }),
    );
  };

  const goals_label = detail?.fitness_goals
    ? detail.fitness_goals.map((g) => GOAL_LABELS[g] ?? g).join(" · ")
    : null;

  // 로딩 상태
  if (isLoading || (!detail && !!routine_id)) {
    return (
      <View style={styles.container}>
        <SafeAreaView edges={["top"]} style={styles.safe_top} />
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()}>
            <Octicons name="chevron-left" size={32} color={colors.primary} />
          </TouchableOpacity>
          <Text style={styles.logo}>SciFit-Sync</Text>
          <View style={styles.placeholder} />
        </View>
        <View style={styles.loading_container}>
          <ActivityIndicator size="large" color={colors.primary} />
          <Text style={styles.loading_text}>루틴 불러오는 중...</Text>
        </View>
      </View>
    );
  }

  const has_multiple_days = (detail?.days.length ?? 0) > 1;

  return (
    <View style={styles.container}>
      <SafeAreaView edges={["top"]} style={styles.safe_top} />

      {/* 헤더 */}
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()}>
          <Octicons name="chevron-left" size={32} color={colors.primary} />
        </TouchableOpacity>
        <Text style={styles.logo}>SciFit-Sync</Text>
        <View style={styles.placeholder} />
      </View>

      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
        style={styles.flex}
      >
        <View style={styles.card}>
          {/* 루틴 제목 */}
          <Text style={styles.routine_title}>
            {detail?.name ?? "루틴 상세"}
          </Text>
          {goals_label && (
            <Text style={styles.goals_label}>{goals_label}</Text>
          )}

          {/* 데이 선택 탭 (다중 날 루틴) */}
          {has_multiple_days && (
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={styles.day_tabs}
            >
              {detail!.days.map((day, idx) => (
                <TouchableOpacity
                  key={day.routine_day_id}
                  style={[
                    styles.day_tab,
                    selected_day_idx === idx && styles.day_tab_active,
                  ]}
                  onPress={() => set_selected_day_idx(idx)}
                  activeOpacity={0.7}
                >
                  <Text
                    style={[
                      styles.day_tab_text,
                      selected_day_idx === idx && styles.day_tab_text_active,
                    ]}
                  >
                    {day.label || `Day ${day.day_number}`}
                  </Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
          )}

          {/* 운동 목록 */}
          {exercises.map((exercise) => {
            const is_editing = editing_exercise_id === exercise.id;
            return (
              <View
                key={exercise.id}
                style={[
                  styles.exercise_card,
                  exercise.is_expanded && styles.exercise_card_expanded,
                ]}
              >
                {/* 운동 헤더 */}
                <TouchableOpacity
                  style={styles.exercise_header}
                  onPress={() => toggle_exercise(exercise.id)}
                  activeOpacity={0.8}
                >
                  <View style={styles.exercise_info}>
                    <Text style={styles.exercise_name}>{exercise.name}</Text>
                    <Text style={styles.exercise_sub}>
                      세트 {exercise.sets.filter((s) => s.is_done).length}/
                      {exercise.sets.length}회
                    </Text>
                  </View>
                  <Octicons
                    name={
                      exercise.is_expanded ? "chevron-down" : "chevron-right"
                    }
                    size={20}
                    color={colors.primary}
                  />
                </TouchableOpacity>

                {/* 펼친 내용 */}
                {exercise.is_expanded && (
                  <View style={styles.expanded_content}>
                    {/* 운동 변경 / TIPS 버튼 */}
                    <View style={styles.action_row}>
                      <TouchableOpacity
                        style={styles.action_button}
                        activeOpacity={0.8}
                      >
                        <Text style={styles.action_text}>운동 변경</Text>
                        <Octicons
                          name="arrow-switch"
                          size={14}
                          color={colors.primary}
                        />
                      </TouchableOpacity>
                      <TouchableOpacity
                        style={styles.action_button}
                        activeOpacity={0.8}
                      >
                        <Text style={styles.action_text}>TIPS</Text>
                        <Octicons
                          name="light-bulb"
                          size={14}
                          color={colors.primary}
                        />
                      </TouchableOpacity>
                    </View>

                    {/* 그래픽 영상 placeholder */}
                    <View style={styles.image_placeholder}>
                      <Octicons name="play" size={32} color={colors.bluegray} />
                    </View>

                    {/* 세트 섹션 */}
                    <View style={styles.sets_section}>
                      {/* 세트 헤더 */}
                      <View style={styles.sets_header}>
                        <View style={styles.sets_title_row}>
                          <Text style={styles.section_label}>세트</Text>
                          <TouchableOpacity
                            style={styles.set_count_button}
                            onPress={() => remove_set(exercise.id)}
                            activeOpacity={0.8}
                          >
                            <Octicons
                              name="dash"
                              size={14}
                              color={colors.primary}
                            />
                          </TouchableOpacity>
                          <TouchableOpacity
                            style={styles.set_count_button}
                            onPress={() => add_set(exercise.id)}
                            activeOpacity={0.8}
                          >
                            <Octicons
                              name="plus"
                              size={14}
                              color={colors.primary}
                            />
                          </TouchableOpacity>
                        </View>
                        <TouchableOpacity
                          style={[
                            styles.small_button,
                            is_editing && styles.small_button_active,
                          ]}
                          onPress={() => toggle_edit(exercise.id)}
                          activeOpacity={0.8}
                        >
                          <Text
                            style={[
                              styles.small_button_text,
                              is_editing && styles.small_button_text_active,
                            ]}
                          >
                            {is_editing ? "완료" : "수정"}
                          </Text>
                        </TouchableOpacity>
                      </View>

                      {/* 세트 행들 */}
                      {exercise.sets.map((set, idx) => (
                        <View key={set.id} style={styles.set_row}>
                          {/* 세트 번호 */}
                          <Text style={styles.set_number}>{idx + 1}</Text>

                          {/* 중량/횟수 박스 */}
                          <View style={styles.set_inputs}>
                            <View style={styles.set_input_group}>
                              <Text style={styles.set_input_label}>중량</Text>
                              {is_editing ? (
                                <TextInput
                                  style={styles.set_input_edit}
                                  value={set.weight}
                                  onChangeText={(v) =>
                                    update_set(exercise.id, set.id, "weight", v)
                                  }
                                  keyboardType="numeric"
                                  selectTextOnFocus
                                />
                              ) : (
                                <Text style={styles.set_input_value}>
                                  {set.weight}
                                </Text>
                              )}
                              <Text style={styles.set_input_unit}>kg</Text>
                            </View>
                            <View style={styles.set_input_group}>
                              <Text style={styles.set_input_label}>횟수</Text>
                              {is_editing ? (
                                <TextInput
                                  style={styles.set_input_edit}
                                  value={set.reps}
                                  onChangeText={(v) =>
                                    update_set(exercise.id, set.id, "reps", v)
                                  }
                                  keyboardType="numeric"
                                  selectTextOnFocus
                                />
                              ) : (
                                <Text style={styles.set_input_value}>
                                  {set.reps}
                                </Text>
                              )}
                              <Text style={styles.set_input_unit}>회</Text>
                            </View>
                          </View>

                          {/* 체크 버튼 */}
                          <TouchableOpacity
                            style={[
                              styles.check_button,
                              set.is_done && styles.check_button_done,
                            ]}
                            onPress={() => toggle_set_done(exercise.id, set.id)}
                            activeOpacity={0.7}
                          >
                            <Octicons
                              name="check"
                              size={16}
                              color={set.is_done ? colors.white : colors.border}
                            />
                          </TouchableOpacity>
                        </View>
                      ))}
                    </View>

                    {/* 휴식 타이머 */}
                    <View style={styles.timer_section}>
                      <View style={styles.timer_section_header}>
                        <Text style={styles.section_label}>휴식 타이머</Text>
                        <TouchableOpacity style={styles.small_button}>
                          <Text style={styles.small_button_text}>수정</Text>
                        </TouchableOpacity>
                      </View>
                      <TouchableOpacity
                        style={styles.timer_card}
                        onPress={() => set_is_timer_running((prev) => !prev)}
                        activeOpacity={0.8}
                      >
                        <View style={styles.timer_play_button}>
                          <Octicons
                            name={is_timer_running ? "pause" : "play"}
                            size={20}
                            color={colors.white}
                          />
                        </View>
                        <Text style={styles.timer_time}>
                          {format_time(timer)}
                        </Text>
                      </TouchableOpacity>
                    </View>
                  </View>
                )}
              </View>
            );
          })}
        </View>
      </ScrollView>

      <SafeAreaView edges={["bottom"]} style={styles.safe_bottom} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  safe_top: {
    backgroundColor: colors.background,
  },
  safe_bottom: {
    backgroundColor: colors.background,
  },
  flex: { flex: 1 },
  loading_container: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
  },
  loading_text: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.bluegray,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 24,
    paddingTop: 24,
    paddingBottom: 24,
  },
  logo: {
    fontFamily: "sacheon",
    fontSize: 20,
    color: colors.primary,
  },
  placeholder: { width: 32 },
  scroll: {
    paddingHorizontal: 24,
    paddingBottom: 32,
  },
  card: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 20,
    gap: 16,
  },
  routine_title: {
    fontFamily: "semibold",
    fontSize: 18,
    color: colors.primary,
    textAlign: "center",
  },
  goals_label: {
    fontFamily: "regular",
    fontSize: 13,
    color: colors.bluegray,
    textAlign: "center",
    marginTop: -8,
  },

  // 데이 탭
  day_tabs: {
    flexDirection: "row",
    gap: 8,
    paddingHorizontal: 4,
  },
  day_tab: {
    paddingHorizontal: 16,
    paddingVertical: 7,
    borderRadius: 20,
    backgroundColor: colors.select,
  },
  day_tab_active: {
    backgroundColor: colors.primary,
  },
  day_tab_text: {
    fontFamily: "medium",
    fontSize: 13,
    color: colors.bluegray,
  },
  day_tab_text_active: {
    color: colors.white,
  },

  // 운동 카드
  exercise_card: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    overflow: "hidden",
  },
  exercise_card_expanded: {
    borderColor: colors.primary,
  },
  exercise_header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 20,
    paddingVertical: 16,
  },
  exercise_info: { gap: 4 },
  exercise_name: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.primary,
  },
  exercise_sub: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
  },

  // 펼친 내용
  expanded_content: {
    paddingHorizontal: 16,
    paddingBottom: 16,
    gap: 16,
  },

  // 액션 버튼 (운동 변경 / TIPS)
  action_row: {
    flexDirection: "row",
    gap: 8,
  },
  action_button: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    backgroundColor: colors.select,
    borderRadius: 8,
    paddingVertical: 8,
  },
  action_text: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.primary,
  },

  // 그래픽 영상
  image_placeholder: {
    width: "100%",
    height: 110,
    borderRadius: 8,
    backgroundColor: colors.select,
    alignItems: "center",
    justifyContent: "center",
  },

  // 세트 섹션
  sets_section: {
    gap: 8,
  },
  section_label: {
    fontFamily: "medium",
    fontSize: 14,
    color: colors.primary,
  },
  sets_header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  sets_title_row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  set_count_button: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: colors.select,
    alignItems: "center",
    justifyContent: "center",
  },
  small_button: {
    backgroundColor: colors.select,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 5,
  },
  small_button_active: {
    backgroundColor: colors.primary,
  },
  small_button_text: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.primary,
  },
  small_button_text_active: {
    color: colors.white,
  },

  // 세트 행
  set_row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  set_number: {
    fontFamily: "medium",
    fontSize: 14,
    color: colors.primary,
    width: 16,
    textAlign: "center",
  },
  set_inputs: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: 16,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  set_input_group: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  set_input_label: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
  },
  set_input_value: {
    fontFamily: "medium",
    fontSize: 14,
    color: colors.primary,
    minWidth: 24,
    textAlign: "right",
  },
  set_input_edit: {
    fontFamily: "medium",
    fontSize: 14,
    color: colors.primary,
    minWidth: 30,
    padding: 0,
    textAlign: "right",
    borderBottomWidth: 1,
    borderBottomColor: colors.primary,
  },
  set_input_unit: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
  },
  check_button: {
    width: 36,
    height: 36,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.white,
  },
  check_button_done: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },

  // 타이머
  timer_section: {
    gap: 8,
  },
  timer_section_header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  timer_card: {
    flexDirection: "row",
    alignItems: "center",
    borderWidth: 1.5,
    borderColor: colors.primary,
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 14,
    gap: 16,
  },
  timer_play_button: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  timer_time: {
    fontFamily: "semibold",
    fontSize: 24,
    color: colors.primary,
  },
});
