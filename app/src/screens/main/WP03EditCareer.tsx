import { useState, useEffect } from "react";
import {
  StyleSheet,
  Text,
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
import { getMe, updateCareer } from "../../services/users";

type Level = "beginner" | "novice" | "intermediate" | "advanced";

const LEVELS: { key: Level; label: string }[] = [
  { key: "beginner", label: "헬린이" },
  { key: "novice", label: "초급" },
  { key: "intermediate", label: "중급" },
  { key: "advanced", label: "고급" },
];

export default function WP03EditCareer() {
  const navigation = useNavigation();
  const token = useAuthStore((s) => s.accessToken) ?? "";

  const [level, set_level] = useState<Level>("intermediate");
  const [loading, set_loading] = useState(true);
  const [saving, set_saving] = useState(false);

  useEffect(() => {
    load_data();
  }, []);

  const load_data = async () => {
    try {
      const me = await getMe(token);
      const current = me.profile?.career_level as Level | undefined;
      if (current) set_level(current);
    } catch {
      // 기본값 유지
    } finally {
      set_loading(false);
    }
  };

  const handle_save = async () => {
    set_saving(true);
    try {
      await updateCareer(token, level);
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
            <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
          ) : (
            <View style={styles.card}>
              <Text style={styles.card_title}>운동 경력 수정</Text>

              {/* 운동 레벨 */}
              <View style={styles.field}>
                <Text style={styles.label}>운동 레벨</Text>
                <View style={styles.row}>
                  {LEVELS.slice(0, 2).map((l) => (
                    <TouchableOpacity
                      key={l.key}
                      style={[
                        styles.select_button,
                        level === l.key && styles.select_button_active,
                      ]}
                      onPress={() => set_level(l.key)}
                      activeOpacity={0.8}
                    >
                      <Text
                        style={[
                          styles.select_button_text,
                          level === l.key && styles.select_button_text_active,
                        ]}
                      >
                        {l.label}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>
                <View style={styles.row}>
                  {LEVELS.slice(2).map((l) => (
                    <TouchableOpacity
                      key={l.key}
                      style={[
                        styles.select_button,
                        level === l.key && styles.select_button_active,
                      ]}
                      onPress={() => set_level(l.key)}
                      activeOpacity={0.8}
                    >
                      <Text
                        style={[
                          styles.select_button_text,
                          level === l.key && styles.select_button_text_active,
                        ]}
                      >
                        {l.label}
                      </Text>
                    </TouchableOpacity>
                  ))}
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
