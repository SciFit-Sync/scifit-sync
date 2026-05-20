import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { getNotifications, markNotificationRead, type NotificationItem } from '../../services/notifications';
import { useAuthStore } from '../../stores/authStore';

type FilterType = 'all' | 'unread';

const TYPE_ICON: Record<string, string> = {
  WORKOUT_REMINDER: '🏋️',
  MOTIVATION: '🔥',
  PROGRESSIVE_OVERLOAD: '📈',
  SYSTEM: '🔔',
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const min = Math.floor(diff / 60000);
  if (min < 1) return '방금 전';
  if (min < 60) return `${min}분 전`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}시간 전`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}일 전`;
  return new Date(iso).toLocaleDateString('ko-KR', { month: 'short', day: 'numeric' });
}

interface NotificationCardProps {
  item: NotificationItem;
  onRead: (id: string) => void;
  isLoading: boolean;
}

function NotificationCard({ item, onRead, isLoading }: NotificationCardProps) {
  const icon = TYPE_ICON[item.type] ?? '📣';

  return (
    <TouchableOpacity
      style={[styles.card, item.is_read && styles.cardRead]}
      onPress={() => !item.is_read && onRead(item.notification_id)}
      activeOpacity={item.is_read ? 1 : 0.7}
      disabled={isLoading}
    >
      <View style={styles.cardLeft}>
        <Text style={styles.icon}>{icon}</Text>
      </View>
      <View style={styles.cardBody}>
        <View style={styles.cardHeader}>
          <Text style={[styles.cardTitle, item.is_read && styles.textDim]} numberOfLines={1}>
            {item.title}
          </Text>
          {!item.is_read && <View style={styles.unreadDot} />}
        </View>
        <Text style={[styles.cardBodyText, item.is_read && styles.textDim]} numberOfLines={2}>
          {item.body}
        </Text>
        <Text style={styles.cardTime}>{timeAgo(item.created_at)}</Text>
      </View>
    </TouchableOpacity>
  );
}

export default function WN01Notifications({ navigation }: { navigation: any }) {
  const token = useAuthStore((s) => s.accessToken) ?? '';
  const [filter, set_filter] = useState<FilterType>('all');
  const queryClient = useQueryClient();

  const { data, isLoading, isRefetching, refetch, isError } = useQuery({
    queryKey: ['notifications'],
    queryFn: () => getNotifications(token),
    enabled: !!token,
  });

  const { mutate: read, variables: readingId } = useMutation({
    mutationFn: (id: string) => markNotificationRead(token, id),
    onSuccess: (updated) => {
      queryClient.setQueryData<typeof data>(['notifications'], (old) => {
        if (!old) return old;
        return {
          items: old.items.map((n) =>
            n.notification_id === updated.notification_id ? updated : n,
          ),
          unread_count: Math.max(0, old.unread_count - 1),
        };
      });
    },
    onError: () => Alert.alert('오류', '읽음 처리에 실패했습니다.'),
  });

  const items = data?.items ?? [];
  const unread_count = data?.unread_count ?? 0;
  const filtered = filter === 'unread' ? items.filter((n) => !n.is_read) : items;

  return (
    <SafeAreaView style={styles.container}>
      {/* 헤더 */}
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()} style={styles.backButton}>
          <Text style={styles.backText}>←</Text>
        </TouchableOpacity>
        <Text style={styles.headerTitle}>알림</Text>
        {unread_count > 0 ? (
          <View style={styles.badge}>
            <Text style={styles.badgeText}>{unread_count > 99 ? '99+' : unread_count}</Text>
          </View>
        ) : (
          <View style={styles.backButton} />
        )}
      </View>

      {/* 필터 탭 */}
      <View style={styles.tabs}>
        {(['all', 'unread'] as FilterType[]).map((f) => (
          <TouchableOpacity key={f} style={[styles.tab, filter === f && styles.tabActive]} onPress={() => set_filter(f)}>
            <Text style={[styles.tabText, filter === f && styles.tabTextActive]}>
              {f === 'all' ? '전체' : '안읽음'}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* 리스트 */}
      {isLoading ? (
        <View style={styles.center}>
          <ActivityIndicator color="#fff" size="large" />
        </View>
      ) : isError ? (
        <View style={styles.center}>
          <Text style={styles.emptyText}>알림을 불러오지 못했습니다.</Text>
          <TouchableOpacity onPress={() => refetch()} style={styles.retryButton}>
            <Text style={styles.retryText}>다시 시도</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={filtered}
          keyExtractor={(item) => item.notification_id}
          renderItem={({ item }) => (
            <NotificationCard
              item={item}
              onRead={read}
              isLoading={readingId === item.notification_id}
            />
          )}
          refreshControl={
            <RefreshControl refreshing={isRefetching} onRefresh={refetch} tintColor="#fff" />
          }
          contentContainerStyle={filtered.length === 0 ? styles.emptyContainer : styles.listContent}
          ListEmptyComponent={
            <Text style={styles.emptyText}>
              {filter === 'unread' ? '읽지 않은 알림이 없습니다.' : '알림이 없습니다.'}
            </Text>
          }
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000' },

  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingVertical: 12,
  },
  backButton: { width: 40 },
  backText: { color: '#fff', fontSize: 22 },
  headerTitle: { color: '#fff', fontSize: 18, fontWeight: 'bold' },
  badge: {
    width: 40,
    alignItems: 'flex-end',
  },
  badgeText: {
    backgroundColor: '#ff4444',
    color: '#fff',
    fontSize: 11,
    fontWeight: 'bold',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 10,
    overflow: 'hidden',
  },

  tabs: { flexDirection: 'row', paddingHorizontal: 20, gap: 8, marginBottom: 8 },
  tab: {
    paddingVertical: 6,
    paddingHorizontal: 16,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: '#333',
  },
  tabActive: { backgroundColor: '#fff', borderColor: '#fff' },
  tabText: { color: '#888', fontSize: 13 },
  tabTextActive: { color: '#000', fontWeight: '600' },

  listContent: { paddingHorizontal: 16, paddingBottom: 32 },
  emptyContainer: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingTop: 80 },

  card: {
    flexDirection: 'row',
    backgroundColor: '#111',
    borderRadius: 12,
    padding: 14,
    marginBottom: 10,
    gap: 12,
  },
  cardRead: { opacity: 0.6 },
  cardLeft: { justifyContent: 'flex-start', paddingTop: 2 },
  icon: { fontSize: 22 },
  cardBody: { flex: 1, gap: 4 },
  cardHeader: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  cardTitle: { color: '#fff', fontSize: 14, fontWeight: '700', flex: 1 },
  cardBodyText: { color: '#ccc', fontSize: 13, lineHeight: 18 },
  cardTime: { color: '#555', fontSize: 11, marginTop: 2 },
  textDim: { color: '#666' },
  unreadDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#4a9eff' },

  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 16 },
  emptyText: { color: '#555', fontSize: 14 },
  retryButton: { backgroundColor: '#222', paddingVertical: 10, paddingHorizontal: 24, borderRadius: 8 },
  retryText: { color: '#fff', fontSize: 14 },
});
