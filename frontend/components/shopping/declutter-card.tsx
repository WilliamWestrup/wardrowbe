'use client';

import Link from 'next/link';
import { useTranslations } from 'next-intl';
import { Check, RotateCcw, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { ItemThumbLink } from '@/components/shopping/thumb';
import { getErrorMessage } from '@/lib/api';
import { useTypeLabel } from '@/lib/hooks/use-translated-constants';
import {
  DECLUTTER_ACTIONS,
  type DeclutterAction,
  type DeclutterStatus,
  type DeclutterSuggestion,
  useDeleteDeclutter,
  useUpdateDeclutter,
} from '@/lib/hooks/use-shopping';

/** Marking a suggestion done only records the decision; archiving the item stays a separate
 *  step in the wardrobe, reached through the item link. */
export function DeclutterCard({ suggestion }: { suggestion: DeclutterSuggestion }) {
  const t = useTranslations('shopping');
  const typeLabel = useTypeLabel();
  const update = useUpdateDeclutter();
  const remove = useDeleteDeclutter();
  const busy = update.isPending || remove.isPending;
  const { item } = suggestion;
  const itemLabel = item.name || typeLabel(item.type);

  const save = async (fields: { status?: DeclutterStatus; action?: DeclutterAction }) => {
    try {
      await update.mutateAsync({ id: suggestion.id, fields });
    } catch (error) {
      toast.error(getErrorMessage(error, t('saveError')));
    }
  };

  const onDelete = async () => {
    if (!confirm(t('declutter.deleteConfirm'))) return;
    try {
      await remove.mutateAsync(suggestion.id);
      toast.success(t('declutter.deleted'));
    } catch (error) {
      toast.error(getErrorMessage(error, t('deleteError')));
    }
  };

  return (
    <Card>
      <CardContent className="flex gap-3 p-4">
        <ItemThumbLink item={item} size={64} />
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Link href={`/dashboard/wardrobe?item=${item.id}`} className="font-semibold hover:underline">
              {itemLabel}
            </Link>
            {suggestion.status !== 'open' && (
              <Badge variant="outline">{t(`declutterStatus.${suggestion.status}`)}</Badge>
            )}
            {item.is_archived && <Badge variant="secondary">{t('declutter.archived')}</Badge>}
          </div>
          <p className="whitespace-pre-line text-sm">{suggestion.reason}</p>
          {suggestion.notes && (
            <p className="whitespace-pre-line text-xs text-muted-foreground">{suggestion.notes}</p>
          )}
          <div className="flex flex-wrap items-center gap-1">
            <select
              aria-label={t('declutter.changeAction')}
              value={suggestion.action}
              disabled={busy}
              onChange={(e) => save({ action: e.target.value as DeclutterAction })}
              className="h-9 rounded-md border border-input bg-background px-2 text-sm"
            >
              {DECLUTTER_ACTIONS.map((action) => (
                <option key={action} value={action}>
                  {t(`action.${action}`)}
                </option>
              ))}
            </select>
            {suggestion.status === 'open' ? (
              <>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => save({ status: 'done' })}>
                  <Check className="h-4 w-4 mr-1" />
                  {t('declutter.markDone')}
                </Button>
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => save({ status: 'dismissed' })}>
                  <X className="h-4 w-4 mr-1" />
                  {t('declutter.dismiss')}
                </Button>
              </>
            ) : (
              <Button size="sm" variant="outline" disabled={busy} onClick={() => save({ status: 'open' })}>
                <RotateCcw className="h-4 w-4 mr-1" />
                {t('reopen')}
              </Button>
            )}
            <Button size="icon" variant="ghost" aria-label={t('delete')} title={t('delete')} disabled={busy} onClick={onDelete}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
