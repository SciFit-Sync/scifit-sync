import { useState } from "react";
import {
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation } from "@react-navigation/native";
import { Octicons } from "@expo/vector-icons";
import { colors } from "../../assets/colors/colors";

interface Equipment {
  id: string;
  name: string;
  spec: string;
  brand: string;
}

const brands = ["전체", "브랜드1", "브랜드2", "브랜드3", "브랜드4"];

const mock_equipment: Equipment[] = [
  {
    id: "1",
    name: "케이블 크로스오버",
    spec: "도르래 2:1 스택 2.3kg",
    brand: "브랜드1",
  },
  { id: "2", name: "렛풀다운", spec: "도르래 1:1 스택 5kg", brand: "브랜드2" },
  {
    id: "3",
    name: "케이블 로우",
    spec: "도르래 1.5:1 스택 5kg",
    brand: "브랜드2",
  },
  { id: "4", name: "레그프레스", spec: "스택 100kg", brand: "브랜드3" },
  { id: "5", name: "스미스머신", spec: "바벨 20kg", brand: "브랜드1" },
  { id: "6", name: "인클라인 벤치프레스", spec: "스택 80kg", brand: "브랜드3" },
  {
    id: "7",
    name: "펙덱 플라이",
    spec: "도르래 1:1 스택 10kg",
    brand: "브랜드4",
  },
  {
    id: "8",
    name: "시티드 로우",
    spec: "도르래 2:1 스택 5kg",
    brand: "브랜드4",
  },
  { id: "9", name: "레그 컬", spec: "스택 60kg", brand: "브랜드2" },
  { id: "10", name: "레그 익스텐션", spec: "스택 60kg", brand: "브랜드1" },
];

export default function WO02Equipment() {
  const navigation = useNavigation();
  const [search, set_search] = useState("");
  const [selected_brand, set_selected_brand] = useState("전체");
  const [selected_ids, set_selected_ids] = useState<string[]>([]);

  const filtered = mock_equipment.filter((e) => {
    const match_brand = selected_brand === "전체" || e.brand === selected_brand;
    const match_search = search === "" || e.name.includes(search);
    return match_brand && match_search;
  });

  const toggle_equipment = (id: string) => {
    set_selected_ids((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id],
    );
  };

  const handle_next = () => {
    navigation.navigate("WO03OneRM" as never);
  };

  const handle_skip = () => {
    navigation.navigate("WO03OneRM" as never);
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

      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
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
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            <View style={styles.brand_row}>
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
                      selected_brand === brand && styles.brand_chip_text_active,
                    ]}
                  >
                    {brand}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
          </ScrollView>

          {/* 기구 리스트 - 이 부분만 스크롤 */}
          <ScrollView
            style={styles.equipment_scroll}
            showsVerticalScrollIndicator={false}
            nestedScrollEnabled={true}
          >
            <View style={styles.equipment_list}>
              {filtered.map((item) => {
                const is_selected = selected_ids.includes(item.id);
                return (
                  <TouchableOpacity
                    key={item.id}
                    style={[
                      styles.equipment_item,
                      is_selected && styles.equipment_item_active,
                    ]}
                    onPress={() => toggle_equipment(item.id)}
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
                      <Text style={styles.equipment_spec}>{item.spec}</Text>
                    </View>
                  </TouchableOpacity>
                );
              })}

              {/* 기구 추가 버튼 */}
              <TouchableOpacity
                style={styles.add_button}
                activeOpacity={0.8}
                onPress={() =>
                  navigation.navigate("WO02EquipmentRegister" as never)
                }
              >
                <Octicons name="plus" size={16} color={colors.primary} />
              </TouchableOpacity>
            </View>
          </ScrollView>

          {/* 다음 / 건너뛰기 */}
          <TouchableOpacity
            style={styles.next_button}
            onPress={handle_next}
            activeOpacity={0.8}
          >
            <Text style={styles.next_button_text}>다음</Text>
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
    paddingTop: 16,
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
  brand_row: {
    flexDirection: "row",
    gap: 4,
  },
  brand_chip: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 100,
    backgroundColor: colors.white,
  },
  brand_chip_active: {
    backgroundColor: colors.primary,
    shadowOpacity: 0,
    elevation: 0,
  },
  brand_chip_text: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.bluegray,
  },
  brand_chip_text_active: {
    color: colors.white,
  },
  equipment_scroll: {
    maxHeight: 308,
    marginBottom: 24,
  },
  equipment_list: {
    gap: 8,
  },
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
  equipment_info: { gap: 8 },
  equipment_name: {
    fontFamily: "regular",
    fontSize: 16,
    color: colors.primary,
  },
  equipment_name_active: { color: colors.white },
  equipment_spec: {
    fontFamily: "regular",
    fontSize: 14,
    color: "#C8D5FF",
  },
  add_button: {
    backgroundColor: colors.select,
    borderRadius: 8,
    height: 35,
    alignItems: "center",
    justifyContent: "center",
  },
  next_button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    justifyContent: "center",
  },
  next_button_text: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.white,
  },
  skip_text: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.primary,
    textAlign: "center",
  },
});
