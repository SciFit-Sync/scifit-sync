const path = require('path');
require('dotenv').config({ path: path.join(__dirname, '.env') });

const KAKAO_NATIVE_APP_KEY =
  process.env.EXPO_PUBLIC_KAKAO_NATIVE_APP_KEY ||
  '31250347642127059188b6723d38cca3';

module.exports = {
  expo: {
    name: "SciFit-Sync",
    slug: "scifiit-sync",
    version: "1.0.0",
    orientation: "portrait",
    scheme: "scifiitsync",
    userInterfaceStyle: "light",
    newArchEnabled: false,
    splash: {
      backgroundColor: "#000000",
    },
    ios: {
      supportsTablet: false,
      bundleIdentifier: "com.scifitsync.app",
    },
    android: {
      package: "com.scifitsync.app",
      adaptiveIcon: {
        backgroundColor: "#000000",
      },
    },
    plugins: [
      "expo-secure-store",
      [
        "@react-native-seoul/kakao-login",
        {
          kotlinVersion: "1.9.25",
          kakaoAppKey: KAKAO_NATIVE_APP_KEY,
        },
      ],
      "expo-build-properties",
      "expo-font",
      "expo-web-browser",
    ],
    extra: {
      eas: {
        projectId: "f1014d53-e69b-4d8b-b2aa-5c2514bbb14a",
      },
    },
    owner: "2ziziy",
  },
};
