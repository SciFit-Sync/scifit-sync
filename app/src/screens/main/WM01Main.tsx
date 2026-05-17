import { StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { useAuthStore } from '../../stores/authStore';

export default function WM01Main({ navigation }: { navigation: any }) {
  const clearAuth = useAuthStore((s) => s.clearAuth);

  return (
    <View style={styles.container}>
      <TouchableOpacity
        style={styles.bellButton}
        onPress={() => navigation.navigate('WN01Notifications')}
      >
        <Text style={styles.bellIcon}>🔔</Text>
      </TouchableOpacity>
      <Text style={styles.title}>SciFit-Sync</Text>
      <Text style={styles.subtitle}>메인 화면 준비 중</Text>
      <TouchableOpacity style={styles.logoutButton} onPress={clearAuth}>
        <Text style={styles.logoutText}>로그아웃</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000', alignItems: 'center', justifyContent: 'center', gap: 16 },
  bellButton: { position: 'absolute', top: 56, right: 24 },
  bellIcon: { fontSize: 24 },
  title: { color: '#fff', fontSize: 32, fontWeight: 'bold' },
  subtitle: { color: '#888', fontSize: 14 },
  logoutButton: { marginTop: 24, backgroundColor: '#222', paddingVertical: 12, paddingHorizontal: 32, borderRadius: 8 },
  logoutText: { color: '#fff', fontSize: 14 },
});
