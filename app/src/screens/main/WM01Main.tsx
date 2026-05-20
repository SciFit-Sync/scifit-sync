import { useQuery } from '@tanstack/react-query';
import { ActivityIndicator, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { getHome } from '../../services/home';
import { useAuthStore } from '../../stores/authStore';

export default function WM01Main({ navigation }: { navigation: any }) {
  const token = useAuthStore((s) => s.accessToken) ?? '';
  const clearAuth = useAuthStore((s) => s.clearAuth);

  const { data, isLoading } = useQuery({
    queryKey: ['home'],
    queryFn: () => getHome(token),
    enabled: !!token,
  });

  return (
    <SafeAreaView style={styles.container}>
      {/* 우상단 알림 버튼 */}
      <TouchableOpacity
        style={styles.bellButton}
        onPress={() => navigation.navigate('WN01Notifications')}
      >
        <Text style={styles.bellIcon}>🔔</Text>
      </TouchableOpacity>

      {isLoading ? (
        <ActivityIndicator color="#fff" size="large" />
      ) : (
        <View style={styles.content}>
          {/* 인사 */}
          <Text style={styles.greeting}>
            안녕하세요, {data?.user_name ?? ''}님 👋
          </Text>

          {/* 스트릭 */}
          <View style={styles.streakCard}>
            <Text style={styles.streakNumber}>{data?.streak_days ?? 0}</Text>
            <Text style={styles.streakLabel}>일 연속 운동 중 🔥</Text>
          </View>

          {/* 오늘의 루틴 */}
          {data?.today_routine ? (
            <TouchableOpacity
              style={styles.routineCard}
              onPress={() =>
                navigation.navigate('WR04RoutineDetail', {
                  routine_id: data.today_routine!.routine_id,
                })
              }
            >
              <Text style={styles.routineCardLabel}>오늘의 루틴</Text>
              <Text style={styles.routineCardName}>{data.today_routine.name}</Text>
              {data.today_routine.next_day_label && (
                <Text style={styles.routineCardDay}>{data.today_routine.next_day_label}</Text>
              )}
              <Text style={styles.routineCardArrow}>→</Text>
            </TouchableOpacity>
          ) : (
            <View style={styles.noRoutineCard}>
              <Text style={styles.noRoutineText}>등록된 루틴이 없습니다</Text>
            </View>
          )}

          {/* 주간 볼륨 */}
          <View style={styles.volumeCard}>
            <Text style={styles.volumeLabel}>이번 주 볼륨</Text>
            <Text style={styles.volumeValue}>
              {data?.recent_volume_kg.toLocaleString() ?? '0'} kg
            </Text>
          </View>
        </View>
      )}

      {/* 로그아웃 */}
      <TouchableOpacity style={styles.logoutButton} onPress={clearAuth}>
        <Text style={styles.logoutText}>로그아웃</Text>
      </TouchableOpacity>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000' },
  bellButton: { position: 'absolute', top: 56, right: 24, zIndex: 10 },
  bellIcon: { fontSize: 24 },

  content: { flex: 1, paddingHorizontal: 24, paddingTop: 72, gap: 16 },

  greeting: { color: '#fff', fontSize: 22, fontWeight: '700' },

  streakCard: {
    backgroundColor: '#111',
    borderRadius: 16,
    padding: 20,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  streakNumber: { color: '#FEE500', fontSize: 36, fontWeight: '900' },
  streakLabel: { color: '#ccc', fontSize: 16 },

  routineCard: {
    backgroundColor: '#111',
    borderRadius: 16,
    padding: 20,
    gap: 4,
  },
  routineCardLabel: { color: '#888', fontSize: 12, fontWeight: '600', letterSpacing: 0.5 },
  routineCardName: { color: '#fff', fontSize: 18, fontWeight: '700', marginTop: 4 },
  routineCardDay: { color: '#aaa', fontSize: 14 },
  routineCardArrow: { color: '#FEE500', fontSize: 20, position: 'absolute', right: 20, top: 20 },

  noRoutineCard: {
    backgroundColor: '#111',
    borderRadius: 16,
    padding: 20,
    alignItems: 'center',
  },
  noRoutineText: { color: '#555', fontSize: 14 },

  volumeCard: {
    backgroundColor: '#111',
    borderRadius: 16,
    padding: 20,
    gap: 4,
  },
  volumeLabel: { color: '#888', fontSize: 12, fontWeight: '600', letterSpacing: 0.5 },
  volumeValue: { color: '#fff', fontSize: 28, fontWeight: '800' },

  logoutButton: {
    marginHorizontal: 24,
    marginBottom: 16,
    backgroundColor: '#222',
    paddingVertical: 12,
    borderRadius: 8,
    alignItems: 'center',
  },
  logoutText: { color: '#fff', fontSize: 14 },
});
