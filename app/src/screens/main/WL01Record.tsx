import { useState, useCallback } from "react";
import {
  ActivityIndicator,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Octicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useFocusEffect, useNavigation } from "@react-navigation/native";
import { colors } from "../../assets/colors/colors";
import BottomNavBar from "../../components/NavBar";
import { useAuthStore } from "../../stores/authStore";
import { getSessions, getSessionStats } from "../../services/sessions";

const GOAL_LABELS: Record<string, string> = {
  hypertrophy: "근비대",
  strength: "근력 향상",
  endurance: "근지구력",
  rehabilitation: "재활",
  weight_loss: "다이어트",
};

function fmt_duration(minutes: number | null): string {
  if (minutes == null) return "-";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

const DAYS = ["월", "화", "수", "목", "금", "토", "일"];

function get_calendar_weeks(year: number, month: number) {
  const first_day = new Date(year, month - 1, 1).getDay();
  const last_date = new Date(year, month, 0).getDate();
  const start_offset = first_day === 0 ? 6 : first_day - 1;
  const days: (number | null)[] = [];
  for (let i = 0; i < start_offset; i++) days.push(null);
  for (let i = 1; i <= last_date; i++) days.push(i);
  while (days.length % 7 !== 0) days.push(null);
  const weeks: (number | null)[][] = [];
  for (let i = 0; i < days.length; i += 7) weeks.push(days.slice(i, i + 7));
  return weeks;
}

function to_date_key(year: number, month: number, day: number) {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

export default function WL01Record() {
  const navigation = useNavigation();
  const token = useAuthStore((s) => s.accessToken) ?? "";
  const today = new Date();
  const [year, set_year] = useState(today.getFullYear());
  const [month, set_month] = useState(today.getMonth() + 1);
  const [selected_day, set_selected_day] = useState<number | null>(today.getDate());
  const query_client = useQueryClient();

  // 탭 포커스 시 세션 데이터 갱신 — 탭 이동은 컴포넌트를 재마운트하지 않으므로
  // useFocusEffect 없이는 루틴 상세에서 체크한 세트가 분석 탭에 반영되지 않음
  useFocusEffect(
    useCallback(() => {
      query_client.invalidateQueries({ queryKey: ["sessions"] });
    }, [query_client]),
  );

  const { data: calendarData, isLoading: calendarLoading } = useQuery({
    queryKey: ["sessions", "calendar", token, year, month],
    queryFn: () => getSessions(token, year, month),
    enabled: !!token,
  });

  const { data: statsData } = useQuery({
    queryKey: ["sessions", "stats", token],
    queryFn: () => getSessionStats(token),
    enabled: !!token,
  });

  const records = calendarData?.records ?? [];

  const weeks = get_calendar_weeks(year, month);

  const handle_prev = () => {
    set_selected_day(null);
    if (month === 1) { set_year((y) => y - 1); set_month(12); }
    else set_month((m) => m - 1);
  };

  const handle_next = () => {
    set_selected_day(null);
    if (month === 12) { set_year((y) => y + 1); set_month(1); }
    else set_month((m) => m + 1);
  };

  const handle_day_press = (day: number | null) => {
    if (day === null) return;
    set_selected_day((prev) => (prev === day ? null : day));
  };

  const is_today = (day: number | null) =>
    day !== null && day === today.getDate() &&
    month === today.getMonth() + 1 && year === today.getFullYear();

  const is_selected = (day: number | null) => day !== null && day === selected_day;

  const has_data = (day: number | null) =>
    day !== null && records.some((r) => r.date === to_date_key(year, month, day));

  const day_records = selected_day !== null
    ? records.filter((r) => r.date === to_date_key(year, month, selected_day))
    : records;

  const section_title = selected_day !== null
    ? `${month}월 ${selected_day}일 운동`
    : "최근 한 운동";

  const total_duration = day_records.reduce((sum, r) => sum + (r.duration_minutes ?? 0), 0);

  // 하루 선택 시: 해당 날짜의 세션들을 합산
  const day_total_volume = day_records.reduce((s, r) => s + (r.total_weight_kg ?? 0), 0);
  const day_total_sets = day_records.reduce((s, r) => s + (r.total_sets ?? 0), 0);

  // 통계 표시값 (날짜 선택·미선택 모두 총 중량 / 총 세트 / 총 시간 3개 표시)
  const top_stats = selected_day !== null
    ? [
        { value: `${parseFloat(day_total_volume.toFixed(2))}kg`, label: "총 중량" },
        { value: `${day_total_sets}세트`, label: "총 세트" },
        { value: fmt_duration(total_duration || null), label: "총 시간" },
      ]
    : [
        { value: `${statsData?.total_calories_kcal ?? 0} kcal`, label: "칼로리" },
        { value: `${statsData?.total_sets ?? 0}세트`, label: "총 세트" },
        { value: fmt_duration(statsData?.total_duration_minutes ?? null), label: "운동 시간" },
      ];

  const streak = statsData?.streak_days ?? 0;

  return (
    <View style={styles.container}>
      <SafeAreaView edges={["top"]} style={styles.safe_top} />

      {/* 헤더 */}
      <View style={styles.header}>
        <Text style={styles.logo}>SciFit-Sync</Text>
      </View>

      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
        style={styles.flex}
      >
        {/* ─── 달력 카드 ─── */}
        <View style={styles.calendar_card}>
          {/* 월 이동 */}
          <View style={styles.month_row}>
            <TouchableOpacity onPress={handle_prev} activeOpacity={0.7}>
              <Octicons name="chevron-left" size={16} color={colors.primary} />
            </TouchableOpacity>
            <Text style={styles.month_title}>
              {year}년 {month}월
            </Text>
            <TouchableOpacity onPress={handle_next} activeOpacity={0.7}>
              <Octicons name="chevron-right" size={16} color={colors.primary} />
            </TouchableOpacity>
          </View>

          {/* 요일 헤더 */}
          <View style={styles.week_row}>
            {DAYS.map((d) => (
              <Text key={d} style={styles.day_label}>
                {d}
              </Text>
            ))}
          </View>

          {/* 날짜 그리드 */}
          {weeks.map((week, wi) => (
            <View key={wi} style={styles.week_row}>
              {week.map((day, di) => (
                <TouchableOpacity
                  key={di}
                  style={styles.day_cell}
                  onPress={() => handle_day_press(day)}
                  activeOpacity={day !== null ? 0.7 : 1}
                >
                  {day !== null && (
                    <View
                      style={[
                        styles.day_inner,
                        is_today(day) &&
                          !is_selected(day) &&
                          styles.day_today_bg,
                        is_selected(day) && styles.day_selected_bg,
                      ]}
                    >
                      <Text
                        style={[
                          styles.day_text,
                          is_today(day) &&
                            !is_selected(day) &&
                            styles.day_today_text,
                          is_selected(day) && styles.day_selected_text,
                        ]}
                      >
                        {day}
                      </Text>
                      {has_data(day) && !is_selected(day) && (
                        <View style={styles.dot_row}>
                          <View style={[styles.dot, { backgroundColor: colors.primary }]} />
                        </View>
                      )}
                    </View>
                  )}
                </TouchableOpacity>
              ))}
            </View>
          ))}
        </View>

        {/* ─── 통계 ─── */}
        <View style={styles.stats_row}>
          {top_stats.map((s) => (
            <View key={s.label} style={styles.stat_card}>
              <Text style={styles.stat_value}>{s.value}</Text>
              <Text style={styles.stat_label}>{s.label}</Text>
            </View>
          ))}
        </View>

        {/* 연속 운동 배지 */}
        {streak > 0 && (
          <View style={styles.badge_small}>
            <Octicons name="flame" size={16} color={colors.white} />
            <Text style={styles.badge_text}>{streak}일 연속 운동</Text>
          </View>
        )}

        {/* ─── 운동 목록 ─── */}
        <View style={styles.section}>
          <Text style={styles.section_title}>{section_title}</Text>
          {calendarLoading ? (
            <ActivityIndicator color={colors.primary} style={{ marginTop: 20 }} />
          ) : day_records.length > 0 ? (
            day_records.map((item) => (
              <TouchableOpacity
                key={item.session_id}
                style={styles.routine_item}
                activeOpacity={0.8}
                onPress={() => {
                  if (item.routine_id) {
                    (navigation as any).navigate("WR04RoutineDetail", {
                      routine_id: item.routine_id,
                    });
                  }
                }}
              >
                <View style={styles.routine_info}>
                  <Text style={styles.routine_name}>
                    {item.routine_name ?? "자유 운동"}
                  </Text>
                  {item.gym_name != null && (
                    <Text style={styles.routine_sub}>{item.gym_name}</Text>
                  )}
                  {item.fitness_goals.length > 0 && (
                    <Text style={styles.routine_sub}>
                      {item.fitness_goals.map((g) => GOAL_LABELS[g] ?? g).join(" · ")}
                    </Text>
                  )}
                  <Text style={styles.routine_sub}>
                    {item.date.replace(/-/g, ".")}
                  </Text>
                </View>
                <Octicons
                  name="triangle-right"
                  size={24}
                  color={item.routine_id ? colors.primary : colors.border}
                />
              </TouchableOpacity>
            ))
          ) : (
            <View style={styles.empty_box}>
              <Text style={styles.empty_text}>운동 기록이 없어요</Text>
            </View>
          )}
        </View>

        {streak > 0 && (
          <View style={styles.badge_wide}>
            <Octicons name="light-bulb" size={16} color={colors.white} />
            <Text style={styles.badge_text}>
              {streak}일째, 당신은 이미 어제보다 강해졌어요
            </Text>
          </View>
        )}
      </ScrollView>

      {/* 하단 네브바 */}
      <SafeAreaView edges={["bottom"]} style={styles.safe_bottom}>
        <BottomNavBar />
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  safe_top: { backgroundColor: colors.background },
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
  header: {
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 24,
    paddingTop: 29,
    paddingBottom: 24,
  },
  logo: { fontFamily: "sacheon", fontSize: 20, color: colors.primary },
  placeholder: { width: 32 },
  scroll: { paddingHorizontal: 24, paddingBottom: 32, gap: 8 },

  // 달력
  calendar_card: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 8,
    overflow: "hidden",
  },
  month_row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 24,
    height: 50,
  },
  month_title: {
    fontFamily: "medium",
    fontSize: 18,
    color: colors.primary,
    textAlign: "center",
    minWidth: 120,
  },
  week_row: { flexDirection: "row" },
  day_label: {
    flex: 1,
    textAlign: "center",
    fontFamily: "regular",
    fontSize: 16,
    color: colors.bluegray,
    height: 35,
    lineHeight: 35,
  },
  day_cell: {
    flex: 1,
    height: 55,
    alignItems: "center",
    justifyContent: "flex-start",
    paddingTop: 10,
  },
  day_inner: {
    width: 30,
    height: 30,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 15,
  },
  day_today_bg: { backgroundColor: colors.button }, // 연한 파란색
  day_selected_bg: { backgroundColor: colors.primary }, // primary (진한)
  day_text: { fontFamily: "regular", fontSize: 16, color: colors.primary },
  day_today_text: { color: colors.primary, fontFamily: "medium" },
  day_selected_text: { color: colors.white, fontFamily: "medium" },
  dot_row: {
    flexDirection: "row",
    gap: 2,
    marginTop: 2,
    justifyContent: "center",
  },
  dot: {
    width: 4,
    height: 4,
    borderRadius: 2,
  },

  // 통계
  stats_row: { flexDirection: "row", gap: 8 },
  stat_card: {
    flex: 1,
    backgroundColor: colors.white,
    borderRadius: 8,
    height: 60,
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  stat_value: { fontFamily: "medium", fontSize: 16, color: colors.primary },
  stat_label: { fontFamily: "regular", fontSize: 12, color: colors.bluegray },

  // 배지
  badge_small: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: colors.primary,
    borderRadius: 8,
    height: 39,
    paddingHorizontal: 16,
    alignSelf: "flex-start",
  },
  badge_wide: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: colors.primary,
    borderRadius: 8,
    height: 39,
    paddingHorizontal: 16,
  },
  badge_text: { fontFamily: "medium", fontSize: 16, color: colors.white },

  // 운동 목록
  section: { gap: 8, marginTop: 16 },
  section_title: { fontFamily: "medium", fontSize: 16, color: colors.primary },
  routine_item: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: colors.white,
    borderRadius: 8,
    paddingHorizontal: 20,
    height: 90,
  },
  routine_info: { gap: 4 },
  routine_name: { fontFamily: "medium", fontSize: 16, color: colors.primary },
  routine_sub: { fontFamily: "regular", fontSize: 12, color: colors.bluegray },
  empty_box: {
    backgroundColor: colors.white,
    borderRadius: 8,
    height: 70,
    alignItems: "center",
    justifyContent: "center",
  },
  empty_text: { fontFamily: "regular", fontSize: 14, color: colors.bluegray },
});
