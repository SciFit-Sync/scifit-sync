import { useState } from "react";
import {
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation } from "@react-navigation/native";
import { Octicons } from "@expo/vector-icons";
import { colors } from "../../assets/colors/colors";
import { useAuthStore } from "../../stores/authStore";
import { withdrawUser } from "../../services/users";

export default function WP06Withdraw() {
  const navigation = useNavigation();
  const token = useAuthStore((s) => s.accessToken) ?? "";
  const clearAuth = useAuthStore((s) => s.clearAuth);

  const [password, set_password] = useState("");
  const [loading, set_loading] = useState(false);

  const handle_withdraw = () => {
    if (!password) {
      Alert.alert("알림", "비밀번호를 입력해주세요");
      return;
    }
    Alert.alert(
      "회원 탈퇴",
      "정말로 탈퇴하시겠어요?\n탈퇴 후 모든 데이터가 삭제됩니다.",
      [
        { text: "취소", style: "cancel" },
        {
          text: "탈퇴하기",
          style: "destructive",
          onPress: async () => {
            set_loading(true);
            try {
              await withdrawUser(token, password);
              await clearAuth();
            } catch (e: any) {
              Alert.alert("오류", e.message ?? "탈퇴 처리에 실패했어요.");
            } finally {
              set_loading(false);
            }
          },
        },
      ],
    );
  };

  return (
    <SafeAreaView style={styles.container}>
      {/* 헤더 */}
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()}>
          <Octicons name="chevron-left" size={32} color={colors.primary} />
        </TouchableOpacity>
        <Text style={styles.logo}>SciFit-Sync</Text>
        <View style={styles.placeholder} />
      </View>

      {/* 카드 */}
      <View style={styles.content}>
        <View style={styles.card}>
          <View style={styles.field}>
            <Text style={styles.label}>비밀번호를 입력해 주세요</Text>
            <TextInput
              style={styles.input}
              placeholder="비밀번호 입력"
              placeholderTextColor={colors.border}
              value={password}
              onChangeText={set_password}
              secureTextEntry
              autoCapitalize="none"
            />
          </View>
          <TouchableOpacity
            style={[styles.withdraw_button, loading && styles.withdraw_button_disabled]}
            onPress={handle_withdraw}
            disabled={loading}
            activeOpacity={0.8}
          >
            <Text style={styles.withdraw_button_text}>
              {loading ? "처리 중..." : "탈퇴하기"}
            </Text>
          </TouchableOpacity>
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 24,
    paddingTop: 24,
    paddingBottom: 24,
  },
  logo: { fontFamily: "sacheon", fontSize: 20, color: colors.primary },
  placeholder: { width: 32 },
  content: { paddingHorizontal: 24, paddingTop: 16 },
  card: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 20,
    gap: 16,
  },
  field: { gap: 8 },
  label: { fontFamily: "medium", fontSize: 16, color: colors.primary },
  input: {
    fontFamily: "regular",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 10,
    fontSize: 14,
    color: colors.primary,
  },
  withdraw_button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
  },
  withdraw_button_disabled: { opacity: 0.5 },
  withdraw_button_text: { fontFamily: "medium", fontSize: 16, color: colors.white },
});
