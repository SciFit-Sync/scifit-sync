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
import { searchGyms, setMyGym, GymItem } from "../../services/gyms";

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
    } else {
      do_search(v);
    }
  };

  // 다음 버튼 → 헬스장 저장 후 이동
  const handle_next = async () => {
    if (!selected_gym) return;
    if (!selected_gym.gym_id) {
      Alert.alert("알림", "아직 등록되지 않은 헬스장이에요. 다른 헬스장을 선택해주세요.");
      return;
    }
    set_next_loading(true);
    try {
      await setMyGym(selected_gym.gym_id, token);
      (navigation as any).navigate("WO02Equipment", { gym_id: selected_gym.gym_id });
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
          keyboardShouldPersistTaps="handled"
        >
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

            {/* 위치 권한 없으면 버튼 */}
            {has_location_permission === false && search.length === 0 && (
              <View style={styles.location_button_wrapper}>
                <TouchableOpacity
                  style={styles.location_button}
                  onPress={request_location_permission}
                  activeOpacity={0.8}
                >
                  <Text style={styles.location_button_text}>위치 정보 동의하러 가기</Text>
                </TouchableOpacity>
              </View>
            )}

            {/* 검색 결과 */}
            {loading ? (
              <ActivityIndicator color={colors.primary} style={{ marginVertical: 20 }} />
            ) : gyms.length > 0 ? (
              <View style={styles.gym_list}>
                {gyms.map((gym) => (
                  <TouchableOpacity
                    key={gym.gym_id || gym.kakao_place_id || gym.name}
                    style={[
                      styles.gym_item,
                      selected_gym?.gym_id === gym.gym_id && styles.gym_item_active,
                      !gym.gym_id && styles.gym_item_unregistered,
                    ]}
                    onPress={() => set_selected_gym(gym)}
                    activeOpacity={0.8}
                  >
                    <View style={styles.gym_info}>
                      <Text
                        style={[
                          styles.gym_name,
                          selected_gym?.gym_id === gym.gym_id && styles.gym_name_active,
                        ]}
                      >
                        {gym.name}
                        {!gym.gym_id && (
                          <Text style={styles.unregistered_badge}> (미등록)</Text>
                        )}
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
              </View>
            ) : search.length > 0 && !loading ? (
              <Text style={styles.empty_text}>검색 결과가 없어요</Text>
            ) : null}

            <View style={styles.spacer} />

            {/* 다음 / 건너뛰기 */}
            <TouchableOpacity
              style={[
                styles.next_button,
                (!selected_gym || !selected_gym.gym_id || next_loading) && styles.next_button_disabled,
              ]}
              onPress={handle_next}
              disabled={!selected_gym || !selected_gym.gym_id || next_loading}
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
    minHeight: 500,
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
  location_button_wrapper: { alignItems: "center" },
  location_button: {
    marginTop: 40,
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
  gym_item_unregistered: { opacity: 0.6 },
  gym_info: { gap: 4, flex: 1 },
  gym_name: { fontFamily: "regular", fontSize: 16, color: colors.primary },
  gym_name_active: { color: colors.white },
  unregistered_badge: { fontSize: 12, color: colors.bluegray },
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
  spacer: { flex: 1 },
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
