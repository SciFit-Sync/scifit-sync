import { StyleSheet, TouchableOpacity, View } from "react-native";
import { Octicons } from "@expo/vector-icons";
import { useNavigation, useRoute } from "@react-navigation/native";
import { colors } from "../assets/colors/colors";

type TabName =
  | "WM01Main"
  | "WH02Analysis"
  | "WL01Record"
  | "WC01Chat"
  | "WP01MyPage";

interface TabItem {
  name: TabName;
  icon: string;
}

const tabs: TabItem[] = [
  { name: "WC01Chat", icon: "comment-discussion" },
  { name: "WH02Analysis", icon: "graph" },
  { name: "WM01Main", icon: "home" },
  { name: "WL01Record", icon: "pencil" },
  { name: "WP01MyPage", icon: "person" },
];

export default function BottomNavBar() {
  const navigation = useNavigation();
  const route = useRoute();

  return (
    <View style={styles.container}>
      {tabs.map((tab) => {
        const is_active = route.name === tab.name;
        return (
          <TouchableOpacity
            key={tab.name}
            style={styles.tab}
            onPress={() => navigation.navigate(tab.name as never)}
            activeOpacity={0.7}
          >
            {/* 선택됐을 때 파란 배경 박스 */}
            <View
              style={[styles.icon_box, is_active && styles.icon_box_active]}
            >
              <Octicons
                name={tab.icon as any}
                size={24}
                color={is_active ? colors.white : colors.primary}
              />
            </View>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: "row",
    backgroundColor: colors.white,
    height: 70,
    borderTopLeftRadius: 16,
    borderTopRightRadius: 16,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: -2 },
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 10,
  },
  tab: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  icon_box: {
    width: 60,
    height: 50,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
  },
  icon_box_active: {
    backgroundColor: colors.primary,
  },
});
