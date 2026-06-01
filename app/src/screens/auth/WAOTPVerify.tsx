import { useState, useRef } from "react";
import {
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  Alert,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation, useRoute } from "@react-navigation/native";
import { Octicons } from "@expo/vector-icons";
import { colors } from "../../assets/colors/colors";
import { verifyEmail, loginApi } from "../../services/auth";
import { useAuthStore } from "../../stores/authStore";

export default function WAOTPVerify() {
  const navigation = useNavigation();
  const route = useRoute();
  const { email, password } = (route.params ?? {}) as {
    email: string;
    password: string;
  };

  const [otp, set_otp] = useState("");
  const [loading, set_loading] = useState(false);
  const setAuth = useAuthStore((s) => s.setAuth);
  const input_ref = useRef<TextInput>(null);

  const handle_verify = async () => {
    if (otp.length !== 6) {
      Alert.alert("알림", "6자리 인증번호를 입력해주세요");
      return;
    }
    set_loading(true);
    try {
      await verifyEmail(email, otp);
      // 인증 완료 후 자동 로그인
      const result = await loginApi(email, password);
      await setAuth({
        access_token: result.access_token,
        refresh_token: result.refresh_token,
        is_new_user: true,
      });
    } catch (e: any) {
      Alert.alert("인증 실패", e.message ?? "인증번호를 확인해주세요.");
    } finally {
      set_loading(false);
    }
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

      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        style={styles.flex}
      >
        <View style={styles.card}>
          <Text style={styles.card_title}>이메일 인증</Text>

          <Text style={styles.desc}>
            <Text style={styles.email}>{email}</Text>
            {"\n"}으로 발송된 6자리 인증번호를 입력해주세요.
          </Text>

          {/* OTP 입력 */}
          <TouchableOpacity
            activeOpacity={1}
            onPress={() => input_ref.current?.focus()}
          >
            <View style={styles.otp_row} pointerEvents="none">
              {Array.from({ length: 6 }).map((_, i) => (
                <View
                  key={i}
                  style={[
                    styles.otp_box,
                    otp.length === i && styles.otp_box_active,
                  ]}
                >
                  <Text style={styles.otp_text}>{otp[i] ?? ""}</Text>
                </View>
              ))}
            </View>
            <TextInput
              ref={input_ref}
              value={otp}
              onChangeText={(v) => set_otp(v.replace(/[^0-9]/g, "").slice(0, 6))}
              keyboardType="number-pad"
              maxLength={6}
              style={styles.hidden_input}
              autoFocus
            />
          </TouchableOpacity>

          {/* 인증 버튼 */}
          <TouchableOpacity
            style={[styles.button, loading && { opacity: 0.5 }]}
            onPress={handle_verify}
            disabled={loading}
            activeOpacity={0.8}
          >
            <Text style={styles.button_text}>
              {loading ? "인증 중..." : "인증하기"}
            </Text>
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1, justifyContent: "center", paddingHorizontal: 24 },
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
  card: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 24,
    gap: 20,
  },
  card_title: {
    fontFamily: "semibold",
    fontSize: 18,
    color: colors.primary,
    textAlign: "center",
  },
  desc: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.bluegray,
    textAlign: "center",
    lineHeight: 22,
  },
  email: {
    fontFamily: "medium",
    color: colors.primary,
  },
  otp_row: {
    flexDirection: "row",
    justifyContent: "center",
    gap: 10,
  },
  otp_box: {
    width: 44,
    height: 52,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.background,
  },
  otp_box_active: {
    borderColor: colors.primary,
    borderWidth: 2,
  },
  otp_text: {
    fontFamily: "semibold",
    fontSize: 20,
    color: colors.primary,
  },
  hidden_input: {
    position: "absolute",
    width: 0,
    height: 0,
    opacity: 0,
  },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 12,
    alignItems: "center",
  },
  button_text: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.white,
  },
});
