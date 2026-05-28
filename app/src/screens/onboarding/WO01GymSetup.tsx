import { useState, useEffect, useCallback } from "react";
import {
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  ScrollView,
  KeyboardAvoidingView,
  Platform,
  Linking,
  Alert,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation } from "@react-navigation/native";
import { Octicons } from "@expo/vector-icons";
import * as Location from "expo-location";
import { colors } from "../../assets/colors/colors";
import { useAuthStore } from "../../stores/authStore";
import { searchGyms, createGym, setMyGym, GymItem } from "../../services/gyms";

export default function WO01GymSetup() {
  const navigation = useNavigation();
  const token = useAuthStore((s) => s.accessToken) ?? "";

  const [search, set_search] = useState("");
  const [selected_gym, set_selected_gym] = useState<GymItem | null>(null);
  const [gyms, set_gyms] = useState<GymItem[]>([]);
  const [loading, set_loading] = useState(false);
  const [next_loading, set_next_loading] = useState(false);
  const [has_location_permission, set_has_location_permission] = useState<boolean | null>(null);
  const [coords, set_coords] = useState<{ lat: number; lng: number } | null>(null);

  useEffect(() => {
    check_location_permission();
  }, []);

  // 위치 권한 확인 + 있으면 좌표 취득 후 자동 검색
  const check_location_permission = async () => {
    const { status } = await Location.getForegroundPermissionsAsync();
    if (status === "granted") {
      set_has_location_permission(true);
      try {
        const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
        const new_coords = { lat: loc.coords.latitude, lng: loc.coords.longitude };
        set_coords(new_coords);
        // 좌표 확보 즉시 주변 헬스장 자동 검색
        await do_nearby_search(new_coords);
      } catch {
        // 위치 취득 실패 시 키워드 검색만 가능
      }
    } else {
      set_has_location_permission(false);
    }
  };

  const request_location_permission = async () => {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status === "granted") {
      set_has_location_permission(true);
      try {
        const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
        const new_coords = { lat: loc.coords.latitude, lng: loc.coords.longitude };
        set_coords(new_coords);
        await do_nearby_search(new_coords);
      } catch {}
    } else {
      Linking.openSettings();
    }
  };

  // 주변 헬스장 검색 (keyword 없음 → 백엔드에서 "헬스장"으로 거리순 검색)
  const do_nearby_search = async (c: { lat: number; lng: number }) => {
    set_loading(true);
    try {
      const results = await searchGyms("", token, c.lat, c.lng);
      set_gyms(results);
    } catch {
      set_gyms([]);
    } finally {
      set_loading(false);
    }
  };

  // 키워드 검색 실행
  const do_search = useCallback(
    async (keyword: string) => {
      set_loading(true);
      try {
        const results = await searchGyms(keyword, token, coords?.lat, coords?.lng);
        set_gyms(results);
      } catch {
        set_gyms([]);
      } finally {
        set_loading(false);
      }
    },
    [coords, token],
  );

  const handle_search_change = (v: string) => {
    set_search(v);
    set_selected_gym(null);
    if (v.length === 0) {
      // 검색어 지워지면 주변 헬스장 다시 표시 (좌표 있을 때)
      if (coords) {
        do_nearby_search(coords);
      } else {
        set_gyms([]);
      }
    }
    // 키워드 검색은 아래 useEffect 디바운스에서 처리
  };

  // 키워드 검색 — 300ms 디바운스
  useEffect(() => {
    if (search.length === 0) return;
    const timer = setTimeout(() => {
      do_search(search);
    }, 300);
    return () => clearTimeout(timer);
  }, [search, do_search]);

  // 다음 버튼 → 미등록이면 먼저 DB 등록 후 내 헬스장으로 저장
  const handle_next = async () => {
    if (!selected_gym) return;
    set_next_loading(true);
    try {
      let gym_id = selected_gym.gym_id;
      // DB에 없는 헬스장이면 자동 등록
      if (!gym_id) {
        const created = await createGym(selected_gym, token);
        gym_id = created.gym_id;
      }
      await setMyGym(gym_id, token);
      (navigation as any).navigate("WO02Equipment", { gym_id });
    } catch (e: any) {
      Alert.alert("오류", e.message ?? "헬스장 등록에 실패했어요. 다시 시도해주세요.");
    } finally {
      set_next_loading(false);
    }
  };

  const handle_skip = () => {
    (navigation as any).navigate("WO02Equipment", { gym_id: null });
  };

  return (
    <SafeAreaView style={styles.container}>
      {/* 헤더 — 온보딩 첫 단계이므로 뒤로가기 없음 */}
      <View style={styles.header}>
        <View style={styles.placeholder} />
        <Text style={styles.logo}>SciFit-Sync</Text>
        <View style={styles.placeholder} />
      </View>

      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        style={styles.flex}
      >
        {/* 카드가 나머지 공간을 꽉 채움 — 외부 ScrollView 없음 */}
        <View style={styles.content}>
          <View style={styles.card}>
            <Text style={styles.card_title}>헬스장 설정</Text>

            {/* 검색창 */}
            <View style={styles.search_container}>
              <Octicons name="search" size={20} color={colors.border} />
              <TextInput
                style={styles.search_input}
                placeholder="이용 중인 헬스장을 검색해 주세요."
                placeholderTextColor={colors.border}
                value={search}
                onChangeText={handle_search_change}
              />
              {search.length > 0 && (
                <TouchableOpacity onPress={() => handle_search_change("")}>
                  <Octicons name="x" size={16} color={colors.border} />
                </TouchableOpacity>
              )}
            </View>

            {/* 목록 영역 — flex: 1로 남은 공간 차지 + 내부만 스크롤 */}
            <View style={styles.list_container}>
              {loading || has_location_permission === null ? (
                /* 권한 확인 중이거나 검색 중 */
                <ActivityIndicator color={colors.primary} style={{ marginTop: 24 }} />
              ) : has_location_permission === false && search.length === 0 ? (
                /* 위치 권한 없을 때 버튼 */
                <View style={styles.location_button_wrapper}>
                  <TouchableOpacity
                    style={styles.location_button}
                    onPress={request_location_permission}
                    activeOpacity={0.8}
                  >
                    <Text style={styles.location_button_text}>위치 정보 동의하러 가기</Text>
                  </TouchableOpacity>
                </View>
              ) : gyms.length > 0 ? (
                <ScrollView
                  showsVerticalScrollIndicator={false}
                  keyboardShouldPersistTaps="handled"
                  contentContainerStyle={styles.gym_list}
                >
                  {gyms.map((gym) => (
                    <TouchableOpacity
                      key={gym.kakao_place_id || gym.gym_id || gym.name}
                      style={[
                        styles.gym_item,
                        selected_gym?.kakao_place_id === gym.kakao_place_id && styles.gym_item_active,
                      ]}
                      onPress={() => set_selected_gym(gym)}
                      activeOpacity={0.8}
                    >
                      <View style={styles.gym_info}>
                        <Text
                          style={[
                            styles.gym_name,
                            selected_gym?.kakao_place_id === gym.kakao_place_id && styles.gym_name_active,
                          ]}
                        >
                          {gym.name}
                        </Text>
                        <Text style={styles.gym_address}>{gym.address}</Text>
                      </View>
                      {gym.equipment_count > 0 && (
                        <Text style={styles.gym_equipment_count}>
                          기구 {gym.equipment_count}개
                        </Text>
                      )}
                    </TouchableOpacity>
                  ))}
                </ScrollView>
              ) : search.length > 0 ? (
                <Text style={styles.empty_text}>검색 결과가 없어요</Text>
              ) : (
                /* 위치 권한은 있지만 좌표 취득 실패 (시뮬레이터 등) — 검색 안내 */
                <View style={styles.location_button_wrapper}>
                  <TouchableOpacity
                    style={styles.location_button}
                    onPress={() => check_location_permission()}
                    activeOpacity={0.8}
                  >
                    <Text style={styles.location_button_text}>주변 헬스장 불러오기</Text>
                  </TouchableOpacity>
                  <Text style={styles.search_hint_text}>또는 위 검색창에 헬스장 이름을 입력하세요.</Text>
                </View>
              )}
            </View>

            {/* 다음 / 건너뛰기 — 항상 하단 고정 */}
            <TouchableOpacity
              style={[
                styles.next_button,
                (!selected_gym || next_loading) && styles.next_button_disabled,
              ]}
              onPress={handle_next}
              disabled={!selected_gym || next_loading}
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
  content: {
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
  search_hint_text: {
    fontFamily: "regular",
    fontSize: 13,
    color: colors.bluegray,
    textAlign: "center",
    marginTop: 10,
  },
  // 목록 영역 — 남은 공간 전부 차지
  list_container: { flex: 1 },
  location_button_wrapper: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  location_button: {
    backgroundColor: colors.select,
    borderRadius: 8,
    paddingVertical: 13,
    width: 209,
    alignItems: "center",
    justifyContent: "center",
  },
  location_button_text: {
    fontFamily: "regular",
    fontSize: 16,
    color: colors.primary,
  },
  gym_list: { gap: 8 },
  gym_item: {
    backgroundColor: colors.select,
    borderRadius: 8,
    paddingHorizontal: 15,
    minHeight: 70,
    paddingVertical: 12,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  gym_item_active: { backgroundColor: colors.primary },
  gym_info: { gap: 4, flex: 1 },
  gym_name: { fontFamily: "regular", fontSize: 16, color: colors.primary },
  gym_name_active: { color: colors.white },
  gym_address: { fontFamily: "regular", fontSize: 13, color: colors.bluegray },
  gym_equipment_count: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
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
  next_button_disabled: { opacity: 0.5 },
  next_button_text: { fontFamily: "medium", fontSize: 16, color: colors.white },
  skip_text: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.primary,
    textAlign: "center",
  },
});
