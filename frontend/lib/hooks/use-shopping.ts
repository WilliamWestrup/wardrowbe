import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSession } from 'next-auth/react';
import { api } from '@/lib/api';
import { useSetTokenIfAvailable } from '@/lib/hooks/use-session-token';
import { queryKeys } from '@/lib/hooks/query-keys';

export type GapPriority = 'high' | 'medium' | 'low';
export type GapStatus = 'open' | 'bought' | 'dropped';
export type DeclutterAction = 'donate' | 'sell' | 'alter' | 'decide' | 'keep';
export type DeclutterStatus = 'open' | 'done' | 'dismissed';

export const GAP_PRIORITIES: GapPriority[] = ['high', 'medium', 'low'];
export const GAP_STATUSES: GapStatus[] = ['open', 'bought', 'dropped'];
export const DECLUTTER_ACTIONS: DeclutterAction[] = ['donate', 'sell', 'alter', 'decide', 'keep'];
export const DECLUTTER_STATUSES: DeclutterStatus[] = ['open', 'done', 'dismissed'];

export interface ShoppingItemSummary {
  id: string;
  name: string | null;
  type: string;
  primary_color: string | null;
  thumbnail_url: string | null;
  is_archived: boolean;
}

export interface ShoppingLookSummary {
  id: string;
  title: string | null;
  thumbnail_url: string | null;
}

export interface ProductSuggestion {
  name: string;
  store: string | null;
  url: string | null;
  price: number | null;
  currency: string | null;
  checked_at: string | null;
  notes: string | null;
}

export interface WardrobeGap {
  id: string;
  title: string;
  type: string | null;
  priority: GapPriority;
  status: GapStatus;
  reason: string | null;
  look_for: string | null;
  avoid: string | null;
  size: string | null;
  notes: string | null;
  tags: string[];
  pairs_with_item_ids: string[];
  inspiration_look_ids: string[];
  bought_item_id: string | null;
  products: ProductSuggestion[];
  position: number;
  created_at: string;
  updated_at: string;
  pairs_with: ShoppingItemSummary[];
  inspiration_looks: ShoppingLookSummary[];
  bought_item: ShoppingItemSummary | null;
}

export interface WardrobeGapFields {
  title?: string;
  type?: string | null;
  priority?: GapPriority;
  status?: GapStatus;
  reason?: string | null;
  look_for?: string | null;
  avoid?: string | null;
  size?: string | null;
  notes?: string | null;
  tags?: string[];
}

export interface DeclutterSuggestion {
  id: string;
  item_id: string;
  action: DeclutterAction;
  reason: string;
  status: DeclutterStatus;
  notes: string | null;
  created_at: string;
  updated_at: string;
  item: ShoppingItemSummary;
}

export interface DeclutterFields {
  action?: DeclutterAction;
  reason?: string;
  status?: DeclutterStatus;
  notes?: string | null;
}

export interface GapFilters {
  status?: GapStatus;
}

export interface DeclutterFilters {
  status?: DeclutterStatus;
}

const LIST_LIMIT = '200';

function gapPath(id: string) {
  return `/shopping/gaps/${encodeURIComponent(id)}`;
}

function declutterPath(id: string) {
  return `/shopping/declutter/${encodeURIComponent(id)}`;
}

export function useWardrobeGaps(filters: GapFilters = {}) {
  const { status } = useSession();
  useSetTokenIfAvailable();

  return useQuery({
    queryKey: queryKeys.shopping.gaps(filters),
    queryFn: () => {
      const params: Record<string, string> = { limit: LIST_LIMIT };
      if (filters.status) params.status = filters.status;
      return api.get<{ gaps: WardrobeGap[]; total: number }>('/shopping/gaps', { params });
    },
    enabled: status !== 'loading',
  });
}

export function useDeclutterSuggestions(filters: DeclutterFilters = {}) {
  const { status } = useSession();
  useSetTokenIfAvailable();

  return useQuery({
    queryKey: queryKeys.shopping.declutter(filters),
    queryFn: () => {
      const params: Record<string, string> = { limit: LIST_LIMIT };
      if (filters.status) params.status = filters.status;
      return api.get<{ suggestions: DeclutterSuggestion[]; total: number }>(
        '/shopping/declutter',
        { params },
      );
    },
    enabled: status !== 'loading',
  });
}

function useShoppingMutation<V, R>(mutationFn: (vars: V) => Promise<R>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.shopping.all }),
  });
}

export function useCreateGap() {
  return useShoppingMutation((fields: WardrobeGapFields & { title: string }) =>
    api.post<WardrobeGap>('/shopping/gaps', fields),
  );
}

export function useUpdateGap() {
  return useShoppingMutation(({ id, fields }: { id: string; fields: WardrobeGapFields }) =>
    api.patch<WardrobeGap>(gapPath(id), fields),
  );
}

export function useDeleteGap() {
  return useShoppingMutation((id: string) => api.delete<void>(gapPath(id)));
}

export function useUpdateDeclutter() {
  return useShoppingMutation(({ id, fields }: { id: string; fields: DeclutterFields }) =>
    api.patch<DeclutterSuggestion>(declutterPath(id), fields),
  );
}

export function useDeleteDeclutter() {
  return useShoppingMutation((id: string) => api.delete<void>(declutterPath(id)));
}
