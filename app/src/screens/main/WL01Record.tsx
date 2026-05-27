import { useState } from "react";
import {
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation } from "@react-navigation/native";
import { Octicons } from "@expo/vector-icons";
import { colors } from "../../assets/colors/colors";
import BottomNavBar from "../../components/NavBar";

interface Routine {
  id: string;
  name: string;
  gym: string;
  date: string;
}

type MuscleKey = "chest" | "back" | "shoulder" | "legs" | "arms" | "core";

const MUSCLE_COLORS: Record<MuscleKey, string> = {
  chest: colors.muscle_chest,
  back: colors.muscle_back,
  shoulder: colors.muscle_shoulder,
  legs: colors.muscle_legs,
  arms: colors.muscle_arms,
  core: colors.muscle_core,
};

interface DayData {
  routines: Routine[];
  stats: { kcal: string; sets: string; duration: string };
  streak: number;
  bottom_stats: { weight: string; sets: string; visits: string };
  muscles: MuscleKey[]; // 그날 사용한 근육 부위
}

// 날짜키: "YYYY-MM-DD"
const mock_day_data: Record<string, DayData> = {
  "2026-03-26": {
    routines: [
      {
        id: "1",
        name: "상체 근비대 루틴",
        gym: "스포애니 강남점",
        date: "2026.03.26",
      },
    ],
    stats: { kcal: "320 kcal", sets: "18세트", duration: "1h 10m" },
    streak: 5,
    bottom_stats: { weight: "5kg", sets: "18세트", visits: "5번" },
    muscles: ["chest", "back", "shoulder"],
  },
  "2026-03-24": {
    routines: [
      {
        id: "2",
        name: "하체 근비대 루틴",
        gym: "스포애니 강남점",
        date: "2026.03.24",
      },
    ],
    stats: { kcal: "410 kcal", sets: "20세트", duration: "1h 30m" },
    streak: 3,
    bottom_stats: { weight: "80kg", sets: "20세트", visits: "4번" },
    muscles: ["legs", "core"],
  },
  "2026-03-22": {
    routines: [
      {
        id: "3",
        name: "전신 스트렝스 루틴",
        gym: "스포애니 강남점",
        date: "2026.03.22",
      },
    ],
    stats: { kcal: "280 kcal", sets: "15세트", duration: "55m" },
    streak: 1,
    bottom_stats: { weight: "100kg", sets: "15세트", visits: "3번" },
    muscles: ["chest", "legs", "arms", "core"],
  },
};

// 월간 기본값
const monthly_default: DayData = {
  routines: [
    {
      id: "1",
      name: "상체 근비대 루틴",
      gym: "스포애니 강남점",
      date: "2026.03.26",
    },
    {
      id: "2",
      name: "상체 근비대 루틴",
      gym: "스포애니 강남점",
      date: "2026.03.24",
    },
    {
      id: "3",
      name: "상체 근비대 루틴",
      gym: "스포애니 강남점",
      date: "2026.03.22",
    },
  ],
  stats: { kcal: "0 kcal", sets: "42세트", duration: "4h 20m" },
  streak: 5,
  bottom_stats: { weight: "5kg", sets: "5세트", visits: "5번" },
  muscles: [],
};

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
  const today = new Date();
  const [year, set_year] = useState(today.getFullYear());
  const [month, set_month] = useState(today.getMonth() + 1);
  const [selected_day, set_selected_day] = useState<number | null>(null);

  const weeks = get_calendar_weeks(year, month);

  const handle_prev = () => {
    set_selected_day(null);
    if (month === 1) {
      set_year((y) => y - 1);
      set_month(12);
    } else set_month((m) => m - 1);
  };

  const handle_next = () => {
    set_selected_day(null);
    if (month === 12) {
      set_year((y) => y + 1);
      set_month(1);
    } else set_month((m) => m + 1);
  };

  const handle_day_press = (day: number | null) => {
    if (day === null) return;
    set_selected_day((prev) => (prev === day ? null : day));
  };

  const is_today = (day: number | null) =>
    day !== null &&
    day === today.getDate() &&
    month === today.getMonth() + 1 &&
    year === today.getFullYear();

  const is_selected = (day: number | null) =>
    day !== null && day === selected_day;

  const has_data = (day: number | null) =>
    day !== null && !!mock_day_data[to_date_key(year, month, day)];

  const current_data: DayData =
    selected_day !== null
      ? (mock_day_data[to_date_key(year, month, selected_day)] ?? {
          routines: [],
          stats: { kcal: "0 kcal", sets: "0세트", duration: "0m" },
          streak: 0,
          bottom_stats: { weight: "0kg", sets: "0세트", visits: "0번" },
        })
      : monthly_default;

  const title_day = selected_day ?? today.getDate();
  const title_month = selected_day !== null ? month : today.getMonth() + 1;
  const section_title = `${title_month}월 ${title_day}일 운동`;

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
                          {mock_day_data[to_date_key(year, month, day)].muscles
                            .slice(0, 4)
                            .map((m) => (
                              <View
                                key={m}
                                style={[
                                  styles.dot,
                                  { backgroundColor: MUSCLE_COLORS[m] },
                                ]}
                              />
                            ))}
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
          {[
            { value: current_data.stats.kcal, label: "칼로리" },
            { value: current_data.stats.sets, label: "총 세트" },
            { value: current_data.stats.duration, label: "운동 시간" },
          ].map((s) => (
            <View key={s.label} style={styles.stat_card}>
              <Text style={styles.stat_value}>{s.value}</Text>
              <Text style={styles.stat_label}>{s.label}</Text>
            </View>
          ))}
        </View>

        {/* 연속 운동 배지 */}
        {current_data.streak > 0 && (
          <View style={styles.badge_small}>
            <Octicons name="flame" size={16} color={colors.white} />
            <Text style={styles.badge_text}>
              {current_data.streak}일 연속 운동
            </Text>
          </View>
        )}

        {/* ─── 운동 목록 ─── */}
        <View style={styles.section}>
          <Text style={styles.section_title}>{section_title}</Text>
          {current_data.routines.length > 0 ? (
            current_data.routines.map((item) => (
              <TouchableOpacity
                key={item.id}
                style={styles.routine_item}
                onPress={() =>
                  navigation.navigate("WR04RoutineDetail" as never)
                }
                activeOpacity={0.8}
              >
                <View style={styles.routine_info}>
                  <Text style={styles.routine_name}>{item.name}</Text>
                  <Text style={styles.routine_sub}>{item.gym}</Text>
                  <Text style={styles.routine_sub}>{item.date}</Text>
                </View>
                <Octicons
                  name="triangle-right"
                  size={24}
                  color={colors.primary}
                />
              </TouchableOpacity>
            ))
          ) : (
            <View style={styles.empty_box}>
              <Text style={styles.empty_text}>운동 기록이 없어요</Text>
            </View>
          )}
        </View>

        {/* ─── 하단 통계 ─── */}
        <View style={styles.stats_row}>
          {[
            { value: current_data.bottom_stats.weight, label: "총 중량" },
            { value: current_data.bottom_stats.sets, label: "세트 수" },
            {
              value: current_data.bottom_stats.visits,
              label: "주간 방문 횟수",
            },
          ].map((s) => (
            <View key={s.label} style={styles.stat_card}>
              <Text style={styles.stat_value}>{s.value}</Text>
              <Text style={styles.stat_label}>{s.label}</Text>
            </View>
          ))}
        </View>

        {/* AI 인사이트 배지 */}
        <View style={styles.badge_wide}>
          <Octicons name="light-bulb" size={16} color={colors.white} />
          <Text style={styles.badge_text}>
            5일째, 당신은 이미 어제보다 강해졌어요
          </Text>
        </View>
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
