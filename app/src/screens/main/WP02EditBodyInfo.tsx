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
import { getMe, updateBody } from "../../services/users";

export default function WP02EditBodyInfo() {
  const navigation = useNavigation();
  const token = useAuthStore((s) => s.accessToken) ?? "";

  const [height, set_height] = useState("");
  const [weight, set_weight] = useState("");
  const [loading, set_loading] = useState(true);
  const [saving, set_saving] = useState(false);

  useEffect(() => {
    load_data();
  }, []);

  const load_data = async () => {
    try {
      const me = await getMe(token);
      if (me.profile?.height_cm) set_height(String(me.profile.height_cm));
      if (me.latest_measurement?.weight_kg)
        set_weight(String(me.latest_measurement.weight_kg));
    } catch {
      // 기존 값 없으면 빈 입력으로 시작
    } finally {
      set_loading(false);
    }
  };

  const handle_save = async () => {
    const h = parseFloat(height);
    const w = parseFloat(weight);
    if (height && isNaN(h)) {
      Alert.alert("알림", "키를 올바르게 입력해주세요.");
      return;
    }
    if (weight && isNaN(w)) {
      Alert.alert("알림", "몸무게를 올바르게 입력해주세요.");
      return;
    }
    set_saving(true);
    try {
      await updateBody(token, {
        ...(height ? { height_cm: h } : {}),
        ...(weight ? { weight_kg: w } : {}),
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
            <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
          ) : (
            <View style={styles.card}>
              <Text style={styles.card_title}>신체 정보 수정</Text>

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
  button_disabled: { opacity: 0.5 },
  button_text: { fontFamily: "medium", fontSize: 16, color: colors.white },
});
