import { useState } from "react";
import {
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation } from "@react-navigation/native";
import { colors } from "../../assets/colors/colors";
import { Octicons } from "@expo/vector-icons";
import { register, verifyEmail, loginApi, checkUsername } from "../../services/auth";

// ── 유효성 검사 헬퍼 ──────────────────────────────────────────────────────────
const ID_REGEX = /^[a-zA-Z0-9_]+$/;

function validate_id(v: string): string {
  if (!v) return "";
  if (v.length < 2 || v.length > 20) return "2~20자로 입력해주세요";
  if (!ID_REGEX.test(v)) return "영문, 숫자, _만 사용할 수 있어요";
  return "";
}

function validate_password(v: string): string {
  if (!v) return "";
  if (v.length < 8) return "8자 이상 입력해주세요";
  return "";
}

function validate_password_confirm(pw: string, confirm: string): string {
  if (!confirm) return "";
  if (pw !== confirm) return "비밀번호가 일치하지 않아요";
  return "";
}

export default function WA02Signup() {
  const navigation = useNavigation();

  // 입력값
  const [id, set_id] = useState("");
  const [password, set_password] = useState("");
  const [password_confirm, set_password_confirm] = useState("");
  const [name, set_name] = useState("");
  const [email, set_email] = useState("");

  // 실시간 오류
  const [id_error, set_id_error] = useState("");
  const [password_error, set_password_error] = useState("");
  const [password_confirm_error, set_password_confirm_error] = useState("");

  // 아이디 중복 확인
  const [id_check_loading, set_id_check_loading] = useState(false);
  const [id_checked, set_id_checked] = useState<"available" | "taken" | null>(null);

  // OTP / 이메일 인증
  const [otp_sent, set_otp_sent] = useState(false);
  const [otp, set_otp] = useState("");
  const [email_verified, set_email_verified] = useState(false);
  const [access_token, set_access_token] = useState("");
  const [refresh_token, set_refresh_token] = useState("");
  const [send_loading, set_send_loading] = useState(false);
  const [verify_loading, set_verify_loading] = useState(false);

  // ── 핸들러 ──────────────────────────────────────────────────────────────────

  const handle_id_change = (v: string) => {
    set_id(v);
    set_id_error(validate_id(v));
    set_id_checked(null); // 아이디 바뀌면 중복 확인 초기화
  };

  const handle_password_change = (v: string) => {
    set_password(v);
    set_password_error(validate_password(v));
    if (password_confirm) {
      set_password_confirm_error(validate_password_confirm(v, password_confirm));
    }
  };

  const handle_password_confirm_change = (v: string) => {
    set_password_confirm(v);
    set_password_confirm_error(validate_password_confirm(password, v));
  };

  // 아이디 중복 확인
  const handle_check_id = async () => {
    const err = validate_id(id);
    if (err) {
      set_id_error(err);
      return;
    }
    set_id_check_loading(true);
    try {
      const result = await checkUsername(id);
      set_id_checked(result.available ? "available" : "taken");
    } catch {
      Alert.alert("오류", "중복 확인 중 문제가 발생했어요. 다시 시도해주세요.");
    } finally {
      set_id_check_loading(false);
    }
  };

  // 코드 전송 → register API 호출
  const handle_send_code = async () => {
    if (!id || !password || !password_confirm || !name || !email) {
      Alert.alert("알림", "모든 항목을 입력해주세요");
      return;
    }
    if (id_checked !== "available") {
      Alert.alert("알림", "아이디 중복 확인을 해주세요");
      return;
    }
    if (validate_id(id) || validate_password(password) || password !== password_confirm) {
      Alert.alert("알림", "입력값을 확인해주세요");
      return;
    }
    set_send_loading(true);
    try {
      const result = await register({ username: id, password, name, email });
      set_otp_sent(true);
      // 개발 환경: 이메일 미발송 → 응답에 otp_code가 포함되면 자동 입력
      if (result.otp_code) {
        set_otp(result.otp_code);
      } else {
        set_otp("");
      }
    } catch (e: any) {
      Alert.alert("오류", e.message ?? "다시 시도해주세요.");
    } finally {
      set_send_loading(false);
    }
  };

  // 인증하기 → verify-email 후 자동 로그인
  const handle_verify = async () => {
    if (otp.length !== 6) {
      Alert.alert("알림", "6자리 인증번호를 입력해주세요");
      return;
    }
    set_verify_loading(true);
    try {
      await verifyEmail(email, otp);
      const result = await loginApi(email, password);
      set_access_token(result.access_token);
      set_refresh_token(result.refresh_token);
      set_email_verified(true);
    } catch (e: any) {
      Alert.alert("인증 실패", e.message ?? "인증번호를 확인해주세요.");
    } finally {
      set_verify_loading(false);
    }
  };

  // 다음 → WA03에 토큰 포함 전달
  const handle_next = () => {
    (navigation as any).navigate("WA03SignupInfo", {
      username: id,
      password,
      name,
      email,
      access_token,
      refresh_token,
    });
  };

  // 다음 버튼 활성화 조건
  const can_next = email_verified;

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
        <ScrollView
          contentContainerStyle={styles.scroll}
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.card}>
            <Text style={styles.cardTitle}>회원가입</Text>

            {/* 진행 indicator */}
            <View style={styles.indicator}>
              <View style={[styles.dot, styles.dotActive]} />
              <View style={[styles.dot, styles.dotInactive]} />
            </View>

            {/* 아이디 */}
            <View style={styles.field}>
              <Text style={styles.label}>아이디</Text>
              <View style={styles.row_input}>
                <TextInput
                  style={[
                    styles.input,
                    styles.flex,
                    id_checked === "available" && styles.input_valid,
                    id_checked === "taken" && styles.input_error,
                  ]}
                  placeholder="영문, 숫자, _ 조합 (2~20자)"
                  placeholderTextColor={colors.border}
                  value={id}
                  onChangeText={handle_id_change}
                  autoCapitalize="none"
                  autoCorrect={false}
                />
                <TouchableOpacity
                  style={[styles.code_btn, id_check_loading && { opacity: 0.5 }]}
                  onPress={handle_check_id}
                  disabled={id_check_loading}
                  activeOpacity={0.8}
                >
                  <Text style={styles.code_btn_text}>
                    {id_check_loading ? "확인 중" : "중복 확인"}
                  </Text>
                </TouchableOpacity>
              </View>
              {/* 아이디 실시간 오류 */}
              {id_error ? (
                <Text style={styles.error_text}>{id_error}</Text>
              ) : id_checked === "available" ? (
                <Text style={styles.success_text}>✓ 사용 가능한 아이디예요</Text>
              ) : id_checked === "taken" ? (
                <Text style={styles.error_text}>이미 사용 중인 아이디예요</Text>
              ) : null}
            </View>

            {/* 비밀번호 */}
            <View style={styles.field}>
              <Text style={styles.label}>비밀번호</Text>
              <Text style={styles.hint}>8자 이상 입력해주세요</Text>
              <TextInput
                style={[styles.input, password_error ? styles.input_error_border : null]}
                placeholder="비밀번호 입력"
                placeholderTextColor={colors.border}
                value={password}
                onChangeText={handle_password_change}
                secureTextEntry
                autoCapitalize="none"
              />
              {password_error ? (
                <Text style={styles.error_text}>{password_error}</Text>
              ) : null}
              <TextInput
                style={[styles.input, password_confirm_error ? styles.input_error_border : null]}
                placeholder="비밀번호 확인"
                placeholderTextColor={colors.border}
                value={password_confirm}
                onChangeText={handle_password_confirm_change}
                secureTextEntry
                autoCapitalize="none"
              />
              {password_confirm_error ? (
                <Text style={styles.error_text}>{password_confirm_error}</Text>
              ) : null}
            </View>

            {/* 이름 */}
            <View style={styles.field}>
              <Text style={styles.label}>이름</Text>
              <TextInput
                style={styles.input}
                placeholder="이름 입력"
                placeholderTextColor={colors.border}
                value={name}
                onChangeText={set_name}
              />
            </View>

            {/* 이메일 + 코드 전송 */}
            <View style={styles.field}>
              <Text style={styles.label}>이메일</Text>
              <View style={styles.row_input}>
                <TextInput
                  style={[
                    styles.input,
                    styles.flex,
                    email_verified && styles.input_valid,
                  ]}
                  placeholder="이메일 입력"
                  placeholderTextColor={colors.border}
                  value={email}
                  onChangeText={(v) => {
                    set_email(v);
                    set_otp_sent(false);
                    set_email_verified(false);
                  }}
                  keyboardType="email-address"
                  autoCapitalize="none"
                  editable={!email_verified}
                />
                {email_verified ? (
                  <View style={styles.verified_badge}>
                    <Octicons name="check" size={14} color={colors.white} />
                    <Text style={styles.verified_text}>인증완료</Text>
                  </View>
                ) : (
                  <TouchableOpacity
                    style={[styles.code_btn, send_loading && { opacity: 0.5 }]}
                    onPress={handle_send_code}
                    disabled={send_loading}
                    activeOpacity={0.8}
                  >
                    <Text style={styles.code_btn_text}>
                      {send_loading ? "전송 중" : otp_sent ? "재전송" : "코드 전송"}
                    </Text>
                  </TouchableOpacity>
                )}
              </View>

              {/* OTP 입력창 */}
              {otp_sent && !email_verified && (
                <View style={styles.row_input}>
                  <TextInput
                    style={[styles.input, styles.flex]}
                    placeholder="인증번호 6자리"
                    placeholderTextColor={colors.border}
                    value={otp}
                    onChangeText={(v) => set_otp(v.replace(/[^0-9]/g, "").slice(0, 6))}
                    keyboardType="number-pad"
                    maxLength={6}
                    autoFocus
                  />
                  <TouchableOpacity
                    style={[styles.code_btn, verify_loading && { opacity: 0.5 }]}
                    onPress={handle_verify}
                    disabled={verify_loading}
                    activeOpacity={0.8}
                  >
                    <Text style={styles.code_btn_text}>
                      {verify_loading ? "확인 중" : "인증하기"}
                    </Text>
                  </TouchableOpacity>
                </View>
              )}
            </View>

            {/* 다음 버튼 */}
            <TouchableOpacity
              style={[styles.button, !can_next && styles.button_disabled]}
              onPress={handle_next}
              disabled={!can_next}
              activeOpacity={0.8}
            >
              <Text style={styles.buttonText}>다음</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  flex: { flex: 1 },
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
  scroll: { paddingHorizontal: 24, paddingBottom: 32 },
  card: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 20,
    gap: 16,
  },
  cardTitle: {
    fontFamily: "semibold",
    fontSize: 18,
    color: colors.primary,
    textAlign: "center",
  },
  indicator: { flexDirection: "row", justifyContent: "center", gap: 8 },
  dot: { width: 25, height: 4, borderRadius: 100 },
  dotActive: { backgroundColor: colors.primary },
  dotInactive: { backgroundColor: "#C8D5FF" },
  field: { gap: 6 },
  label: { fontFamily: "medium", fontSize: 16, color: colors.primary },
  hint: { fontFamily: "regular", fontSize: 12, color: colors.border },
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
  input_valid: {
    borderColor: "#4CAF50",
    backgroundColor: "#F6FFF6",
  },
  input_error_border: {
    borderColor: "#FF3B30",
  },
  input_error: {
    borderColor: "#FF3B30",
    backgroundColor: "#FFF6F6",
  },
  error_text: {
    fontFamily: "regular",
    fontSize: 12,
    color: "#FF3B30",
  },
  success_text: {
    fontFamily: "regular",
    fontSize: 12,
    color: "#4CAF50",
  },
  // 아이디/이메일 행
  row_input: { flexDirection: "row", gap: 8, alignItems: "center" },
  code_btn: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    alignItems: "center",
    justifyContent: "center",
  },
  code_btn_text: { fontFamily: "medium", fontSize: 13, color: colors.white },
  verified_badge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#4CAF50",
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 10,
  },
  verified_text: { fontFamily: "medium", fontSize: 13, color: colors.white },
  // 다음 버튼
  button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
  },
  button_disabled: { opacity: 0.3 },
  buttonText: { fontFamily: "medium", fontSize: 16, color: colors.white },
});
