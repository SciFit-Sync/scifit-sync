import { NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { useEffect, useState } from "react";
import WS01Splash from "../screens/splash/WS01Splash";
import WO01GymSetup from "../screens/onboarding/WO01GymSetup";
import WO02Equipment from "../screens/onboarding/WO02Equipment";
import WO02EquipmentRegister from "../screens/onboarding/WO02-REquipmentRegister";
import WA01Login from "../screens/auth/WA01Login";
import WM01Main from "../screens/main/WM01Main";
import { useAuthStore } from "../stores/authStore";
import WA02Signup from "../screens/auth/WA02Signup";
import WN01Notifications from "../screens/main/WN01Notifications";
import WR04RoutineDetail from "../screens/main/WR04RoutineDetail";
import WL01Record from "../screens/main/WL01Record";
import WA03SignupInfo from "../screens/auth/WA03SignupInfo";
import WO03OneRM from "@/screens/onboarding/WO03OneRM";
import WP01MyPage from "@/screens/main/WP01MyPage";
import WP02EditBodyInfo from "@/screens/main/WP02EditBodyInfo";
import WP03EditCareer from "@/screens/main/WP03EditCareer";
import WP05EditOneRM from "@/screens/main/WP05EditOneRM";
import WP04EditGym from "@/screens/main/WP04EditGym";

const AuthStack = createNativeStackNavigator();
const OnboardingStack = createNativeStackNavigator();
const MainStack = createNativeStackNavigator();

function AuthNavigator() {
  return (
    <AuthStack.Navigator screenOptions={{ headerShown: false }}>
      <AuthStack.Screen name="WA01Login" component={WA01Login} />
      <AuthStack.Screen name="WA02Signup" component={WA02Signup} />
      <AuthStack.Screen
        name="WA03SignupInfo"
        component={WA03SignupInfo}
        options={{ animation: "none" }}
      />
    </AuthStack.Navigator>
  );
}

function OnboardingNavigator() {
  return (
    <OnboardingStack.Navigator screenOptions={{ headerShown: false }}>
      <OnboardingStack.Screen name="WO01GymSetup" component={WO01GymSetup} />
      <OnboardingStack.Screen name="WO02Equipment" component={WO02Equipment} />
      <OnboardingStack.Screen
        name="WO02EquipmentRegister"
        component={WO02EquipmentRegister}
      />
      <OnboardingStack.Screen name="WO03OneRM" component={WO03OneRM} />
    </OnboardingStack.Navigator>
  );
}

function MainNavigator() {
  return (
    <MainStack.Navigator
      screenOptions={{ headerShown: false, animation: "none" }}
    >
      <MainStack.Screen name="WM01Main" component={WM01Main} />
      <MainStack.Screen
        name="WN01Notifications"
        component={WN01Notifications}
      />
      <MainStack.Screen
        name="WR04RoutineDetail"
        component={WR04RoutineDetail}
      />
      <MainStack.Screen name="WL01Record" component={WL01Record} />
      <MainStack.Screen name="WP01MyPage" component={WP01MyPage} />
      <MainStack.Screen name="WP02EditBodyInfo" component={WP02EditBodyInfo} />
      <MainStack.Screen name="WP03EditCareer" component={WP03EditCareer} />
      <MainStack.Screen name="WP04EditGym" component={WP04EditGym} />
      <MainStack.Screen name="WP05EditOneRM" component={WP05EditOneRM} />
    </MainStack.Navigator>
  );
}

export default function RootNavigator() {
  const { isLoggedIn, isNewUser, isLoading } = useAuthStore();

  // 스플래시 최소 표시 시간 (1.8초)
  const [showSplash, setShowSplash] = useState(true);

  useEffect(() => {
    // 무조건 1.8초는 스플래시 보이게
    const timer = setTimeout(() => {
      setShowSplash(false);
    }, 1800);

    return () => clearTimeout(timer);
  }, []);

  // 스플래시 표시 조건:
  // 1. showSplash가 true (1.8초 안 지남)
  // 2. 또는 isLoading이 true (토큰 체크 중)
  if (showSplash || isLoading) {
    return <WS01Splash />;
  }

  // 분기: 로그인 상태에 따라
  return (
    <NavigationContainer>
      {!isLoggedIn ? (
        <AuthNavigator /> // 로그인 안 됨
      ) : isNewUser ? (
        <OnboardingNavigator /> // 신규 사용자
      ) : (
        <MainNavigator /> // 기존 로그인 사용자
      )}
    </NavigationContainer>
  );
}
