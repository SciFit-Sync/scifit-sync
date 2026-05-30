import { useState, useEffect } from "react";
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
import {
  getMyOneRMs,
  getCoreLifts,
  bulkSaveOneRM,
  CoreLiftItem,
} from "../../services/users";

const CORE_LABELS: Record<string, string> = {
  bench_press: "벤치프레스",
  squat: "스쿼트",
  deadlift: "데드리프트",
  overhead_press: "오버헤드프레스",
};

const DISPLAY_ORDER = ["bench_press", "squat", "deadlift", "overhead_press"];

export default function WP05EditOneRM() {
  const navigation = useNavigation();
  const token = useAuthStore((s) => s.accessToken) ?? "";

  const [core_lifts, set_core_lifts] = useState<CoreLiftItem[]>([]);
  const [values, set_values] = useState<Record<string, string>>({});
  const [loading, set_loading] = useState(true);
  const [saving, set_saving] = useState(false);

  useEffect(() => {
    load_data();
  }, []);

  const load_data = async () => {
    try {
      const [lifts, one_rms] = await Promise.all([
        getCoreLifts(token),
        getMyOneRMs(token),
      ]);
      set_core_lifts(lifts);

      // 기존 1RM 값 pre-fill — exercise_id 기준 매칭
      const pre: Record<string, string> = {};
      for (const lift of lifts) {
        const match = one_rms.find((r) => r.exercise_id === lift.exercise_id);
        if (match) pre[lift.code] = String(match.weight_kg);
      }
      set_values(pre);
    } catch (e: any) {
      Alert.alert("오류", e.message ?? "데이터를 불러오지 못했어요.");
    } finally {
      set_loading(false);
    }
  };

  const handle_change = (code: string, value: string) => {
    set_values((prev) => ({ ...prev, [code]: value }));
  };

  const handle_save = async () => {
    const items = core_lifts
      .filter((l) => {
        const v = values[l.code];
        return v && v.trim().length > 0 && !isNaN(parseFloat(v));
      })
      .map((l) => ({
        exercise_code: l.code,
        weight_kg: parseFloat(values[l.code]),
      }));

    if (items.length === 0) {
      navigation.goBack();
      return;
    }

    set_saving(true);
    try {
      await bulkSaveOneRM(token, items);
      navigation.goBack();
    } catch (e: any) {
      Alert.alert("오류", e.message ?? "저장에 실패했어요.");
    } finally {
      set_saving(false);
    }
  };

  // core_lifts를 DISPLAY_ORDER 순서대로 정렬
  const ordered_lifts = DISPLAY_ORDER.map((code) =>
    core_lifts.find((l) => l.code === code),
  ).filter(Boolean) as CoreLiftItem[];

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
            <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
          ) : (
            <View style={styles.card}>
              <Text style={styles.card_title}>1RM 수정</Text>

              {/* 1RM 입력 */}
              {ordered_lifts.map((lift) => (
                <View key={lift.code} style={styles.exercise_row}>
                  <Text style={styles.exercise_label}>
                    {CORE_LABELS[lift.code] ?? lift.name}
                  </Text>
                  <View style={styles.input_container}>
                    <TextInput
                      style={styles.input}
                      placeholder="kg 입력"
                      placeholderTextColor={colors.border}
                      value={values[lift.code] ?? ""}
                      onChangeText={(v) => handle_change(lift.code, v)}
                      keyboardType="numeric"
                    />
                  </View>
                </View>
              ))}

              <View style={styles.spacer} />

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
    height: 30,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 5,
    justifyContent: "center",
    paddingHorizontal: 10,
  },
  input: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.primary,
    padding: 0,
  },
  spacer: { height: 16 },
  button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
  },
  button_disabled: { opacity: 0.5 },
  button_text: { fontFamily: "medium", fontSize: 16, color: colors.white },
});
