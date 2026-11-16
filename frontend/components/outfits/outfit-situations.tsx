'use client';

import { useTranslations } from 'next-intl';
import { toast } from 'sonner';

import { cn } from '@/lib/utils';
import { getErrorMessage } from '@/lib/api';
import type { Outfit } from '@/lib/types';
import { CLIMATE_VALUES } from '@/lib/generated/garment-vocabulary';
import { usePatchOutfit } from '@/lib/hooks/use-studio';
import { useOutfitTagLabel } from '@/lib/hooks/use-translated-constants';

// The situations offered as chips; any other stored tag stays visible so it can be removed.
export const SITUATION_TAGS = [
  'work',
  'dinner',
  'date',
  'party',
  'weekend',
  'travel',
  'casual',
  'formal',
  'beach',
  'gym',
] as const;

export const OUTFIT_TAG_OPTIONS: readonly string[] = [...SITUATION_TAGS, ...CLIMATE_VALUES];

export function OutfitSituations({ outfit }: { outfit: Outfit }) {
  const t = useTranslations('outfits.situations');
  const tagLabel = useOutfitTagLabel();
  const patch = usePatchOutfit();
  const selected = outfit.tags ?? [];
  const options = [...OUTFIT_TAG_OPTIONS, ...selected.filter((tag) => !OUTFIT_TAG_OPTIONS.includes(tag))];

  const toggle = async (tag: string) => {
    const next = selected.includes(tag) ? selected.filter((s) => s !== tag) : [...selected, tag];
    try {
      await patch.mutateAsync({ id: outfit.id, payload: { tags: next } });
    } catch (error) {
      toast.error(getErrorMessage(error, t('saveError')));
    }
  };

  return (
    <div className="space-y-2">
      <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
        {t('title')}
      </h2>
      <p className="text-xs text-muted-foreground">{t('hint')}</p>
      <div className="flex flex-wrap gap-2">
        {options.map((tag) => {
          const on = selected.includes(tag);
          return (
            <button
              key={tag}
              type="button"
              aria-pressed={on}
              disabled={patch.isPending}
              onClick={() => toggle(tag)}
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
  );
}
