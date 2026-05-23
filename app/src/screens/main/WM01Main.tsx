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
import BottomNavBar from "../../components/NavBar";
import RoutineCreate from "../../components/WR01RoutineCreate";
import ProgramCreate from "../../components/WR02ProgramCreate";

type RoutineTab = "single" | "program";

interface Routine {
  id: string;
  name: string;
  gym: string;
  date: string;
}

interface Program {
  id: string;
  name: string;
  date: string;
  routines: { id: string; name: string }[];
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

const mock_programs: Program[] = [
  {
    id: "1",
    name: "박재훈 루틴",
    date: "2026.03.26",
    routines: [
      { id: "1", name: "상체 근비대 루틴" },
      { id: "2", name: "하체 스트렝스 루틴" },
    ],
  },
  {
    id: "2",
    name: "이지연 루틴",
    date: "2026.03.26",
    routines: [
      { id: "1", name: "상체 근비대 루틴" },
      { id: "2", name: "하체 스트렝스 루틴" },
    ],
  },
  {
    id: "3",
    name: "구예빈 루틴",
    date: "2026.03.26",
    routines: [{ id: "1", name: "풀 바디 루틴" }],
  },
  {
    id: "4",
    name: "장태현 루틴",
    date: "2026.03.26",
    routines: [{ id: "1", name: "하체 강화 루틴" }],
  },
];

export default function WM01Main() {
  const navigation = useNavigation();
  const [tab, set_tab] = useState<RoutineTab>("single");
  const [expanded_id, set_expanded_id] = useState<string | null>(null);
  const [show_create_sheet, set_show_create_sheet] = useState(false);
  const [show_program_sheet, set_show_program_sheet] = useState(false);

  const toggle_program = (id: string) => {
    set_expanded_id((prev) => (prev === id ? null : id));
  };

  return (
    <View style={styles.container}>
      <SafeAreaView edges={["top"]} style={styles.safe_top} />

      {/* 헤더 */}
      <View style={styles.header}>
        <Text style={styles.logo}>SciFit-Sync</Text>
      </View>

      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
        style={styles.flex}
      >
        <View style={styles.card}>
          {/* 제목 + 생성 버튼 */}
          <View style={styles.card_header}>
            <View style={styles.placeholder} />
            <Text style={styles.card_title}>
              {tab === "single" ? "내 루틴" : "프로그램"}
            </Text>
            <TouchableOpacity
              style={styles.create_button}
              onPress={() => {
                if (tab === "single") {
                  set_show_create_sheet(true); // 단일 루틴 생성
                } else {
                  set_show_program_sheet(true); // 프로그램 생성
                }
              }}
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

          {/* 단일 루틴 리스트 */}
          {tab === "single" && (
            <View style={styles.routine_list}>
              {mock_routines.map((item) => (
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
          )}

          {/* 프로그램 리스트 */}
          {tab === "program" && (
            <View style={styles.routine_list}>
              {mock_programs.map((program) => {
                const is_expanded = expanded_id === program.id;
                return (
                  <View
                    key={program.id}
                    style={[
                      styles.program_item,
                      is_expanded && styles.program_item_expanded,
                    ]}
                  >
                    {/* 프로그램 헤더 */}
                    <TouchableOpacity
                      style={[
                        styles.program_header,
                        is_expanded && styles.program_header_expanded,
                      ]}
                      onPress={() => toggle_program(program.id)}
                      activeOpacity={0.8}
                    >
                      <View style={styles.routine_info}>
                        <Text style={styles.routine_name}>{program.name}</Text>
                        <Text style={styles.routine_sub}>{program.date}</Text>
                      </View>
                      <Octicons
                        name={is_expanded ? "triangle-down" : "triangle-right"}
                        size={24}
                        color={colors.primary}
                      />
                    </TouchableOpacity>

                    {/* 펼쳐진 루틴 목록 */}
                    {is_expanded && (
                      <>
                        {program.routines.map((routine, index) => (
                          <View key={routine.id}>
                            <View style={styles.divider} />
                            <View style={styles.sub_routine_item}>
                              <Text style={styles.sub_routine_name}>
                                {routine.name}
                              </Text>
                              <TouchableOpacity
                                style={styles.detail_button}
                                onPress={() =>
                                  navigation.navigate(
                                    "WR04RoutineDetail" as never,
                                  )
                                }
                                activeOpacity={0.8}
                              >
                                <Text style={styles.detail_button_text}>
                                  루틴 상세보기
                                </Text>
                              </TouchableOpacity>
                            </View>
                          </View>
                        ))}
                      </>
                    )}
                  </View>
                );
              })}
            </View>
          )}
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
        <BottomNavBar />
      </SafeAreaView>
      {show_create_sheet && (
        <RoutineCreate
          onConfirm={(data) => {
            if (__DEV__) console.log("루틴 생성:", data);
            set_show_create_sheet(false);
            // TODO: API 연동
          }}
          onClose={() => set_show_create_sheet(false)}
        />
      )}
      {show_program_sheet && (
        <ProgramCreate
          routines={mock_routines} // 단일 루틴 목록 넘겨주기
          onConfirm={(ids) => {
            if (__DEV__) console.log("프로그램 생성:", ids);
            set_show_program_sheet(false);
            // TODO: API 연동
          }}
          onClose={() => set_show_program_sheet(false)}
        />
      )}
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

  // 단일 루틴
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

  // 프로그램 아이템
  program_item: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    overflow: "hidden",
  },
  program_item_expanded: {
    borderColor: colors.primary, // ⭐ 펼쳐지면 파란 테두리
    backgroundColor: colors.select,
  },
  program_header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 20,
    paddingVertical: 14,
    height: 77,
  },
  program_header_expanded: {
    backgroundColor: colors.select,
  },

  // 펼쳐진 루틴 목록
  divider: {
    height: 1,
    backgroundColor: colors.border,
  },
  sub_routine_item: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: colors.white,
    paddingLeft: 15,
    paddingRight: 10,
    height: 49,
  },
  sub_routine_name: {
    fontFamily: "medium",
    fontSize: 14,
    color: colors.primary,
  },
  detail_button: {
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: "#C8D5FF",
    borderRadius: 16,
    paddingHorizontal: 10,
    paddingVertical: 7,
  },
  detail_button_text: {
    fontFamily: "medium",
    fontSize: 12,
    color: colors.primary,
  },

  // FAB
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
