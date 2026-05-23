import { useState } from "react";
import {
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation } from "@react-navigation/native";
import { Octicons } from "@expo/vector-icons";
import { colors } from "../../assets/colors/colors";
import NavBar from "../../components/NavBar";

type RoutineTab = "single" | "program";

interface Routine {
  id: string;
  name: string;
  gym: string;
  date: string;
}

const mock_routines: Routine[] = [
  {
    id: "1",
    name: "상체 근비대 루틴",
    gym: "스포애니 강남점",
    date: "2026.03.26",
  },
  {
    id: "2",
    name: "하체 강화 루틴",
    gym: "스포애니 강남점",
    date: "2026.03.24",
  },
  { id: "3", name: "풀 바디 루틴", gym: "스포애니 강남점", date: "2026.03.22" },
  {
    id: "4",
    name: "어깨 집중 루틴",
    gym: "스포애니 강남점",
    date: "2026.03.20",
  },
];

const mock_programs: Routine[] = [
  {
    id: "1",
    name: "3분할 프로그램",
    gym: "스포애니 강남점",
    date: "2026.03.26",
  },
  {
    id: "2",
    name: "5분할 프로그램",
    gym: "스포애니 강남점",
    date: "2026.03.20",
  },
  { id: "3", name: "PPL 프로그램", gym: "스포애니 강남점", date: "2026.03.15" },
];

export default function WM01Main() {
  const navigation = useNavigation();
  const [tab, set_tab] = useState<RoutineTab>("single");

  const displayed = tab === "single" ? mock_routines : mock_programs;

  return (
    <View style={styles.container}>
      {/* 상단 SafeArea */}
      <SafeAreaView edges={["top"]} style={styles.safe_top} />

      {/* 헤더 */}
      <View style={styles.header}>
        <Text style={styles.logo}>SciFit-Sync</Text>
      </View>

      {/* 콘텐츠 */}
      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
        style={styles.flex}
      >
        <View style={styles.card}>
          {/* 제목 + 생성 버튼 */}
          <View style={styles.card_header}>
            <View style={styles.placeholder} />
            <Text style={styles.card_title}>내 루틴</Text>
            <TouchableOpacity
              style={styles.create_button}
              onPress={() => navigation.navigate("WR01RoutineCreate" as never)}
              activeOpacity={0.7}
            >
              <Text style={styles.create_text}>생성</Text>
              <Octicons name="plus" size={16} color={colors.primary} />
            </TouchableOpacity>
          </View>

          {/* 단일루틴 / 프로그램 토글 */}
          <View style={styles.toggle_container}>
            <TouchableOpacity
              style={[
                styles.toggle_button,
                tab === "single" && styles.toggle_button_active,
              ]}
              onPress={() => set_tab("single")}
              activeOpacity={0.8}
            >
              <Text
                style={[
                  styles.toggle_text,
                  tab === "single" && styles.toggle_text_active,
                ]}
              >
                단일 루틴
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[
                styles.toggle_button,
                tab === "program" && styles.toggle_button_active,
              ]}
              onPress={() => set_tab("program")}
              activeOpacity={0.8}
            >
              <Text
                style={[
                  styles.toggle_text,
                  tab === "program" && styles.toggle_text_active,
                ]}
              >
                프로그램
              </Text>
            </TouchableOpacity>
          </View>

          {/* 루틴 / 프로그램 리스트 */}
          <View style={styles.routine_list}>
            {displayed.map((item) => (
              <TouchableOpacity
                key={item.id}
                style={styles.routine_item}
                onPress={() =>
                  navigation.navigate("WR04RoutineDetail" as never)
                }
                activeOpacity={0.8}
              >
                <View style={styles.routine_info}>
                  <Text style={styles.routine_name}>{item.name}</Text>
                  <Text style={styles.routine_sub}>{item.gym}</Text>
                  <Text style={styles.routine_sub}>{item.date}</Text>
                </View>
                <Octicons
                  name="triangle-right"
                  size={24}
                  color={colors.primary}
                />
              </TouchableOpacity>
            ))}
          </View>
        </View>
      </ScrollView>

      {/* 챗봇 FAB */}
      <TouchableOpacity
        style={styles.fab}
        onPress={() => navigation.navigate("WC01Chatbot" as never)}
        activeOpacity={0.8}
      >
        <Octicons name="comment" size={24} color={colors.white} />
      </TouchableOpacity>

      {/* 하단 네브바 */}
      <SafeAreaView edges={["bottom"]} style={styles.safe_bottom}>
        <NavBar />
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  safe_top: {
    backgroundColor: colors.background,
  },
  flex: {
    flex: 1,
  },
  header: {
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    paddingHorizontal: 24,
    paddingTop: 24,
    paddingBottom: 24,
  },
  logo: {
    fontFamily: "sacheon",
    fontSize: 20,
    color: colors.primary,
  },
  scroll: {
    paddingHorizontal: 24,
    paddingBottom: 32,
  },
  card: {
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 20,
    gap: 16,
  },
  card_header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  placeholder: {
    width: 40,
  },
  card_title: {
    fontFamily: "semibold",
    fontSize: 18,
    color: colors.primary,
  },
  create_button: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  create_text: {
    fontFamily: "medium",
    fontSize: 14,
    color: colors.primary,
  },
  toggle_container: {
    flexDirection: "row",
    backgroundColor: colors.select,
    borderRadius: 8,
    padding: 4,
    height: 35,
  },
  toggle_button: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 4,
  },
  toggle_button_active: {
    backgroundColor: colors.white,
    shadowColor: "#26272E",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.2,
    shadowRadius: 4,
    elevation: 2,
  },
  toggle_text: {
    fontFamily: "semibold",
    fontSize: 12,
    color: colors.bluegray,
  },
  toggle_text_active: {
    color: colors.primary,
  },
  routine_list: {
    gap: 16,
  },
  routine_item: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 20,
    paddingVertical: 14,
    height: 90,
  },
  routine_info: {
    gap: 4,
  },
  routine_name: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.primary,
  },
  routine_sub: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
  },
  fab: {
    position: "absolute",
    right: 24,
    bottom: 104,
    width: 55,
    height: 55,
    borderRadius: 1000,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: colors.primary,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.25,
    shadowRadius: 10,
    elevation: 8,
  },
  safe_bottom: {
    backgroundColor: colors.white,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: -2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 10,
  },
});
