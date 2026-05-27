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
        projectId: "2c24df8a-4e78-4de3-aaec-b5b9f0344b56",
      },
    },
    owner: "kuyebin",
  },
};
