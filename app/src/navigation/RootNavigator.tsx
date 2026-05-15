import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { ActivityIndicator, View } from 'react-native';
import WO01GymSetup from '../screens/onboarding/WO01GymSetup';
import WA01Login from '../screens/auth/WA01Login';
import WM01Main from '../screens/main/WM01Main';
import WN01Notifications from '../screens/main/WN01Notifications';
import { useAuthStore } from '../stores/authStore';

const AuthStack = createNativeStackNavigator();
const OnboardingStack = createNativeStackNavigator();
const MainStack = createNativeStackNavigator();

function AuthNavigator() {
  return (
    <AuthStack.Navigator screenOptions={{ headerShown: false }}>
      <AuthStack.Screen name="WA01Login" component={WA01Login} />
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
      <MainStack.Screen name="WN01Notifications" component={WN01Notifications} />
    </MainStack.Navigator>
  );
}

export default function RootNavigator() {
  const { isLoggedIn, isNewUser, isLoading } = useAuthStore();

  if (isLoading) {
    return (
      <View style={{ flex: 1, backgroundColor: '#000', alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator color="#FEE500" size="large" />
      </View>
    );
  }

  return (
    <NavigationContainer>
      {!isLoggedIn ? (
        <AuthNavigator />
      ) : isNewUser ? (
        <OnboardingNavigator />
      ) : (
        <MainNavigator />
      )}
    </NavigationContainer>
  );
}
