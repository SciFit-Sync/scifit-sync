import { useState, useEffect } from "react";
import {
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  ScrollView,
  ActivityIndicator,
  Alert,
  Image,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation, useRoute } from "@react-navigation/native";
import { Octicons } from "@expo/vector-icons";
import { colors } from "../../assets/colors/colors";
import { useAuthStore } from "../../stores/authStore";
import {
  getEquipmentBrands,
  getEquipment,
  addGymEquipmentBulk,
  BrandItem,
  EquipmentItem,
} from "../../services/gyms";

export default function WO02EquipmentRegister() {
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
  const [adding, set_adding] = useState(false);

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

  // 기구 목록 로드 (검색어 / 브랜드 변경 시 재조회, 300ms 디바운스)
  useEffect(() => {
    const timer = setTimeout(async () => {
      set_equipment_loading(true);
      try {
        const data = await getEquipment(
          { keyword: search || undefined, brand_id: selected_brand_id ?? undefined },
          token,
        );
        set_equipment_list(data);
      } catch {
        set_equipment_list([]);
      } finally {
        set_equipment_loading(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [search, selected_brand_id, token]);

  const toggle_equipment = (id: string) => {
    set_selected_ids((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id],
    );
  };

  const handle_add = async () => {
    if (selected_ids.length === 0) return;
    if (!gym_id) {
      Alert.alert("알림", "헬스장 정보가 없어요.");
      return;
    }
    set_adding(true);
    try {
      await addGymEquipmentBulk(gym_id, selected_ids, token);
      navigation.goBack();
    } catch (e: any) {
      Alert.alert("오류", e.message ?? "기구 추가에 실패했어요. 다시 시도해주세요.");
    } finally {
      set_adding(false);
    }
  };

  const handle_suggest = () => {
    (navigation as any).navigate("WO02EquipmentSuggest", { gym_id });
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
          <Text style={styles.card_title}>기구 추가</Text>

          {/* 검색창 + 브랜드 필터 */}
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
                  <Octicons name="x" size={16} color={colors.border} />
                </TouchableOpacity>
              )}
            </View>

            {!brands_loading && (
              <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                <View style={styles.brand_row}>
                  <TouchableOpacity
                    style={[styles.brand_chip, selected_brand_id === null && styles.brand_chip_active]}
                    onPress={() => set_selected_brand_id(null)}
                    activeOpacity={0.8}
                  >
                    <Text style={[styles.brand_chip_text, selected_brand_id === null && styles.brand_chip_text_active]}>
                      전체
                    </Text>
                  </TouchableOpacity>
                  {brands.map((brand) => (
                    <TouchableOpacity
                      key={brand.brand_id}
                      style={[styles.brand_chip, selected_brand_id === brand.brand_id && styles.brand_chip_active]}
                      onPress={() => set_selected_brand_id(brand.brand_id)}
                      activeOpacity={0.8}
                    >
                      <Text style={[styles.brand_chip_text, selected_brand_id === brand.brand_id && styles.brand_chip_text_active]}>
                        {brand.name}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </ScrollView>
            )}
          </View>

          {/* 기구 리스트 */}
          <View style={styles.list_container}>
            {equipment_loading ? (
              <ActivityIndicator color={colors.primary} style={{ marginTop: 24 }} />
            ) : (
              <ScrollView showsVerticalScrollIndicator={false} keyboardShouldPersistTaps="handled" contentContainerStyle={styles.equipment_list}>
                {equipment_list.map((item) => {
                  const is_selected = selected_ids.includes(item.equipment_id);
                  return (
                    <TouchableOpacity
                      key={item.equipment_id}
                      style={[styles.equipment_item, is_selected && styles.equipment_item_active]}
                      onPress={() => toggle_equipment(item.equipment_id)}
                      activeOpacity={0.8}
                    >
                      {item.image_url ? (
                        <Image source={{ uri: item.image_url }} style={styles.equipment_image} />
                      ) : (
                        <View style={styles.equipment_image_placeholder} />
                      )}
                      <View style={styles.equipment_info}>
                        <Text style={[styles.equipment_name, is_selected && styles.equipment_name_active]}>
                          {item.name}
                        </Text>
                        <Text style={styles.equipment_spec}>
                          {[item.brand, item.equipment_type].filter(Boolean).join(" · ")}
                        </Text>
                      </View>
                    </TouchableOpacity>
                  );
                })}

                {equipment_list.length === 0 && (
                  <View style={styles.empty_wrapper}>
                    <Text style={styles.empty_text}>검색 결과가 없어요.</Text>
                    <TouchableOpacity onPress={handle_suggest} activeOpacity={0.8}>
                      <Text style={styles.suggest_link}>기구 제보하기</Text>
                    </TouchableOpacity>
                  </View>
                )}
              </ScrollView>
            )}
          </View>

          {/* 선택 개수 + 제보 링크 */}
          <View style={styles.bottom_info}>
            {selected_ids.length > 0 ? (
              <Text style={styles.selected_count}>{selected_ids.length}개 선택됨</Text>
            ) : (
              <Text style={styles.hint_text}>원하는 기구를 선택해 주세요.</Text>
            )}
            <TouchableOpacity onPress={handle_suggest} activeOpacity={0.8}>
              <Text style={styles.suggest_link}>기구 제보하기</Text>
            </TouchableOpacity>
          </View>

          {/* 추가하기 버튼 */}
          <TouchableOpacity
            style={[styles.add_button, (selected_ids.length === 0 || adding) && styles.add_button_disabled]}
            onPress={handle_add}
            disabled={selected_ids.length === 0 || adding}
            activeOpacity={0.8}
          >
            <Text style={styles.add_button_text}>
              {adding ? "추가 중..." : "추가하기"}
            </Text>
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
  card: { flex: 1, backgroundColor: colors.white, borderRadius: 16, padding: 20, gap: 16 },
  card_title: { fontFamily: "semibold", fontSize: 18, color: colors.primary, textAlign: "center" },
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
  search_input: { flex: 1, fontFamily: "regular", fontSize: 16, color: colors.primary },
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
  brand_chip_text: { fontFamily: "regular", fontSize: 14, color: colors.bluegray },
  brand_chip_text_active: { color: colors.white },
  list_container: { flex: 1 },
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
  equipment_item_active: { backgroundColor: colors.primary },
  equipment_image: { width: 56, height: 56, borderRadius: 4 },
  equipment_image_placeholder: { width: 56, height: 56, borderRadius: 4, backgroundColor: colors.border },
  equipment_info: { gap: 4, flex: 1 },
  equipment_name: { fontFamily: "regular", fontSize: 14, color: colors.primary },
  equipment_name_active: { color: colors.white },
  equipment_spec: { fontFamily: "regular", fontSize: 12, color: colors.bluegray },
  empty_wrapper: { alignItems: "center", paddingVertical: 32, gap: 8 },
  empty_text: { fontFamily: "regular", fontSize: 14, color: colors.bluegray },
  bottom_info: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  selected_count: { fontFamily: "medium", fontSize: 13, color: colors.primary },
  hint_text: { fontFamily: "regular", fontSize: 13, color: colors.bluegray },
  suggest_link: { fontFamily: "regular", fontSize: 13, color: colors.bluegray, textDecorationLine: "underline" },
  add_button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    justifyContent: "center",
  },
  add_button_disabled: { opacity: 0.5 },
  add_button_text: { fontFamily: "medium", fontSize: 16, color: colors.white },
});
