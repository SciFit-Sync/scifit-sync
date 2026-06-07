import {
  Dimensions,
  Keyboard,
  Linking,
  Modal,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  Animated,
  ScrollView,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { useEffect, useMemo, useRef, useState } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { Octicons } from "@expo/vector-icons";
import { colors } from "../assets/colors/colors";
import { sendChatMessage } from "../services/chat";
import { listRoutines } from "../services/routines";
import { useAuthStore } from "../stores/authStore";

/** JWT payload를 디코드해서 sub(user_id)를 추출 */
function decode_jwt_sub(token: string): string {
  try {
    const payload = token.split(".")[1];
    const decoded = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    return (JSON.parse(decoded) as { sub?: string }).sub ?? "anonymous";
  } catch {
    return "anonymous";
  }
}

interface PaperSource {
  doi: string;
  pmid?: string;
  title?: string;
}

interface Message {
  id: string;
  type: "bot" | "user";
  text: string;
  chips?: string[];
  sources?: PaperSource[];
  timestamp: number;
}

/** 봇 답변에서 논문 인용 표기 제거 */
function strip_citations(text: string): string {
  return text
    .replace(/\[논문\s*\d+[^\]]*\]/g, "")          // [논문 N] 또는 [논문 N: 제목...]
    .replace(/\(논문\s*\d+[:\s][^)]*\)/g, "")      // (논문 N: 제목)
    .replace(/\s*\(\s*[A-Z][^)]{35,}\)/g, "")      // ( Paper Title...) — 영어 논문 제목 괄호
    .replace(/  +/g, " ")
    .trim();
}

interface Props {
  onClose: () => void;
}

/** timestamp → "5월 12일 (화)" 형식 */
function format_date(ts: number): string {
  const d = new Date(ts);
  const days = ["일", "월", "화", "수", "목", "금", "토"];
  return `${d.getMonth() + 1}월 ${d.getDate()}일 (${days[d.getDay()]})`;
}

export default function WC01Chatbot({ onClose }: Props) {
  const [messages, set_messages] = useState<Message[]>([
    {
      id: "greeting",
      type: "bot",
      text: "안녕하세요, 운동에 대해 무엇이든 물어보세요!",
      timestamp: Date.now(),
    },
  ]);
  const [input, set_input] = useState("");
  const [is_sending, set_is_sending] = useState(false);
  const [session_id, set_session_id] = useState<string | undefined>(undefined);
  const [papers_modal, set_papers_modal] = useState<PaperSource[] | null>(null);
  const papers_overlay_anim = useRef(new Animated.Value(0)).current;
  const papers_sheet_anim = useRef(new Animated.Value(400)).current;
  const SHEET_DUR = 250;
  const scroll_ref = useRef<ScrollView>(null);
  const fade_anim = useRef(new Animated.Value(0)).current;
  const scale_anim = useRef(new Animated.Value(0.95)).current;
  const keyboard_shift = useRef(new Animated.Value(0)).current;
  const access_token = useAuthStore((s) => s.accessToken) ?? "";

  // M-1: user_id 기반 격리 키 — A 로그아웃 후 B 로그인 시 대화 노출 방지
  const chat_storage_key = useMemo(
    () => `chatbot_messages_v1_${decode_jwt_sub(access_token)}`,
    [access_token]
  );

  // M-3: 언마운트 시 XHR abort + setState 방지
  const is_mounted_ref = useRef(true);
  const xhr_abort_ref = useRef<(() => void) | null>(null);

  useEffect(() => {
    return () => {
      is_mounted_ref.current = false;
      xhr_abort_ref.current?.();
    };
  }, []);

  useEffect(() => {
    if (Platform.OS !== "android") return;
    const on_show = Keyboard.addListener("keyboardDidShow", (e) => {
      const screen_h = Dimensions.get("window").height;
      const kb_h = e.endCoordinates.height;
      const container_h = 588;
      const margin = 12;
      // 컨테이너 현재 위치(center 기준)와 키보드 위 필요 위치 차이를 계산
      const current_top = (screen_h - container_h) / 2;
      const needed_top = screen_h - kb_h - container_h - margin;
      const shift = Math.min(0, needed_top - current_top);
      Animated.timing(keyboard_shift, {
        toValue: shift,
        duration: 200,
        useNativeDriver: true,
      }).start();
    });
    const on_hide = Keyboard.addListener("keyboardDidHide", () => {
      Animated.timing(keyboard_shift, {
        toValue: 0,
        duration: 150,
        useNativeDriver: true,
      }).start();
    });
    return () => {
      on_show.remove();
      on_hide.remove();
    };
  }, [keyboard_shift]);

  // 진입 애니메이션 + 저장된 대화 or 신규 인사 로드
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    Animated.parallel([
      Animated.timing(fade_anim, {
        toValue: 1,
        duration: 200,
        useNativeDriver: true,
      }),
      Animated.timing(scale_anim, {
        toValue: 1,
        duration: 200,
        useNativeDriver: true,
      }),
    ]).start();

    (async () => {
      // 1. 저장된 대화 이력 로드
      let restored = false;
      try {
        const json = await AsyncStorage.getItem(chat_storage_key);
        if (json) {
          const saved = JSON.parse(json) as Message[];
          if (saved.length > 0) {
            if (is_mounted_ref.current) set_messages(saved);
            restored = true;
          }
        }
      } catch {
        // 스토리지 오류 무시
      }

      // 2. 항상 루틴 목록을 가져와서 인사 메시지 칩 갱신
      try {
        const data = await listRoutines(access_token);
        const chips = data.items.map((r) => r.name);
        if (!is_mounted_ref.current) return;

        if (!restored) {
          // 저장 내역 없음 → 신규 인사 메시지
          set_messages([
            {
              id: "greeting",
              type: "bot",
              text: chips.length > 0
                ? "안녕하세요, 어떤 루틴이 궁금하신가요?"
                : "안녕하세요, 운동에 대해 무엇이든 물어보세요!",
              chips: chips.length > 0 ? chips : undefined,
              timestamp: Date.now(),
            },
          ]);
        } else if (chips.length > 0) {
          // 기존 대화 복원 시 → 첫 인사 메시지 칩만 업데이트
          set_messages((prev) => {
            if (prev.length > 0 && prev[0].id === "greeting") {
              return [
                {
                  ...prev[0],
                  text: "안녕하세요, 어떤 루틴이 궁금하신가요?",
                  chips,
                },
                ...prev.slice(1),
              ];
            }
            return prev;
          });
        }
      } catch {
        // listRoutines 실패 시 현재 메시지 유지
      }
    })();
  }, []); // access_token은 마운트 시 한 번만 읽으면 되므로 의도적으로 [] 사용

  const open_papers = (sources: PaperSource[]) => {
    set_papers_modal(sources);
    papers_overlay_anim.setValue(0);
    papers_sheet_anim.setValue(400);
    Animated.parallel([
      Animated.timing(papers_overlay_anim, { toValue: 1, duration: SHEET_DUR, useNativeDriver: true }),
      Animated.timing(papers_sheet_anim, { toValue: 0, duration: SHEET_DUR, useNativeDriver: true }),
    ]).start();
  };

  const close_papers = () => {
    Animated.parallel([
      Animated.timing(papers_overlay_anim, { toValue: 0, duration: SHEET_DUR, useNativeDriver: true }),
      Animated.timing(papers_sheet_anim, { toValue: 400, duration: SHEET_DUR, useNativeDriver: true }),
    ]).start(() => set_papers_modal(null));
  };

  const handle_new_chat = async () => {
    // 저장된 대화 삭제 + 세션 초기화
    await AsyncStorage.removeItem(chat_storage_key).catch(() => {});
    set_session_id(undefined);
    set_input("");
    const now = Date.now();
    set_messages([
      {
        id: "greeting",
        type: "bot",
        text: "안녕하세요, 운동에 대해 무엇이든 물어보세요!",
        timestamp: now,
      },
    ]);
    // 루틴 칩 새로 로드
    try {
      const data = await listRoutines(access_token);
      const chips = data.items.map((r) => r.name);
      set_messages([
        {
          id: "greeting",
          type: "bot",
          text: chips.length > 0
            ? "안녕하세요, 어떤 루틴이 궁금하신가요?"
            : "안녕하세요, 운동에 대해 무엇이든 물어보세요!",
          chips: chips.length > 0 ? chips : undefined,
          timestamp: now,
        },
      ]);
    } catch {}
    scroll_ref.current?.scrollTo({ y: 0, animated: false });
  };

  const handle_close = () => {
    // 닫기 전 대화 저장 (M-2: 최대 100개 유지 — AsyncStorage 6MB 한계 방어)
    AsyncStorage.setItem(chat_storage_key, JSON.stringify(messages.slice(-100))).catch(() => {});

    Animated.parallel([
      Animated.timing(fade_anim, {
        toValue: 0,
        duration: 150,
        useNativeDriver: true,
      }),
      Animated.timing(scale_anim, {
        toValue: 0.95,
        duration: 150,
        useNativeDriver: true,
      }),
    ]).start(() => onClose());
  };

  const handle_send = async (text?: string) => {
    const content = (text ?? input).trim();
    if (!content || is_sending) return;

    const now = Date.now();
    const user_msg: Message = { id: String(now), type: "user", text: content, timestamp: now };
    set_messages((prev) => [...prev, user_msg]);
    set_input("");
    set_is_sending(true);

    // 스트리밍 응답용 빈 봇 메시지 미리 추가
    const bot_id = String(now) + "_bot";
    set_messages((prev) => [
      ...prev,
      { id: bot_id, type: "bot", text: "", timestamp: now + 1 },
    ]);

    try {
      await sendChatMessage(
        content,
        access_token,
        {
          on_session_id: (sid) => {
            if (is_mounted_ref.current) set_session_id(sid);
          },
          on_chunk: (chunk) => {
            if (!is_mounted_ref.current) return;
            set_messages((prev) =>
              prev.map((m) => (m.id === bot_id ? { ...m, text: m.text + chunk } : m))
            );
            setTimeout(() => scroll_ref.current?.scrollToEnd({ animated: true }), 50);
          },
          on_sources: (sources) => {
            if (!is_mounted_ref.current) return;
            set_messages((prev) =>
              prev.map((m) => (m.id === bot_id ? { ...m, sources } : m))
            );
          },
          on_done: () => {
            if (is_mounted_ref.current) set_is_sending(false);
          },
          on_error: (msg) => {
            if (!is_mounted_ref.current) return;
            set_messages((prev) =>
              prev.map((m) => (m.id === bot_id ? { ...m, text: msg } : m))
            );
            set_is_sending(false);
          },
          // M-3: XHR abort 함수 저장 — 언마운트 시 useEffect cleanup에서 호출
          on_abort_fn: (fn) => { xhr_abort_ref.current = fn; },
        },
        session_id
      );
    } catch (e: unknown) {
      if (!is_mounted_ref.current) return;
      const msg = e instanceof Error ? e.message : "오류가 발생했습니다.";
      set_messages((prev) =>
        prev.map((m) => (m.id === bot_id ? { ...m, text: msg } : m))
      );
      set_is_sending(false);
    }

    setTimeout(() => scroll_ref.current?.scrollToEnd({ animated: true }), 100);
  };

  const handle_chip_press = (chip: string) => {
    // 루틴 칩 선택 시 로컬 봇 메시지로 질문 유도 (API 호출 없음)
    const now = Date.now();
    set_messages((prev) => [
      ...prev,
      { id: String(now), type: "user", text: chip, timestamp: now },
      {
        id: String(now) + "_bot",
        type: "bot",
        text: `"${chip}"가 궁금하시군요!\n운동 방법, 세트·무게 설정, 부상 예방 등\n궁금한 점을 질문해 주세요.`,
        timestamp: now + 1,
      },
    ]);
    setTimeout(() => scroll_ref.current?.scrollToEnd({ animated: true }), 100);
  };

  return (
    <Modal
      transparent
      animationType="none"
      visible
      onRequestClose={handle_close}
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={styles.keyboard_view}
        keyboardVerticalOffset={60}
        enabled={Platform.OS === "ios"}
      >
        <Animated.View style={[styles.overlay, { opacity: fade_anim }]}>
          {/* 딤 배경 */}
          <TouchableOpacity
            style={styles.dim}
            activeOpacity={1}
            onPress={handle_close}
          />

          {/* 중앙 카드 */}
          <Animated.View
            style={[
              styles.chatbot_container,
              {
                opacity: fade_anim,
                transform: [{ scale: scale_anim }, { translateY: keyboard_shift }],
              },
            ]}
          >
            {/* 헤더 */}
            <View style={styles.header}>
              <TouchableOpacity
                style={styles.new_chat_btn}
                onPress={handle_new_chat}
                activeOpacity={0.7}
              >
                <Octicons name="plus" size={13} color={colors.primary} />
                <Text style={styles.new_chat_text}>새 채팅</Text>
              </TouchableOpacity>
              <Text style={styles.title}>운동 AI 가이드</Text>
              <TouchableOpacity onPress={handle_close}>
                <Octicons name="x" size={24} color={colors.primary} />
              </TouchableOpacity>
            </View>

            {/* 채팅 영역 */}
            <ScrollView
              ref={scroll_ref}
              style={styles.messages}
              contentContainerStyle={styles.messages_content}
              showsVerticalScrollIndicator={false}
              keyboardShouldPersistTaps="handled"
              onContentSizeChange={() =>
                scroll_ref.current?.scrollToEnd({ animated: true })
              }
            >
              {messages.map((message, index) => {
                const prev_msg = messages[index - 1];
                const show_date =
                  prev_msg !== undefined &&
                  format_date(message.timestamp) !== format_date(prev_msg.timestamp);

                return (
                  <View key={message.id}>
                    {/* 날짜가 바뀔 때 구분선 */}
                    {show_date && (
                      <View style={styles.date_divider}>
                        <View style={styles.date_line} />
                        <Text style={styles.date_text}>
                          {format_date(message.timestamp)}
                        </Text>
                        <View style={styles.date_line} />
                      </View>
                    )}

                    {message.type === "bot" ? (
                      <View style={styles.bot_message_group}>
                        <View style={styles.bot_bubble}>
                          <Text style={styles.bot_text}>
                            {strip_citations(message.text)}
                          </Text>
                        </View>
                        {message.sources && message.sources.length > 0 && (
                          <TouchableOpacity
                            style={styles.sources_btn}
                            onPress={() => open_papers(message.sources!)}
                            activeOpacity={0.8}
                          >
                            <Text style={styles.sources_btn_text}>
                              논문 근거 확인하기
                            </Text>
                          </TouchableOpacity>
                        )}
                        {message.chips && (
                          <View style={styles.chips_container}>
                            <View style={styles.chips_row}>
                              {message.chips.slice(0, 3).map((chip, i) => (
                                <TouchableOpacity
                                  key={`chip_${i}_${chip}`}
                                  style={styles.chip}
                                  onPress={() => handle_chip_press(chip)}
                                  activeOpacity={0.8}
                                >
                                  <Text style={styles.chip_text}>{chip}</Text>
                                </TouchableOpacity>
                              ))}
                            </View>
                            {message.chips.length > 3 && (
                              <View style={styles.chips_row}>
                                {message.chips.slice(3).map((chip, i) => (
                                  <TouchableOpacity
                                    key={`chip_${i + 3}_${chip}`}
                                    style={styles.chip}
                                    onPress={() => handle_chip_press(chip)}
                                    activeOpacity={0.8}
                                  >
                                    <Text style={styles.chip_text}>{chip}</Text>
                                  </TouchableOpacity>
                                ))}
                              </View>
                            )}
                          </View>
                        )}
                      </View>
                    ) : (
                      <View style={styles.user_message_wrapper}>
                        <View style={styles.user_bubble}>
                          <Text style={styles.user_text}>{message.text}</Text>
                        </View>
                      </View>
                    )}
                  </View>
                );
              })}
            </ScrollView>

            {/* 입력창 */}
            <View style={styles.input_row}>
              <TextInput
                style={styles.input}
                placeholder="질문을 입력해 보세요"
                placeholderTextColor={colors.border}
                value={input}
                onChangeText={set_input}
                onSubmitEditing={() => handle_send()}
                returnKeyType="send"
              />
              <TouchableOpacity
                style={[styles.send_button, is_sending && { opacity: 0.5 }]}
                onPress={() => handle_send()}
                disabled={is_sending}
                activeOpacity={0.8}
              >
                <Octicons
                  name="paper-airplane"
                  size={16}
                  color={colors.white}
                />
              </TouchableOpacity>
            </View>
          </Animated.View>

          {/* 논문 근거 바텀시트 */}
          {papers_modal && (
            <>
              <Animated.View
                style={[styles.papers_backdrop, { opacity: papers_overlay_anim }]}
                pointerEvents="none"
              />
              <View style={styles.papers_overlay_container}>
                <TouchableOpacity style={{ flex: 1 }} activeOpacity={1} onPress={close_papers} />
                <Animated.View
                  style={[styles.papers_sheet, { transform: [{ translateY: papers_sheet_anim }] }]}
                >
                  {/* 핸들 */}
                  <View style={styles.papers_handle} />

                  {/* 헤더 */}
                  <View style={styles.papers_header}>
                    <View style={styles.papers_header_side} />
                    <Text style={styles.papers_title}>논문 근거</Text>
                    <TouchableOpacity style={styles.papers_header_side} onPress={close_papers}>
                      <Octicons name="x" size={20} color={colors.primary} />
                    </TouchableOpacity>
                  </View>

                  {/* 논문 목록 */}
                  <ScrollView
                    style={styles.papers_scroll}
                    showsVerticalScrollIndicator={false}
                    contentContainerStyle={styles.papers_scroll_content}
                  >
                    {papers_modal.map((s, i) => (
                      <View key={i} style={styles.paper_card}>
                        <Text style={styles.paper_title}>
                          {s.title ?? `논문 ${i + 1}`}
                        </Text>
                        {s.doi ? (
                          <TouchableOpacity
                            style={styles.paper_link_btn}
                            onPress={() => Linking.openURL(`https://doi.org/${s.doi}`)}
                            activeOpacity={0.8}
                          >
                            <Text style={styles.paper_link_text}>논문 링크</Text>
                            <Octicons name="arrow-right" size={13} color={colors.primary} />
                          </TouchableOpacity>
                        ) : null}
                      </View>
                    ))}
                  </ScrollView>

                  {/* 확인 버튼 */}
                  <TouchableOpacity
                    style={styles.papers_confirm_btn}
                    onPress={close_papers}
                    activeOpacity={0.8}
                  >
                    <Text style={styles.papers_confirm_text}>확인</Text>
                  </TouchableOpacity>
                </Animated.View>
              </View>
            </>
          )}
        </Animated.View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  keyboard_view: {
    flex: 1,
  },
  overlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.2)",
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: 24,
  },
  dim: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
  },
  chatbot_container: {
    backgroundColor: colors.white,
    borderRadius: 16,
    width: "100%",
    height: 588,
    overflow: "hidden",
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 20,
    paddingTop: 20,
    marginBottom: 16,
  },
  new_chat_btn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
  },
  new_chat_text: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.primary,
  },
  title: {
    flex: 1,
    textAlign: "center",
    fontFamily: "semibold",
    fontSize: 18,
    color: colors.primary,
  },
  messages: {
    flex: 1,
    paddingHorizontal: 20,
  },
  messages_content: {
    gap: 8,
    paddingBottom: 8,
  },
  bot_message_group: {
    gap: 8,
    alignItems: "flex-start",
  },
  bot_bubble: {
    backgroundColor: colors.primary,
    borderTopLeftRadius: 8,
    borderTopRightRadius: 8,
    borderBottomRightRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 10,
    maxWidth: "80%",
  },
  bot_text: {
    fontFamily: "medium",
    fontSize: 14,
    color: colors.white,
    lineHeight: 20,
  },
  user_message_wrapper: {
    alignItems: "flex-end",
  },
  user_bubble: {
    borderWidth: 1,
    borderColor: colors.primary,
    borderTopLeftRadius: 8,
    borderTopRightRadius: 8,
    borderBottomLeftRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 10,
    maxWidth: "80%",
  },
  user_text: {
    fontFamily: "medium",
    fontSize: 14,
    color: colors.primary,
  },
  chips_container: {
    gap: 8,
  },
  chips_row: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  chip: {
    borderWidth: 1,
    borderColor: colors.primary,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 10,
  },
  chip_text: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.primary,
  },
  date_divider: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    marginVertical: 8,
  },
  date_line: {
    flex: 1,
    height: 1,
    backgroundColor: "#C8D5FF",
  },
  date_text: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
  },
  input_row: {
    flexDirection: "row",
    gap: 4,
    paddingHorizontal: 20,
    paddingVertical: 12,
    alignItems: "center",
  },
  input: {
    flex: 1,
    height: 37,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 10,
    fontFamily: "regular",
    fontSize: 14,
    color: colors.primary,
  },
  send_button: {
    width: 37,
    height: 37,
    borderRadius: 8,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
  },
  sources_btn: {
    borderWidth: 1,
    borderColor: colors.primary,
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 10,
    backgroundColor: colors.white,
    alignSelf: "flex-start",
  },
  sources_btn_text: {
    fontFamily: "regular",
    fontSize: 13,
    color: colors.primary,
  },

  // 논문 바텀시트
  papers_backdrop: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "rgba(0,0,0,0.45)",
  },
  papers_overlay_container: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    justifyContent: "flex-end",
  },
  papers_sheet: {
    backgroundColor: colors.white,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 24,
    paddingBottom: 32,
    maxHeight: "75%",
  },
  papers_handle: {
    width: 36,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.border,
    alignSelf: "center",
    marginTop: 12,
    marginBottom: 4,
  },
  papers_header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 16,
  },
  papers_header_side: {
    width: 24,
    alignItems: "flex-end",
  },
  papers_title: {
    fontFamily: "semibold",
    fontSize: 18,
    color: colors.primary,
  },
  papers_scroll: {
    flexGrow: 0,
    marginBottom: 16,
  },
  papers_scroll_content: {
    gap: 12,
  },
  paper_card: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 16,
    gap: 10,
    backgroundColor: colors.white,
  },
  paper_title: {
    fontFamily: "semibold",
    fontSize: 14,
    color: colors.primary,
    lineHeight: 20,
  },
  paper_link_btn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    alignSelf: "flex-start",
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 20,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  paper_link_text: {
    fontFamily: "regular",
    fontSize: 13,
    color: colors.primary,
  },
  papers_confirm_btn: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingVertical: 14,
    alignItems: "center",
  },
  papers_confirm_text: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.white,
  },
});
