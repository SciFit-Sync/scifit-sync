import { useState } from "react";
import {
  Alert,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { colors } from "../../assets/colors/colors";
import { useNavigation } from "@react-navigation/native";
import { LinearGradient } from "expo-linear-gradient";
import { SafeAreaView } from "react-native-safe-area-context";
import { signInWithKakao } from "../../services/kakaoAuth";
import { useAuthStore } from "../../stores/authStore";

export default function WA01Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const setAuth = useAuthStore((s) => s.setAuth);
  const navigation = useNavigation();

  const handleLogin = () => {
    if (!email || !password) {
      Alert.alert("알림", "이메일과 비밀번호를 입력해주세요");
      return;
    }
    // TODO: 이메일/비밀번호 로그인 API 연동
    console.log("이메일 로그인 시도:", email);
  };

  const handleKakaoLogin = async () => {
    setLoading(true);
    try {
      const result = await signInWithKakao();
      await setAuth(result);
    } catch (e: any) {
      Alert.alert("로그인 실패", e.message ?? "다시 시도해주세요.");
    } finally {
      setLoading(false);
    }
  };

  const handleFindPassword = () => {
    //
    console.log("비밀번호 찾기");
  };

  const handleSignup = () => {
    navigation.navigate("WA02Signup" as never);
    console.log("회원가입");
  };

  return (
    <LinearGradient colors={["#D0DCFF", "#EEF1F8"]} style={styles.container}>
      <SafeAreaView style={styles.container}>
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : "height"}
          style={styles.flex}
        >
          {/* 상단 로고 영역 */}
          <View style={styles.logoContainer}>
            <Text style={styles.logo}>SciFit-Sync</Text>
            <Text style={styles.slogan}>당신의 운동에 근거를 더하다</Text>
          </View>

          {/* 로그인 카드 */}
          <View style={styles.card}>
            <Text style={styles.cardTitle}>로그인</Text>

            <TextInput
              style={styles.input}
              placeholder="이메일 입력"
              placeholderTextColor="#B0B0B0"
              value={email}
              onChangeText={setEmail}
              keyboardType="email-address"
              autoCapitalize="none"
              autoCorrect={false}
            />

            <TextInput
              style={styles.input}
              placeholder="비밀번호 입력"
              placeholderTextColor="#B0B0B0"
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              autoCapitalize="none"
            />

            {/* 로그인 버튼 */}
            <TouchableOpacity
              style={styles.loginButton}
              onPress={handleLogin}
              activeOpacity={0.8}
            >
              <Text style={styles.loginButtonText}>로그인</Text>
            </TouchableOpacity>

            {/* 비밀번호 찾기 / 회원가입 */}
            <View style={styles.linkContainer}>
              <TouchableOpacity onPress={handleFindPassword}>
                <Text style={styles.linkText}>비밀번호 찾기</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={handleSignup}>
                <Text style={styles.linkText}>회원가입</Text>
              </TouchableOpacity>
            </View>

            {/* 구분선 */}
            <View style={styles.divider}>
              <View style={styles.dividerLine} />
              <Text style={styles.dividerText}>또는</Text>
              <View style={styles.dividerLine} />
            </View>

            {/* 카카오 로그인 버튼 */}
            <TouchableOpacity
              style={[
                styles.kakaoButton,
                loading && styles.kakaoButtonDisabled,
              ]}
              onPress={handleKakaoLogin}
              disabled={loading}
              activeOpacity={0.8}
            >
              <Text style={styles.kakaoText}>
                {loading ? "로그인 중..." : "카카오 로그인"}
              </Text>
            </TouchableOpacity>
          </View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  flex: {
    flex: 1,
  },
  logoContainer: {
    alignItems: "center",
    marginTop: 63,
    marginBottom: 56,
    gap: 8,
  },
  logo: {
    fontFamily: "sacheon",
    color: colors.primary,
    fontSize: 20,
  },
  slogan: {
    fontFamily: "medium",
    fontSize: 14,
    color: "#1E3A8A",
  },
  card: {
    backgroundColor: "#FFFFFF",
    marginHorizontal: 24,
    borderRadius: 16,
    padding: 20,
  },
  cardTitle: {
    fontFamily: "semibold",
    color: colors.primary,
    fontSize: 18,
    textAlign: "center",
    marginBottom: 16,
  },
  input: {
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 10,
    fontSize: 14,
    color: colors.primary,
    marginBottom: 8,
    fontFamily: "regular",
  },
  loginButton: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    marginTop: 8,
  },
  loginButtonText: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.white,
  },
  linkContainer: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginTop: 8,
    marginBottom: 24,
  },
  linkText: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
  },
  divider: {
    flexDirection: "row",
    alignItems: "center",
    marginBottom: 16,
  },
  dividerLine: {
    flex: 1,
    height: 1,
    backgroundColor: colors.border,
  },
  dividerText: {
    fontFamily: "regular",
    marginHorizontal: 10,
    fontSize: 14,
    color: colors.bluegray,
  },
  kakaoButton: {
    backgroundColor: colors.kakao,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
  },
  kakaoButtonDisabled: {
    opacity: 0.5,
  },
  kakaoText: {
    fontFamily: "medium",
    color: "#111111",
    fontSize: 16,
  },
});
