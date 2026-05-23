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

interface InfoItem {
  title: string;
  value: string;
}

const mock_info: InfoItem[] = [
  { title: "신체 정보", value: "175cm · 75kg · 27세 · 남성" },
  { title: "운동 경력", value: "중급자 · 3년" },
  { title: "MY 헬스장", value: "스포애니 강남점" },
  {
    title: "1RM",
    value: "벤치 80kg · 스쿼트 100kg · 데드리프트 · 오버헤드프레스",
  },
];

export default function WP01MyPage() {
  const navigation = useNavigation();

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
        {/* 프로필 */}
        <View style={styles.profile_section}>
          <View style={styles.avatar} />
          <Text style={styles.greeting}>장태현 님, 안녕하세요!</Text>
        </View>

        {/* 정보 카드 목록 */}
        <View style={styles.info_list}>
          {mock_info.map((item) => (
            <View key={item.title} style={styles.info_card}>
              <View style={styles.info_content}>
                <Text style={styles.info_title}>{item.title}</Text>
                <Text style={styles.info_value} numberOfLines={1}>
                  {item.value}
                </Text>
              </View>
              <TouchableOpacity>
                <Text style={styles.edit_text}>수정</Text>
              </TouchableOpacity>
            </View>
          ))}
        </View>

        {/* 로그아웃 / 회원탈퇴 */}
        <View style={styles.bottom_buttons}>
          <TouchableOpacity>
            <Text style={styles.logout_text}>로그아웃</Text>
          </TouchableOpacity>
          <TouchableOpacity>
            <Text style={styles.withdraw_text}>회원 탈퇴</Text>
          </TouchableOpacity>
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
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 24,
    paddingTop: 16,
    paddingBottom: 8,
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

  // 프로필
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

  // 정보 카드
  info_list: {
    gap: 8,
  },
  info_card: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: colors.white,
    borderRadius: 8,
    paddingHorizontal: 20,
    height: 77,
  },
  info_content: {
    gap: 4,
    flex: 1,
    marginRight: 12,
  },
  info_title: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.primary,
  },
  info_value: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
  },
  edit_text: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
  },

  // 하단 버튼
  bottom_buttons: {
    flexDirection: "row",
    justifyContent: "center",
    gap: 40,
    marginTop: 40,
  },
  logout_text: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
  },
  withdraw_text: {
    fontFamily: "regular",
    fontSize: 12,
    color: "#3C4455",
  },
});
