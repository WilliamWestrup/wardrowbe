'use client';

import Image from 'next/image';
import Link from 'next/link';
import { Shirt } from 'lucide-react';
import { useTranslations } from 'next-intl';

import { useOutfits } from '@/lib/hooks/use-outfits';
import { useOutfitTitle } from '@/lib/hooks/use-outfit-title';
import { useTypeLabel } from '@/lib/hooks/use-translated-constants';

const MAX_OUTFITS = 50;

// Every outfit that uses the item, directly or as an alternate. Wear records of a lookbook
// outfit are left out: they repeat the outfit they came from.
export function ItemOutfits({ itemId }: { itemId: string }) {
  const t = useTranslations('outfits.itemOutfits');
  const typeLabel = useTypeLabel();
  const getTitle = useOutfitTitle();
  const { data, isLoading } = useOutfits({ item_id: itemId }, 1, MAX_OUTFITS);

  if (isLoading || !data?.outfits) return null;
  const outfits = data.outfits.filter((o) => !o.cloned_from_outfit_id);

  return (
    <div className="space-y-2 pt-2 border-t">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Shirt className="h-4 w-4 text-muted-foreground" />
        {t('title', { count: outfits.length })}
      </div>
      {outfits.length === 0 ? (
        <p className="text-xs text-muted-foreground">{t('empty')}</p>
      ) : (
        <div className="space-y-1.5">
          {outfits.map((outfit) => {
            const asAlternate = !outfit.items.some((i) => i.id === itemId);
            return (
              <Link
                key={outfit.id}
                href={`/dashboard/outfits/${outfit.id}`}
                className="flex items-center gap-2 rounded-md border px-2 py-1.5 hover:bg-muted/50"
              >
                <div className="flex -space-x-1.5 shrink-0">
                  {outfit.items.slice(0, 4).map((oi) => (
                    <div
                      key={oi.id}
                      className="w-7 h-7 rounded-full bg-muted border-2 border-background overflow-hidden"
                    >
                      {(oi.thumbnail_url || oi.image_url) && (
                        <Image
                          src={(oi.thumbnail_url || oi.image_url)!}
                          alt={oi.name || typeLabel(oi.type)}
                          width={28}
                          height={28}
                          className="object-cover w-full h-full"
                        />
                      )}
                    </div>
                  ))}
                </div>
                <span className="text-xs truncate flex-1">{getTitle(outfit)}</span>
                {asAlternate && (
                  <span className="text-[10px] text-muted-foreground whitespace-nowrap">
                    {t('asAlternate')}
                  </span>
                )}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
