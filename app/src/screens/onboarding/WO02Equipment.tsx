import { useState, useEffect, useCallback } from "react";
import {
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  ScrollView,
  ActivityIndicator,
  Image,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation, useRoute, useFocusEffect } from "@react-navigation/native";
import { Octicons } from "@expo/vector-icons";
import { colors } from "../../assets/colors/colors";
import { useAuthStore } from "../../stores/authStore";
import { getGymEquipment, EquipmentItem } from "../../services/gyms";

export default function WO02Equipment() {
  const navigation = useNavigation();
  const route = useRoute();
  const { gym_id } = (route.params ?? {}) as { gym_id: string | null };
  const token = useAuthStore((s) => s.accessToken) ?? "";

  const [equipment_list, set_equipment_list] = useState<EquipmentItem[]>([]);
  const [gym_name, set_gym_name] = useState<string | null>(null);
  const [loading, set_loading] = useState(false);

  const fetch_gym_equipment = useCallback(async () => {
    if (!gym_id) return;
    set_loading(true);
    try {
      const data = await getGymEquipment(gym_id, token);
      set_gym_name(data.gym_name);
      set_equipment_list(data.equipment);
    } catch {
      set_equipment_list([]);
    } finally {
      set_loading(false);
    }
  }, [gym_id, token]);

  // 기구 추가 화면에서 돌아올 때도 목록 새로고침
  useFocusEffect(
    useCallback(() => {
      fetch_gym_equipment();
    }, [fetch_gym_equipment]),
  );

  const handle_next = () => {
    (navigation as any).navigate("WO03OneRM");
  };

  const handle_skip = () => {
    (navigation as any).navigate("WO03OneRM");
  };

  const handle_add = () => {
    (navigation as any).navigate("WO02EquipmentRegister", { gym_id });
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

      <View style={styles.content}>
        <View style={styles.card}>
          {/* 타이틀 + + 버튼 */}
          <View style={styles.title_row}>
            <View style={styles.title_text_col}>
              <Text style={styles.card_title}>기구 목록</Text>
              {gym_name ? (
                <Text style={styles.gym_name_text}>{gym_name}</Text>
              ) : null}
            </View>
            <TouchableOpacity style={styles.add_btn} onPress={handle_add} activeOpacity={0.8}>
              <Octicons name="plus" size={18} color={colors.white} />
            </TouchableOpacity>
          </View>

          {/* 기구 목록 */}
          <View style={styles.list_container}>
            {loading ? (
              <ActivityIndicator color={colors.primary} style={{ marginTop: 24 }} />
            ) : !gym_id ? (
              <View style={styles.empty_wrapper}>
                <Text style={styles.empty_text}>헬스장을 선택하지 않았어요.</Text>
                <Text style={styles.empty_sub}>기구 목록을 이용하려면 헬스장을 설정해 주세요.</Text>
              </View>
            ) : equipment_list.length === 0 ? (
              <View style={styles.empty_wrapper}>
                <Text style={styles.empty_text}>등록된 기구가 없어요.</Text>
                <TouchableOpacity onPress={handle_add} activeOpacity={0.8}>
                  <Text style={styles.empty_add_hint}>
                    <Text style={styles.plus_text}>+</Text> 버튼을 눌러 기구를 추가해 보세요.
                  </Text>
                </TouchableOpacity>
              </View>
            ) : (
              <ScrollView
                showsVerticalScrollIndicator={false}
                keyboardShouldPersistTaps="handled"
                contentContainerStyle={styles.equipment_list}
              >
                {equipment_list.map((item) => (
                  <View key={item.equipment_id} style={styles.equipment_item}>
                    {item.image_url ? (
                      <Image source={{ uri: item.image_url }} style={styles.equipment_image} />
                    ) : (
                      <View style={styles.equipment_image_placeholder} />
                    )}
                    <View style={styles.equipment_info}>
                      <Text style={styles.equipment_name}>{item.name}</Text>
                      <Text style={styles.equipment_spec}>
                        {[item.brand, item.equipment_type].filter(Boolean).join(" · ")}
                      </Text>
                    </View>
                  </View>
                ))}
              </ScrollView>
            )}
          </View>

          {/* 다음 / 건너뛰기 */}
          <TouchableOpacity style={styles.next_button} onPress={handle_next} activeOpacity={0.8}>
            <Text style={styles.next_button_text}>다음</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={handle_skip}>
            <Text style={styles.skip_text}>건너뛰기</Text>
          </TouchableOpacity>
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
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
  card: {
    flex: 1,
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 20,
    gap: 16,
  },
  title_row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  title_text_col: {
    gap: 2,
    flex: 1,
  },
  card_title: {
    fontFamily: "semibold",
    fontSize: 18,
    color: colors.primary,
  },
  gym_name_text: {
    fontFamily: "regular",
    fontSize: 13,
    color: colors.bluegray,
  },
  add_btn: {
    width: 32,
    height: 32,
    borderRadius: 8,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  list_container: { flex: 1 },
  empty_wrapper: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  empty_text: {
    fontFamily: "medium",
    fontSize: 15,
    color: colors.primary,
    textAlign: "center",
  },
  empty_sub: {
    fontFamily: "regular",
    fontSize: 13,
    color: colors.bluegray,
    textAlign: "center",
  },
  empty_add_hint: {
    fontFamily: "regular",
    fontSize: 13,
    color: colors.bluegray,
    textAlign: "center",
  },
  plus_text: {
    fontFamily: "semibold",
    color: colors.primary,
  },
  equipment_list: { gap: 8 },
  equipment_item: {
    backgroundColor: colors.select,
    borderRadius: 8,
    height: 70,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 10,
    gap: 10,
  },
  equipment_image: {
    width: 56,
    height: 56,
    borderRadius: 4,
  },
  equipment_image_placeholder: {
    width: 56,
    height: 56,
    borderRadius: 4,
    backgroundColor: colors.border,
  },
  equipment_info: { gap: 4, flex: 1 },
  equipment_name: { fontFamily: "regular", fontSize: 14, color: colors.primary },
  equipment_spec: { fontFamily: "regular", fontSize: 12, color: colors.bluegray },
  next_button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    justifyContent: "center",
  },
  next_button_text: { fontFamily: "medium", fontSize: 16, color: colors.white },
  skip_text: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.primary,
    textAlign: "center",
  },
});
