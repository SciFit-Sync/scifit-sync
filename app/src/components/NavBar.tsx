// src/components/BottomNavBar.tsx

import { StyleSheet, TouchableOpacity, View } from "react-native";
import { Octicons } from "@expo/vector-icons";
import { useNavigation, useRoute } from "@react-navigation/native";
import { colors } from "../assets/colors/colors";

type TabName =
  | "WM01Main"
  | "WH01Calendar"
  | "WL01Record"
  | "WN01Notifications"
  | "WP01MyPage";

interface TabItem {
  name: TabName;
  icon: string;
  icon_active: string;
}

const tabs: TabItem[] = [
  {
    name: "WN01Notifications",
    icon: "bell",
    icon_active: "bell-fill",
  },
  {
    name: "WH01Calendar",
    icon: "graph",
    icon_active: "graph",
  },
  {
    name: "WM01Main",
    icon: "home",
    icon_active: "home-fill",
  },
  {
    name: "WL01Record",
    icon: "pencil",
    icon_active: "pencil",
  },
  {
    name: "WP01MyPage",
    icon: "person",
    icon_active: "person-fill",
  },
];

export default function BottomNavBar() {
  const navigation = useNavigation();
  const route = useRoute();

  return (
    <View style={styles.container}>
      {tabs.map((tab, index) => {
        const is_active = route.name === tab.name;
        return (
          <TouchableOpacity
            key={tab.name}
            style={[
              styles.tab,
              index === 0 && styles.tab_first,
              index === tabs.length - 1 && styles.tab_last,
            ]}
            onPress={() => navigation.navigate(tab.name as never)}
            activeOpacity={0.7}
          >
            <Octicons
              name={(is_active ? tab.icon_active : tab.icon) as any}
              size={24}
              color={is_active ? colors.primary : colors.primary}
            />
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
    // 그림자
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
  tab_first: {
    borderTopLeftRadius: 16,
  },
  tab_last: {
    borderTopRightRadius: 16,
  },
});
