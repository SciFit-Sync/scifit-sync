import {
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
import { useEffect, useRef, useState } from "react";
import { Octicons } from "@expo/vector-icons";
import { colors } from "../assets/colors/colors";

interface Message {
  id: string;
  type: "bot" | "user";
  text: string;
  chips?: string[];
  date_divider?: string;
}

interface Props {
  onClose: () => void;
}

const mock_routines = [
  "상체 근비대 루틴",
  "뭐시기 루틴",
  "어쩌구 루틴",
  "하체 뭐시기 루틴",
];

const initial_messages: Message[] = [
  {
    id: "1",
    type: "bot",
    text: "안녕하세요, 어떤 루틴이 궁금하신가요?",
    chips: mock_routines,
  },
  {
    id: "2",
    type: "bot",
    text: "상체 근비대 루틴이 궁금하시군요!\n운동, 부상, 영양 등 물어보세요.",
  },
  {
    id: "3",
    type: "user",
    text: "인클라인이 왜 더 효과적인가요?",
  },
  {
    id: "4",
    type: "bot",
    text: "안녕하세요, 어떤 루틴이 궁금하신가요?",
    chips: mock_routines,
    date_divider: "5월 12일 (화)",
  },
];

export default function WC01Chatbot({ onClose }: Props) {
  const [messages, set_messages] = useState<Message[]>(initial_messages);
  const [input, set_input] = useState("");
  const scroll_ref = useRef<ScrollView>(null);
  const fade_anim = useRef(new Animated.Value(0)).current;
  const scale_anim = useRef(new Animated.Value(0.95)).current;

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
  }, []);

  const handle_close = () => {
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

  const handle_send = () => {
    if (!input.trim()) return;
    const new_message: Message = {
      id: String(Date.now()),
      type: "user",
      text: input.trim(),
    };
    set_messages((prev) => [...prev, new_message]);
    set_input("");
    setTimeout(() => {
      scroll_ref.current?.scrollToEnd({ animated: true });
    }, 100);
  };

  const handle_chip_press = (chip: string) => {
    const new_message: Message = {
      id: String(Date.now()),
      type: "user",
      text: chip,
    };
    set_messages((prev) => [...prev, new_message]);
    setTimeout(() => {
      scroll_ref.current?.scrollToEnd({ animated: true });
    }, 100);
  };

  return (
    <Modal
      transparent
      animationType="none"
      visible
      onRequestClose={handle_close}
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        style={styles.keyboard_view}
        keyboardVerticalOffset={60}
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
                transform: [{ scale: scale_anim }],
              },
            ]}
          >
            {/* 헤더 */}
            <View style={styles.header}>
              <View style={styles.placeholder} />
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
              onContentSizeChange={() =>
                scroll_ref.current?.scrollToEnd({ animated: true })
              }
            >
              {messages.map((message) => (
                <View key={message.id}>
                  {/* 날짜 구분선 */}
                  {message.date_divider && (
                    <View style={styles.date_divider}>
                      <View style={styles.date_line} />
                      <Text style={styles.date_text}>
                        {message.date_divider}
                      </Text>
                      <View style={styles.date_line} />
                    </View>
                  )}

                  {message.type === "bot" ? (
                    <View style={styles.bot_message_group}>
                      <View style={styles.bot_bubble}>
                        <Text style={styles.bot_text}>{message.text}</Text>
                      </View>
                      {message.chips && (
                        <View style={styles.chips_container}>
                          <View style={styles.chips_row}>
                            {message.chips.slice(0, 3).map((chip) => (
                              <TouchableOpacity
                                key={chip}
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
                              {message.chips.slice(3).map((chip) => (
                                <TouchableOpacity
                                  key={chip}
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
              ))}
            </ScrollView>

            {/* 입력창 */}
            <View style={styles.input_row}>
              <TextInput
                style={styles.input}
                placeholder="질문을 입력해 보세요"
                placeholderTextColor={colors.border}
                value={input}
                onChangeText={set_input}
                onSubmitEditing={handle_send}
                returnKeyType="send"
              />
              <TouchableOpacity
                style={styles.send_button}
                onPress={handle_send}
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
  placeholder: {
    width: 24,
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
});
