import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { colors } from "../../assets/colors/colors";
import BottomNavBar from "../../components/NavBar";
import { useAuthStore } from "../../stores/authStore";
import { fetchChatHistory, sendChatMessage } from "../../services/chat";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: { doi: string; pmid?: string; title?: string }[];
}

export default function WC01Chat() {
  const token = useAuthStore((s) => s.accessToken) ?? "";
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const flatListRef = useRef<FlatList>(null);
  const streamingMsgId = useRef<string | null>(null);

  useEffect(() => {
    if (!sessionId || !token) return;
    setIsLoadingHistory(true);
    fetchChatHistory(sessionId, token)
      .then((data) => {
        setMessages(
          data.items.map((item) => ({
            id: item.message_id,
            role: item.role,
            content: item.content,
          }))
        );
      })
      .catch(() => {})
      .finally(() => setIsLoadingHistory(false));
  }, []);

  const scrollToBottom = useCallback(() => {
    flatListRef.current?.scrollToEnd({ animated: true });
  }, []);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");

    const userMsgId = `user-${Date.now()}`;
    const assistantMsgId = `asst-${Date.now()}`;
    streamingMsgId.current = assistantMsgId;

    setMessages((prev) => [
      ...prev,
      { id: userMsgId, role: "user", content: text },
      { id: assistantMsgId, role: "assistant", content: "" },
    ]);
    setIsStreaming(true);
    setTimeout(scrollToBottom, 80);

    try {
      await sendChatMessage(
        text,
        token,
        {
          on_session_id: (sid) => setSessionId(sid),
          on_chunk: (chunk) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMsgId
                  ? { ...m, content: m.content + chunk }
                  : m
              )
            );
            setTimeout(scrollToBottom, 50);
          },
          on_sources: (sources) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMsgId ? { ...m, sources } : m
              )
            );
          },
          on_done: () => setIsStreaming(false),
          on_error: () => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMsgId
                  ? { ...m, content: "오류가 발생했습니다. 다시 시도해주세요." }
                  : m
              )
            );
            setIsStreaming(false);
          },
        },
        sessionId ?? undefined
      );
    } catch {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsgId
            ? { ...m, content: "오류가 발생했습니다. 다시 시도해주세요." }
            : m
        )
      );
      setIsStreaming(false);
    }
  }, [input, isStreaming, sessionId, token, scrollToBottom]);

  const handleNewChat = useCallback(() => {
    setSessionId(null);
    setMessages([]);
  }, []);

  const renderMessage = useCallback(
    ({ item }: { item: Message }) => {
      const isUser = item.role === "user";
      const isTyping =
        isStreaming && item.id === streamingMsgId.current && !item.content;

      return (
        <View
          style={[
            styles.bubble,
            isUser ? styles.userBubble : styles.assistantBubble,
          ]}
        >
          {isTyping ? (
            <ActivityIndicator size="small" color={colors.gray} />
          ) : (
            <Text style={[styles.bubbleText, isUser && styles.userText]}>
              {item.content}
            </Text>
          )}
          {item.sources && item.sources.length > 0 && (
            <View style={styles.sources}>
              {item.sources.map((s, i) => (
                <View key={i} style={styles.sourceChip}>
                  <Text style={styles.sourceText} numberOfLines={1}>
                    📄 {s.title ?? s.doi}
                  </Text>
                </View>
              ))}
            </View>
          )}
        </View>
      );
    },
    [isStreaming]
  );

  return (
    <SafeAreaView style={styles.container} edges={["top"]}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>AI 챗봇</Text>
        <TouchableOpacity onPress={handleNewChat} style={styles.newChatBtn}>
          <Text style={styles.newChatText}>새 대화</Text>
        </TouchableOpacity>
      </View>

      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        keyboardVerticalOffset={0}
      >
        {isLoadingHistory ? (
          <ActivityIndicator style={styles.flex} color={colors.primary} />
        ) : (
          <FlatList
            ref={flatListRef}
            data={messages}
            keyExtractor={(item) => item.id}
            renderItem={renderMessage}
            contentContainerStyle={styles.messageList}
            onContentSizeChange={scrollToBottom}
            ListEmptyComponent={
              <View style={styles.empty}>
                <Text style={styles.emptyTitle}>
                  운동·영양·루틴에 대해 무엇이든 물어보세요!
                </Text>
                <Text style={styles.emptySubTitle}>
                  논문 기반으로 정확한 정보를 제공합니다.
                </Text>
              </View>
            }
          />
        )}

        <View style={styles.inputRow}>
          <TextInput
            style={styles.input}
            value={input}
            onChangeText={setInput}
            placeholder="메시지를 입력하세요..."
            placeholderTextColor={colors.gray}
            multiline
            maxLength={500}
            editable={!isStreaming}
          />
          <TouchableOpacity
            style={[
              styles.sendBtn,
              (!input.trim() || isStreaming) && styles.sendBtnDisabled,
            ]}
            onPress={handleSend}
            disabled={!input.trim() || isStreaming}
          >
            {isStreaming ? (
              <ActivityIndicator size="small" color={colors.white} />
            ) : (
              <Text style={styles.sendText}>전송</Text>
            )}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>

      <BottomNavBar />
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
    paddingHorizontal: 20,
    paddingVertical: 14,
    backgroundColor: colors.white,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  headerTitle: { fontSize: 18, fontWeight: "700", color: colors.primary },
  newChatBtn: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    backgroundColor: colors.select,
    borderRadius: 8,
  },
  newChatText: { fontSize: 13, color: colors.primary, fontWeight: "600" },

  messageList: { padding: 16, flexGrow: 1 },

  bubble: {
    maxWidth: "80%",
    borderRadius: 12,
    padding: 12,
    marginBottom: 10,
  },
  userBubble: { alignSelf: "flex-end", backgroundColor: colors.primary },
  assistantBubble: {
    alignSelf: "flex-start",
    backgroundColor: colors.white,
    borderWidth: 1,
    borderColor: colors.border,
  },
  bubbleText: { fontSize: 14, color: "#111", lineHeight: 20 },
  userText: { color: colors.white },

  sources: { marginTop: 8 },
  sourceChip: {
    backgroundColor: colors.select,
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 4,
    marginTop: 4,
  },
  sourceText: { fontSize: 11, color: colors.bluegray },

  empty: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingTop: 80,
    paddingHorizontal: 32,
  },
  emptyTitle: {
    fontSize: 15,
    fontWeight: "600",
    color: colors.primary,
    textAlign: "center",
    marginBottom: 8,
  },
  emptySubTitle: {
    fontSize: 13,
    color: colors.gray,
    textAlign: "center",
  },

  inputRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    paddingHorizontal: 16,
    paddingVertical: 10,
    backgroundColor: colors.white,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  input: {
    flex: 1,
    minHeight: 40,
    maxHeight: 100,
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 10,
    fontSize: 14,
    color: "#111",
    marginRight: 10,
  },
  sendBtn: {
    width: 60,
    height: 40,
    backgroundColor: colors.primary,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
  },
  sendBtnDisabled: { backgroundColor: colors.button },
  sendText: { color: colors.white, fontSize: 13, fontWeight: "600" },
});
