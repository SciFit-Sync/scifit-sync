import { useState, useEffect } from "react";
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
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation } from "@react-navigation/native";
import { Octicons } from "@expo/vector-icons";
import * as Location from "expo-location";
import { colors } from "../../assets/colors/colors";

interface Gym {
  id: string;
  name: string;
  address: string;
  distance?: string;
}

const mock_nearby_gyms: Gym[] = [
  {
    id: "1",
    name: "스포애니 강남점",
    address: "서울 강남구 테헤란로 152",
    distance: "0.3km",
  },
  {
    id: "2",
    name: "스포애니 서초점",
    address: "서울 서초구 서초대로 77",
    distance: "0.8km",
  },
  {
    id: "3",
    name: "헬스장 홍대점",
    address: "서울 마포구 양화로 162",
    distance: "1.2km",
  },
];

const mock_search_gyms: Gym[] = [
  ...mock_nearby_gyms,
  {
    id: "4",
    name: "피트니스 센터 종로",
    address: "서울 종로구 종로 1",
    distance: "3.1km",
  },
  {
    id: "5",
    name: "짐박스 신촌",
    address: "서울 서대문구 신촌로 12",
    distance: "4.5km",
  },
];

export default function WO01GymSetup() {
  const navigation = useNavigation();
  const [search, set_search] = useState("");
  const [selected_gym, set_selected_gym] = useState<Gym | null>(null);
  // 테스트용 - 나중에 원래대로 되돌리기
  const [has_location_permission, set_has_location_permission] = useState<
    boolean | null
  >(false); // ⭐ null → false

  useEffect(() => {
    check_location_permission();
  }, []);

  const check_location_permission = async () => {
    const { status } = await Location.getForegroundPermissionsAsync();
    set_has_location_permission(status === "granted");
  };

  const request_location_permission = async () => {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status === "granted") {
      set_has_location_permission(true);
    } else {
      Linking.openSettings();
    }
  };

  const displayed_gyms =
    search.length > 0
      ? mock_search_gyms.filter((gym) => gym.name.includes(search))
      : mock_nearby_gyms;

  const handle_next = () => {
    navigation.navigate("WO02Equipment" as never);
  };

  const handle_skip = () => {
    navigation.navigate("WO02Equipment" as never);
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
                onChangeText={set_search}
              />
              {search.length > 0 && (
                <TouchableOpacity onPress={() => set_search("")}>
                  <Octicons name="x" size={16} color={colors.border} />
                </TouchableOpacity>
              )}
            </View>

            {/* 위치 동의 여부에 따라 분기 */}
            {has_location_permission === false ? (
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
            ) : (
              <View style={styles.gym_list}>
                {displayed_gyms.length > 0 ? (
                  displayed_gyms.map((gym) => (
                    <TouchableOpacity
                      key={gym.id}
                      style={[
                        styles.gym_item,
                        selected_gym?.id === gym.id && styles.gym_item_active,
                      ]}
                      onPress={() => set_selected_gym(gym)}
                      activeOpacity={0.8}
                    >
                      <View style={styles.gym_info}>
                        <Text
                          style={[
                            styles.gym_name,
                            selected_gym?.id === gym.id &&
                              styles.gym_name_active,
                          ]}
                        >
                          {gym.name}
                        </Text>
                        <Text style={styles.gym_address}>{gym.address}</Text>
                      </View>
                      {gym.distance && (
                        <Text style={styles.gym_distance}>{gym.distance}</Text>
                      )}
                    </TouchableOpacity>
                  ))
                ) : (
                  <Text style={styles.empty_text}>검색 결과가 없어요</Text>
                )}
              </View>
            )}

            <View style={styles.spacer} />

            {/* 다음 / 건너뛰기 */}
            <TouchableOpacity
              style={[
                styles.next_button,
                !selected_gym && styles.next_button_disabled,
              ]}
              onPress={handle_next}
              disabled={!selected_gym}
              activeOpacity={0.8}
            >
              <Text style={styles.next_button_text}>다음</Text>
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
  location_button_wrapper: {
    alignItems: "center",
  },
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
    height: 70,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  gym_item_active: { backgroundColor: colors.primary },
  gym_info: { gap: 8 },
  gym_name: {
    fontFamily: "regular",
    fontSize: 16,
    color: colors.primary,
  },
  gym_name_active: { color: colors.white },
  gym_address: {
    fontFamily: "regular",
    fontSize: 14,
    color: "#C8D5FF",
  },
  gym_distance: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
  },
  empty_text: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.gray,
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
