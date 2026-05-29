import { apiFetch } from './api';

export interface GymItem {
  gym_id: string;
  name: string;
  address: string;
  latitude: number;
  longitude: number;
  kakao_place_id: string | null;
  equipment_count: number;
}

export interface BrandItem {
  brand_id: string;
  name: string;
  logo_url: string | null;
}

export interface EquipmentItem {
  equipment_id: string;
  name: string;
  brand: string | null;
  category: string | null;
  equipment_type: string | null;
  image_url: string | null;
}

// 헬스장 검색 (GET /api/v1/gyms)
export async function searchGyms(
  keyword: string,
  token: string,
  latitude?: number,
  longitude?: number,
): Promise<GymItem[]> {
  const params = new URLSearchParams({ keyword });
  if (latitude != null) params.append('latitude', String(latitude));
  if (longitude != null) params.append('longitude', String(longitude));
  const data = await apiFetch<{ gyms: GymItem[] }>(`/api/v1/gyms?${params}`, { token });
  return data.gyms;
}

// 헬스장 생성 (POST /api/v1/gyms) — 카카오 결과가 DB에 없을 때 자동 등록
export async function createGym(gym: GymItem, token: string): Promise<GymItem> {
  const data = await apiFetch<GymItem>('/api/v1/gyms', {
    method: 'POST',
    token,
    body: JSON.stringify({
      name: gym.name,
      address: gym.address,
      latitude: gym.latitude,
      longitude: gym.longitude,
      kakao_place_id: gym.kakao_place_id,
    }),
  });
  return data;
}

// 내 헬스장 등록 (POST /api/v1/users/me/gym)
export async function setMyGym(gym_id: string, token: string): Promise<void> {
  await apiFetch<unknown>('/api/v1/users/me/gym', {
    method: 'POST',
    token,
    body: JSON.stringify({ gym_id }),
  });
}

// 기구 브랜드 목록 (GET /api/v1/equipment/brands)
export async function getEquipmentBrands(token: string): Promise<BrandItem[]> {
  const data = await apiFetch<{ items: BrandItem[] }>('/api/v1/equipment/brands', { token });
  return data.items;
}

// 기구 목록 (GET /api/v1/equipment)
export async function getEquipment(
  params: { keyword?: string; brand_id?: string },
  token: string,
): Promise<EquipmentItem[]> {
  const query = new URLSearchParams();
  if (params.keyword) query.append('keyword', params.keyword);
  if (params.brand_id) query.append('brand_id', params.brand_id);
  const data = await apiFetch<{ items: EquipmentItem[] }>(
    `/api/v1/equipment?${query}`,
    { token },
  );
  return data.items;
}

// 헬스장 보유 기구 목록 (GET /api/v1/gyms/{gym_id}/equipment)
export async function getGymEquipment(
  gym_id: string,
  token: string,
): Promise<{ gym_name: string; equipment: EquipmentItem[] }> {
  const data = await apiFetch<{ gym_id: string; gym_name: string; equipment: EquipmentItem[] }>(
    `/api/v1/gyms/${gym_id}/equipment`,
    { token },
  );
  return { gym_name: data.gym_name, equipment: data.equipment };
}

// 헬스장 기구 삭제 (DELETE /api/v1/gyms/{gym_id}/equipment/{equipment_id})
export async function deleteGymEquipment(
  gym_id: string,
  equipment_id: string,
  token: string,
): Promise<void> {
  await apiFetch<unknown>(`/api/v1/gyms/${gym_id}/equipment/${equipment_id}`, {
    method: 'DELETE',
    token,
  });
}

// 헬스장에 기구 일괄 추가 (POST /api/v1/gyms/{gym_id}/equipment/bulk)
export async function addGymEquipmentBulk(
  gym_id: string,
  equipment_ids: string[],
  token: string,
): Promise<void> {
  await apiFetch<unknown>(`/api/v1/gyms/${gym_id}/equipment/bulk`, {
    method: 'POST',
    token,
    body: JSON.stringify({ equipment_ids }),
  });
}

// 기구 제보 (POST /api/v1/gyms/{gym_id}/equipment/suggest)
export async function suggestGymEquipment(
  gym_id: string,
  params: { name: string; brand?: string; description?: string },
  token: string,
): Promise<void> {
  await apiFetch<unknown>(`/api/v1/gyms/${gym_id}/equipment/suggest`, {
    method: 'POST',
    token,
    body: JSON.stringify(params),
  });
}

// 기구 선택 저장 (POST /api/v1/equipment/select)
export async function selectEquipment(
  equipment_ids: string[],
  token: string,
): Promise<void> {
  await apiFetch<unknown>('/api/v1/equipment/select', {
    method: 'POST',
    token,
    body: JSON.stringify({ equipment_ids }),
  });
}

// 1RM 일괄 등록 (POST /api/v1/users/me/1rm/bulk)
export interface OneRMItem {
  exercise_code: string;
  weight_kg: number;
}

export async function bulkAdd1RM(items: OneRMItem[], token: string): Promise<void> {
  await apiFetch<unknown>('/api/v1/users/me/1rm/bulk', {
    method: 'POST',
    token,
    body: JSON.stringify({ items }),
  });
}
