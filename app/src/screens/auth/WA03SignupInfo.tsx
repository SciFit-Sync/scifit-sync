import { useState } from "react";
import {
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  ScrollView,
  KeyboardAvoidingView,
  Platform,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation } from "@react-navigation/native";
import * as DocumentPicker from "expo-document-picker";
import { colors } from "../../assets/colors/colors";
import { Octicons } from "@expo/vector-icons";
import BirthDateBottomSheet from "../../components/WA03SignupBs";
import { useAuthStore } from "../../stores/authStore";

type Gender = "female" | "male";
type Experience = "헬린이" | "초급" | "중급" | "고급";

export default function WA03SignupInfo() {
  const navigation = useNavigation();

  const [birth_date, set_birth_date] = useState("");
  const [height, set_height] = useState("");
  const [weight, set_weight] = useState("");
  const [gender, set_gender] = useState<Gender>("male");
  const [experience, set_experience] = useState<Experience | null>(null);
  const [inbody_file, set_inbody_file] = useState<string | null>(null);
  const [show_date_picker, set_show_date_picker] = useState(false);
  const setAuth = useAuthStore((s) => s.setAuth);

  const experiences: Experience[] = ["헬린이", "초급", "중급", "고급"];

  const handle_pick_file = async () => {
    const result = await DocumentPicker.getDocumentAsync({
      type: "application/pdf",
    });
    if (!result.canceled) {
      set_inbody_file(result.assets[0].name);
    }
  };

  const handle_signup = async () => {
    if (!birth_date || !height || !weight || !experience) {
      Alert.alert("알림", "필수 항목을 입력해주세요");
      return;
    }
    // TODO: 실제 API 연동 후 진짜 토큰으로 교체
    await setAuth({
      accessToken: "temp_token",
      refreshToken: "temp_refresh",
      isNewUser: true,
    });
  };

  const handle_date_confirm = (date: string) => {
    set_birth_date(date);
    set_show_date_picker(false);
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
          <View style={styles.card}>
            {/* 제목 */}
            <Text style={styles.cardTitle}>회원가입</Text>

            {/* 진행 indicator (2단계) */}
            <View style={styles.indicator}>
              <View style={[styles.dot, styles.dotInactive]} />
              <View style={[styles.dot, styles.dotActive]} />
            </View>

            {/* 생년월일 */}
            <View style={styles.field}>
              <Text style={styles.label}>생년월일</Text>
              <TouchableOpacity
                style={styles.input}
                onPress={() => set_show_date_picker(true)}
                activeOpacity={0.8}
              >
                <Text
                  style={[
                    styles.inputText,
                    !birth_date && styles.placeholderText,
                  ]}
                >
                  {birth_date || "생년월일 입력"}
                </Text>
              </TouchableOpacity>
            </View>

            {/* 키 / 몸무게 */}
            <View style={styles.row}>
              <View style={[styles.field, styles.flex]}>
                <Text style={styles.label}>키</Text>
                <View style={styles.inputRow}>
                  <TextInput
                    style={[styles.inputInner, styles.flex]}
                    placeholder="키 입력"
                    placeholderTextColor={colors.border}
                    value={height}
                    onChangeText={set_height}
                    keyboardType="numeric"
                  />
                  <Text style={styles.unit}>cm</Text>
                </View>
              </View>
              <View style={[styles.field, styles.flex]}>
                <Text style={styles.label}>몸무게</Text>
                <View style={styles.inputRow}>
                  <TextInput
                    style={[styles.inputInner, styles.flex]}
                    placeholder="몸무게 입력"
                    placeholderTextColor={colors.border}
                    value={weight}
                    onChangeText={set_weight}
                    keyboardType="numeric"
                  />
                  <Text style={styles.unit}>kg</Text>
                </View>
              </View>
            </View>

            {/* 성별 */}
            <View style={styles.field}>
              <Text style={styles.label}>성별</Text>
              <View style={styles.row}>
                <TouchableOpacity
                  style={[
                    styles.selectButton,
                    gender === "female" && styles.selectButtonActive,
                  ]}
                  onPress={() => set_gender("female")}
                  activeOpacity={0.8}
                >
                  <Text
                    style={[
                      styles.selectButtonText,
                      gender === "female" && styles.selectButtonTextActive,
                    ]}
                  >
                    여성
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[
                    styles.selectButton,
                    gender === "male" && styles.selectButtonActive,
                  ]}
                  onPress={() => set_gender("male")}
                  activeOpacity={0.8}
                >
                  <Text
                    style={[
                      styles.selectButtonText,
                      gender === "male" && styles.selectButtonTextActive,
                    ]}
                  >
                    남성
                  </Text>
                </TouchableOpacity>
              </View>
            </View>

            {/* 운동 경력 */}
            <View style={styles.field}>
              <Text style={styles.label}>운동 경력</Text>
              <View style={styles.row}>
                {experiences.slice(0, 2).map((exp) => (
                  <TouchableOpacity
                    key={exp}
                    style={[
                      styles.selectButton,
                      experience === exp && styles.selectButtonActive,
                    ]}
                    onPress={() => set_experience(exp)}
                    activeOpacity={0.8}
                  >
                    <Text
                      style={[
                        styles.selectButtonText,
                        experience === exp && styles.selectButtonTextActive,
                      ]}
                    >
                      {exp}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
              <View style={styles.row}>
                {experiences.slice(2).map((exp) => (
                  <TouchableOpacity
                    key={exp}
                    style={[
                      styles.selectButton,
                      experience === exp && styles.selectButtonActive,
                    ]}
                    onPress={() => set_experience(exp)}
                    activeOpacity={0.8}
                  >
                    <Text
                      style={[
                        styles.selectButtonText,
                        experience === exp && styles.selectButtonTextActive,
                      ]}
                    >
                      {exp}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>

            {/* 인바디 업로드 */}
            <View style={styles.field}>
              <Text style={styles.label}>인바디 업로드 (선택)</Text>
              <TouchableOpacity
                style={styles.input}
                onPress={handle_pick_file}
                activeOpacity={0.8}
              >
                <Text
                  style={[
                    styles.inputText,
                    !inbody_file && styles.placeholderText,
                  ]}
                >
                  {inbody_file || "파일 첨부"}
                </Text>
              </TouchableOpacity>
            </View>

            {/* 회원가입 버튼 */}
            <TouchableOpacity
              style={styles.button}
              onPress={handle_signup}
              activeOpacity={0.8}
            >
              <Text style={styles.buttonText}>회원가입</Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>

      {/* 바텀시트 */}
      {show_date_picker && (
        <BirthDateBottomSheet
          onConfirm={handle_date_confirm}
          onClose={() => set_show_date_picker(false)}
        />
      )}
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
  dotActive: { backgroundColor: colors.primary },
  dotInactive: { backgroundColor: colors.button },
  field: { gap: 8 },
  label: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.primary,
  },
  row: {
    flexDirection: "row",
    gap: 7,
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
    justifyContent: "center",
  },
  inputText: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.primary,
  },
  placeholderText: {
    color: colors.border,
  },
  inputRow: {
    flexDirection: "row",
    alignItems: "center",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 10,
  },
  inputInner: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.primary,
    paddingVertical: 10,
  },
  unit: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.primary,
    paddingLeft: 4,
  },
  selectButton: {
    flex: 1,
    backgroundColor: colors.select,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
  },
  selectButtonActive: {
    backgroundColor: colors.primary,
  },
  selectButtonText: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.primary,
  },
  selectButtonTextActive: {
    color: colors.white,
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
