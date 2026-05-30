import { useState, useEffect, useCallback, useRef } from "react";
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
import { searchGyms, createGym, GymItem } from "../../services/gyms";
import { getMe, updateMyGym } from "../../services/users";

export default function WP04EditGym() {
  const navigation = useNavigation();
  const token = useAuthStore((s) => s.accessToken) ?? "";

  const [search, set_search] = useState("");
  const [selected_gym, set_selected_gym] = useState<GymItem | null>(null);
  const [gyms, set_gyms] = useState<GymItem[]>([]);
  const [loading, set_loading] = useState(true);
  const [saving, set_saving] = useState(false);
  const [has_location_permission, set_has_location_permission] = useState<
    boolean | null
  >(null);
  const [coords, set_coords] = useState<{ lat: number; lng: number } | null>(
    null,
  );
  const search_timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const search_seq = useRef(0);

  useEffect(() => {
    init();
  }, []);

  const init = async () => {
    // 현재 헬스장 불러오기
    try {
      const me = await getMe(token);
      const primary = me.gyms?.find((g) => g.is_primary) ?? me.gyms?.[0];
      if (primary) {
        set_selected_gym({
          gym_id: primary.gym_id,
          kakao_place_id: null,
          name: primary.name,
          address: "",
          latitude: null,
          longitude: null,
          equipment_count: 0,
        });
      }
    } catch {
      // 무시
    }

    // 위치 권한 확인
    const { status } = await Location.getForegroundPermissionsAsync();
    if (status === "granted") {
      set_has_location_permission(true);
      try {
        const loc = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        });
        const c = { lat: loc.coords.latitude, lng: loc.coords.longitude };
        set_coords(c);
        await do_nearby_search(c);
      } catch {
        await do_fallback_search();
      }
    } else {
      set_has_location_permission(false);
      set_loading(false);
    }
  };

  const do_nearby_search = async (c: { lat: number; lng: number }) => {
    set_loading(true);
    try {
      const results = await searchGyms("", token, c.lat, c.lng);
      if (results.length > 0) {
        set_gyms(results);
        set_loading(false);
        return;
      }
    } catch {
      // fallback으로 계속
    }
    await do_fallback_search();
  };

  const do_fallback_search = useCallback(async () => {
    set_loading(true);
    try {
      const results = await searchGyms("헬스장", token);
      set_gyms(results);
    } catch {
      set_gyms([]);
    } finally {
      set_loading(false);
    }
  }, [token]);

  const do_search = useCallback(
    async (keyword: string) => {
      search_seq.current += 1;
      const seq = search_seq.current;
      set_loading(true);
      try {
        const results = await searchGyms(keyword, token, coords?.lat, coords?.lng);
        if (seq !== search_seq.current) return;
        set_gyms(results);
      } catch {
        if (seq !== search_seq.current) return;
        set_gyms([]);
      } finally {
        if (seq === search_seq.current) set_loading(false);
      }
    },
    [coords, token],
  );

  const handle_search_change = (v: string) => {
    set_search(v);
    if (search_timer.current) clearTimeout(search_timer.current);
    if (v.length === 0) {
      if (coords) do_nearby_search(coords);
      else do_fallback_search();
    } else {
      search_timer.current = setTimeout(() => do_search(v), 300);
    }
  };

  const request_location_permission = async () => {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status === "granted") {
      set_has_location_permission(true);
      try {
        const loc = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        });
        const c = { lat: loc.coords.latitude, lng: loc.coords.longitude };
        set_coords(c);
        await do_nearby_search(c);
      } catch {
        await do_fallback_search();
      }
    } else {
      Linking.openSettings();
    }
  };

  const handle_save = async () => {
    if (!selected_gym) return;
    set_saving(true);
    try {
      let gym_id = selected_gym.gym_id;
      if (!gym_id) {
        const created = await createGym(selected_gym, token);
        gym_id = created.gym_id;
      }
      await updateMyGym(token, gym_id);
      navigation.goBack();
    } catch (e: any) {
      Alert.alert("오류", e.message ?? "헬스장 변경에 실패했어요.");
    } finally {
      set_saving(false);
    }
  };

  const is_selected = (gym: GymItem) =>
    gym.gym_id != null
      ? selected_gym?.gym_id === gym.gym_id
      : selected_gym?.kakao_place_id != null &&
        selected_gym.kakao_place_id === gym.kakao_place_id;

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
            <Text style={styles.card_title}>MY 헬스장 수정</Text>

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

            {/* 목록 영역 */}
            <View style={styles.list_container}>
              {loading || has_location_permission === null ? (
                <ActivityIndicator color={colors.primary} style={{ marginTop: 24 }} />
              ) : has_location_permission === false && search.length === 0 ? (
                <View style={styles.location_button_wrapper}>
                  <TouchableOpacity
                    style={styles.location_button}
                    onPress={request_location_permission}
                    activeOpacity={0.8}
                  >
                    <Text style={styles.location_button_text}>
                      위치 정보 동의하러 가기
                    </Text>
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
                        is_selected(gym) && styles.gym_item_active,
                      ]}
                      onPress={() => set_selected_gym(gym)}
                      activeOpacity={0.8}
                    >
                      <View style={styles.gym_info}>
                        <Text
                          style={[
                            styles.gym_name,
                            is_selected(gym) && styles.gym_name_active,
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
                <Text style={styles.empty_text}>
                  검색창에 헬스장 이름을 입력해 주세요.
                </Text>
              )}
            </View>

            {/* 저장 버튼 */}
            <TouchableOpacity
              style={[
                styles.save_button,
                (!selected_gym || saving) && styles.save_button_disabled,
              ]}
              onPress={handle_save}
              disabled={!selected_gym || saving}
              activeOpacity={0.8}
            >
              <Text style={styles.save_button_text}>
                {saving ? "저장 중..." : "저장하기"}
              </Text>
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
  save_button: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    justifyContent: "center",
  },
  save_button_disabled: { opacity: 0.5 },
  save_button_text: { fontFamily: "medium", fontSize: 16, color: colors.white },
});
