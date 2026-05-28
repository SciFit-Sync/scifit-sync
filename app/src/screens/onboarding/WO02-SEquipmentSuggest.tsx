import { useState } from "react";
import {
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  KeyboardAvoidingView,
  Platform,
  Alert,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation, useRoute } from "@react-navigation/native";
import { Octicons } from "@expo/vector-icons";
import { colors } from "../../assets/colors/colors";
import { useAuthStore } from "../../stores/authStore";
import { suggestGymEquipment } from "../../services/gyms";

export default function WO02EquipmentSuggest() {
  const navigation = useNavigation();
  const route = useRoute();
  const { gym_id } = (route.params ?? {}) as { gym_id: string | null };
  const token = useAuthStore((s) => s.accessToken) ?? "";

  const [equipment_name, set_equipment_name] = useState("");
  const [brand_name, set_brand_name] = useState("");
  const [loading, set_loading] = useState(false);

  const handle_submit = async () => {
    if (!equipment_name.trim()) return;
    if (!gym_id) {
      Alert.alert("알림", "헬스장 정보가 없어요.");
      return;
    }
    set_loading(true);
    try {
      await suggestGymEquipment(
        gym_id,
        { name: equipment_name.trim(), brand: brand_name.trim() || undefined },
        token,
      );
      Alert.alert("완료", "기구 제보가 접수됐어요. 검토 후 반영될 예정이에요.", [
        { text: "확인", onPress: () => navigation.goBack() },
      ]);
    } catch (e: any) {
      Alert.alert("오류", e.message ?? "제보에 실패했어요. 다시 시도해주세요.");
    } finally {
      set_loading(false);
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
        <View style={styles.content}>
          <View style={styles.card}>
            <Text style={styles.card_title}>기구 제보하기</Text>

            {/* 기구명 */}
            <View style={styles.field}>
              <Text style={styles.label}>기구명</Text>
              <TextInput
                style={styles.input}
                placeholder="기구명 입력"
                placeholderTextColor={colors.border}
                value={equipment_name}
                onChangeText={set_equipment_name}
              />
            </View>

            {/* 브랜드명 */}
            <View style={styles.field}>
              <Text style={styles.label}>브랜드명 (선택)</Text>
              <TextInput
                style={styles.input}
                placeholder="브랜드명 입력"
                placeholderTextColor={colors.border}
                value={brand_name}
                onChangeText={set_brand_name}
              />
            </View>

            <View style={styles.spacer} />

            {/* 등록하기 버튼 */}
            <TouchableOpacity
              style={[styles.submit_button, (!equipment_name.trim() || loading) && styles.submit_button_disabled]}
              onPress={handle_submit}
              disabled={!equipment_name.trim() || loading}
              activeOpacity={0.8}
            >
              {loading ? (
                <ActivityIndicator color={colors.white} />
              ) : (
                <Text style={styles.submit_button_text}>등록하기</Text>
              )}
            </TouchableOpacity>
          </View>
        </View>
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
  content: { flex: 1, paddingHorizontal: 24, paddingBottom: 32 },
  card: { flex: 1, backgroundColor: colors.white, borderRadius: 16, padding: 20, gap: 16 },
  card_title: { fontFamily: "semibold", fontSize: 18, color: colors.primary, textAlign: "center" },
  field: { gap: 8 },
  label: { fontFamily: "semibold", fontSize: 16, color: colors.primary },
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
  spacer: { flex: 1 },
  submit_button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    justifyContent: "center",
    height: 44,
  },
  submit_button_disabled: { opacity: 0.5 },
  submit_button_text: { fontFamily: "medium", fontSize: 16, color: colors.white },
});
