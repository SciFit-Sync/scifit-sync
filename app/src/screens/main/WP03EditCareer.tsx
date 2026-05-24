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
import { colors } from "../../assets/colors/colors";

type Level = "헬린이" | "초급" | "중급" | "고급";

const levels: Level[] = ["헬린이", "초급", "중급", "고급"];

export default function WP03EditCareer() {
  const navigation = useNavigation();
  const [level, set_level] = useState<Level>("중급");
  const [years, set_years] = useState("3");

  const handle_save = () => {
    // TODO: API 연동
    navigation.goBack();
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
            <Text style={styles.card_title}>운동 경력 수정</Text>

            {/* 운동 레벨 */}
            <View style={styles.field}>
              <Text style={styles.label}>운동 레벨</Text>
              <View style={styles.row}>
                {levels.slice(0, 2).map((l) => (
                  <TouchableOpacity
                    key={l}
                    style={[
                      styles.select_button,
                      level === l && styles.select_button_active,
                    ]}
                    onPress={() => set_level(l)}
                    activeOpacity={0.8}
                  >
                    <Text
                      style={[
                        styles.select_button_text,
                        level === l && styles.select_button_text_active,
                      ]}
                    >
                      {l}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
              <View style={styles.row}>
                {levels.slice(2).map((l) => (
                  <TouchableOpacity
                    key={l}
                    style={[
                      styles.select_button,
                      level === l && styles.select_button_active,
                    ]}
                    onPress={() => set_level(l)}
                    activeOpacity={0.8}
                  >
                    <Text
                      style={[
                        styles.select_button_text,
                        level === l && styles.select_button_text_active,
                      ]}
                    >
                      {l}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>

            {/* 저장 버튼 */}
            <TouchableOpacity
              style={styles.button}
              onPress={handle_save}
              activeOpacity={0.8}
            >
              <Text style={styles.button_text}>저장하기</Text>
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
  card_title: {
    fontFamily: "semibold",
    fontSize: 18,
    color: colors.primary,
    textAlign: "center",
  },
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
  select_button: {
    flex: 1,
    backgroundColor: colors.select,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
  },
  select_button_active: {
    backgroundColor: colors.primary,
  },
  select_button_text: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.primary,
  },
  select_button_text_active: {
    color: colors.white,
  },
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
  button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
  },
  button_text: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.white,
  },
});
