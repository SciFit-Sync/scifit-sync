import { useState, useCallback } from "react";
import WC01DChatbotFloating from "../../components/WC01-DChatbotFloating";
import WC01Chatbot from "../../components/WC01Chatbot";
import {
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  ScrollView,
  ActivityIndicator,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation, useFocusEffect } from "@react-navigation/native";
import { colors } from "../../assets/colors/colors";
import BottomNavBar from "../../components/NavBar";
import { useAuthStore } from "../../stores/authStore";
import { getMe, getMyOneRMs, MeData, OneRMData } from "../../services/users";

const CAREER_LABEL: Record<string, string> = {
  beginner: "헬린이",
  novice: "초급",
  intermediate: "중급",
  advanced: "고급",
};

const GENDER_LABEL: Record<string, string> = {
  male: "남성",
  female: "여성",
};

export default function WP01MyPage() {
  const navigation = useNavigation();
  const token = useAuthStore((s) => s.accessToken) ?? "";
  const clearAuth = useAuthStore((s) => s.clearAuth);
  const [show_chatbot, set_show_chatbot] = useState(false);

  const [me, set_me] = useState<MeData | null>(null);
  const [one_rms, set_one_rms] = useState<OneRMData[]>([]);
  const [loading, set_loading] = useState(true);

  const fetch_data = useCallback(async () => {
    set_loading(true);
    try {
      const [me_data, rm_data] = await Promise.all([
        getMe(token),
        getMyOneRMs(token),
      ]);
      set_me(me_data);
      set_one_rms(rm_data);
    } catch (e: any) {
      Alert.alert("오류", e.message ?? "정보를 불러오지 못했어요.");
    } finally {
      set_loading(false);
    }
  }, [token]);

  useFocusEffect(
    useCallback(() => {
      fetch_data();
    }, [fetch_data]),
  );

  const handle_logout = () => {
    Alert.alert("로그아웃", "로그아웃 하시겠습니까?", [
      { text: "취소", style: "cancel" },
      { text: "로그아웃", style: "destructive", onPress: clearAuth },
    ]);
  };

  // ── 표시 값 계산 ──────────────────────────────────────────────────────────────
  const body_value = (() => {
    const p = me?.profile;
    const m = me?.latest_measurement;
    const parts = [
      p?.height_cm ? `${p.height_cm}cm` : null,
      m?.weight_kg ? `${m.weight_kg}kg` : null,
      p?.age ? `${p.age}세` : null,
      p?.gender ? GENDER_LABEL[p.gender] : null,
    ].filter(Boolean);
    return parts.length > 0 ? parts.join(" · ") : "미입력";
  })();

  const career_value = (() => {
    const level = me?.profile?.career_level;
    return level ? CAREER_LABEL[level] ?? level : "미입력";
  })();

  const gym_value = (() => {
    if (!me?.gyms || me.gyms.length === 0) return "미설정";
    const primary = me.gyms.find((g) => g.is_primary);
    return primary?.name ?? me.gyms[0].name;
  })();

  const one_rm_value = (() => {
    if (one_rms.length === 0) return "미입력";
    return one_rms
      .slice(0, 4)
      .map((r) => `${r.exercise_name ?? "운동"} ${r.weight_kg}kg`)
      .join(" · ");
  })();

  const info_items = [
    { title: "신체 정보", value: body_value, screen: "WP02EditBodyInfo" },
    { title: "운동 경력", value: career_value, screen: "WP03EditCareer" },
    { title: "MY 헬스장", value: gym_value, screen: "WP04EditGym" },
    { title: "1RM", value: one_rm_value, screen: "WP05EditOneRM" },
  ];

  return (
    <View style={styles.container}>
      <SafeAreaView edges={["top"]} style={styles.safe_top} />

      {/* 헤더 */}
      <View style={styles.header}>
        <Text style={styles.logo}>SciFit-Sync</Text>
      </View>

      {loading ? (
        <View style={styles.loading}>
          <ActivityIndicator color={colors.primary} />
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={styles.scroll}
          showsVerticalScrollIndicator={false}
          style={styles.flex}
        >
          {/* 프로필 */}
          <View style={styles.profile_section}>
            <View style={styles.avatar} />
            <Text style={styles.greeting}>
              {me?.name ?? me?.username ?? "사용자"} 님, 안녕하세요!
            </Text>
          </View>

          {/* 정보 카드 목록 */}
          <View style={styles.info_list}>
            {info_items.map((item) => (
              <View key={item.title} style={styles.info_card}>
                <View style={styles.info_content}>
                  <Text style={styles.info_title}>{item.title}</Text>
                  <Text style={styles.info_value} numberOfLines={1}>
                    {item.value}
                  </Text>
                </View>
                <TouchableOpacity
                  onPress={() => navigation.navigate(item.screen as never)}
                >
                  <Text style={styles.edit_text}>수정</Text>
                </TouchableOpacity>
              </View>
            ))}
          </View>

          {/* 로그아웃 / 회원탈퇴 */}
          <View style={styles.bottom_buttons}>
            <TouchableOpacity onPress={handle_logout}>
              <Text style={styles.logout_text}>로그아웃</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => navigation.navigate("WP06Withdraw" as never)}
            >
              <Text style={styles.withdraw_text}>회원 탈퇴</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      )}

      {/* 하단 네브바 */}
      <SafeAreaView edges={["bottom"]} style={styles.safe_bottom}>
        <BottomNavBar />
      </SafeAreaView>
      <WC01DChatbotFloating onPress={() => set_show_chatbot(true)} />
      {show_chatbot && <WC01Chatbot onClose={() => set_show_chatbot(false)} />}
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
    flexDirection: "row",
    paddingHorizontal: 24,
    paddingTop: 29,
    paddingBottom: 24,
  },
  logo: { fontFamily: "sacheon", fontSize: 20, color: colors.primary },
  loading: { flex: 1, alignItems: "center", justifyContent: "center" },
  scroll: { paddingHorizontal: 24, paddingBottom: 32 },
  profile_section: {
    alignItems: "center",
    gap: 16,
    marginBottom: 24,
    marginTop: 8,
  },
  avatar: {
    width: 90,
    height: 90,
    borderRadius: 45,
    backgroundColor: "#000000",
  },
  greeting: {
    fontFamily: "medium",
    fontSize: 20,
    color: "#000000",
    textAlign: "center",
  },
  info_list: { gap: 8 },
  info_card: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: colors.white,
    borderRadius: 8,
    paddingHorizontal: 20,
    height: 77,
  },
  info_content: { gap: 4, flex: 1, marginRight: 12 },
  info_title: { fontFamily: "medium", fontSize: 16, color: colors.primary },
  info_value: { fontFamily: "regular", fontSize: 12, color: colors.bluegray },
  edit_text: { fontFamily: "regular", fontSize: 12, color: colors.bluegray },
  bottom_buttons: {
    flexDirection: "row",
    justifyContent: "center",
    gap: 40,
    marginTop: 40,
  },
  logout_text: { fontFamily: "regular", fontSize: 12, color: colors.bluegray },
  withdraw_text: { fontFamily: "regular", fontSize: 12, color: "#3C4455" },
});
