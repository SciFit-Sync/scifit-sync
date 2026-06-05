import { useState, useRef } from "react";
import {
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  ScrollView,
  ActivityIndicator,
  Alert,
  Modal,
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
  renameRoutine,
  deleteRoutine,
  GOAL_LABELS,
  type RoutineSummary,
} from "../../services/routines";
import {
  getProgramList,
  createProgram,
  updateProgram,
  deleteProgram,
  type ProgramItem,
} from "../../services/programs";
import { getNotifications } from "../../services/notifications";
import { getMe } from "../../services/users";
import WC01DChatbotFloating from "../../components/WC01-DChatbotFloating";
import WC01Chatbot from "../../components/WC01Chatbot";

type RoutineTab = "single" | "program";

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
  const parts: string[] = [];
  if (item.fitness_goals && item.fitness_goals.length > 0) {
    parts.push(item.fitness_goals.map((g) => GOAL_LABELS[g] ?? g).join(", "));
  }
  if (item.target_muscle_names && item.target_muscle_names.length > 0) {
    parts.push(item.target_muscle_names.join(", "));
  }
  return parts.join(" · ");
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
  const [generate_message, set_generate_message] =
    useState("AI가 루틴을 생성하는 중...");
  const [show_chatbot, set_show_chatbot] = useState(false);
  const [show_rename_modal, set_show_rename_modal] = useState(false);
  const [rename_target_id, set_rename_target_id] = useState("");
  const [rename_target_type, set_rename_target_type] = useState<
    "routine" | "program"
  >("routine");
  const [rename_input, set_rename_input] = useState("");
  const [is_renaming, set_is_renaming] = useState(false);

  // cleanup ref (SSE abort)
  const cleanup_ref = useRef<(() => void) | null>(null);

  const open_rename = (
    type: "routine" | "program",
    id: string,
    current_name: string,
  ) => {
    set_rename_target_type(type);
    set_rename_target_id(id);
    set_rename_input(current_name);
    set_show_rename_modal(true);
  };

  const confirm_rename = () => {
    const trimmed = rename_input.trim();
    if (!trimmed) return;
    set_is_renaming(true);
    const api_call =
      rename_target_type === "program"
        ? updateProgram(token, rename_target_id, { name: trimmed }).then(() => {
            query_client.invalidateQueries({ queryKey: ["programs"] });
          })
        : renameRoutine(token, rename_target_id, trimmed).then(() => {
            query_client.invalidateQueries({ queryKey: ["routines"] });
          });
    api_call
      .then(() => set_show_rename_modal(false))
      .catch((err: unknown) => {
        const msg =
          err instanceof Error ? err.message : "이름 변경에 실패했습니다.";
        Alert.alert("오류", msg);
      })
      .finally(() => set_is_renaming(false));
  };

  const { data: notif_data } = useQuery({
    queryKey: ["notifications_unread", token],
    queryFn: () => getNotifications(token),
    enabled: !!token,
    staleTime: 30_000,
  });
  const unread_count = notif_data?.unread_count ?? 0;

  const { data: routines_data, isLoading: routines_loading } = useQuery({
    queryKey: ["routines"],
    queryFn: () => listRoutines(token),
    enabled: !!token,
  });

  const { data: programs_data, isLoading: programs_loading } = useQuery({
    queryKey: ["programs"],
    queryFn: () => getProgramList(token),
    enabled: !!token,
  });

  const { data: me_data } = useQuery({
    queryKey: ["me"],
    queryFn: () => getMe(token),
    enabled: !!token,
  });

  // 회원가입 시 선택한 기본 헬스장 → 루틴 생성에 전달 (머신 후보 포함).
  // 미전달 시 서버가 기본 gym 으로 fallback (D-M9).
  const primary_gym_id =
    me_data?.gyms?.find((g) => g.is_primary)?.gym_id ??
    me_data?.gyms?.[0]?.gym_id ??
    null;

  const real_routines = routines_data?.items ?? [];
  const real_programs = programs_data?.items ?? [];

  const open_routine_actions = (item: RoutineSummary) => {
    Alert.alert("루틴 설정", undefined, [
      {
        text: "이름 수정",
        onPress: () => open_rename("routine", item.routine_id, item.name),
      },
      {
        text: "삭제",
        style: "destructive",
        onPress: () => {
          Alert.alert(
            "루틴 삭제",
            `"${item.name}"을(를) 삭제할까요?\n삭제 후 복구가 불가능합니다.`,
            [
              { text: "취소", style: "cancel" },
              {
                text: "삭제",
                style: "destructive",
                onPress: async () => {
                  try {
                    await deleteRoutine(token, item.routine_id);
                    query_client.invalidateQueries({ queryKey: ["routines"] });
                  } catch (err: unknown) {
                    const msg =
                      err instanceof Error ? err.message : "삭제에 실패했습니다.";
                    Alert.alert("삭제 실패", msg);
                  }
                },
              },
            ],
          );
        },
      },
      { text: "취소", style: "cancel" },
    ]);
  };

  const open_program_actions = (program: ProgramItem) => {
    Alert.alert("프로그램 설정", undefined, [
      {
        text: "이름 수정",
        onPress: () =>
          open_rename("program", program.program_id, program.name),
      },
      {
        text: "삭제",
        style: "destructive",
        onPress: () => {
          Alert.alert(
            "프로그램 삭제",
            `"${program.name}"을(를) 삭제할까요?\n삭제 후 복구가 불가능합니다.`,
            [
              { text: "취소", style: "cancel" },
              {
                text: "삭제",
                style: "destructive",
                onPress: async () => {
                  try {
                    await deleteProgram(token, program.program_id);
                    query_client.invalidateQueries({ queryKey: ["programs"] });
                  } catch (err: unknown) {
                    const msg =
                      err instanceof Error ? err.message : "삭제에 실패했습니다.";
                    Alert.alert("삭제 실패", msg);
                  }
                },
              },
            ],
          );
        },
      },
      { text: "취소", style: "cancel" },
    ]);
  };

  const toggle_program = (id: string) => {
    set_expanded_id((prev) => (prev === id ? null : id));
  };

  return (
    <View style={styles.container}>
      <SafeAreaView edges={["top"]} style={styles.safe_top} />

      {/* 헤더 */}
      <View style={styles.header}>
        <View style={styles.bell_btn} />
        <Text style={styles.logo}>SciFit-Sync</Text>
        <TouchableOpacity
          style={styles.bell_btn}
          onPress={() => navigation.navigate("WN01Notifications" as never)}
          activeOpacity={0.7}
        >
          <Octicons name="bell" size={22} color={colors.primary} />
          {unread_count > 0 && (
            <View style={styles.badge}>
              <Text style={styles.badge_text}>
                {unread_count > 99 ? "99+" : unread_count}
              </Text>
            </View>
          )}
        </TouchableOpacity>
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
                    아직 루틴이 없어요.{"\n"}오른쪽 상단 생성 버튼을 눌러 AI
                    루틴을 만들어 보세요!
                  </Text>
                </View>
              ) : (
                real_routines.map((item) => (
                  <TouchableOpacity
                    key={item.routine_id}
                    style={styles.routine_item}
                    onPress={() =>
                      (navigation as any).navigate("WR04RoutineDetail", {
                        routine_id: item.routine_id,
                      })
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
                        {item.gym_name ? `  ·  ${item.gym_name}` : ""}
                      </Text>
                    </View>
                    <TouchableOpacity
                      style={styles.kebab_button}
                      onPress={() => open_routine_actions(item)}
                      hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                      activeOpacity={0.6}
                    >
                      <Octicons
                        name="kebab-horizontal"
                        size={18}
                        color={colors.primary}
                      />
                    </TouchableOpacity>
                  </TouchableOpacity>
                ))
              )}
            </View>
          )}

          {/* 프로그램 리스트 */}
          {tab === "program" && (
            <View style={styles.routine_list}>
              {programs_loading ? (
                <ActivityIndicator
                  size="large"
                  color={colors.primary}
                  style={styles.loader}
                />
              ) : real_programs.length === 0 ? (
                <View style={styles.empty_container}>
                  <Text style={styles.empty_text}>
                    아직 프로그램이 없어요.{"\n"}오른쪽 상단 생성 버튼을 눌러
                    프로그램을 만들어 보세요!
                  </Text>
                </View>
              ) : (
                real_programs.map((program) => {
                  const is_expanded = expanded_id === program.program_id;
                  return (
                    <View
                      key={program.program_id}
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
                        onPress={() => toggle_program(program.program_id)}
                        activeOpacity={0.8}
                      >
                        <View style={styles.routine_info}>
                          <Text style={styles.routine_name}>
                            {program.name}
                          </Text>
                          <Text style={styles.routine_sub}>
                            {format_date(program.created_at)}
                          </Text>
                        </View>
                        <TouchableOpacity
                          style={styles.kebab_button}
                          onPress={() => open_program_actions(program)}
                          hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                          activeOpacity={0.6}
                        >
                          <Octicons
                            name="kebab-horizontal"
                            size={18}
                            color={colors.primary}
                          />
                        </TouchableOpacity>
                      </TouchableOpacity>

                      {/* 펼쳐진 루틴 목록 */}
                      {is_expanded && (
                        <>
                          {program.routines.map((routine) => (
                            <View key={routine.routine_id}>
                              <View style={styles.divider} />
                              <View style={styles.sub_routine_item}>
                                <Text style={styles.sub_routine_name}>
                                  {routine.name}
                                </Text>
                                <TouchableOpacity
                                  style={styles.detail_button}
                                  onPress={() =>
                                    (navigation as any).navigate(
                                      "WR04RoutineDetail",
                                      { routine_id: routine.routine_id },
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
                })
              )}
            </View>
          )}
        </View>
      </ScrollView>

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

            const cleanup = generateRoutineSSE(token, { ...data, gym_id: primary_gym_id }, {
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
                (navigation as any).navigate("WR04RoutineDetail", {
                  routine_id: _routine_id,
                });
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
            set_show_program_sheet(false);
            createProgram(token, data.program_name, data.selected_routine_ids)
              .then(() => {
                query_client.invalidateQueries({ queryKey: ["programs"] });
              })
              .catch((err: unknown) => {
                const msg =
                  err instanceof Error
                    ? err.message
                    : "프로그램 생성에 실패했습니다.";
                Alert.alert("프로그램 생성 실패", msg);
              });
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

      {/* 프로그램 이름 수정 모달 */}
      <Modal
        visible={show_rename_modal}
        transparent
        animationType="fade"
        onRequestClose={() => set_show_rename_modal(false)}
      >
        <TouchableOpacity
          style={styles.modal_overlay}
          activeOpacity={1}
          onPress={() => set_show_rename_modal(false)}
        >
          <TouchableOpacity style={styles.modal_box} activeOpacity={1}>
            <Text style={styles.modal_title}>
              {rename_target_type === "program" ? "프로그램" : "루틴"} 이름 수정
            </Text>
            <TextInput
              style={styles.modal_input}
              value={rename_input}
              onChangeText={set_rename_input}
              placeholder="프로그램 이름을 입력하세요"
              placeholderTextColor={colors.bluegray}
              maxLength={200}
              autoFocus
            />
            <View style={styles.modal_actions}>
              <TouchableOpacity
                style={styles.modal_btn_cancel}
                onPress={() => set_show_rename_modal(false)}
                activeOpacity={0.8}
              >
                <Text style={styles.modal_btn_cancel_text}>취소</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[
                  styles.modal_btn_confirm,
                  is_renaming && { opacity: 0.6 },
                ]}
                onPress={confirm_rename}
                disabled={is_renaming}
                activeOpacity={0.8}
              >
                {is_renaming ? (
                  <ActivityIndicator size="small" color={colors.white} />
                ) : (
                  <Text style={styles.modal_btn_confirm_text}>확인</Text>
                )}
              </TouchableOpacity>
            </View>
          </TouchableOpacity>
        </TouchableOpacity>
      </Modal>

      <WC01DChatbotFloating onPress={() => set_show_chatbot(true)} />
      {show_chatbot && <WC01Chatbot onClose={() => set_show_chatbot(false)} />}
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
    justifyContent: "space-between",
    flexDirection: "row",
    paddingHorizontal: 24,
    paddingTop: 29,
    paddingBottom: 24,
  },
  bell_btn: {
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
  },
  badge: {
    position: "absolute",
    top: 4,
    right: 4,
    minWidth: 16,
    height: 16,
    borderRadius: 8,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 3,
  },
  badge_text: {
    color: colors.white,
    fontSize: 9,
    fontFamily: "semibold",
    lineHeight: 12,
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

  // 케밥 버튼
  kebab_button: {
    padding: 4,
    alignItems: "center",
    justifyContent: "center",
  },

  // 프로그램 헤더 우측 (케밥 + chevron)
  program_header_actions: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },

  // 이름 수정 모달 (WR04RoutineDetail과 동일)
  modal_overlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.45)",
    alignItems: "center",
    justifyContent: "center",
  },
  modal_box: {
    width: "80%",
    backgroundColor: colors.white,
    borderRadius: 16,
    padding: 24,
    gap: 16,
  },
  modal_title: {
    fontFamily: "semibold",
    fontSize: 16,
    color: colors.primary,
    textAlign: "center",
  },
  modal_input: {
    fontFamily: "regular",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 10,
    fontSize: 14,
    color: colors.primary,
  },
  modal_actions: {
    flexDirection: "row",
    gap: 8,
  },
  modal_btn_cancel: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 8,
    backgroundColor: colors.select,
    alignItems: "center",
    justifyContent: "center",
  },
  modal_btn_cancel_text: {
    fontFamily: "medium",
    fontSize: 14,
    color: colors.primary,
  },
  modal_btn_confirm: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 8,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  modal_btn_confirm_text: {
    fontFamily: "medium",
    fontSize: 14,
    color: colors.white,
  },
});
