import { StyleSheet, View, Image, Text } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { LinearGradient } from "expo-linear-gradient";
import { colors } from "../../assets/colors/colors";

export default function WS01Splash() {
  return (
    <LinearGradient colors={["#D0DCFF", "#EEF1F8"]} style={styles.container}>
      <SafeAreaView style={styles.container}>
        {/* 로고 영역 */}
        <View style={styles.logoContainer}>
          <Image
            source={require("../../assets/images/app-logo.png")}
            style={styles.logo}
            resizeMode="contain"
          />
          <Text style={styles.title}>SciFit-Sync</Text>
        </View>

        {/* 하단 슬로건 */}
        <View style={styles.bottomContainer}>
          <Text style={styles.slogan}>당신의 운동에 근거를 더하다</Text>
        </View>
      </SafeAreaView>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: "space-between",
    alignItems: "center",
  },
  logoContainer: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
  },
  logo: {
    width: 70,
    height: 105,
    marginBottom: 16,
  },
  title: {
    fontFamily: "sacheon",
    fontSize: 24,
    color: colors.primary,
  },
  bottomContainer: {
    marginBottom: 150,
  },
  slogan: {
    fontFamily: "medium",
    fontSize: 16,
    color: colors.primary,
  },
});
