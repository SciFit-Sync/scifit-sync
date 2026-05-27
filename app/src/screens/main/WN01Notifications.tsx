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

interface Notification {
  id: string;
  title: string;
  body: string;
  time: string;
  is_read: boolean;
  type: "routine" | "ai" | "system";
}

const mock_notifications: Notification[] = [
  {
    id: "1",
    title: "루틴 알림",
    body: "오늘 상체 근비대 루틴이 예정되어 있어요!",
    time: "방금 전",
    is_read: false,
    type: "routine",
  },
  {
    id: "2",
    title: "AI 가이드",
    body: "벤치프레스 1RM이 5kg 증가했어요! 새로운 루틴을 추천해드릴까요?",
    time: "1시간 전",
    is_read: false,
    type: "ai",
  },
  {
    id: "3",
    title: "루틴 알림",
    body: "어제 하체 강화 루틴을 완료하지 못했어요. 오늘 진행해보세요!",
    time: "어제",
    is_read: true,
    type: "routine",
  },
  {
    id: "4",
    title: "시스템",
    body: "SciFit-Sync 앱이 업데이트 되었어요. 새로운 기능을 확인해보세요!",
    time: "3일 전",
    is_read: true,
    type: "system",
  },
  {
    id: "5",
    title: "AI 가이드",
    body: "이번 주 운동 목표의 80%를 달성했어요. 조금만 더 힘내세요!",
    time: "5일 전",
    is_read: true,
    type: "ai",
  },
];

const get_icon = (type: Notification["type"]) => {
  switch (type) {
    case "routine":
      return "calendar";
    case "ai":
      return "light-bulb";
    case "system":
      return "bell";
  }
};

export default function WN01Notifications() {
  const navigation = useNavigation();
  const [notifications, set_notifications] = useState(mock_notifications);

  const mark_all_read = () => {
    set_notifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
  };

  const unread_count = notifications.filter((n) => !n.is_read).length;

  return (
    <View style={styles.container}>
      <SafeAreaView edges={["top"]} style={styles.safe_top} />

      {/* 헤더 */}
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()}>
          <Octicons name="chevron-left" size={32} color={colors.primary} />
        </TouchableOpacity>
        <Text style={styles.logo}>SciFit-Sync</Text>
        <View style={styles.placeholder} />
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

          {/* 알림 목록 */}
          {notifications.length > 0 ? (
            <View style={styles.notification_list}>
              {notifications.map((item, index) => (
                <View key={item.id}>
                  <TouchableOpacity
                    style={[
                      styles.notification_item,
                      !item.is_read && styles.notification_item_unread,
                    ]}
                    onPress={() =>
                      set_notifications((prev) =>
                        prev.map((n) =>
                          n.id === item.id ? { ...n, is_read: true } : n,
                        ),
                      )
                    }
                    activeOpacity={0.8}
                  >
                    {/* 아이콘 */}
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

                    {/* 내용 */}
                    <View style={styles.notification_content}>
                      <View style={styles.notification_header}>
                        <Text style={styles.notification_title}>
                          {item.title}
                        </Text>
                        <Text style={styles.notification_time}>
                          {item.time}
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

                    {/* 읽지 않은 점 */}
                    {!item.is_read && <View style={styles.unread_dot} />}
                  </TouchableOpacity>

                  {/* 구분선 */}
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

      {/* 하단 네브바 */}
      <SafeAreaView edges={["bottom"]} style={styles.safe_bottom}>
        <BottomNavBar />
      </SafeAreaView>
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
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 24,
    paddingTop: 16,
    paddingBottom: 8,
  },
  logo: { fontFamily: "sacheon", fontSize: 20, color: colors.primary },
  placeholder: { width: 60 },
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
  empty_text: {
    fontFamily: "regular",
    fontSize: 14,
    color: colors.bluegray,
  },
});
