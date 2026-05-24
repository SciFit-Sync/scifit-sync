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

export default function WA02Signup() {
  const navigation = useNavigation();
  const [id, set_id] = useState("");
  const [password, set_password] = useState("");
  const [password_confirm, set_password_confirm] = useState("");
  const [name, set_name] = useState("");
  const [email, set_email] = useState("");

  const handle_next = () => {
    if (!id || !password || !password_confirm || !name || !email) {
      Alert.alert("알림", "모든 항목을 입력해주세요");
      return;
    }
    if (password !== password_confirm) {
      Alert.alert("알림", "비밀번호가 일치하지 않습니다");
      return;
    }
    navigation.navigate("WA03SignupInfo" as never);
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
        <ScrollView
          contentContainerStyle={styles.scroll}
          showsVerticalScrollIndicator={false}
        >
          {/* 카드 */}
          <View style={styles.card}>
            {/* 제목 */}
            <Text style={styles.cardTitle}>회원가입</Text>

            {/* 진행 indicator */}
            <View style={styles.indicator}>
              <View style={[styles.dot, styles.dotActive]} />
              <View style={[styles.dot, styles.dotInactive]} />
            </View>

            {/* 아이디 */}
            <View style={styles.field}>
              <Text style={styles.label}>아이디</Text>
              <TextInput
                style={styles.input}
                placeholder="아이디 입력"
                placeholderTextColor={colors.border}
                value={id}
                onChangeText={set_id}
                autoCapitalize="none"
                autoCorrect={false}
              />
            </View>

            {/* 비밀번호 */}
            <View style={styles.field}>
              <Text style={styles.label}>비밀번호</Text>
              <TextInput
                style={styles.input}
                placeholder="비밀번호 입력"
                placeholderTextColor={colors.border}
                value={password}
                onChangeText={set_password}
                secureTextEntry
                autoCapitalize="none"
              />
              <TextInput
                style={styles.input}
                placeholder="비밀번호 확인"
                placeholderTextColor={colors.border}
                value={password_confirm}
                onChangeText={set_password_confirm}
                secureTextEntry
                autoCapitalize="none"
              />
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

            {/* 이메일 */}
            <View style={styles.field}>
              <Text style={styles.label}>이메일</Text>
              <TextInput
                style={styles.input}
                placeholder="이메일 입력"
                placeholderTextColor={colors.border}
                value={email}
                onChangeText={set_email}
                keyboardType="email-address"
                autoCapitalize="none"
              />
            </View>

            {/* 회원가입 버튼 */}
            <TouchableOpacity
              style={styles.button}
              onPress={handle_next}
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
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  flex: { flex: 1 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 24,
    paddingTop: 24,
    paddingBottom: 24,
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
  indicator: {
    flexDirection: "row",
    justifyContent: "center",
    gap: 8,
  },
  dot: {
    width: 25,
    height: 4,
    borderRadius: 100,
  },
  dotActive: {
    backgroundColor: colors.primary,
  },
  dotInactive: {
    backgroundColor: "#C8D5FF",
  },
  field: { gap: 8 },
  label: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.primary,
  },
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
  button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
  },
  buttonText: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.white,
  },
});
