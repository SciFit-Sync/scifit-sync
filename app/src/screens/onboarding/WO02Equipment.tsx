import { useState, useEffect } from "react";
import {
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  ScrollView,
  Alert,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation, useRoute } from "@react-navigation/native";
import { Octicons } from "@expo/vector-icons";
import { colors } from "../../assets/colors/colors";
import { useAuthStore } from "../../stores/authStore";
import {
  getEquipmentBrands,
  getEquipment,
  selectEquipment,
  BrandItem,
  EquipmentItem,
} from "../../services/gyms";

export default function WO02Equipment() {
  const navigation = useNavigation();
  const route = useRoute();
  const { gym_id } = (route.params ?? {}) as { gym_id: string | null };
  const token = useAuthStore((s) => s.accessToken) ?? "";

  const [search, set_search] = useState("");
  const [brands, set_brands] = useState<BrandItem[]>([]);
  const [selected_brand_id, set_selected_brand_id] = useState<string | null>(null);
  const [equipment_list, set_equipment_list] = useState<EquipmentItem[]>([]);
  const [selected_ids, set_selected_ids] = useState<string[]>([]);
  const [brands_loading, set_brands_loading] = useState(true);
  const [equipment_loading, set_equipment_loading] = useState(true);
  const [next_loading, set_next_loading] = useState(false);

  // 브랜드 목록 로드
  useEffect(() => {
    (async () => {
      try {
        const data = await getEquipmentBrands(token);
        set_brands(data);
      } catch {
        // 브랜드 로드 실패해도 계속 진행
      } finally {
        set_brands_loading(false);
      }
    })();
  }, [token]);

  // 기구 목록 로드 (검색어 / 브랜드 변경 시 재조회)
  useEffect(() => {
    const timer = setTimeout(async () => {
      set_equipment_loading(true);
      try {
        const data = await getEquipment(
          {
            keyword: search || undefined,
            brand_id: selected_brand_id ?? undefined,
          },
          token,
        );
        set_equipment_list(data);
      } catch {
        set_equipment_list([]);
      } finally {
        set_equipment_loading(false);
      }
    }, 300); // 300ms 디바운스
    return () => clearTimeout(timer);
  }, [search, selected_brand_id, token]);

  const toggle_equipment = (id: string) => {
    set_selected_ids((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id],
    );
  };

  const handle_next = async () => {
    if (selected_ids.length === 0) {
      // 선택 없이 다음 → 건너뛰기와 동일
      (navigation as any).navigate("WO03OneRM");
      return;
    }
    set_next_loading(true);
    try {
      await selectEquipment(selected_ids, token);
      (navigation as any).navigate("WO03OneRM");
    } catch (e: any) {
      Alert.alert("오류", e.message ?? "기구 저장에 실패했어요. 다시 시도해주세요.");
    } finally {
      set_next_loading(false);
    }
  };

  const handle_skip = () => {
    (navigation as any).navigate("WO03OneRM");
  };

  const ALL_BRAND_ID = "__all__";

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

      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.card}>
          <Text style={styles.card_title}>기구 설정</Text>

          {/* 검색창 */}
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
                <Octicons name="x" size={16} color={colors.border} />
              </TouchableOpacity>
            )}
          </View>

          {/* 브랜드 필터 */}
          {!brands_loading && (
            <ScrollView horizontal showsHorizontalScrollIndicator={false}>
              <View style={styles.brand_row}>
                {/* 전체 칩 */}
                <TouchableOpacity
                  style={[
                    styles.brand_chip,
                    selected_brand_id === null && styles.brand_chip_active,
                  ]}
                  onPress={() => set_selected_brand_id(null)}
                  activeOpacity={0.8}
                >
                  <Text
                    style={[
                      styles.brand_chip_text,
                      selected_brand_id === null && styles.brand_chip_text_active,
                    ]}
                  >
                    전체
                  </Text>
                </TouchableOpacity>

                {brands.map((brand) => (
                  <TouchableOpacity
                    key={brand.brand_id}
                    style={[
                      styles.brand_chip,
                      selected_brand_id === brand.brand_id && styles.brand_chip_active,
                    ]}
                    onPress={() => set_selected_brand_id(brand.brand_id)}
                    activeOpacity={0.8}
                  >
                    <Text
                      style={[
                        styles.brand_chip_text,
                        selected_brand_id === brand.brand_id &&
                          styles.brand_chip_text_active,
                      ]}
                    >
                      {brand.name}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
            </ScrollView>
          )}

          {/* 기구 리스트 */}
          <ScrollView
            style={styles.equipment_scroll}
            showsVerticalScrollIndicator={false}
            nestedScrollEnabled={true}
          >
            {equipment_loading ? (
              <ActivityIndicator color={colors.primary} style={{ marginVertical: 20 }} />
            ) : (
              <View style={styles.equipment_list}>
                {equipment_list.map((item) => {
                  const is_selected = selected_ids.includes(item.equipment_id);
                  return (
                    <TouchableOpacity
                      key={item.equipment_id}
                      style={[
                        styles.equipment_item,
                        is_selected && styles.equipment_item_active,
                      ]}
                      onPress={() => toggle_equipment(item.equipment_id)}
                      activeOpacity={0.8}
                    >
                      <View style={styles.equipment_image_box} />
                      <View style={styles.equipment_info}>
                        <Text
                          style={[
                            styles.equipment_name,
                            is_selected && styles.equipment_name_active,
                          ]}
                        >
                          {item.name}
                        </Text>
                        <Text style={styles.equipment_spec}>
                          {item.brand ?? ""}
                          {item.equipment_type ? ` · ${item.equipment_type}` : ""}
                        </Text>
                      </View>
                    </TouchableOpacity>
                  );
                })}

                {equipment_list.length === 0 && !equipment_loading && (
                  <Text style={styles.empty_text}>기구 목록이 없어요</Text>
                )}

                {/* 기구 추가 버튼 */}
                <TouchableOpacity
                  style={styles.add_button}
                  activeOpacity={0.8}
                  onPress={() =>
                    (navigation as any).navigate("WO02EquipmentRegister")
                  }
                >
                  <Octicons name="plus" size={16} color={colors.primary} />
                </TouchableOpacity>
              </View>
            )}
          </ScrollView>

          {/* 선택 개수 표시 */}
          {selected_ids.length > 0 && (
            <Text style={styles.selected_count}>
              {selected_ids.length}개 선택됨
            </Text>
          )}

          {/* 다음 / 건너뛰기 */}
          <TouchableOpacity
            style={[styles.next_button, next_loading && { opacity: 0.5 }]}
            onPress={handle_next}
            disabled={next_loading}
            activeOpacity={0.8}
          >
            <Text style={styles.next_button_text}>
              {next_loading ? "저장 중..." : "다음"}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={handle_skip}>
            <Text style={styles.skip_text}>건너뛰기</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>
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
  brand_row: { flexDirection: "row", gap: 4 },
  brand_chip: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 100,
    backgroundColor: colors.white,
  },
  brand_chip_active: { backgroundColor: colors.primary },
  brand_chip_text: { fontFamily: "regular", fontSize: 14, color: colors.bluegray },
  brand_chip_text_active: { color: colors.white },
  equipment_scroll: { maxHeight: 308, marginBottom: 8 },
  equipment_list: { gap: 8 },
  equipment_item: {
    backgroundColor: colors.select,
    borderRadius: 8,
    height: 70,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 7,
    gap: 10,
  },
  equipment_item_active: { backgroundColor: colors.primary },
  equipment_image_box: {
    width: 56,
    height: 56,
    borderRadius: 4,
    backgroundColor: colors.border,
  },
  equipment_info: { gap: 4 },
  equipment_name: { fontFamily: "regular", fontSize: 14, color: colors.primary },
  equipment_name_active: { color: colors.white },
  equipment_spec: { fontFamily: "regular", fontSize: 12, color: colors.bluegray },
  add_button: {
    backgroundColor: colors.select,
    borderRadius: 8,
    height: 35,
    alignItems: "center",
    justifyContent: "center",
  },
  selected_count: {
    fontFamily: "medium",
    fontSize: 13,
    color: colors.primary,
    textAlign: "center",
  },
  empty_text: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.bluegray,
    textAlign: "center",
    paddingVertical: 20,
  },
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
