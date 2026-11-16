import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from 'next-auth/react';
import { api, API_BASE_PATH, ApiError, getAccessToken } from '@/lib/api';
import { useSetTokenIfAvailable } from '@/lib/hooks/use-session-token';
import { queryKeys } from '@/lib/hooks/query-keys';

export type InspirationVote = 'love' | 'like';
export type InspirationStatus = 'skipped' | 'pending' | 'analyzing' | 'analyzed' | 'error';

export interface WardrobeItemSummary {
  id: string;
  type: string;
  subtype: string | null;
  name: string | null;
  primary_color: string | null;
  image_url: string | null;
  thumbnail_url: string | null;
}

export interface InspirationGarment {
  id: string;
  position: number;
  type: string;
  subtype: string | null;
  primary_color: string | null;
  colors: string[];
  pattern: string | null;
  material: string | null;
  style: string[];
  formality: string | null;
  season: string[];
  fit: string | null;
  description: string | null;
  confidence: number | null;
  matched_item_id: string | null;
  matched_item: WardrobeItemSummary | null;
  suggested_items: WardrobeItemSummary[];
}

export interface InspirationLook {
  id: string;
  title: string | null;
  source_url: string | null;
  vote: InspirationVote | null;
  tags: string[];
  notes: string | null;
  status: InspirationStatus;
  error_message: string | null;
  photo_url: string | null;
  photo_medium_url: string | null;
  photo_thumbnail_url: string | null;
  matched_at: string | null;
  created_at: string;
  updated_at: string;
  garment_count: number;
  garments: InspirationGarment[];
}

export interface InspirationFilters {
  vote?: InspirationVote;
  tag?: string;
}

export interface InspirationLookUpdate {
  title?: string | null;
  source_url?: string | null;
  vote?: InspirationVote | null;
  tags?: string[];
  notes?: string | null;
}

export interface NewInspirationLook {
  file: File;
  title?: string;
  sourceUrl?: string;
}

export interface NewGarment {
  type: string;
  primary_color?: string | null;
  description?: string | null;
}

const ANALYSIS_RUNNING: InspirationStatus[] = ['pending', 'analyzing'];
const ANALYSIS_POLL_MS = 3000;

export function isAnalysisRunning(look: Pick<InspirationLook, 'status'> | undefined): boolean {
  return !!look && ANALYSIS_RUNNING.includes(look.status);
}

function uploadErrorMessage(data: { detail?: unknown }, fallback: string): string {
  const { detail } = data;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as { message: unknown }).message);
  }
  return fallback;
}

// Multipart bodies can't go through api.*, which always sends JSON.
async function sendForm<T>(
  path: string,
  method: 'POST' | 'PUT',
  form: FormData,
  token: string | null | undefined,
): Promise<T> {
  const response = await fetch(`${API_BASE_PATH}${path}`, {
    method,
    body: form,
    credentials: 'include',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(uploadErrorMessage(data, 'Failed to upload photo'), response.status, data);
  }
  return response.json() as Promise<T>;
}

function lookPath(id: string) {
  return `/inspiration/${encodeURIComponent(id)}`;
}

export function useInspirationLooks(filters: InspirationFilters = {}) {
  const { status } = useSession();
  useSetTokenIfAvailable();

  return useQuery({
    queryKey: queryKeys.inspiration.list(filters),
    queryFn: () => {
      const params: Record<string, string> = { limit: '100' };
      if (filters.vote) params.vote = filters.vote;
      if (filters.tag) params.tags = filters.tag;
      return api.get<{ looks: InspirationLook[]; total: number }>('/inspiration', { params });
    },
    enabled: status !== 'loading',
  });
}

export function useInspirationLook(id: string | undefined) {
  const { status } = useSession();
  useSetTokenIfAvailable();

  return useQuery({
    queryKey: queryKeys.inspirationLook(id ?? ''),
    queryFn: () => api.get<InspirationLook>(lookPath(id!)),
    enabled: status !== 'loading' && !!id,
    // Keep asking while the AI is working on the photo, so its garments appear by themselves.
    refetchInterval: (query) =>
      isAnalysisRunning(query.state.data) ? ANALYSIS_POLL_MS : false,
  });
}

function useLookCache() {
  const queryClient = useQueryClient();
  return (look?: InspirationLook) => {
    if (look) queryClient.setQueryData(queryKeys.inspirationLook(look.id), look);
    queryClient.invalidateQueries({ queryKey: queryKeys.inspiration.all });
  };
}

export function useCreateInspirationLook() {
  const { data: session } = useSession();
  const updateCache = useLookCache();

  return useMutation({
    mutationFn: ({ file, title, sourceUrl }: NewInspirationLook) => {
      const form = new FormData();
      form.append('image', file);
      if (title?.trim()) form.append('title', title.trim());
      if (sourceUrl?.trim()) form.append('source_url', sourceUrl.trim());
      return sendForm<InspirationLook>(
        '/inspiration',
        'POST',
        form,
        session?.accessToken || getAccessToken(),
      );
    },
    onSuccess: (look) => updateCache(look),
  });
}

export function useReplaceInspirationPhoto(id: string) {
  const { data: session } = useSession();
  const updateCache = useLookCache();

  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append('image', file);
      return sendForm<InspirationLook>(
        `${lookPath(id)}/photo`,
        'PUT',
        form,
        session?.accessToken || getAccessToken(),
      );
    },
    onSuccess: (look) => updateCache(look),
  });
}

export function useUpdateInspirationLook(id: string) {
  const updateCache = useLookCache();
  return useMutation({
    mutationFn: (payload: InspirationLookUpdate) =>
      api.patch<InspirationLook>(lookPath(id), payload),
    onSuccess: (look) => updateCache(look),
  });
}

export function useReanalyzeInspirationLook(id: string) {
  const updateCache = useLookCache();
  return useMutation({
    mutationFn: () => api.post<InspirationLook>(`${lookPath(id)}/analyze`),
    onSuccess: (look) => updateCache(look),
  });
}

export function useRematchInspirationLook(id: string) {
  const updateCache = useLookCache();
  return useMutation({
    mutationFn: () => api.post<InspirationLook>(`${lookPath(id)}/match`),
    onSuccess: (look) => updateCache(look),
  });
}

export function useDeleteInspirationLook() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(lookPath(id)),
    onSuccess: (_, id) => {
      queryClient.removeQueries({ queryKey: queryKeys.inspirationLook(id) });
      queryClient.invalidateQueries({ queryKey: queryKeys.inspiration.all });
    },
  });
}

// Garment edits answer with the garment only, so the look is fetched again.
function useGarmentMutation<V>(id: string, mutationFn: (vars: V) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.inspirationLook(id) });
      queryClient.invalidateQueries({ queryKey: queryKeys.inspiration.all });
    },
  });
}

export function useAddInspirationGarment(id: string) {
  return useGarmentMutation(id, (garment: NewGarment) =>
    api.post<InspirationGarment>(`${lookPath(id)}/garments`, garment),
  );
}

export function useDeleteInspirationGarment(id: string) {
  return useGarmentMutation(id, (garmentId: string) =>
    api.delete<void>(`${lookPath(id)}/garments/${encodeURIComponent(garmentId)}`),
  );
}

export function useSetInspirationMatch(id: string) {
  return useGarmentMutation(
    id,
    ({ garmentId, itemId }: { garmentId: string; itemId: string | null }) =>
      api.put<InspirationGarment>(
        `${lookPath(id)}/garments/${encodeURIComponent(garmentId)}/match`,
        { wardrobe_item_id: itemId },
      ),
  );
}
