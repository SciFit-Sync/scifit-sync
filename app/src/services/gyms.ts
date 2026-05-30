import { apiFetch } from './api';

export interface GymItem {
  gym_id: string | null;
  kakao_place_id: string | null;
  name: string;
  address: string;
  latitude: number | null;
  longitude: number | null;
  equipment_count: number;
}

// GET /api/v1/gyms?keyword=&latitude=&longitude=
export async function searchGyms(
  keyword: string,
  token: string,
  lat?: number,
  lng?: number,
): Promise<GymItem[]> {
  const params = new URLSearchParams();
  if (keyword) params.set('keyword', keyword);
  if (lat != null) params.set('latitude', String(lat));
  if (lng != null) params.set('longitude', String(lng));
  const query = params.toString() ? `?${params.toString()}` : '';
  const data = await apiFetch<{ gyms: GymItem[] }>(`/api/v1/gyms${query}`, { token });
  return data.gyms;
}

// POST /api/v1/gyms (미등록 헬스장 DB 등록)
export async function createGym(
  gym: Pick<GymItem, 'name' | 'address' | 'kakao_place_id' | 'latitude' | 'longitude'>,
  token: string,
): Promise<{ gym_id: string }> {
  return apiFetch<{ gym_id: string }>('/api/v1/gyms', {
    method: 'POST',
    token,
    body: JSON.stringify({
      name: gym.name,
      address: gym.address,
      kakao_place_id: gym.kakao_place_id,
      latitude: gym.latitude,
      longitude: gym.longitude,
    }),
  });
}
