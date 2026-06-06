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
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation, useRoute } from "@react-navigation/native";
import * as ImagePicker from "expo-image-picker";
import * as FileSystem from "expo-file-system/legacy";
import { colors } from "../../assets/colors/colors";
import { Octicons } from "@expo/vector-icons";
import BirthDateBottomSheet from "../../components/WA03SignupBs";
import { useAuthStore } from "../../stores/authStore";
import { onboardUser, ocrInbody, updateBody } from "../../services/users";

type Gender = "female" | "male";
type Experience = "헬린이" | "초급" | "중급" | "고급";

const CAREER_MAP: Record<
  Experience,
  "beginner" | "novice" | "intermediate" | "advanced"
> = {
  헬린이: "beginner",
  초급: "novice",
  중급: "intermediate",
  고급: "advanced",
};

// "2000년 1월 15일" → "2000-01-15"
function parse_birth_date(korean_date: string): string {
  const match = korean_date.match(/(\d+)년\s*(\d+)월\s*(\d+)일/);
  if (!match) return korean_date;
  const [, year, month, day] = match;
  return `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`;
}

export default function WA03SignupInfo() {
  const navigation = useNavigation();
  const route = useRoute();
  const { access_token, refresh_token } = (route.params ?? {}) as {
    access_token: string;
    refresh_token: string;
  };
  const setAuth = useAuthStore((s) => s.setAuth);

  const [birth_date, set_birth_date] = useState("");
  const [height, set_height] = useState("");
  const [weight, set_weight] = useState("");
  const [skeletal_muscle, set_skeletal_muscle] = useState("");
  const [body_fat, set_body_fat] = useState("");
  const [gender, set_gender] = useState<Gender>("male");
  const [experience, set_experience] = useState<Experience | null>(null);
  const [show_date_picker, set_show_date_picker] = useState(false);
  const [loading, set_loading] = useState(false);
  const [ocr_loading, set_ocr_loading] = useState(false);

  const run_ocr = async (source: "camera" | "library") => {
    try {
      const perm =
        source === "camera"
          ? await ImagePicker.requestCameraPermissionsAsync()
          : await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        Alert.alert("권한 필요", "사진 접근 권한을 허용해주세요.");
        return;
      }
      const result =
        source === "camera"
          ? await ImagePicker.launchCameraAsync({ quality: 0.5 })
          : await ImagePicker.launchImageLibraryAsync({ quality: 0.5 });
      if (result.canceled || !result.assets?.[0]?.uri) return;
      set_ocr_loading(true);
      const asset = result.assets[0];
      const base64 = await FileSystem.readAsStringAsync(asset.uri, {
        encoding: FileSystem.EncodingType.Base64,
      });
      const mime = asset.mimeType ?? "image/jpeg";
      const m = await ocrInbody(access_token, base64, mime);
      if (m.weight_kg != null) set_weight(String(m.weight_kg));
      if (m.skeletal_muscle_kg != null) set_skeletal_muscle(String(m.skeletal_muscle_kg));
      if (m.body_fat_pct != null) set_body_fat(String(m.body_fat_pct));
      Alert.alert(
        "인식 완료",
        "추출된 값을 확인하고 수정 후 회원가입해주세요.",
      );
    } catch (e: any) {
      Alert.alert(
        "인식 실패",
        e.message ?? "더 선명한 사진으로 다시 시도해주세요.",
      );
    } finally {
      set_ocr_loading(false);
    }
  };

  const handle_ocr = () => {
    Alert.alert("인바디 결과지 입력", "사진을 선택하세요", [
      { text: "카메라로 촬영", onPress: () => run_ocr("camera") },
      { text: "갤러리에서 선택", onPress: () => run_ocr("library") },
      { text: "취소", style: "cancel" },
    ]);
  };

  const experiences: Experience[] = ["헬린이", "초급", "중급", "고급"];

  const handle_signup = async () => {
    if (!birth_date || !height || !weight || !experience) {
      Alert.alert("알림", "필수 항목을 입력해주세요.");
      return;
    }
    const height_num = parseFloat(height);
    const weight_num = parseFloat(weight);
    if (isNaN(height_num) || height_num <= 0) {
      Alert.alert("알림", "키를 올바르게 입력해주세요.");
      return;
    }
    if (isNaN(weight_num) || weight_num <= 0) {
      Alert.alert("알림", "몸무게를 올바르게 입력해주세요.");
      return;
    }

    set_loading(true);
    try {
      const skeletal_num = skeletal_muscle ? parseFloat(skeletal_muscle) : undefined;
      const fat_num = body_fat ? parseFloat(body_fat) : undefined;
      await onboardUser(
        {
          gender,
          birth_date: parse_birth_date(birth_date),
          height_cm: height_num,
          weight_kg: weight_num,
          skeletal_muscle_kg: skeletal_num && !isNaN(skeletal_num) ? skeletal_num : undefined,
          body_fat_pct: fat_num && !isNaN(fat_num) ? fat_num : undefined,
          career_level: CAREER_MAP[experience],
        },
        access_token,
      );
      const sm = skeletal_muscle.trim() !== "" ? parseFloat(skeletal_muscle) : undefined;
      const bf = body_fat.trim() !== "" ? parseFloat(body_fat) : undefined;
      if ((sm !== undefined && !isNaN(sm)) || (bf !== undefined && !isNaN(bf))) {
        await updateBody(access_token, {
          weight_kg: weight_num,
          ...(sm !== undefined && !isNaN(sm) ? { skeletal_muscle_kg: sm } : {}),
          ...(bf !== undefined && !isNaN(bf) ? { body_fat_pct: bf } : {}),
        });
      }
      await setAuth({
        access_token,
        refresh_token,
        is_new_user: true,
      });
    } catch (e: any) {
      Alert.alert(
        "오류",
        e.message ?? "신체 정보 등록에 실패했어요. 다시 시도해주세요.",
      );
    } finally {
      set_loading(false);
    }
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

            {/* 인바디 OCR */}
            <TouchableOpacity
              style={[styles.ocr_button, ocr_loading && styles.button_disabled]}
              onPress={handle_ocr}
              disabled={ocr_loading}
              activeOpacity={0.8}
            >
              {ocr_loading ? (
                <ActivityIndicator color={colors.primary} />
              ) : (
                <>
                  <Octicons name="device-camera" size={18} color={colors.primary} />
                  <Text style={styles.ocr_button_text}>
                    인바디 결과지 사진으로 자동 입력
                  </Text>
                </>
              )}
            </TouchableOpacity>

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

            {/* 골격근량 / 체지방률 */}
            <View style={styles.row}>
              <View style={[styles.field, styles.flex]}>
                <Text style={styles.label}>골격근량 (선택)</Text>
                <View style={styles.inputRow}>
                  <TextInput
                    style={[styles.inputInner, styles.flex]}
                    placeholder="골격근량"
                    placeholderTextColor={colors.border}
                    value={skeletal_muscle}
                    onChangeText={set_skeletal_muscle}
                    keyboardType="numeric"
                  />
                  <Text style={styles.unit}>kg</Text>
                </View>
              </View>
              <View style={[styles.field, styles.flex]}>
                <Text style={styles.label}>체지방률 (선택)</Text>
                <View style={styles.inputRow}>
                  <TextInput
                    style={[styles.inputInner, styles.flex]}
                    placeholder="체지방률"
                    placeholderTextColor={colors.border}
                    value={body_fat}
                    onChangeText={set_body_fat}
                    keyboardType="numeric"
                  />
                  <Text style={styles.unit}>%</Text>
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

            {/* 회원가입 버튼 */}
            <TouchableOpacity
              style={[styles.button, loading && { opacity: 0.5 }]}
              onPress={handle_signup}
              disabled={loading}
              activeOpacity={0.8}
            >
              {loading ? (
                <ActivityIndicator color={colors.white} />
              ) : (
                <Text style={styles.buttonText}>회원가입</Text>
              )}
            </TouchableOpacity>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>

      {/* 생년월일 바텀시트 */}
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
  dotInactive: { backgroundColor: colors.button },
  field: { gap: 8 },
  label: { fontFamily: "medium", fontSize: 16, color: colors.primary },
  row: { flexDirection: "row", gap: 7 },
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
  inputText: { fontFamily: "regular", fontSize: 14, color: colors.primary },
  placeholderText: { color: colors.border },
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
  selectButtonActive: { backgroundColor: colors.primary },
  selectButtonText: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.primary,
  },
  selectButtonTextActive: { color: colors.white },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    justifyContent: "center",
  },
  buttonText: { fontFamily: "medium", fontSize: 16, color: colors.white },
  ocr_button: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    borderWidth: 1,
    borderColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
  },
  ocr_button_text: {
    fontFamily: "medium",
    fontSize: 14,
    color: colors.primary,
  },
  button_disabled: { opacity: 0.5 },
});
