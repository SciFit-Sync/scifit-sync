import { useState, useCallback } from "react";
import {
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  ScrollView,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation, useFocusEffect } from "@react-navigation/native";
import { Octicons } from "@expo/vector-icons";
import { colors } from "../../assets/colors/colors";
import { useAuthStore } from "../../stores/authStore";
import { getMe, GymData } from "../../services/users";

export default function WP04EditGym() {
  const navigation = useNavigation();
  const token = useAuthStore((s) => s.accessToken) ?? "";

  const [gyms, set_gyms] = useState<GymData[]>([]);
  const [loading, set_loading] = useState(true);

  useFocusEffect(
    useCallback(() => {
      load_gyms();
    }, [token]),
  );

  const load_gyms = async () => {
    set_loading(true);
    try {
      const me = await getMe(token);
      set_gyms(me.gyms ?? []);
    } catch {
      set_gyms([]);
    } finally {
      set_loading(false);
    }
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
          <View style={styles.title_row}>
            <View style={styles.title_spacer} />
            <Text style={styles.card_title}>MY 헬스장</Text>
            <TouchableOpacity
              style={styles.add_btn}
              onPress={() => (navigation as any).navigate("WP04AddGym")}
              activeOpacity={0.8}
            >
              <Octicons name="plus" size={18} color={colors.white} />
            </TouchableOpacity>
          </View>

          <View style={styles.list_container}>
            {loading ? (
              <ActivityIndicator
                color={colors.primary}
                style={{ marginTop: 24 }}
              />
            ) : gyms.length === 0 ? (
              <View style={styles.empty_wrapper}>
                <Text style={styles.empty_text}>등록된 헬스장이 없어요.</Text>
              </View>
            ) : (
              <ScrollView
                showsVerticalScrollIndicator={false}
                contentContainerStyle={styles.gym_list}
              >
                {gyms.map((gym) => (
                  <TouchableOpacity
                    key={gym.gym_id}
                    style={styles.gym_item}
                    onPress={() =>
                      (navigation as any).navigate("WP04GymEquipment", {
                        gym_id: gym.gym_id,
                        gym_name: gym.name,
                      })
                    }
                    activeOpacity={0.8}
                  >
                    <View style={styles.gym_info}>
                      <Text style={styles.gym_name}>{gym.name}</Text>
                      {gym.is_primary && (
                        <Text style={styles.primary_badge}>주 헬스장</Text>
                      )}
                    </View>
                    <Octicons
                      name="chevron-right"
                      size={18}
                      color={colors.bluegray}
                    />
                  </TouchableOpacity>
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
  title_spacer: { width: 32 },
  card_title: {
    fontFamily: "semibold",
    fontSize: 18,
    color: colors.primary,
    textAlign: "center",
    flex: 1,
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
  },
  empty_text: {
    fontFamily: "regular",
    fontSize: 15,
    color: colors.bluegray,
  },
  gym_list: { gap: 8 },
  gym_item: {
    backgroundColor: colors.select,
    borderRadius: 8,
    paddingHorizontal: 16,
    height: 64,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  gym_info: { gap: 4 },
  gym_name: {
    fontFamily: "medium",
    fontSize: 15,
    color: colors.primary,
  },
  primary_badge: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
  },
});
