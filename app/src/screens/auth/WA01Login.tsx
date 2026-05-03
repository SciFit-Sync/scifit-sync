import { useState } from 'react';
import { Alert, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { signInWithKakao } from '../../services/kakaoAuth';
import { useAuthStore } from '../../stores/authStore';

export default function WA01Login() {
  const [loading, setLoading] = useState(false);
  const setAuth = useAuthStore((s) => s.setAuth);

  const handleKakaoLogin = async () => {
    setLoading(true);
    try {
      const result = await signInWithKakao();
      await setAuth(result);
    } catch (e: any) {
      Alert.alert('로그인 실패', e.message ?? '다시 시도해주세요.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>SciFit-Sync</Text>
      <TouchableOpacity style={styles.kakaoButton} onPress={handleKakaoLogin} disabled={loading}>
        <Text style={styles.kakaoText}>{loading ? '로그인 중...' : '카카오로 시작하기'}</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000', alignItems: 'center', justifyContent: 'center', gap: 24 },
  title: { color: '#fff', fontSize: 32, fontWeight: 'bold' },
  kakaoButton: {
    backgroundColor: '#FEE500',
    paddingVertical: 14,
    paddingHorizontal: 48,
    borderRadius: 12,
  },
  kakaoText: { color: '#000', fontSize: 16, fontWeight: '600' },
});
