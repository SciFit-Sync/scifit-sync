import { useState } from "react";
import {
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation } from "@react-navigation/native";
import { Octicons } from "@expo/vector-icons";
import { colors } from "../../assets/colors/colors";

export default function WO02EquipmentRegister() {
  const navigation = useNavigation();
  const [equipment_name, set_equipment_name] = useState("");
  const [brand_name, set_brand_name] = useState("");

  const handle_register = () => {
    // TODO: 기구 등록 API 연동
    console.log("기구 등록:", { equipment_name, brand_name });
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
        <View style={styles.scroll}>
          <View style={styles.card}>
            <Text style={styles.card_title}>기구 등록하기</Text>

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
              <Text style={styles.label}>브랜드명</Text>
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
              style={[
                styles.register_button,
                (!equipment_name || !brand_name) &&
                  styles.register_button_disabled,
              ]}
              onPress={handle_register}
              disabled={!equipment_name || !brand_name}
              activeOpacity={0.8}
            >
              <Text style={styles.register_button_text}>등록하기</Text>
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
    paddingTop: 16,
    paddingBottom: 24,
  },
  logo: { fontFamily: "sacheon", fontSize: 20, color: colors.primary },
  placeholder: { width: 32 },
  scroll: {
    flex: 1,
    paddingHorizontal: 24,
    paddingBottom: 32,
  },
  card: {
    flex: 1,
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
    fontFamily: "semibold",
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
  spacer: { flex: 1 },
  register_button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    justifyContent: "center",
  },
  register_button_disabled: { opacity: 0.5 },
  register_button_text: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.white,
  },
});
