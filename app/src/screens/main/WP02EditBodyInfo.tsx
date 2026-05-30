import { useState, useEffect, useCallback } from "react";
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
import { useNavigation } from "@react-navigation/native";
import { Octicons } from "@expo/vector-icons";
import { colors } from "../../assets/colors/colors";
import { useAuthStore } from "../../stores/authStore";
import { getMe, updateBody } from "../../services/users";
import BirthDateBottomSheet from "../../components/WA03SignupBs";

type Gender = "female" | "male";

/** "YYYY-MM-DD" → "YYYY년 M월 D일" */
function api_to_display(date_str: string): string {
  const [y, m, d] = date_str.split("-").map(Number);
  return `${y}년 ${m}월 ${d}일`;
}

/** "YYYY년 M월 D일" → "YYYY-MM-DD" */
function display_to_api(display: string): string {
  const match = display.match(/(\d+)년\s*(\d+)월\s*(\d+)일/);
  if (!match) return "";
  const [, y, m, d] = match;
  return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

export default function WP02EditBodyInfo() {
  const navigation = useNavigation();
  const token = useAuthStore((s) => s.accessToken) ?? "";

  const [birth_date, set_birth_date] = useState(""); // "YYYY년 M월 D일"
  const [height, set_height] = useState("");
  const [weight, set_weight] = useState("");
  const [gender, set_gender] = useState<Gender>("male");
  const [show_date_picker, set_show_date_picker] = useState(false);
  const [loading, set_loading] = useState(true);
  const [saving, set_saving] = useState(false);

  const load_data = useCallback(async () => {
    try {
      const me = await getMe(token);
      const p = me.profile;
      if (p?.birth_date) set_birth_date(api_to_display(p.birth_date));
      if (p?.height_cm) set_height(String(p.height_cm));
      if (me.latest_measurement?.weight_kg)
        set_weight(String(me.latest_measurement.weight_kg));
      if (p?.gender === "female" || p?.gender === "male")
        set_gender(p.gender);
    } catch (e) {
      console.warn("신체 정보 프리필 실패:", e);
    } finally {
      set_loading(false);
    }
  }, [token]);

  useEffect(() => {
    load_data();
  }, [load_data]);

  const handle_date_confirm = (date: string) => {
    set_birth_date(date);
    set_show_date_picker(false);
  };

  const handle_save = async () => {
    const h = height.trim() !== "" ? parseFloat(height) : undefined;
    const w = weight.trim() !== "" ? parseFloat(weight) : undefined;
    if (h !== undefined && isNaN(h)) {
      Alert.alert("알림", "키를 올바르게 입력해주세요.");
      return;
    }
    if (w !== undefined && isNaN(w)) {
      Alert.alert("알림", "몸무게를 올바르게 입력해주세요.");
      return;
    }
    set_saving(true);
    try {
      await updateBody(token, {
        ...(h !== undefined ? { height_cm: h } : {}),
        ...(w !== undefined ? { weight_kg: w } : {}),
        ...(birth_date ? { birth_date: display_to_api(birth_date) } : {}),
        gender,
      });
      navigation.goBack();
    } catch (e: any) {
      Alert.alert("오류", e.message ?? "저장에 실패했어요.");
    } finally {
      set_saving(false);
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
        <ScrollView
          contentContainerStyle={styles.scroll}
          showsVerticalScrollIndicator={false}
        >
          {loading ? (
            <ActivityIndicator
              color={colors.primary}
              style={{ marginTop: 40 }}
            />
          ) : (
            <View style={styles.card}>
              <Text style={styles.card_title}>신체 정보 수정</Text>

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
                      styles.input_text,
                      !birth_date && styles.input_placeholder,
                    ]}
                  >
                    {birth_date || "생년월일 선택"}
                  </Text>
                </TouchableOpacity>
              </View>

              {/* 키 / 몸무게 */}
              <View style={styles.row}>
                <View style={[styles.field, styles.flex]}>
                  <Text style={styles.label}>키</Text>
                  <View style={styles.input_row}>
                    <TextInput
                      style={[styles.input_inner, styles.flex]}
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
                  <View style={styles.input_row}>
                    <TextInput
                      style={[styles.input_inner, styles.flex]}
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
                      styles.select_button,
                      gender === "female" && styles.select_button_active,
                    ]}
                    onPress={() => set_gender("female")}
                    activeOpacity={0.8}
                  >
                    <Text
                      style={[
                        styles.select_button_text,
                        gender === "female" && styles.select_button_text_active,
                      ]}
                    >
                      여성
                    </Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[
                      styles.select_button,
                      gender === "male" && styles.select_button_active,
                    ]}
                    onPress={() => set_gender("male")}
                    activeOpacity={0.8}
                  >
                    <Text
                      style={[
                        styles.select_button_text,
                        gender === "male" && styles.select_button_text_active,
                      ]}
                    >
                      남성
                    </Text>
                  </TouchableOpacity>
                </View>
              </View>

              {/* 저장 버튼 */}
              <TouchableOpacity
                style={[styles.button, saving && styles.button_disabled]}
                onPress={handle_save}
                disabled={saving}
                activeOpacity={0.8}
              >
                <Text style={styles.button_text}>
                  {saving ? "저장 중..." : "저장하기"}
                </Text>
              </TouchableOpacity>
            </View>
          )}
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
  card_title: {
    fontFamily: "semibold",
    fontSize: 18,
    color: colors.primary,
    textAlign: "center",
  },
  field: { gap: 8 },
  label: { fontFamily: "medium", fontSize: 16, color: colors.primary },
  row: { flexDirection: "row", gap: 7 },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 10,
    justifyContent: "center",
  },
  input_text: { fontFamily: "regular", fontSize: 14, color: colors.primary },
  input_placeholder: { color: colors.border },
  input_row: {
    flexDirection: "row",
    alignItems: "center",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 10,
  },
  input_inner: {
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
  select_button: {
    flex: 1,
    backgroundColor: colors.select,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
  },
  select_button_active: { backgroundColor: colors.primary },
  select_button_text: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.primary,
  },
  select_button_text_active: { color: colors.white },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
  },
  button_disabled: { opacity: 0.5 },
  button_text: { fontFamily: "medium", fontSize: 16, color: colors.white },
});
