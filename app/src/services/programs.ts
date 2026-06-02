import { apiFetch } from './api';

export interface ProgramRoutineItem {
  routine_id: string;
  name: string;
  gym_name: string | null;
  order_index: number;
}

export interface ProgramItem {
  program_id: string;
  name: string;
  description: string | null;
  created_at: string;
  routines: ProgramRoutineItem[];
}

export interface ProgramListData {
  items: ProgramItem[];
}

export interface DeleteProgramData {
  program_id: string;
  message: string;
}

export function getProgramList(token: string): Promise<ProgramListData> {
  return apiFetch<ProgramListData>('/api/v1/programs', { token });
}

export function getProgram(token: string, program_id: string): Promise<ProgramItem> {
  return apiFetch<ProgramItem>(`/api/v1/programs/${program_id}`, { token });
}

export function createProgram(
  token: string,
  name: string,
  routine_ids: string[],
  description?: string,
): Promise<ProgramItem> {
  return apiFetch<ProgramItem>('/api/v1/programs', {
    method: 'POST',
    token,
    body: JSON.stringify({ name, routine_ids, description }),
  });
}

export function updateProgram(
  token: string,
  program_id: string,
  fields: { name?: string; description?: string },
): Promise<ProgramItem> {
  return apiFetch<ProgramItem>(`/api/v1/programs/${program_id}`, {
    method: 'PATCH',
    token,
    body: JSON.stringify(fields),
  });
}

export function deleteProgram(token: string, program_id: string): Promise<DeleteProgramData> {
  return apiFetch<DeleteProgramData>(`/api/v1/programs/${program_id}`, {
    method: 'DELETE',
    token,
  });
}
