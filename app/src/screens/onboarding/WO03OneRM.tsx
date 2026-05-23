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
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation } from "@react-navigation/native";
import { Octicons } from "@expo/vector-icons";
import { useAuthStore } from "../../stores/authStore";
import { colors } from "../../assets/colors/colors";

type WeightUnit = "kg" | "lb";

const exercises = [
  { key: "bench_press", label: "벤치프레스" },
  { key: "squat", label: "스쿼트" },
  { key: "deadlift", label: "데드리프트" },
  { key: "overhead_press", label: "오버헤드프레스" },
];

export default function WO03OneRM() {
  const navigation = useNavigation();
  const completeOnboarding = useAuthStore((s) => s.completeOnboarding);

  const [unit, set_unit] = useState<WeightUnit>("kg");
  const [values, set_values] = useState<Record<string, string>>({
    bench_press: "",
    squat: "",
    deadlift: "",
    overhead_press: "",
  });

  const handle_change = (key: string, value: string) => {
    set_values((prev) => ({ ...prev, [key]: value }));
  };

  const handle_register = async () => {
    // TODO: 1RM API 연동
    console.log("1RM 등록:", { unit, ...values });
    await completeOnboarding();
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
            <Text style={styles.card_title}>1RM 설정</Text>

            {/* 무게 단위 */}
            <View style={styles.unit_row}>
              <Text style={styles.unit_label}>무게 단위</Text>
              <View style={styles.unit_toggle}>
                <TouchableOpacity
                  style={[
                    styles.unit_button,
                    unit === "kg" && styles.unit_button_active,
                  ]}
                  onPress={() => set_unit("kg")}
                  activeOpacity={0.8}
                >
                  <Text
                    style={[
                      styles.unit_button_text,
                      unit === "kg" && styles.unit_button_text_active,
                    ]}
                  >
                    kg
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[
                    styles.unit_button,
                    unit === "lb" && styles.unit_button_active,
                  ]}
                  onPress={() => set_unit("lb")}
                  activeOpacity={0.8}
                >
                  <Text
                    style={[
                      styles.unit_button_text,
                      unit === "lb" && styles.unit_button_text_active,
                    ]}
                  >
                    lb
                  </Text>
                </TouchableOpacity>
              </View>
            </View>

            {/* 1RM 입력 */}
            {exercises.map((ex) => (
              <View key={ex.key} style={styles.exercise_row}>
                <Text style={styles.exercise_label}>{ex.label}</Text>
                <View style={styles.input_container}>
                  <TextInput
                    style={styles.input}
                    placeholder={`${unit} 입력`}
                    placeholderTextColor={colors.border}
                    value={values[ex.key]}
                    onChangeText={(v) => handle_change(ex.key, v)}
                    keyboardType="numeric"
                  />
                </View>
              </View>
            ))}

            <View style={styles.spacer} />

            {/* 등록하기 버튼 */}
            <TouchableOpacity
              style={styles.next_button}
              onPress={handle_register}
              activeOpacity={0.8}
            >
              <Text style={styles.next_button_text}>등록하기</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={handle_register}>
              <Text style={styles.skip_text}>건너뛰기</Text>
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
    paddingTop: 16,
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
  unit_row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  unit_label: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.bluegray,
  },
  unit_toggle: {
    flexDirection: "row",
    backgroundColor: colors.select,
    borderRadius: 8,
    padding: 4,
    width: 158,
    height: 35,
  },
  unit_button: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 4,
  },
  unit_button_active: {
    backgroundColor: colors.white,
    shadowColor: "#26272E",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.2,
    shadowRadius: 4,
    elevation: 2,
  },
  unit_button_text: {
    fontFamily: "medium",
    fontSize: 12,
    color: colors.bluegray,
  },
  unit_button_text_active: {
    color: colors.primary,
  },
  exercise_row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    height: 45,
  },
  exercise_label: {
    fontFamily: "semibold",
    fontSize: 16,
    color: colors.primary,
  },
  input_container: {
    width: 97,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 5,
    justifyContent: "center",
    paddingHorizontal: 10,
    paddingVertical: 10,
  },
  input: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.primary,
    padding: 0,
  },
  spacer: { height: 16 },
  next_button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    justifyContent: "center",
  },
  next_button_text: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.white,
  },
  skip_text: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.primary,
    textAlign: "center",
  },
});
