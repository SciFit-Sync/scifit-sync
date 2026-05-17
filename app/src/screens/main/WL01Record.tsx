import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { getSessions, getSessionStats } from '../../services/sessions';
import { useAuthStore } from '../../stores/authStore';

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'];

function buildCalendar(year: number, month: number, workoutDates: Set<string>) {
  const firstDay = new Date(year, month - 1, 1).getDay(); // 0=Sun
  const daysInMonth = new Date(year, month, 0).getDate();
  const cells: Array<{ day: number | null; hasWorkout: boolean; isToday: boolean }> = [];

  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

  for (let i = 0; i < firstDay; i++) {
    cells.push({ day: null, hasWorkout: false, isToday: false });
  }
  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    cells.push({ day: d, hasWorkout: workoutDates.has(dateStr), isToday: dateStr === todayStr });
  }
  return cells;
}

export default function WL01Record({ navigation }: { navigation: any }) {
  const token = useAuthStore((s) => s.accessToken) ?? '';
  const now = new Date();
  const [year, set_year] = useState(now.getFullYear());
  const [month, set_month] = useState(now.getMonth() + 1);

  const { data: sessionData, isLoading: loadingSessions } = useQuery({
    queryKey: ['sessions', year, month],
    queryFn: () => getSessions(token, year, month),
    enabled: !!token,
  });

  const { data: statsData, isLoading: loadingStats } = useQuery({
    queryKey: ['session-stats'],
    queryFn: () => getSessionStats(token),
    enabled: !!token,
  });

  function prevMonth() {
    if (month === 1) { set_year(y => y - 1); set_month(12); }
    else set_month(m => m - 1);
  }

  function nextMonth() {
    if (month === 12) { set_year(y => y + 1); set_month(1); }
    else set_month(m => m + 1);
  }

  const workoutDates = new Set(
    (sessionData?.records ?? []).map((s) => s.date),
  );
  const cells = buildCalendar(year, month, workoutDates);

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backBtn}>
          <Text style={styles.backText}>←</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>기록</Text>
        <View style={styles.backBtn} />
      </View>

      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        {/* 달력 헤더 */}
        <View style={styles.calendarHeader}>
          <TouchableOpacity onPress={prevMonth} style={styles.monthBtn}>
            <Text style={styles.monthBtnText}>‹</Text>
          </TouchableOpacity>
          <Text style={styles.monthTitle}>{year}년 {month}월</Text>
          <TouchableOpacity onPress={nextMonth} style={styles.monthBtn}>
            <Text style={styles.monthBtnText}>›</Text>
          </TouchableOpacity>
        </View>

        {/* 요일 헤더 */}
        <View style={styles.weekRow}>
          {WEEKDAYS.map((d) => (
            <Text key={d} style={[styles.weekDay, d === '일' && styles.sunday, d === '토' && styles.saturday]}>
              {d}
            </Text>
          ))}
        </View>

        {/* 달력 그리드 */}
        {loadingSessions ? (
          <View style={styles.calendarLoading}>
            <ActivityIndicator color="#fff" />
          </View>
        ) : (
          <View style={styles.calendarGrid}>
            {cells.map((cell, idx) => (
              <View key={idx} style={styles.calendarCell}>
                {cell.day !== null && (
                  <>
                    <Text
                      style={[
                        styles.dayText,
                        idx % 7 === 0 && styles.sundayText,
                        idx % 7 === 6 && styles.saturdayText,
                        cell.isToday && styles.todayText,
                      ]}
                    >
                      {cell.day}
                    </Text>
                    {cell.hasWorkout && <View style={styles.workoutDot} />}
                  </>
                )}
              </View>
            ))}
          </View>
        )}

        {/* 이번 달 운동 횟수 */}
        <Text style={styles.monthSummary}>
          이번 달 <Text style={styles.monthSummaryHighlight}>{workoutDates.size}회</Text> 운동
        </Text>

        {/* 통계 카드 */}
        <Text style={styles.sectionTitle}>전체 통계</Text>

        {loadingStats ? (
          <ActivityIndicator color="#fff" style={{ marginTop: 20 }} />
        ) : (
          <>
            <View style={styles.statsGrid}>
              <StatCard label="총 운동 횟수" value={`${statsData?.total_sessions ?? 0}회`} />
              <StatCard label="연속 운동" value={`${statsData?.streak_days ?? 0}일`} accent />
            </View>
            <View style={styles.statsGrid}>
              <StatCard label="이번 주 운동" value={`${statsData?.weekly_session_count ?? 0}회`} />
              <StatCard label="총 세트" value={`${statsData?.total_sets ?? 0}세트`} />
            </View>
            <View style={styles.statsGrid}>
              <StatCard
                label="총 운동 시간"
                value={`${Math.floor((statsData?.total_duration_minutes ?? 0) / 60)}시간 ${(statsData?.total_duration_minutes ?? 0) % 60}분`}
              />
              <StatCard
                label="총 볼륨"
                value={`${(statsData?.total_volume_kg ?? 0).toLocaleString()} kg`}
              />
            </View>

            {statsData?.recent_session && (
              <View style={styles.recentCard}>
                <Text style={styles.recentLabel}>최근 운동</Text>
                <Text style={styles.recentName}>
                  {statsData.recent_session.routine_name ?? '자유 운동'}
                </Text>
                <Text style={styles.recentDate}>{statsData.recent_session.date}</Text>
              </View>
            )}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function StatCard({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <View style={styles.statCard}>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={[styles.statValue, accent && styles.statValueAccent]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000' },

  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  backBtn: { width: 40 },
  backText: { color: '#fff', fontSize: 22 },
  headerTitle: { color: '#fff', fontSize: 18, fontWeight: 'bold' },

  content: { paddingHorizontal: 16, paddingBottom: 40, gap: 12 },

  calendarHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 8,
  },
  monthBtn: { padding: 8 },
  monthBtnText: { color: '#fff', fontSize: 28, lineHeight: 30 },
  monthTitle: { color: '#fff', fontSize: 18, fontWeight: '700' },

  weekRow: { flexDirection: 'row' },
  weekDay: {
    flex: 1,
    textAlign: 'center',
    color: '#666',
    fontSize: 12,
    fontWeight: '600',
    paddingVertical: 8,
  },
  sunday: { color: '#ff6b6b' },
  saturday: { color: '#4a9eff' },

  calendarLoading: { height: 200, alignItems: 'center', justifyContent: 'center' },
  calendarGrid: { flexDirection: 'row', flexWrap: 'wrap' },
  calendarCell: {
    width: `${100 / 7}%`,
    aspectRatio: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 2,
  },
  dayText: { color: '#ccc', fontSize: 14 },
  sundayText: { color: '#ff6b6b' },
  saturdayText: { color: '#4a9eff' },
  todayText: { color: '#FEE500', fontWeight: '800' },
  workoutDot: { width: 5, height: 5, borderRadius: 3, backgroundColor: '#FEE500' },

  monthSummary: { color: '#888', fontSize: 13, textAlign: 'center', paddingVertical: 4 },
  monthSummaryHighlight: { color: '#fff', fontWeight: '700' },

  sectionTitle: { color: '#888', fontSize: 12, fontWeight: '600', letterSpacing: 0.5, marginTop: 8 },

  statsGrid: { flexDirection: 'row', gap: 10 },
  statCard: {
    flex: 1,
    backgroundColor: '#111',
    borderRadius: 12,
    padding: 16,
    gap: 6,
  },
  statLabel: { color: '#666', fontSize: 12 },
  statValue: { color: '#fff', fontSize: 20, fontWeight: '800' },
  statValueAccent: { color: '#FEE500' },

  recentCard: {
    backgroundColor: '#111',
    borderRadius: 12,
    padding: 16,
    gap: 4,
  },
  recentLabel: { color: '#666', fontSize: 12 },
  recentName: { color: '#fff', fontSize: 16, fontWeight: '700' },
  recentDate: { color: '#555', fontSize: 12 },
});
