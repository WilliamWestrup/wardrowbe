'use client';

import { useState } from 'react';
import { useFormatter, useTranslations } from 'next-intl';
import { Check, ExternalLink, Pencil, RotateCcw, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { GapDialog } from '@/components/shopping/gap-dialog';
import { ItemThumbLink, LookThumbLink } from '@/components/shopping/thumb';
import { getErrorMessage } from '@/lib/api';
import { useOutfitTagLabel, useTypeLabel } from '@/lib/hooks/use-translated-constants';
import {
  type GapStatus,
  type ProductSuggestion,
  type WardrobeGap,
  useDeleteGap,
  useUpdateGap,
} from '@/lib/hooks/use-shopping';

const PRIORITY_VARIANT = { high: 'destructive', medium: 'default', low: 'secondary' } as const;

function ProductLine({ product }: { product: ProductSuggestion }) {
  const format = useFormatter();
  const t = useTranslations('shopping.products');
  let price: string | null = null;
  if (product.price !== null) {
    try {
      price = product.currency
        ? format.number(product.price, { style: 'currency', currency: product.currency })
        : format.number(product.price, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    } catch {
      price = `${product.price} ${product.currency ?? ''}`.trim();
    }
  }
  const checked = product.checked_at
    ? format.dateTime(new Date(`${product.checked_at}T00:00:00`), { dateStyle: 'medium' })
    : null;

  return (
    <li className="space-y-0.5 text-sm">
      <div className="flex flex-wrap items-baseline gap-x-2">
        {product.url ? (
          <a
            href={product.url}
            target="_blank"
            rel="noopener noreferrer nofollow"
            referrerPolicy="no-referrer"
            className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
          >
            {product.name}
            <ExternalLink className="h-3 w-3" />
          </a>
        ) : (
          <span className="font-medium">{product.name}</span>
        )}
        {product.store && <span className="text-muted-foreground">{product.store}</span>}
        {price && <span className="font-semibold">{price}</span>}
      </div>
      {(checked || product.notes) && (
        <p className="text-xs text-muted-foreground">
          {checked && t('checkedAt', { date: checked })}
          {checked && product.notes && ' · '}
          {product.notes}
        </p>
      )}
    </li>
  );
}

function Field({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="whitespace-pre-line text-sm">{value}</dd>
    </div>
  );
}

export function GapCard({ gap }: { gap: WardrobeGap }) {
  const t = useTranslations('shopping');
  const typeLabel = useTypeLabel();
  const tagLabel = useOutfitTagLabel();
  const update = useUpdateGap();
  const remove = useDeleteGap();
  const [editing, setEditing] = useState(false);
  const busy = update.isPending || remove.isPending;

  const setStatus = async (status: GapStatus) => {
    try {
      await update.mutateAsync({ id: gap.id, fields: { status } });
    } catch (error) {
      toast.error(getErrorMessage(error, t('saveError')));
    }
  };

  const onDelete = async () => {
    if (!confirm(t('gaps.deleteConfirm'))) return;
    try {
      await remove.mutateAsync(gap.id);
      toast.success(t('gaps.deleted'));
    } catch (error) {
      toast.error(getErrorMessage(error, t('deleteError')));
    }
  };

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0 space-y-1">
            <h3 className="font-semibold leading-tight">{gap.title}</h3>
            <div className="flex flex-wrap gap-1">
              <Badge variant={PRIORITY_VARIANT[gap.priority]}>{t(`priority.${gap.priority}`)}</Badge>
              {gap.status !== 'open' && <Badge variant="outline">{t(`gapStatus.${gap.status}`)}</Badge>}
              {gap.type && <Badge variant="secondary">{typeLabel(gap.type)}</Badge>}
              {gap.size && <Badge variant="outline">{t('sizeBadge', { size: gap.size })}</Badge>}
              {gap.tags.map((tag) => (
                <Badge key={tag} variant="secondary" className="font-normal">
                  {tagLabel(tag)}
                </Badge>
              ))}
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap gap-1">
            {gap.status === 'open' ? (
              <>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => setStatus('bought')}>
                  <Check className="h-4 w-4 mr-1" />
                  {t('gaps.markBought')}
                </Button>
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => setStatus('dropped')}>
                  <X className="h-4 w-4 mr-1" />
                  {t('gaps.drop')}
                </Button>
              </>
            ) : (
              <Button size="sm" variant="outline" disabled={busy} onClick={() => setStatus('open')}>
                <RotateCcw className="h-4 w-4 mr-1" />
                {t('reopen')}
              </Button>
            )}
            <Button size="icon" variant="ghost" aria-label={t('edit')} title={t('edit')} onClick={() => setEditing(true)}>
              <Pencil className="h-4 w-4" />
            </Button>
            <Button size="icon" variant="ghost" aria-label={t('delete')} title={t('delete')} disabled={busy} onClick={onDelete}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <dl className="grid gap-2 sm:grid-cols-3">
          <Field label={t('fields.reason')} value={gap.reason} />
          <Field label={t('fields.look_for')} value={gap.look_for} />
          <Field label={t('fields.avoid')} value={gap.avoid} />
        </dl>
        <Field label={t('fields.notes')} value={gap.notes} />

        {gap.products.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {t('products.title')}
            </p>
            <ul className="space-y-1.5">
              {gap.products.map((product, index) => (
                <ProductLine key={index} product={product} />
              ))}
            </ul>
          </div>
        )}

        {(gap.pairs_with.length > 0 || gap.inspiration_looks.length > 0 || gap.bought_item) && (
          <div className="flex flex-wrap gap-6">
            {gap.pairs_with.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {t('gaps.pairsWith')}
                </p>
                <div className="flex flex-wrap gap-2">
                  {gap.pairs_with.map((item) => (
                    <ItemThumbLink key={item.id} item={item} />
                  ))}
                </div>
              </div>
            )}
            {gap.inspiration_looks.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {t('gaps.looks')}
                </p>
                <div className="flex flex-wrap gap-2">
                  {gap.inspiration_looks.map((look) => (
                    <LookThumbLink key={look.id} look={look} fallbackLabel={t('gaps.untitledLook')} />
                  ))}
                </div>
              </div>
            )}
            {gap.bought_item && (
              <div className="space-y-1">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {t('gaps.boughtItem')}
                </p>
                <ItemThumbLink item={gap.bought_item} />
              </div>
            )}
          </div>
        )}
      </CardContent>
      {editing && <GapDialog gap={gap} open={editing} onOpenChange={setEditing} />}
    </Card>
  );
}
