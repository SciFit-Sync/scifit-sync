import { useState, useEffect, useRef } from "react";
import {
  ActivityIndicator,
  Animated,
  Alert,
  FlatList,
  Image,
  Linking,
  Modal,
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
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { colors } from "../../assets/colors/colors";
import { useAuthStore } from "../../stores/authStore";
import { useWorkoutSessionStore } from "../../stores/workoutSessionStore";
import BottomNavBar from "../../components/NavBar";
import {
  getRoutineDetail,
  deleteRoutine,
  renameRoutine,
  updateRoutineExercise,
  getExercisePapers,
  GOAL_LABELS,
  type RoutineExerciseItem,
  type PaperItem,
} from "../../services/routines";
import {
  searchExercises,
  type ExerciseItem as ExerciseSearchItem,
} from "../../services/exercises";
import {
  startSession,
  logSet,
  finishSession,
} from "../../services/sessions";
import WC01Chatbot from "../../components/WC01Chatbot";
import WC01DChatbotFloating from "../../components/WC01-DChatbotFloating";

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
  id: string;           // = routine_exercise_id
  exercise_id: string;  // 실제 exercises.id (세트 기록 API 용)
  name: string;
  sets: Set[];
  is_expanded: boolean;
  muscles: MuscleActivation[];
  rest_seconds: number;
  reps_min: number | null;
  reps_max: number | null;
  has_paper: boolean;
  gif_url: string | null;
}

function api_to_exercise(item: RoutineExerciseItem): Exercise {
  // weight_kg null이면 빈 문자열 → 사용자가 직접 입력
  const default_weight = item.weight_kg != null ? String(item.weight_kg) : "";
  const default_reps =
    item.reps_max != null
      ? String(item.reps_max)
      : item.reps_min != null
        ? String(item.reps_min)
        : "10";
  const sets: Set[] = Array.from({ length: item.sets }, (_, i) => ({
    id: `${item.routine_exercise_id}_${i + 1}`,
    weight: default_weight,
    reps: default_reps,
    is_done: false,
  }));
  return {
    id: item.routine_exercise_id,
    exercise_id: item.exercise_id,
    name: item.exercise_name,
    sets,
    is_expanded: false,
    muscles: (item.muscle_activation ?? []).map((m) => ({
      name: m.muscle,
      percentage: m.activation_pct ?? 0,
    })),
    rest_seconds: item.rest_seconds ?? 90,
    reps_min: item.reps_min ?? null,
    reps_max: item.reps_max ?? null,
    has_paper: item.has_paper ?? false,
    gif_url: item.gif_url ?? null,
  };
}

export default function WR04RoutineDetail() {
  const navigation = useNavigation();
  const route = useRoute();
  const { routine_id } = (route.params ?? {}) as { routine_id?: string };
  const token = useAuthStore((s) => s.accessToken) ?? "";

  const query_client = useQueryClient();
  const [selected_day_idx, set_selected_day_idx] = useState(0);
  const [exercises, set_exercises] = useState<Exercise[]>([]);
  const [editing_exercise_id, set_editing_exercise_id] = useState<
    string | null
  >(null);
  const [timer, set_timer] = useState(180);
  const [is_timer_running, set_is_timer_running] = useState(false);
  const [is_deleting, set_is_deleting] = useState(false);
  const [show_rename_modal, set_show_rename_modal] = useState(false);
  const [rename_value, set_rename_value] = useState("");
  const [is_renaming, set_is_renaming] = useState(false);
  const timer_ref = useRef<ReturnType<typeof setInterval> | null>(null);

  // 세션 관리
  const session_id_ref = useRef<string | null>(null);
  const session_promise_ref = useRef<Promise<string> | null>(null); // race condition 방지용 in-flight 캐시
  const [session_started, set_session_started] = useState(false);
  const [is_finishing, set_is_finishing] = useState(false);
  const [show_chatbot, set_show_chatbot] = useState(false);

  // 워크아웃 세션 스토어 — 화면 이탈 후 복귀 시 체크 상태 복원
  const ws_set_session = useWorkoutSessionStore((s) => s.set_session);
  const ws_toggle_set = useWorkoutSessionStore((s) => s.toggle_set);
  const ws_clear = useWorkoutSessionStore((s) => s.clear);
  const ws_routine_id = useWorkoutSessionStore((s) => s.routine_id);
  const ws_session_id = useWorkoutSessionStore((s) => s.session_id);
  const ws_checked_sets = useWorkoutSessionStore((s) => s.checked_sets);

  // AsyncStorage persist 수화 완료 여부 — 수화 전에 exercises를 초기화하면 복원이 안 됨
  const [store_ready, set_store_ready] = useState(
    () => useWorkoutSessionStore.persist.hasHydrated(),
  );
  useEffect(() => {
    if (useWorkoutSessionStore.persist.hasHydrated()) {
      set_store_ready(true);
      return;
    }
    return useWorkoutSessionStore.persist.onFinishHydration(() => {
      set_store_ready(true);
    });
  }, []);

  // 바텀시트 애니메이션 (backdrop opacity + sheet translateY)
  const MODAL_DUR = 250;
  const tips_overlay_anim = useRef(new Animated.Value(0)).current;
  const tips_sheet_anim = useRef(new Animated.Value(500)).current;
  const replace_overlay_anim = useRef(new Animated.Value(0)).current;
  const replace_sheet_anim = useRef(new Animated.Value(500)).current;

  // TIPS 모달
  const [show_tips_modal, set_show_tips_modal] = useState(false);
  const [tips_papers, set_tips_papers] = useState<PaperItem[]>([]);
  const [is_tips_loading, set_is_tips_loading] = useState(false);

  // 운동 변경 모달
  const [show_replace_modal, set_show_replace_modal] = useState(false);
  const [replacing_rex_id, set_replacing_rex_id] = useState<string | null>(
    null,
  );
  const [replace_keyword, set_replace_keyword] = useState("");
  const [replace_results, set_replace_results] = useState<ExerciseSearchItem[]>(
    [],
  );
  const [is_replace_searching, set_is_replace_searching] = useState(false);
  const [is_replacing, set_is_replacing] = useState(false);

  const { data: detail, isLoading } = useQuery({
    queryKey: ["routine", routine_id],
    queryFn: () => getRoutineDetail(token, routine_id!),
    enabled: !!token && !!routine_id,
  });

  // API 데이터 → 로컬 exercises 변환 (day 인덱스 변경 시 재초기화)
  // store_ready: AsyncStorage 수화가 완료된 뒤에만 실행해야 체크 상태가 올바르게 복원됨
  useEffect(() => {
    if (!detail || !store_ready) return;
    const day = detail.days[selected_day_idx];
    if (!day) {
      set_exercises([]);
      return;
    }
    const sorted = [...day.exercises].sort(
      (a, b) => a.order_index - b.order_index,
    );
    const base = sorted.map(api_to_exercise);

    // 이 루틴의 진행 중 세션이 스토어에 있으면 체크 상태 복원
    if (ws_routine_id === routine_id && ws_session_id) {
      session_id_ref.current = ws_session_id;
      set_session_started(true);
      const restored = base.map((ex) => ({
        ...ex,
        sets: ex.sets.map((s) => ({
          ...s,
          is_done: ws_checked_sets[s.id] ?? false,
        })),
      }));
      set_exercises(restored);
    } else {
      set_exercises(base);
    }
  }, [detail, selected_day_idx, store_ready]);

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
    set_exercises((prev) => {
      const next = prev.map((ex) =>
        ex.id === exercise_id ? { ...ex, is_expanded: !ex.is_expanded } : ex,
      );
      // 카드가 펼쳐지는 경우 해당 운동의 권장 휴식 시간으로 타이머 초기화
      const target = prev.find((ex) => ex.id === exercise_id);
      if (target && !target.is_expanded) {
        set_is_timer_running(false);
        set_timer(target.rest_seconds);
      }
      return next;
    });
  };

  const toggle_set_done = (exercise_id: string, set_id: string) => {
    // 상태 변경 전 현재 값 캡처
    const ex = exercises.find((e) => e.id === exercise_id);
    const current_set = ex?.sets.find((s) => s.id === set_id);
    const becoming_done = !current_set?.is_done;
    const set_index = ex?.sets.findIndex((s) => s.id === set_id) ?? 0;

    set_exercises((prev) =>
      prev.map((e) =>
        e.id === exercise_id
          ? {
              ...e,
              sets: e.sets.map((s) =>
                s.id === set_id ? { ...s, is_done: !s.is_done } : s,
              ),
            }
          : e,
      ),
    );

    // 스토어에 체크 상태 저장 (나갔다 돌아와도 유지)
    ws_toggle_set(set_id, becoming_done);

    const rest = ex?.rest_seconds ?? 90;
    if (becoming_done) {
      // 체크 시: 타이머 리셋 후 시작 + 세트 기록 API 호출 (fire-and-forget)
      set_timer(rest);
      set_is_timer_running(true);
      if (ex && current_set) {
        ensure_session()
          .then((sid) =>
            logSet(token, sid, {
              exercise_id: ex.exercise_id,
              routine_exercise_id: ex.id,
              set_number: set_index + 1,
              weight_kg: current_set.weight
                ? parseFloat(current_set.weight)
                : null,
              reps: parseInt(current_set.reps, 10) || 0,
              is_completed: true,
            }),
          )
          .then(() => {
            query_client.invalidateQueries({ queryKey: ["session-stats"] });
            query_client.invalidateQueries({ queryKey: ["volume-analysis"] });
            query_client.invalidateQueries({ queryKey: ["muscle-volume"] });
          })
          .catch(() => {
            // 세트 기록 실패 — 체크 UI는 유지하되 사용자에게 알림
            Alert.alert(
              "세트 기록 실패",
              "세트가 서버에 저장되지 않았습니다.\n네트워크 연결을 확인해주세요.",
            );
          });
      }
    } else {
      // 체크 해제 시: 타이머 정지 후 권장 시간으로 복원
      set_is_timer_running(false);
      set_timer(rest);
    }
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
          // exercise_id 접두사 + 타임스탬프로 운동 간 ID 충돌 방지
          id: `${exercise_id}_new_${Date.now()}`,
          weight: last_set?.weight ?? "",
          reps: last_set?.reps ?? "10",
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

  // 운동 변경 — 키워드 없으면 전체 목록, 있으면 디바운스 검색 (300ms)
  useEffect(() => {
    if (!show_replace_modal) return;

    if (!replace_keyword.trim()) {
      // 키워드 없음 → 전체 운동 목록 로드 (최대 100개)
      set_is_replace_searching(true);
      searchExercises(token, "", 100)
        .then((data) => set_replace_results(data.items))
        .catch(() => {})
        .finally(() => set_is_replace_searching(false));
      return;
    }

    const timer = setTimeout(async () => {
      set_is_replace_searching(true);
      try {
        const data = await searchExercises(token, replace_keyword.trim());
        set_replace_results(data.items);
      } catch {
        // 검색 오류는 조용히 무시
      } finally {
        set_is_replace_searching(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [replace_keyword, show_replace_modal, token]);

  // ── 바텀시트 애니메이션 헬퍼 ────────────────────────────────────────────────
  const open_tips_modal = () => {
    tips_overlay_anim.setValue(0);
    tips_sheet_anim.setValue(500);
    set_show_tips_modal(true);
    Animated.parallel([
      Animated.timing(tips_overlay_anim, {
        toValue: 1,
        duration: MODAL_DUR,
        useNativeDriver: true,
      }),
      Animated.timing(tips_sheet_anim, {
        toValue: 0,
        duration: MODAL_DUR,
        useNativeDriver: true,
      }),
    ]).start();
  };

  const close_tips_modal = () => {
    Animated.parallel([
      Animated.timing(tips_overlay_anim, {
        toValue: 0,
        duration: MODAL_DUR,
        useNativeDriver: true,
      }),
      Animated.timing(tips_sheet_anim, {
        toValue: 500,
        duration: MODAL_DUR,
        useNativeDriver: true,
      }),
    ]).start(() => set_show_tips_modal(false));
  };

  const open_replace_modal_anim = () => {
    replace_overlay_anim.setValue(0);
    replace_sheet_anim.setValue(500);
    set_show_replace_modal(true);
    Animated.parallel([
      Animated.timing(replace_overlay_anim, {
        toValue: 1,
        duration: MODAL_DUR,
        useNativeDriver: true,
      }),
      Animated.timing(replace_sheet_anim, {
        toValue: 0,
        duration: MODAL_DUR,
        useNativeDriver: true,
      }),
    ]).start();
  };

  const close_replace_modal = () => {
    Animated.parallel([
      Animated.timing(replace_overlay_anim, {
        toValue: 0,
        duration: MODAL_DUR,
        useNativeDriver: true,
      }),
      Animated.timing(replace_sheet_anim, {
        toValue: 500,
        duration: MODAL_DUR,
        useNativeDriver: true,
      }),
    ]).start(() => set_show_replace_modal(false));
  };

  const handle_tips_press = async (rex_id: string) => {
    if (!routine_id) return;
    set_tips_papers([]);
    set_is_tips_loading(true);
    open_tips_modal();
    try {
      const data = await getExercisePapers(token, routine_id, rex_id);
      set_tips_papers(data.items);
    } catch {
      // 조용히 빈 상태로
    } finally {
      set_is_tips_loading(false);
    }
  };

  const handle_replace_press = (rex_id: string) => {
    set_replacing_rex_id(rex_id);
    set_replace_keyword("");
    set_replace_results([]);
    open_replace_modal_anim();
  };

  const handle_replace_confirm = async (new_exercise_id: string) => {
    if (!replacing_rex_id || !routine_id) return;
    try {
      set_is_replacing(true);
      await updateRoutineExercise(
        token,
        routine_id,
        replacing_rex_id,
        new_exercise_id,
      );
      query_client.invalidateQueries({ queryKey: ["routine", routine_id] });
      close_replace_modal();
      set_replacing_rex_id(null);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "운동 변경에 실패했습니다.";
      Alert.alert("변경 실패", msg);
    } finally {
      set_is_replacing(false);
    }
  };

  const goals_label = detail?.fitness_goals
    ? detail.fitness_goals.map((g) => GOAL_LABELS[g] ?? g).join(" · ")
    : null;

  const handle_delete_confirm = () => {
    Alert.alert(
      "루틴 삭제",
      "이 루틴을 삭제할까요?\n삭제 후 복구가 불가능합니다.",
      [
        { text: "취소", style: "cancel" },
        {
          text: "삭제",
          style: "destructive",
          onPress: async () => {
            try {
              set_is_deleting(true);
              await deleteRoutine(token, routine_id!);
              query_client.invalidateQueries({ queryKey: ["routines"] });
              navigation.goBack();
            } catch (e: unknown) {
              set_is_deleting(false);
              const msg =
                e instanceof Error ? e.message : "삭제에 실패했습니다.";
              Alert.alert("삭제 실패", msg);
            }
          },
        },
      ],
    );
  };

  const handle_more_press = () => {
    Alert.alert("루틴 설정", undefined, [
      {
        text: "이름 수정",
        onPress: () => {
          set_rename_value(detail?.name ?? "");
          set_show_rename_modal(true);
        },
      },
      {
        text: "삭제",
        style: "destructive",
        onPress: handle_delete_confirm,
      },
      { text: "취소", style: "cancel" },
    ]);
  };

  const handle_rename_confirm = async () => {
    const trimmed = rename_value.trim();
    if (!trimmed) {
      Alert.alert("이름 오류", "루틴 이름을 입력해주세요.");
      return;
    }
    try {
      set_is_renaming(true);
      await renameRoutine(token, routine_id!, trimmed);
      query_client.invalidateQueries({ queryKey: ["routine", routine_id] });
      query_client.invalidateQueries({ queryKey: ["routines"] });
      set_show_rename_modal(false);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "이름 수정에 실패했습니다.";
      Alert.alert("수정 실패", msg);
    } finally {
      set_is_renaming(false);
    }
  };

  // ── 세션 헬퍼 ───────────────────────────────────────────────────────────────

  /** 세션이 없으면 새로 시작하고 session_id를 반환.
   *  in-flight Promise를 캐싱해 빠른 연속 탭 시 세션 중복 생성을 방지한다. */
  const ensure_session = (): Promise<string> => {
    if (session_id_ref.current) return Promise.resolve(session_id_ref.current);
    if (session_promise_ref.current) return session_promise_ref.current;
    const day = detail?.days[selected_day_idx];
    const p = startSession(token, {
      routine_id: routine_id ?? undefined,
      routine_day_id: day?.routine_day_id ?? undefined,
    })
      .then((data) => {
        session_id_ref.current = data.session_id;
        session_promise_ref.current = null;
        set_session_started(true);
        if (routine_id) ws_set_session(routine_id, data.session_id);
        return data.session_id;
      })
      .catch((e) => {
        session_promise_ref.current = null;
        throw e;
      });
    session_promise_ref.current = p;
    return p;
  };

  /** 타이머 수정 — 프리셋 Alert */
  const handle_timer_edit = (rex_id: string) => {
    const presets: { label: string; seconds: number }[] = [
      { label: "30초", seconds: 30 },
      { label: "1분", seconds: 60 },
      { label: "1분 30초", seconds: 90 },
      { label: "2분", seconds: 120 },
      { label: "3분", seconds: 180 },
    ];
    Alert.alert(
      "휴식 시간 설정",
      undefined,
      [
        ...presets.map((p) => ({
          text: p.label,
          onPress: () => {
            set_exercises((prev) =>
              prev.map((ex) =>
                ex.id === rex_id ? { ...ex, rest_seconds: p.seconds } : ex,
              ),
            );
            set_timer(p.seconds);
            set_is_timer_running(false);
          },
        })),
        { text: "취소", style: "cancel" as const },
      ],
    );
  };

  /** 운동 완료 처리 */
  const handle_finish = async () => {
    if (!session_id_ref.current || is_finishing) return;
    try {
      set_is_finishing(true);
      await finishSession(token, session_id_ref.current);
      ws_clear(); // 스토어 초기화 — 완료 후 재진입 시 깨끗하게 시작
      query_client.invalidateQueries({ queryKey: ["sessions"] });
      query_client.invalidateQueries({ queryKey: ["session-stats"] });
      query_client.invalidateQueries({ queryKey: ["volume-analysis"] });
      query_client.invalidateQueries({ queryKey: ["muscle-volume"] });
      navigation.goBack();
    } catch (e: unknown) {
      set_is_finishing(false);
      const msg =
        e instanceof Error ? e.message : "운동 완료 처리에 실패했습니다.";
      Alert.alert("오류", msg);
    }
  };

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
          {/* 루틴 제목 + 더보기(삭제) */}
          <View style={styles.title_row}>
            <View style={styles.title_side} />
            <Text style={styles.routine_title}>
              {detail?.name ?? "루틴 상세"}
            </Text>
            <TouchableOpacity
              onPress={handle_more_press}
              disabled={is_deleting || is_renaming}
              style={styles.title_side}
              activeOpacity={0.7}
            >
              <Octicons
                name="kebab-horizontal"
                size={16}
                color={colors.primary}
              />
            </TouchableOpacity>
          </View>
          {goals_label && <Text style={styles.goals_label}>{goals_label}</Text>}

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
                        onPress={() => handle_replace_press(exercise.id)}
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
                        onPress={() => handle_tips_press(exercise.id)}
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
                    {exercise.gif_url ? (
                      <Image
                        source={{ uri: exercise.gif_url }}
                        style={styles.exercise_gif}
                        resizeMode="contain"
                      />
                    ) : (
                      <View style={styles.image_placeholder}>
                        <Octicons
                          name="play"
                          size={32}
                          color={colors.bluegray}
                        />
                      </View>
                    )}

                    {/* 근육 활성화 */}
                    <View style={styles.muscle_section}>
                      <Text style={styles.section_label}>근육 활성화</Text>
                      {exercise.muscles.length > 0 ? (
                        <View style={styles.muscle_row}>
                          {exercise.muscles.map((muscle) => (
                            <View key={muscle.name} style={styles.muscle_card}>
                              <Text style={styles.muscle_percent}>
                                {muscle.percentage}%
                              </Text>
                              <Text style={styles.muscle_name}>
                                {muscle.name}
                              </Text>
                            </View>
                          ))}
                        </View>
                      ) : (
                        <View style={styles.muscle_empty}>
                          <Text style={styles.muscle_empty_text}>
                            근육 활성화 데이터 준비 중
                          </Text>
                        </View>
                      )}
                    </View>

                    {/* 세트 섹션 */}
                    <View style={styles.sets_section}>
                      {/* 권장 범위 힌트 */}
                      {(exercise.reps_min != null || exercise.reps_max != null) && (
                        <Text style={styles.recommended_hint}>
                          권장{" "}
                          {exercise.reps_min != null && exercise.reps_max != null
                            ? `${exercise.reps_min}~${exercise.reps_max}회`
                            : exercise.reps_max != null
                              ? `${exercise.reps_max}회`
                              : `${exercise.reps_min}회`}
                        </Text>
                      )}

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
                                <Text style={[styles.set_input_value, !set.weight && styles.set_input_placeholder]}>
                                  {set.weight || "-"}
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
                        <View>
                          <Text style={styles.section_label}>휴식 타이머</Text>
                          <Text style={styles.recommended_hint}>
                            권장 {exercise.rest_seconds}초
                          </Text>
                        </View>
                        <TouchableOpacity
                          style={styles.small_button}
                          onPress={() => handle_timer_edit(exercise.id)}
                          activeOpacity={0.8}
                        >
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

        {/* 운동 완료 버튼 — 첫 세트 체크 후 표시 */}
        {session_started && (
          <TouchableOpacity
            style={[styles.finish_btn, is_finishing && { opacity: 0.6 }]}
            onPress={handle_finish}
            disabled={is_finishing}
            activeOpacity={0.8}
          >
            {is_finishing ? (
              <ActivityIndicator size="small" color={colors.white} />
            ) : (
              <Text style={styles.finish_btn_text}>운동 완료</Text>
            )}
          </TouchableOpacity>
        )}
      </ScrollView>

      {/* 이름 수정 모달 */}
      <Modal
        visible={show_rename_modal}
        transparent
        animationType="fade"
        onRequestClose={() => set_show_rename_modal(false)}
      >
        <TouchableOpacity
          style={styles.modal_overlay}
          activeOpacity={1}
          onPress={() => set_show_rename_modal(false)}
        >
          <TouchableOpacity style={styles.modal_box} activeOpacity={1}>
            <Text style={styles.modal_title}>루틴 이름 수정</Text>
            <TextInput
              style={styles.modal_input}
              value={rename_value}
              onChangeText={set_rename_value}
              placeholder="루틴 이름을 입력하세요"
              placeholderTextColor={colors.bluegray}
              maxLength={50}
              autoFocus
            />
            <View style={styles.modal_actions}>
              <TouchableOpacity
                style={styles.modal_btn_cancel}
                onPress={() => set_show_rename_modal(false)}
                activeOpacity={0.8}
              >
                <Text style={styles.modal_btn_cancel_text}>취소</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[
                  styles.modal_btn_confirm,
                  is_renaming && { opacity: 0.6 },
                ]}
                onPress={handle_rename_confirm}
                disabled={is_renaming}
                activeOpacity={0.8}
              >
                {is_renaming ? (
                  <ActivityIndicator size="small" color={colors.white} />
                ) : (
                  <Text style={styles.modal_btn_confirm_text}>확인</Text>
                )}
              </TouchableOpacity>
            </View>
          </TouchableOpacity>
        </TouchableOpacity>
      </Modal>

      {/* TIPS 모달 (바텀시트) */}
      <Modal
        visible={show_tips_modal}
        transparent
        animationType="none"
        onRequestClose={close_tips_modal}
      >
        {/* 서서히 사라지는 dimmed backdrop */}
        <Animated.View
          style={[styles.modal_backdrop, { opacity: tips_overlay_anim }]}
          pointerEvents="none"
        />
        <View style={styles.tips_overlay}>
          {/* 빈 영역 탭 → 닫기 */}
          <TouchableOpacity
            style={{ flex: 1 }}
            activeOpacity={1}
            onPress={close_tips_modal}
          />
          <Animated.View
            style={[
              styles.tips_sheet,
              { transform: [{ translateY: tips_sheet_anim }] },
            ]}
          >
            {/* 핸들 */}
            <View style={styles.replace_handle} />

            {/* 헤더 */}
            <View style={styles.tips_header}>
              <View style={styles.tips_header_side} />
              <Text style={styles.tips_title}>TIPS</Text>
              <TouchableOpacity
                style={styles.tips_header_side}
                onPress={close_tips_modal}
              >
                <Octicons name="x" size={20} color={colors.primary} />
              </TouchableOpacity>
            </View>

            {/* 내용 */}
            {is_tips_loading ? (
              <View style={styles.tips_center}>
                <ActivityIndicator color={colors.primary} />
              </View>
            ) : tips_papers.length === 0 ? (
              <View style={styles.tips_center}>
                <Octicons name="book" size={28} color={colors.border} />
                <Text style={styles.tips_empty_text}>
                  논문 근거 데이터가 없습니다
                </Text>
              </View>
            ) : (
              <ScrollView
                style={styles.tips_scroll}
                showsVerticalScrollIndicator={false}
              >
                {tips_papers.map((paper, idx) => (
                  <View key={paper.paper_id}>
                    {/* 한국어 근거 요약 */}
                    {paper.relevance_summary && (
                      <Text style={styles.tips_summary}>
                        {paper.relevance_summary}
                      </Text>
                    )}

                    {/* 논문 카드 */}
                    <View
                      style={[
                        styles.tips_paper_card,
                        idx < tips_papers.length - 1 && { marginBottom: 16 },
                      ]}
                    >
                      <Text style={styles.tips_paper_title}>{paper.title}</Text>
                      <Text style={styles.tips_paper_meta}>
                        {[paper.authors, paper.year]
                          .filter(Boolean)
                          .join(" · ")}
                      </Text>
                      {paper.doi_url && (
                        <TouchableOpacity
                          style={styles.tips_link_btn}
                          onPress={() => Linking.openURL(paper.doi_url!)}
                          activeOpacity={0.8}
                        >
                          <Text style={styles.tips_link_text}>논문 링크</Text>
                          <Octicons
                            name="arrow-right"
                            size={13}
                            color={colors.primary}
                          />
                        </TouchableOpacity>
                      )}
                    </View>
                  </View>
                ))}
              </ScrollView>
            )}

            {/* 확인 버튼 */}
            <TouchableOpacity
              style={styles.tips_confirm_btn}
              onPress={close_tips_modal}
              activeOpacity={0.8}
            >
              <Text style={styles.tips_confirm_text}>확인</Text>
            </TouchableOpacity>
          </Animated.View>
        </View>
      </Modal>

      {/* 운동 변경 모달 (바텀시트) */}
      <Modal
        visible={show_replace_modal}
        transparent
        animationType="none"
        onRequestClose={() => {
          if (!is_replacing) close_replace_modal();
        }}
      >
        {/* 서서히 사라지는 dimmed backdrop */}
        <Animated.View
          style={[styles.modal_backdrop, { opacity: replace_overlay_anim }]}
          pointerEvents="none"
        />
        <View style={styles.replace_overlay}>
          {/* 빈 영역 탭 → 닫기 */}
          <TouchableOpacity
            style={{ flex: 1 }}
            activeOpacity={1}
            onPress={() => {
              if (!is_replacing) close_replace_modal();
            }}
          />
          <Animated.View
            style={[
              styles.replace_sheet,
              { transform: [{ translateY: replace_sheet_anim }] },
            ]}
          >
            {/* 핸들 바 */}
            <View style={styles.replace_handle} />

            {/* 헤더 */}
            <View style={styles.replace_header}>
              <Text style={styles.replace_title}>운동 변경</Text>
              <TouchableOpacity
                onPress={() => {
                  if (!is_replacing) close_replace_modal();
                }}
                disabled={is_replacing}
              >
                <Octicons name="x" size={20} color={colors.primary} />
              </TouchableOpacity>
            </View>

            {/* 검색 인풋 */}
            <View style={styles.replace_search_row}>
              <Octicons name="search" size={20} color={colors.border} />
              <TextInput
                style={styles.replace_search_input}
                value={replace_keyword}
                onChangeText={set_replace_keyword}
                placeholder="운동 이름으로 검색"
                placeholderTextColor={colors.bluegray}
                autoFocus
                returnKeyType="search"
                editable={!is_replacing}
              />
              {is_replace_searching && (
                <ActivityIndicator size="small" color={colors.bluegray} />
              )}
            </View>

            {/* 결과 목록 */}
            {is_replace_searching && replace_results.length === 0 ? (
              <View style={styles.replace_empty}>
                <ActivityIndicator color={colors.primary} />
              </View>
            ) : !is_replace_searching && replace_keyword.trim() !== "" && replace_results.length === 0 ? (
              <View style={styles.replace_empty}>
                <Octicons name="x-circle" size={28} color={colors.border} />
                <Text style={styles.replace_empty_text}>
                  검색 결과가 없습니다
                </Text>
              </View>
            ) : (
              <FlatList
                data={replace_results}
                keyExtractor={(item) => item.exercise_id}
                style={styles.replace_list}
                contentContainerStyle={styles.replace_list_content}
                keyboardShouldPersistTaps="handled"
                renderItem={({ item }) => (
                  <TouchableOpacity
                    style={styles.replace_item}
                    activeOpacity={0.7}
                    disabled={is_replacing}
                    onPress={() => handle_replace_confirm(item.exercise_id)}
                  >
                    <View style={styles.replace_item_info}>
                      <Text style={styles.replace_item_name}>{item.name}</Text>
                      {item.primary_muscle_groups.length > 0 && (
                        <Text style={styles.replace_item_muscles}>
                          {item.primary_muscle_groups.join(" · ")}
                        </Text>
                      )}
                    </View>
                    {is_replacing && replacing_rex_id ? (
                      <ActivityIndicator size="small" color={colors.primary} />
                    ) : (
                      <Octicons
                        name="arrow-right"
                        size={16}
                        color={colors.bluegray}
                      />
                    )}
                  </TouchableOpacity>
                )}
                ItemSeparatorComponent={() => (
                  <View style={styles.replace_separator} />
                )}
              />
            )}
          </Animated.View>
        </View>
      </Modal>

      {/* 챗봇 FAB — WM01Main과 동일한 컴포넌트 */}
      <WC01DChatbotFloating onPress={() => set_show_chatbot(true)} />
      {show_chatbot && <WC01Chatbot onClose={() => set_show_chatbot(false)} />}

      {/* 하단 네브바 */}
      <SafeAreaView edges={["bottom"]} style={styles.safe_bottom}>
        <BottomNavBar />
      </SafeAreaView>
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
    backgroundColor: colors.white,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: -2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 10,
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
  more_button: {
    width: 32,
    height: 32,
    alignItems: "center",
    justifyContent: "center",
  },
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
  title_row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  title_side: {
    width: 24,
    alignItems: "flex-end",
  },
  routine_title: {
    flex: 1,
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
  exercise_gif: {
    width: "100%",
    height: 110,
    borderRadius: 8,
    backgroundColor: colors.select,
  },
  image_placeholder: {
    width: "100%",
    height: 110,
    borderRadius: 8,
    backgroundColor: colors.select,
    alignItems: "center",
    justifyContent: "center",
  },

  // 근육 활성화
  muscle_section: {
    gap: 8,
  },
  muscle_row: {
    flexDirection: "row",
    gap: 8,
  },
  muscle_card: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingVertical: 12,
    alignItems: "center",
    gap: 4,
  },
  muscle_percent: {
    fontFamily: "semibold",
    fontSize: 18,
    color: colors.primary,
  },
  muscle_name: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
  },
  muscle_empty: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingVertical: 14,
    alignItems: "center",
    borderStyle: "dashed",
  },
  muscle_empty_text: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
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

  // 권장량 힌트
  recommended_hint: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
    marginBottom: 4,
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
  set_input_placeholder: {
    color: colors.border,
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

  // 이름 수정 모달
  modal_overlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.45)",
    alignItems: "center",
    justifyContent: "center",
  },
  modal_box: {
    width: "80%",
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 24,
    gap: 16,
  },
  modal_title: {
    fontFamily: "semibold",
    fontSize: 16,
    color: colors.primary,
    textAlign: "center",
  },
  modal_input: {
    fontFamily: "regular",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 10,
    fontSize: 14,
    color: colors.primary,
  },
  modal_actions: {
    flexDirection: "row",
    gap: 8,
  },
  modal_btn_cancel: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 8,
    backgroundColor: colors.select,
    alignItems: "center",
    justifyContent: "center",
  },
  modal_btn_cancel_text: {
    fontFamily: "medium",
    fontSize: 14,
    color: colors.primary,
  },
  modal_btn_confirm: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 8,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  modal_btn_confirm_text: {
    fontFamily: "medium",
    fontSize: 14,
    color: colors.white,
  },

  // 모달 공통 dimmed backdrop (Animated.View에 opacity 적용)
  modal_backdrop: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "rgba(0,0,0,0.45)",
  },

  // TIPS 바텀시트
  tips_overlay: {
    flex: 1,
    justifyContent: "flex-end",
  },
  tips_sheet: {
    backgroundColor: colors.white,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 24,
    paddingBottom: 32,
    maxHeight: "80%",
  },
  tips_header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 16,
  },
  tips_header_side: {
    width: 24,
    alignItems: "flex-end",
  },
  tips_title: {
    fontFamily: "semibold",
    fontSize: 18,
    color: colors.primary,
  },
  tips_center: {
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 40,
    gap: 12,
  },
  tips_empty_text: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.bluegray,
  },
  tips_scroll: {
    flexGrow: 0,
    marginBottom: 16,
  },
  tips_summary: {
    fontFamily: "regular",
    fontSize: 15,
    color: colors.primary,
    lineHeight: 24,
    marginBottom: 16,
  },
  tips_paper_card: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 16,
    gap: 6,
    marginBottom: 8,
  },
  tips_paper_title: {
    fontFamily: "semibold",
    fontSize: 14,
    color: colors.primary,
    lineHeight: 20,
  },
  tips_paper_meta: {
    fontFamily: "regular",
    fontSize: 13,
    color: colors.bluegray,
  },
  tips_link_btn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    alignSelf: "flex-start",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 20,
    paddingHorizontal: 12,
    paddingVertical: 6,
    marginTop: 4,
  },
  tips_link_text: {
    fontFamily: "regular",
    fontSize: 13,
    color: colors.primary,
  },
  tips_confirm_btn: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 14,
    alignItems: "center",
  },
  tips_confirm_text: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.white,
  },
  action_button_disabled: {
    opacity: 0.4,
  },
  action_text_disabled: {
    color: colors.bluegray,
  },

  // 운동 변경 바텀시트
  replace_overlay: {
    flex: 1,
    justifyContent: "flex-end",
  },
  replace_sheet: {
    backgroundColor: colors.white,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 20,
    paddingBottom: 32,
    maxHeight: "90%",
  },
  replace_handle: {
    width: 36,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.border,
    alignSelf: "center",
    marginTop: 12,
    marginBottom: 4,
  },
  replace_header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 16,
  },
  replace_title: {
    fontFamily: "semibold",
    fontSize: 16,
    color: colors.primary,
  },
  replace_search_row: {
    flexDirection: "row",
    alignItems: "center",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 10,
    height: 44,
    gap: 10,
    marginBottom: 12,
  },
  replace_search_input: {
    flex: 1,
    fontFamily: "regular",
    fontSize: 16,
    color: colors.primary,
  },
  replace_empty: {
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 40,
    gap: 10,
  },
  replace_empty_text: {
    fontFamily: "regular",
    fontSize: 13,
    color: colors.bluegray,
  },
  replace_list: {
    flexGrow: 0,
  },
  replace_list_content: {
    paddingBottom: 8,
  },
  replace_item: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 14,
    paddingHorizontal: 4,
  },
  replace_item_info: {
    flex: 1,
    gap: 3,
    marginRight: 12,
  },
  replace_item_name: {
    fontFamily: "medium",
    fontSize: 15,
    color: colors.primary,
  },
  replace_item_muscles: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
  },
  replace_separator: {
    height: 1,
    backgroundColor: colors.border,
    marginHorizontal: 4,
  },

  // 운동 완료 버튼
  finish_btn: {
    marginTop: 16,
    backgroundColor: colors.primary,
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: "center",
    justifyContent: "center",
  },
  finish_btn_text: {
    fontFamily: "semibold",
    fontSize: 16,
    color: colors.white,
  },

});

