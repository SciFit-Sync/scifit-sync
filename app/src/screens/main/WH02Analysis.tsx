import { useMemo, useCallback } from "react";
import {
  ActivityIndicator,
  StyleSheet,
  Text,
  View,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Octicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useFocusEffect } from "@react-navigation/native";
import { colors } from "../../assets/colors/colors";
import BottomNavBar from "../../components/NavBar";
import { useAuthStore } from "../../stores/authStore";
import {
  getSessionStats,
  getVolumeAnalysis,
  getMuscleVolumeAnalysis,
  MuscleVolumeItem,
} from "../../services/sessions";

const BAR_MAX_HEIGHT = 130;
const DAYS_KO = ["일", "월", "화", "수", "목", "금", "토"];

const MUSCLE_GROUPS: { label: string; keys: string[]; color: string }[] = [
  { label: "가슴", keys: ["가슴"], color: "#FDB5CE" },
  { label: "어깨", keys: ["어깨 전면", "어깨 측면", "어깨 후면"], color: "#FF9F43" },
  { label: "등", keys: ["광배근", "상부 등", "승모근"], color: "#54A0FF" },
  { label: "다리", keys: ["대퇴사두근", "햄스트링", "둔근", "종아리"], color: "#5F27CD" },
  { label: "팔", keys: ["이두근", "삼두근", "전완근"], color: "#FFEB00" },
  { label: "복근", keys: ["복근"], color: "#2D9596" },
];

function buildWeekDays(): { date: string; dayLabel: string }[] {
  const now = new Date();
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(now);
    d.setDate(now.getDate() - (6 - i));
    return {
      date: d.toISOString().split("T")[0],
      dayLabel: DAYS_KO[d.getDay()],
    };
  });
}

function aggregateMuscle(
  items: MuscleVolumeItem[],
  keys: string[]
): { volume: number; optimalMax: number } {
  const map = Object.fromEntries(items.map((i) => [i.muscle, i]));
  return keys.reduce(
    (acc, key) => {
      const item = map[key];
      if (!item) return acc;
      return {
        volume: acc.volume + item.weekly_volume,
        optimalMax: acc.optimalMax + item.optimal_max,
      };
    },
    { volume: 0, optimalMax: 0 }
  );
}

export default function WH02Analysis() {
  const token = useAuthStore((s) => s.accessToken) ?? "";
  const weekDays = useMemo(() => buildWeekDays(), []);
  const query_client = useQueryClient();

  // 탭 포커스 시 분석 데이터 갱신
  useFocusEffect(
    useCallback(() => {
      query_client.invalidateQueries({ queryKey: ["session-stats"] });
      query_client.invalidateQueries({ queryKey: ["volume-analysis"] });
      query_client.invalidateQueries({ queryKey: ["muscle-volume"] });
    }, [query_client]),
  );

  const { data: statsData } = useQuery({
    queryKey: ["session-stats"],
    queryFn: () => getSessionStats(token),
    enabled: !!token,
  });

  const { data: volumeData } = useQuery({
    queryKey: ["volume-analysis", 7],
    queryFn: () => getVolumeAnalysis(token, 7),
    enabled: !!token,
  });

  const { data: muscleData, isLoading: muscleLoading } = useQuery({
    queryKey: ["muscle-volume", "WEEK"],
    queryFn: () => getMuscleVolumeAnalysis(token, "WEEK"),
    enabled: !!token,
  });

  const barData = useMemo(() => {
    const volMap: Record<string, number> = {};
    for (const item of volumeData?.items ?? []) {
      volMap[item.date] = item.volume_kg;
    }
    const volumes = weekDays.map((d) => volMap[d.date] ?? 0);
    const maxVol = Math.max(...volumes, 1);
    return weekDays.map((d, i) => ({
      day: d.dayLabel,
      height: Math.round((volumes[i] / maxVol) * BAR_MAX_HEIGHT),
    }));
  }, [volumeData, weekDays]);

  const muscleRows = useMemo(() => {
    const items = muscleData?.volume_by_muscle ?? [];
    return MUSCLE_GROUPS.map(({ label, keys, color }) => {
      const { volume, optimalMax } = aggregateMuscle(items, keys);
      const percent =
        optimalMax > 0 ? Math.min(100, Math.round((volume / optimalMax) * 100)) : 0;
      return { label, percent, color };
    });
  }, [muscleData]);

  const statCards = [
    {
      value: statsData
        ? `${Math.round(statsData.total_volume_kg).toLocaleString()}kg`
        : "-",
      label: "총 볼륨",
    },
    {
      value: statsData ? `${statsData.weekly_session_count}세션` : "-",
      label: "이번 주",
    },
    {
      value: statsData ? `${statsData.streak_days}일` : "-",
      label: "연속",
    },
  ];

  return (
    <View style={styles.container}>
      <SafeAreaView edges={["top"]} style={styles.safe_top} />

      <View style={styles.header}>
        <Text style={styles.logo}>SciFit-Sync</Text>
      </View>

      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
        style={styles.flex}
      >
        {/* ─── 주간 운동량 차트 ─── */}
        <View style={styles.card}>
          <Text style={styles.card_title}>주간 운동량</Text>
          <View style={styles.bar_chart}>
            {barData.map((item) => (
              <View key={item.day} style={styles.bar_col}>
                <View style={styles.bar_track}>
                  <View style={[styles.bar_fill, { height: item.height }]} />
                </View>
                <Text style={styles.bar_label}>{item.day}</Text>
              </View>
            ))}
          </View>
        </View>

        {/* ─── 근육 부위별 운동량 ─── */}
        <View style={styles.card}>
          <Text style={styles.card_title}>근육 부위별 운동량</Text>
          {muscleLoading ? (
            <ActivityIndicator color={colors.primary} />
          ) : (
            <View style={styles.muscle_list}>
              {muscleRows.map((item) => (
                <View key={item.label} style={styles.muscle_row}>
                  <Text style={styles.muscle_label}>{item.label}</Text>
                  <View style={styles.progress_track}>
                    <View
                      style={[
                        styles.progress_fill,
                        {
                          width: `${item.percent}%` as any,
                          backgroundColor: item.color,
                        },
                      ]}
                    />
                  </View>
                  <Text style={styles.muscle_percent}>{item.percent}%</Text>
                </View>
              ))}
            </View>
          )}
        </View>

        {/* ─── 통계 카드 ─── */}
        <View style={styles.stats_row}>
          {statCards.map((s) => (
            <View key={s.label} style={styles.stat_card}>
              <Text style={styles.stat_value}>{s.value}</Text>
              <Text style={styles.stat_label}>{s.label}</Text>
            </View>
          ))}
        </View>

        {/* ─── AI 코치 팁 ─── */}
        {!!muscleData?.ai_coach_message && (
          <View style={styles.tip_card}>
            <Octicons name="light-bulb" size={16} color={colors.white} />
            <Text style={styles.tip_text}>{muscleData.ai_coach_message}</Text>
          </View>
        )}
      </ScrollView>

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
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 24,
    paddingTop: 29,
    paddingBottom: 24,
  },
  logo: { fontFamily: "sacheon", fontSize: 20, color: colors.primary },
  scroll: { paddingHorizontal: 24, paddingBottom: 32, gap: 8 },

  card: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 20,
    gap: 16,
  },
  card_title: {
    fontFamily: "semibold",
    fontSize: 16,
    color: colors.primary,
  },

  bar_chart: {
    flexDirection: "row",
    justifyContent: "center",
    gap: 17,
    height: BAR_MAX_HEIGHT + 24,
    alignItems: "flex-end",
  },
  bar_col: { alignItems: "center", gap: 4, width: 28 },
  bar_track: {
    width: 28,
    height: BAR_MAX_HEIGHT,
    backgroundColor: colors.select,
    borderRadius: 6,
    justifyContent: "flex-end",
  },
  bar_fill: { width: 28, backgroundColor: colors.primary, borderRadius: 6 },
  bar_label: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
    textAlign: "center",
  },

  muscle_list: { gap: 16 },
  muscle_row: { flexDirection: "row", alignItems: "center", gap: 14 },
  muscle_label: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
    width: 24,
    textAlign: "center",
  },
  progress_track: {
    flex: 1,
    height: 12,
    backgroundColor: colors.select,
    borderRadius: 100,
    overflow: "hidden",
  },
  progress_fill: { height: 12, borderRadius: 100 },
  muscle_percent: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
    width: 32,
    textAlign: "center",
  },

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

  tip_card: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 8,
    backgroundColor: colors.primary,
    borderRadius: 8,
    padding: 10,
  },
  tip_text: {
    fontFamily: "regular",
    fontSize: 16,
    color: colors.white,
    lineHeight: 24,
    flex: 1,
  },
});
