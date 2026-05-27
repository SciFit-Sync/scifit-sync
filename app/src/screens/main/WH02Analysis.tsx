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

const BAR_MAX_HEIGHT = 130;

const weekly_data = [
  { day: "월", height: 50 },
  { day: "화", height: 80 },
  { day: "수", height: 62 },
  { day: "목", height: 62 },
  { day: "금", height: 62 },
  { day: "토", height: 62 },
  { day: "일", height: 62 },
];

const muscle_data = [
  { label: "가슴", percent: 84, color: "#FDB5CE" },
  { label: "어깨", percent: 84, color: "#FF9F43" },
  { label: "등", percent: 84, color: "#54A0FF" },
  { label: "다리", percent: 84, color: "#5F27CD" },
  { label: "팔", percent: 84, color: "#FFEB00" },
  { label: "복근", percent: 84, color: "#2D9596" },
];

export default function WH02Analysis() {
  const navigation = useNavigation();

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
        {/* ─── 주간 운동량 차트 ─── */}
        <View style={styles.card}>
          <Text style={styles.card_title}>주간 운동량</Text>
          <View style={styles.bar_chart}>
            {weekly_data.map((item) => (
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
          <View style={styles.muscle_list}>
            {muscle_data.map((item) => (
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
        </View>

        {/* ─── 통계 카드 ─── */}
        <View style={styles.stats_row}>
          {[
            { value: "4,800", label: "근육 피로도" },
            { value: "5세션", label: "이번 주" },
            { value: "5일", label: "연속" },
          ].map((s) => (
            <View key={s.label} style={styles.stat_card}>
              <Text style={styles.stat_value}>{s.value}</Text>
              <Text style={styles.stat_label}>{s.label}</Text>
            </View>
          ))}
        </View>

        {/* ─── AI 인사이트 ─── */}
        <View style={styles.insight_card}>
          <Octicons name="light-bulb" size={16} color={colors.white} />
          <Text style={styles.insight_text}>
            현재 가슴 볼륨은 근비대 최적 범위에{"\n"}도달했습니다.
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
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 24,
    paddingTop: 29,
    paddingBottom: 24,
  },
  logo: { fontFamily: "sacheon", fontSize: 20, color: colors.primary },
  placeholder: { width: 32 },
  scroll: { paddingHorizontal: 24, paddingBottom: 32, gap: 8 },

  // 카드
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

  // 막대 차트
  bar_chart: {
    flexDirection: "row",
    justifyContent: "center",
    gap: 17,
    height: BAR_MAX_HEIGHT + 24,
    alignItems: "flex-end",
  },
  bar_col: {
    alignItems: "center",
    gap: 4,
    width: 28,
  },
  bar_track: {
    width: 28,
    height: BAR_MAX_HEIGHT,
    backgroundColor: colors.select,
    borderRadius: 6,
    justifyContent: "flex-end",
  },
  bar_fill: {
    width: 28,
    backgroundColor: colors.primary,
    borderRadius: 6,
  },
  bar_label: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
    textAlign: "center",
  },

  // 근육 부위별
  muscle_list: { gap: 16 },
  muscle_row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
  },
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
  progress_fill: {
    height: 12,
    borderRadius: 100,
  },
  muscle_percent: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
    width: 32,
    textAlign: "center",
  },

  // 통계
  stats_row: {
    flexDirection: "row",
    gap: 8,
  },
  stat_card: {
    flex: 1,
    backgroundColor: colors.white,
    borderRadius: 8,
    height: 60,
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  stat_value: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.primary,
  },
  stat_label: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
  },

  // AI 인사이트
  insight_card: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 8,
    backgroundColor: colors.primary,
    borderRadius: 8,
    padding: 10,
  },
  insight_text: {
    fontFamily: "regular",
    fontSize: 16,
    color: colors.white,
    lineHeight: 24,
    flex: 1,
  },
});
