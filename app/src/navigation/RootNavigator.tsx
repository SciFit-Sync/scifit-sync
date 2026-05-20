import { NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { useEffect, useState } from "react";
import WS01Splash from "../screens/splash/WS01Splash";
import WO01GymSetup from "../screens/onboarding/WO01GymSetup";
import WA01Login from "../screens/auth/WA01Login";
import WM01Main from "../screens/main/WM01Main";
import { useAuthStore } from "../stores/authStore";
import WA02Signup from "../screens/auth/WA02Signin";
import WN01Notifications from "../screens/main/WN01Notifications";
import WR04RoutineDetail from "../screens/main/WR04RoutineDetail";
import WL01Record from "../screens/main/WL01Record";

const AuthStack = createNativeStackNavigator();
const OnboardingStack = createNativeStackNavigator();
const MainStack = createNativeStackNavigator();

function AuthNavigator() {
  return (
    <AuthStack.Navigator screenOptions={{ headerShown: false }}>
      <AuthStack.Screen name="WA01Login" component={WA01Login} />
      <AuthStack.Screen name="WA02Signup" component={WA02Signup} />
    </AuthStack.Navigator>
  );
}

function OnboardingNavigator() {
  return (
    <OnboardingStack.Navigator screenOptions={{ headerShown: false }}>
      <OnboardingStack.Screen name="WO01GymSetup" component={WO01GymSetup} />
    </OnboardingStack.Navigator>
  );
}

function MainNavigator() {
  return (
    <MainStack.Navigator screenOptions={{ headerShown: false }}>
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
    }, 1800000);

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
