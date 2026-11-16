'use client';

import { useRef } from 'react';
import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { Camera, Loader2, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { getErrorMessage } from '@/lib/api';
import type { Outfit } from '@/lib/types';
import { useDeleteOutfitPhoto, useSetOutfitPhoto } from '@/lib/hooks/use-outfits';

export function OutfitPhoto({ outfit }: { outfit: Outfit }) {
  const t = useTranslations('outfits.photo');
  const input = useRef<HTMLInputElement>(null);
  const upload = useSetOutfitPhoto();
  const remove = useDeleteOutfitPhoto();
  const busy = upload.isPending || remove.isPending;

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    try {
      await upload.mutateAsync({ outfitId: outfit.id, file });
      toast.success(t('saved'));
    } catch (error) {
      toast.error(getErrorMessage(error, t('saveError')));
    } finally {
      if (input.current) input.current.value = '';
    }
  };

  const onRemove = async () => {
    if (!confirm(t('removeConfirm'))) return;
    try {
      await remove.mutateAsync(outfit.id);
    } catch (error) {
      toast.error(getErrorMessage(error, t('removeError')));
    }
  };

  return (
    <div className="space-y-3">
      <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
        {t('title')}
      </h2>
      {outfit.photo_url ? (
        <div className="relative mx-auto aspect-[3/4] w-full max-w-sm overflow-hidden rounded-lg border bg-muted">
          <Image
            src={outfit.photo_url}
            alt={t('alt')}
            fill
            className="object-cover"
            sizes="(max-width: 640px) 100vw, 384px"
          />
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">{t('empty')}</p>
      )}
      <div className="flex flex-wrap gap-2">
        <input
          ref={input}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/heic,image/heif"
          className="hidden"
          onChange={(e) => onFile(e.target.files?.[0])}
        />
        <Button variant="outline" size="sm" disabled={busy} onClick={() => input.current?.click()}>
          {upload.isPending ? (
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
          ) : (
            <Camera className="h-4 w-4 mr-2" />
          )}
          {outfit.photo_url ? t('replace') : t('add')}
        </Button>
        {outfit.photo_url && (
          <Button
            variant="outline"
            size="sm"
            className="text-destructive hover:text-destructive"
            disabled={busy}
            onClick={onRemove}
          >
            <Trash2 className="h-4 w-4 mr-2" />
            {t('remove')}
          </Button>
        )}
      </div>
    </div>
  );
}
