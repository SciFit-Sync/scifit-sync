import { useState, useRef } from "react";
import {
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  ScrollView,
  ActivityIndicator,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useNavigation } from "@react-navigation/native";
import { Octicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { colors } from "../../assets/colors/colors";
import BottomNavBar from "../../components/NavBar";
import RoutineCreate from "../../components/WR01RoutineCreate";
import ProgramCreate from "../../components/WR02ProgramCreate";
import { useAuthStore } from "../../stores/authStore";
import {
  listRoutines,
  generateRoutineSSE,
  GOAL_LABELS,
  type RoutineSummary,
} from "../../services/routines";

type RoutineTab = "single" | "program";

interface Program {
  id: string;
  name: string;
  date: string;
  routines: { id: string; name: string }[];
}

// 프로그램 탭은 API 미구현 — 임시 목업
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

function format_date(date_str: string): string {
  try {
    const d = new Date(date_str);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}.${m}.${day}`;
  } catch {
    return date_str;
  }
}

function routine_subtitle(item: RoutineSummary): string {
  if (item.gym_name) return item.gym_name;
  if (item.fitness_goals && item.fitness_goals.length > 0) {
    return item.fitness_goals.map((g) => GOAL_LABELS[g] ?? g).join(", ");
  }
  return "";
}

export default function WM01Main() {
  const navigation = useNavigation();
  const token = useAuthStore((s) => s.accessToken) ?? "";
  const query_client = useQueryClient();

  const [tab, set_tab] = useState<RoutineTab>("single");
  const [expanded_id, set_expanded_id] = useState<string | null>(null);
  const [show_create_sheet, set_show_create_sheet] = useState(false);
  const [show_program_sheet, set_show_program_sheet] = useState(false);
  const [is_generating, set_is_generating] = useState(false);
  const [generate_message, set_generate_message] = useState(
    "AI가 루틴을 생성하는 중...",
  );

  // cleanup ref (SSE abort)
  const cleanup_ref = useRef<(() => void) | null>(null);

  const { data: routines_data, isLoading: routines_loading } = useQuery({
    queryKey: ["routines"],
    queryFn: () => listRoutines(token),
    enabled: !!token,
  });

  const real_routines = routines_data?.items ?? [];

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
                  set_show_create_sheet(true);
                } else {
                  set_show_program_sheet(true);
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
              {routines_loading ? (
                <ActivityIndicator
                  size="large"
                  color={colors.primary}
                  style={styles.loader}
                />
              ) : real_routines.length === 0 ? (
                <View style={styles.empty_container}>
                  <Text style={styles.empty_text}>
                    아직 루틴이 없어요.{"\n"}오른쪽 상단 생성 버튼을 눌러
                    AI 루틴을 만들어보세요!
                  </Text>
                </View>
              ) : (
                real_routines.map((item) => (
                  <TouchableOpacity
                    key={item.routine_id}
                    style={styles.routine_item}
                    onPress={() =>
                      navigation.navigate("WR04RoutineDetail" as never, { routine_id: item.routine_id } as never)
                    }
                    activeOpacity={0.8}
                  >
                    <View style={styles.routine_info}>
                      <Text style={styles.routine_name}>{item.name}</Text>
                      {routine_subtitle(item) !== "" && (
                        <Text style={styles.routine_sub}>
                          {routine_subtitle(item)}
                        </Text>
                      )}
                      <Text style={styles.routine_sub}>
                        {format_date(item.created_at)}
                      </Text>
                    </View>
                    <Octicons
                      name="triangle-right"
                      size={24}
                      color={colors.primary}
                    />
                  </TouchableOpacity>
                ))
              )}
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
                        {program.routines.map((routine) => (
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

      {/* 루틴 생성 바텀시트 */}
      {show_create_sheet && (
        <RoutineCreate
          onConfirm={(data) => {
            set_show_create_sheet(false);
            set_is_generating(true);
            set_generate_message("AI가 루틴을 생성하는 중...");

            const cleanup = generateRoutineSSE(token, data, {
              on_started: () => {
                set_generate_message("논문 데이터를 검색하는 중...");
              },
              on_day_complete: (day) => {
                set_generate_message(`Day ${day} 구성 완료, 저장 중...`);
              },
              on_done: (_routine_id, _name) => {
                set_is_generating(false);
                cleanup_ref.current = null;
                query_client.invalidateQueries({ queryKey: ["routines"] });
                navigation.navigate("WR04RoutineDetail" as never, { routine_id: _routine_id } as never);
              },
              on_error: (message) => {
                set_is_generating(false);
                cleanup_ref.current = null;
                Alert.alert("루틴 생성 실패", message);
              },
            });
            cleanup_ref.current = cleanup;
          }}
          onClose={() => set_show_create_sheet(false)}
        />
      )}

      {/* 프로그램 생성 바텀시트 */}
      {show_program_sheet && (
        <ProgramCreate
          routines={real_routines.map((r) => ({
            id: r.routine_id,
            name: r.name,
            gym: r.gym_name ?? "",
            date: format_date(r.created_at),
          }))}
          onConfirm={(data) => {
            if (__DEV__) console.log("프로그램 생성:", data);
            set_show_program_sheet(false);
            // TODO: 프로그램 API 연동
          }}
          onClose={() => set_show_program_sheet(false)}
        />
      )}

      {/* AI 생성 로딩 오버레이 */}
      {is_generating && (
        <View style={styles.generating_overlay}>
          <View style={styles.generating_card}>
            <ActivityIndicator size="large" color={colors.primary} />
            <Text style={styles.generating_title}>AI 루틴 생성 중</Text>
            <Text style={styles.generating_message}>{generate_message}</Text>
            <TouchableOpacity
              style={styles.cancel_button}
              onPress={() => {
                cleanup_ref.current?.();
                cleanup_ref.current = null;
                set_is_generating(false);
              }}
              activeOpacity={0.7}
            >
              <Text style={styles.cancel_text}>취소</Text>
            </TouchableOpacity>
          </View>
        </View>
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
  loader: {
    marginVertical: 24,
  },
  empty_container: {
    paddingVertical: 32,
    alignItems: "center",
  },
  empty_text: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.bluegray,
    textAlign: "center",
    lineHeight: 22,
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
    minHeight: 90,
  },
  routine_info: {
    gap: 4,
    flex: 1,
    marginRight: 12,
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
    borderColor: colors.primary,
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

  // AI 생성 오버레이
  generating_overlay: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "rgba(0,0,0,0.5)",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 999,
  },
  generating_card: {
    backgroundColor: colors.white,
    borderRadius: 20,
    padding: 32,
    alignItems: "center",
    gap: 16,
    marginHorizontal: 40,
    minWidth: 260,
  },
  generating_title: {
    fontFamily: "semibold",
    fontSize: 18,
    color: colors.primary,
  },
  generating_message: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.bluegray,
    textAlign: "center",
  },
  cancel_button: {
    marginTop: 8,
    paddingHorizontal: 24,
    paddingVertical: 8,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.border,
  },
  cancel_text: {
    fontFamily: "medium",
    fontSize: 14,
    color: colors.bluegray,
  },
});
