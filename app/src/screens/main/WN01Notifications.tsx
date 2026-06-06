import { useState } from "react";
import WC01DChatbotFloating from "../../components/WC01-DChatbotFloating";
import WC01Chatbot from "../../components/WC01Chatbot";
import {
  ActivityIndicator,
  Alert,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Octicons } from "@expo/vector-icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { colors } from "../../assets/colors/colors";
import BottomNavBar from "../../components/NavBar";
import { useAuthStore } from "../../stores/authStore";
import {
  getNotifications,
  markNotificationRead,
  markAllNotificationsRead,
} from "../../services/notifications";

function fmt_relative_time(iso: string): string {
  const utc = iso.endsWith("Z") ? iso : iso + "Z";
  const diff = Date.now() - new Date(utc).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "방금 전";
  if (mins < 60) return `${mins}분 전`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}시간 전`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "어제";
  if (days < 7) return `${days}일 전`;
  return `${Math.floor(days / 7)}주 전`;
}

function get_icon(type: string): string {
  if (type.includes("routine") || type.includes("ROUTINE")) return "calendar";
  if (
    type.includes("ai") ||
    type.includes("AI") ||
    type.includes("po") ||
    type.includes("PO")
  )
    return "light-bulb";
  return "bell";
}

export default function WN01Notifications() {
  const token = useAuthStore((s) => s.accessToken) ?? "";
  const queryClient = useQueryClient();
  const [show_chatbot, set_show_chatbot] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["notifications", token],
    queryFn: () => getNotifications(token),
    enabled: !!token,
  });

  const notifications = data?.items ?? [];

  const mark_read = async (id: string) => {
    try {
      await markNotificationRead(token, id);
      queryClient.invalidateQueries({ queryKey: ["notifications", token] });
    } catch {}
  };

  const mark_all_read = async () => {
    const unread = notifications.filter((n) => !n.is_read);
    if (unread.length === 0) return;
    try {
      await markAllNotificationsRead(token);
      queryClient.invalidateQueries({ queryKey: ["notifications", token] });
      queryClient.invalidateQueries({
        queryKey: ["notifications_unread", token],
      });
    } catch {
      Alert.alert("오류", "읽음 처리에 실패했습니다. 다시 시도해주세요.");
    }
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
          {/* 카드 헤더 */}
          <View style={styles.card_header}>
            <View style={styles.placeholder} />
            <Text style={styles.card_title}>알림</Text>
            <TouchableOpacity onPress={mark_all_read}>
              <Text style={styles.all_read_text}>모두 읽음</Text>
            </TouchableOpacity>
          </View>

          {isLoading ? (
            <ActivityIndicator
              color={colors.primary}
              style={{ paddingVertical: 40 }}
            />
          ) : notifications.length > 0 ? (
            <View style={styles.notification_list}>
              {notifications.map((item, index) => (
                <View key={item.notification_id}>
                  <TouchableOpacity
                    style={[
                      styles.notification_item,
                      !item.is_read && styles.notification_item_unread,
                    ]}
                    onPress={() =>
                      !item.is_read && mark_read(item.notification_id)
                    }
                    activeOpacity={0.8}
                  >
                    <View
                      style={[
                        styles.icon_box,
                        !item.is_read && styles.icon_box_unread,
                      ]}
                    >
                      <Octicons
                        name={get_icon(item.type) as any}
                        size={18}
                        color={!item.is_read ? colors.white : colors.bluegray}
                      />
                    </View>

                    <View style={styles.notification_content}>
                      <View style={styles.notification_header}>
                        <Text style={styles.notification_title}>
                          {item.title}
                        </Text>
                        <Text style={styles.notification_time}>
                          {fmt_relative_time(item.created_at)}
                        </Text>
                      </View>
                      <Text
                        style={[
                          styles.notification_body,
                          item.is_read && styles.notification_body_read,
                        ]}
                        numberOfLines={2}
                      >
                        {item.body}
                      </Text>
                    </View>

                    {!item.is_read && <View style={styles.unread_dot} />}
                  </TouchableOpacity>

                  {index < notifications.length - 1 && (
                    <View style={styles.divider} />
                  )}
                </View>
              ))}
            </View>
          ) : (
            <View style={styles.empty_container}>
              <Octicons name="bell" size={40} color={colors.border} />
              <Text style={styles.empty_text}>알림이 없어요</Text>
            </View>
          )}
        </View>
      </ScrollView>

      <SafeAreaView edges={["bottom"]} style={styles.safe_bottom}>
        <BottomNavBar />
      </SafeAreaView>
      <WC01DChatbotFloating onPress={() => set_show_chatbot(true)} />
      {show_chatbot && <WC01Chatbot onClose={() => set_show_chatbot(false)} />}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  safe_top: { backgroundColor: colors.background },
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
  flex: { flex: 1 },
  header: {
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 24,
    paddingTop: 29,
    paddingBottom: 24,
  },
  logo: { fontFamily: "sacheon", fontSize: 20, color: colors.primary },
  scroll: { paddingHorizontal: 24, paddingBottom: 32 },
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
  card_title: {
    fontFamily: "semibold",
    fontSize: 18,
    color: colors.primary,
  },
  all_read_text: {
    fontFamily: "regular",
    fontSize: 12,
    color: colors.bluegray,
  },
  notification_list: { gap: 0 },
  notification_item: {
    flexDirection: "row",
    alignItems: "flex-start",
    paddingVertical: 14,
    gap: 12,
    borderRadius: 8,
    paddingHorizontal: 4,
  },
  notification_item_unread: {
    backgroundColor: colors.select,
    paddingHorizontal: 8,
    marginHorizontal: -4,
  },
  icon_box: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.select,
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
  },
  icon_box_unread: {
    backgroundColor: colors.primary,
  },
  notification_content: {
    flex: 1,
    gap: 4,
  },
  notification_header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  notification_title: {
    fontFamily: "semibold",
    fontSize: 14,
    color: colors.primary,
  },
  notification_time: {
    fontFamily: "regular",
    fontSize: 11,
    color: colors.bluegray,
  },
  notification_body: {
    fontFamily: "regular",
    fontSize: 13,
    color: colors.primary,
    lineHeight: 18,
  },
  notification_body_read: {
    color: colors.bluegray,
  },
  unread_dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.primary,
    marginTop: 6,
    flexShrink: 0,
  },
  divider: {
    height: 1,
    backgroundColor: colors.border,
  },
  empty_container: {
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 60,
    gap: 12,
  },
  placeholder: {
    width: 44,
  },
  empty_text: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.bluegray,
  },
});
