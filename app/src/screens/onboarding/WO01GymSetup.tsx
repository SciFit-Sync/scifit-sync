import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { useAuthStore } from '../../stores/authStore';

export default function WO01GymSetup() {
  const completeOnboarding = useAuthStore((s) => s.completeOnboarding);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>헬스장 설정</Text>
      <Text style={styles.subtitle}>준비 중입니다</Text>
      <TouchableOpacity style={styles.button} onPress={completeOnboarding}>
        <Text style={styles.buttonText}>건너뛰기 (임시)</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000', alignItems: 'center', justifyContent: 'center', gap: 16 },
  title: { color: '#fff', fontSize: 24, fontWeight: 'bold' },
  subtitle: { color: '#888', fontSize: 14 },
  button: { marginTop: 24, backgroundColor: '#222', paddingVertical: 12, paddingHorizontal: 32, borderRadius: 8 },
  buttonText: { color: '#fff', fontSize: 14 },
});
