import { useState, useMemo, useCallback } from "react";
import {
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  ScrollView,
  ActivityIndicator,
  Image,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import {
  useNavigation,
  useRoute,
  useFocusEffect,
} from "@react-navigation/native";
import { Octicons } from "@expo/vector-icons";
import { colors } from "../../assets/colors/colors";
import { useAuthStore } from "../../stores/authStore";
import {
  getGymEquipment,
  deleteGymEquipment,
  EquipmentItem,
} from "../../services/gyms";

export default function WP04GymEquipment() {
  const navigation = useNavigation();
  const route = useRoute();
  const { gym_id, gym_name } = (route.params ?? {}) as {
    gym_id: string;
    gym_name: string;
  };
  const token = useAuthStore((s) => s.accessToken) ?? "";

  const [equipment_list, set_equipment_list] = useState<EquipmentItem[]>([]);
  const [loading, set_loading] = useState(false);
  const [search, set_search] = useState("");
  const [selected_brand, set_selected_brand] = useState<string | null>(null);

  const fetch_equipment = useCallback(async () => {
    set_loading(true);
    try {
      const data = await getGymEquipment(gym_id, token);
      set_equipment_list(data.equipment);
    } catch {
      set_equipment_list([]);
    } finally {
      set_loading(false);
    }
  }, [gym_id, token]);

  useFocusEffect(
    useCallback(() => {
      fetch_equipment();
    }, [fetch_equipment]),
  );

  // 브랜드 목록 — 로드된 기구에서 추출
  const brands = useMemo(() => {
    const seen = new Set<string>();
    const result: string[] = [];
    for (const item of equipment_list) {
      if (item.brand && !seen.has(item.brand)) {
        seen.add(item.brand);
        result.push(item.brand);
      }
    }
    return result;
  }, [equipment_list]);

  // 검색 + 브랜드 필터 적용
  const filtered_list = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    return equipment_list.filter((item) => {
      const matches_search =
        !keyword || item.name.toLowerCase().includes(keyword);
      const matches_brand = !selected_brand || item.brand === selected_brand;
      return matches_search && matches_brand;
    });
  }, [equipment_list, search, selected_brand]);

  const handle_add = () => {
    (navigation as any).navigate("WP04GymEquipmentRegister", { gym_id });
  };

  const handle_menu = (item: EquipmentItem) => {
    Alert.alert(item.name, undefined, [
      {
        text: "삭제",
        style: "destructive",
        onPress: async () => {
          set_equipment_list((prev) =>
            prev.filter((i) => i.equipment_id !== item.equipment_id),
          );
          try {
            await deleteGymEquipment(gym_id, item.equipment_id, token);
          } catch {
            fetch_equipment();
          }
        },
      },
      { text: "취소", style: "cancel" },
    ]);
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
            <TouchableOpacity
              style={styles.add_btn}
              onPress={handle_add}
              activeOpacity={0.8}
            >
              <Octicons name="plus" size={18} color={colors.white} />
            </TouchableOpacity>
          </View>

          {/* 기구가 있을 때만 검색창 + 브랜드 필터 표시 */}
          {equipment_list.length > 0 && (
            <View style={styles.search_filter_area}>
              <View style={styles.search_container}>
                <Octicons name="search" size={20} color={colors.border} />
                <TextInput
                  style={styles.search_input}
                  placeholder="기구 검색"
                  placeholderTextColor={colors.border}
                  value={search}
                  onChangeText={set_search}
                />
                {search.length > 0 && (
                  <TouchableOpacity onPress={() => set_search("")}>
                    <Octicons name="x" size={14} color={colors.border} />
                  </TouchableOpacity>
                )}
              </View>

              {brands.length > 0 && (
                <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                  <View style={styles.brand_row}>
                    <TouchableOpacity
                      style={[
                        styles.brand_chip,
                        selected_brand === null && styles.brand_chip_active,
                      ]}
                      onPress={() => set_selected_brand(null)}
                      activeOpacity={0.8}
                    >
                      <Text
                        style={[
                          styles.brand_chip_text,
                          selected_brand === null &&
                            styles.brand_chip_text_active,
                        ]}
                      >
                        전체
                      </Text>
                    </TouchableOpacity>
                    {brands.map((brand) => (
                      <TouchableOpacity
                        key={brand}
                        style={[
                          styles.brand_chip,
                          selected_brand === brand && styles.brand_chip_active,
                        ]}
                        onPress={() => set_selected_brand(brand)}
                        activeOpacity={0.8}
                      >
                        <Text
                          style={[
                            styles.brand_chip_text,
                            selected_brand === brand &&
                              styles.brand_chip_text_active,
                          ]}
                        >
                          {brand}
                        </Text>
                      </TouchableOpacity>
                    ))}
                  </View>
                </ScrollView>
              )}
            </View>
          )}

          {/* 기구 목록 */}
          <View style={styles.list_container}>
            {loading ? (
              <ActivityIndicator
                color={colors.primary}
                style={{ marginTop: 24 }}
              />
            ) : equipment_list.length === 0 ? (
              <View style={styles.empty_wrapper}>
                <Text style={styles.empty_text}>등록된 기구가 없어요.</Text>
                <TouchableOpacity onPress={handle_add} activeOpacity={0.8}>
                  <Text style={styles.empty_add_hint}>
                    <Text style={styles.plus_text}>+</Text> 버튼을 눌러 기구를
                    추가해 보세요.
                  </Text>
                </TouchableOpacity>
              </View>
            ) : filtered_list.length === 0 ? (
              <View style={styles.empty_wrapper}>
                <Text style={styles.empty_text}>검색 결과가 없어요.</Text>
              </View>
            ) : (
              <ScrollView
                showsVerticalScrollIndicator={false}
                keyboardShouldPersistTaps="handled"
                contentContainerStyle={styles.equipment_list}
              >
                {filtered_list.map((item) => (
                  <View key={item.equipment_id} style={styles.equipment_item}>
                    {item.image_url ? (
                      <Image
                        source={{ uri: item.image_url }}
                        style={styles.equipment_image}
                      />
                    ) : (
                      <View style={styles.equipment_image_placeholder} />
                    )}
                    <View style={styles.equipment_info}>
                      <Text style={styles.equipment_name}>{item.name}</Text>
                      <Text style={styles.equipment_spec}>
                        {[item.brand, item.equipment_type]
                          .filter(Boolean)
                          .join(" · ")}
                      </Text>
                    </View>
                    <TouchableOpacity
                      style={styles.menu_btn}
                      onPress={() => handle_menu(item)}
                      activeOpacity={0.7}
                      hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
                    >
                      <Octicons
                        name="kebab-horizontal"
                        size={14}
                        color={colors.bluegray}
                      />
                    </TouchableOpacity>
                  </View>
                ))}
              </ScrollView>
            )}
          </View>
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
  title_text_col: { gap: 2, flex: 1 },
  card_title: { fontFamily: "semibold", fontSize: 18, color: colors.primary },
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
  search_filter_area: { gap: 8 },
  search_container: {
    flexDirection: "row",
    alignItems: "center",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 10,
    height: 44,
    gap: 10,
  },
  search_input: {
    flex: 1,
    fontFamily: "regular",
    fontSize: 16,
    color: colors.primary,
  },
  brand_row: { flexDirection: "row", gap: 4, alignItems: "center" },
  brand_chip: {
    paddingHorizontal: 10,
    height: 30,
    borderRadius: 100,
    backgroundColor: colors.white,
    alignItems: "center",
    justifyContent: "center",
  },
  brand_chip_active: { backgroundColor: colors.primary },
  brand_chip_text: {
    fontFamily: "regular",
    fontSize: 13,
    color: colors.bluegray,
  },
  brand_chip_text_active: { color: colors.white },
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
  empty_add_hint: {
    fontFamily: "regular",
    fontSize: 13,
    color: colors.bluegray,
    textAlign: "center",
  },
  plus_text: { fontFamily: "semibold", color: colors.primary },
  equipment_list: { gap: 8 },
  equipment_item: {
    backgroundColor: colors.select,
    borderRadius: 8,
    height: 70,
    flexDirection: "row",
    alignItems: "center",
    padding: 8,
    gap: 8,
    position: "relative",
  },
  equipment_image: { width: 56, height: 56, borderRadius: 4 },
  equipment_image_placeholder: {
    width: 56,
    height: 56,
    borderRadius: 4,
    backgroundColor: colors.border,
  },
  equipment_info: { gap: 4, flex: 1 },
  equipment_name: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.primary,
  },
  equipment_spec: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
  },
  menu_btn: {
    position: "absolute",
    top: 6,
    right: 10,
    padding: 4,
  },
});
