import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useFonts } from "expo-font";
import { useEffect } from "react";
import { ActivityIndicator, View } from "react-native";
import RootNavigator from "./src/navigation/RootNavigator";
import { useAuthStore } from "./src/stores/authStore";
import { SafeAreaProvider } from "react-native-safe-area-context";

const queryClient = new QueryClient();

function AppInner() {
  const init = useAuthStore((s) => s.init);

  useEffect(() => {
    init();
  }, [init]);

  return <RootNavigator />;
}

export default function App() {
  const [fontsLoaded] = useFonts({
    regular: require("./src/assets/fonts/Pretendard-Regular.ttf"),
    medium: require("./src/assets/fonts/Pretendard-Medium.ttf"),
    semibold: require("./src/assets/fonts/Pretendard-SemiBold.ttf"),
    sacheon: require("./src/assets/fonts/SacheonUju-Regular.ttf"),
  });

  if (!fontsLoaded) {
    return (
      <View
        style={{
          flex: 1,
          justifyContent: "center",
          alignItems: "center",
          backgroundColor: "#E8E8FF",
        }}
      >
        <ActivityIndicator size="large" color="#1E3A8A" />
      </View>
    );
  }

  return (
    <QueryClientProvider client={queryClient}>
      <SafeAreaProvider>
        <AppInner />
      </SafeAreaProvider>
    </QueryClientProvider>
  );
}
