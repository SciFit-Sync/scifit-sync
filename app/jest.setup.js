// jest 환경에서 네이티브 모듈(AsyncStorage)을 공식 mock으로 대체.
// async-storage가 jest 하위에서 NativeModule null로 깨지는 것을 방지한다.
jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);
