'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { OUTFIT_TAG_OPTIONS } from '@/components/outfits/outfit-situations';
import { getErrorMessage } from '@/lib/api';
import { CLOTHING_TYPE_VALUES } from '@/lib/generated/garment-vocabulary';
import { cn } from '@/lib/utils';
import { useOutfitTagLabel, useTypeLabel } from '@/lib/hooks/use-translated-constants';
import {
  GAP_PRIORITIES,
  type GapPriority,
  type WardrobeGap,
  type WardrobeGapFields,
  useCreateGap,
  useUpdateGap,
} from '@/lib/hooks/use-shopping';

const TEXT_FIELDS = ['reason', 'look_for', 'avoid', 'notes'] as const;
type TextField = (typeof TEXT_FIELDS)[number];

interface Draft {
  title: string;
  type: string;
  priority: GapPriority;
  size: string;
  tags: string[];
  reason: string;
  look_for: string;
  avoid: string;
  notes: string;
}

function draftFrom(gap?: WardrobeGap): Draft {
  return {
    title: gap?.title ?? '',
    type: gap?.type ?? '',
    priority: gap?.priority ?? 'medium',
    size: gap?.size ?? '',
    tags: gap?.tags ?? [],
    reason: gap?.reason ?? '',
    look_for: gap?.look_for ?? '',
    avoid: gap?.avoid ?? '',
    notes: gap?.notes ?? '',
  };
}

function toFields(draft: Draft): WardrobeGapFields & { title: string } {
  const orNull = (value: string) => value.trim() || null;
  return {
    title: draft.title.trim(),
    type: draft.type || null,
    priority: draft.priority,
    size: orNull(draft.size),
    tags: draft.tags,
    reason: orNull(draft.reason),
    look_for: orNull(draft.look_for),
    avoid: orNull(draft.avoid),
    notes: orNull(draft.notes),
  };
}

/** Create a gap (no `gap`) or edit one. Products and linked pieces are written by the
 *  stylist through the API, so they are shown on the card but not edited here. */
export function GapDialog({
  gap,
  open,
  onOpenChange,
}: {
  gap?: WardrobeGap;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations('shopping.gapDialog');
  const tf = useTranslations('shopping.fields');
  const tp = useTranslations('shopping.priority');
  const typeLabel = useTypeLabel();
  const tagLabel = useOutfitTagLabel();
  const create = useCreateGap();
  const update = useUpdateGap();
  const [draft, setDraft] = useState<Draft>(() => draftFrom(gap));
  const pending = create.isPending || update.isPending;
  const tagOptions = [...OUTFIT_TAG_OPTIONS, ...draft.tags.filter((tag) => !OUTFIT_TAG_OPTIONS.includes(tag))];

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  const toggleTag = (tag: string) =>
    set('tags', draft.tags.includes(tag) ? draft.tags.filter((s) => s !== tag) : [...draft.tags, tag]);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!draft.title.trim()) return;
    try {
      if (gap) await update.mutateAsync({ id: gap.id, fields: toFields(draft) });
      else await create.mutateAsync(toFields(draft));
      toast.success(t('saved'));
      onOpenChange(false);
    } catch (error) {
      toast.error(getErrorMessage(error, t('saveError')));
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (next) setDraft(draftFrom(gap));
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <form onSubmit={onSubmit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{gap ? t('editTitle') : t('newTitle')}</DialogTitle>
            <DialogDescription>{t('description')}</DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="gap-title">{tf('title')}</Label>
            <Input
              id="gap-title"
              value={draft.title}
              maxLength={120}
              required
              placeholder={t('titlePlaceholder')}
              onChange={(e) => set('title', e.target.value)}
            />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="space-y-2">
              <Label htmlFor="gap-type">{tf('type')}</Label>
              <select
                id="gap-type"
                value={draft.type}
                onChange={(e) => set('type', e.target.value)}
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                <option value="">{t('anyType')}</option>
                {CLOTHING_TYPE_VALUES.map((value) => (
                  <option key={value} value={value}>
                    {typeLabel(value)}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="gap-priority">{tf('priority')}</Label>
              <select
                id="gap-priority"
                value={draft.priority}
                onChange={(e) => set('priority', e.target.value as GapPriority)}
                className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              >
                {GAP_PRIORITIES.map((value) => (
                  <option key={value} value={value}>
                    {tp(value)}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="gap-size">{tf('size')}</Label>
              <Input
                id="gap-size"
                value={draft.size}
                maxLength={50}
                onChange={(e) => set('size', e.target.value)}
              />
            </div>
          </div>

          {TEXT_FIELDS.map((field: TextField) => (
            <div key={field} className="space-y-2">
              <Label htmlFor={`gap-${field}`}>{tf(field)}</Label>
              <Textarea
                id={`gap-${field}`}
                value={draft[field]}
                maxLength={2000}
                rows={2}
                onChange={(e) => set(field, e.target.value)}
              />
            </div>
          ))}

          <div className="space-y-2">
            <Label>{tf('tags')}</Label>
            <div className="flex flex-wrap gap-2">
              {tagOptions.map((tag) => {
                const on = draft.tags.includes(tag);
                return (
                  <button
                    key={tag}
                    type="button"
                    aria-pressed={on}
                    onClick={() => toggleTag(tag)}
                    className={cn(
                      'inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium transition-colors',
                      on
                        ? 'border-primary bg-primary text-primary-foreground'
                        : 'border-muted bg-background text-muted-foreground hover:border-muted-foreground/50',
                    )}
                  >
                    {tagLabel(tag)}
                  </button>
                );
              })}
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('cancel')}
            </Button>
            <Button type="submit" disabled={!draft.title.trim() || pending}>
              {pending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              {t('save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
