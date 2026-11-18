'use client';

import { useEffect, useState } from 'react';
import Image from 'next/image';
import { Check, Loader2 } from 'lucide-react';
import { useTranslations } from 'next-intl';
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
import { ItemPicker } from '@/components/shared/item-picker';
import { getErrorMessage } from '@/lib/api';
import type { Outfit, OutfitItem } from '@/lib/hooks/use-outfits';
import { usePatchOutfit } from '@/lib/hooks/use-studio';
import { useTypeLabel } from '@/lib/hooks/use-translated-constants';
import { cn } from '@/lib/utils';

type Piece = { id: string; type: string; name: string | null; thumbnail_url: string | null; image_url: string | null };

function Thumb({ piece, className }: { piece: Piece; className?: string }) {
  const typeLabel = useTypeLabel();
  const src = piece.thumbnail_url || piece.image_url;
  return (
    <div className={cn('relative aspect-square rounded-lg overflow-hidden border bg-muted', className)}>
      {src ? (
        <Image src={src} alt={piece.name || typeLabel(piece.type)} fill className="object-cover" sizes="96px" />
      ) : (
        <div className="w-full h-full flex items-center justify-center">
          <span className="text-[10px] text-muted-foreground">{typeLabel(piece.type)}</span>
        </div>
      )}
    </div>
  );
}

function alternatesMap(outfit: Outfit): Record<string, string[]> {
  const map: Record<string, string[]> = {};
  for (const item of outfit.items) {
    if (item.alternates?.length) map[item.id] = item.alternates.map((a) => a.id);
  }
  return map;
}

// Picks the items that can be worn in place of one of the outfit's items.
export function AlternatesDialog({
  outfit,
  item,
  onClose,
}: {
  outfit: Outfit;
  item: OutfitItem | null;
  onClose: () => void;
}) {
  const t = useTranslations('outfits.alternates');
  const tc = useTranslations('common');
  const typeLabel = useTypeLabel();
  const patch = usePatchOutfit();
  const [selected, setSelected] = useState<string[]>([]);

  useEffect(() => {
    setSelected(item?.alternates?.map((a) => a.id) ?? []);
  }, [item]);

  const inOutfit = new Set(outfit.items.map((i) => i.id));
  // Alternatives come from the same clothing type
  const sameType = item?.type;

  const handleSave = async () => {
    if (!item) return;
    const alternates = alternatesMap(outfit);
    if (selected.length) alternates[item.id] = selected;
    else delete alternates[item.id];
    try {
      await patch.mutateAsync({ id: outfit.id, payload: { alternates } });
      toast.success(t('saved'));
      onClose();
    } catch (error) {
      toast.error(getErrorMessage(error, t('saveError')));
    }
  };

  return (
    <Dialog open={item !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('title', { item: item?.name || typeLabel(item?.type ?? '') })}</DialogTitle>
          <DialogDescription>{t('description')}</DialogDescription>
        </DialogHeader>
        {item && (
          <ItemPicker
            selectedIds={new Set(selected)}
            filterType={sameType}
            hideNeedsWash={false}
            onToggle={(picked) => {
              if (inOutfit.has(picked.id)) return;
              setSelected((prev) =>
                prev.includes(picked.id) ? prev.filter((id) => id !== picked.id) : [...prev, picked.id]
              );
            }}
          />
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {tc('cancel')}
          </Button>
          <Button onClick={handleSave} disabled={patch.isPending}>
            {patch.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            {tc('save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// Asks which option was worn for every item that has alternates.
export function WearChoiceDialog({
  outfit,
  open,
  pending,
  onClose,
  onConfirm,
}: {
  outfit: Outfit;
  open: boolean;
  pending: boolean;
  onClose: () => void;
  onConfirm: (swaps: Record<string, string>) => void;
}) {
  const t = useTranslations('outfits.alternates');
  const tc = useTranslations('common');
  const typeLabel = useTypeLabel();
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const withOptions = outfit.items.filter((i) => i.alternates?.length);

  useEffect(() => {
    if (open) setChosen({});
  }, [open]);

  const handleConfirm = () => {
    const swaps: Record<string, string> = {};
    for (const [itemId, wornId] of Object.entries(chosen)) {
      if (wornId !== itemId) swaps[itemId] = wornId;
    }
    onConfirm(swaps);
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('wearTitle')}</DialogTitle>
          <DialogDescription>{t('wearDescription')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          {withOptions.map((item) => {
            const options: Piece[] = [item, ...(item.alternates ?? [])];
            const current = chosen[item.id] ?? item.id;
            return (
              <div key={item.id} className="space-y-1.5">
                <p className="text-xs font-medium text-muted-foreground">{typeLabel(item.type)}</p>
                <div className="grid grid-cols-4 gap-2">
                  {options.map((option) => {
                    const isChosen = option.id === current;
                    return (
                      <button
                        key={option.id}
                        type="button"
                        onClick={() => setChosen((prev) => ({ ...prev, [item.id]: option.id }))}
                        className="text-left"
                        aria-pressed={isChosen}
                      >
                        <div className="relative">
                          <Thumb
                            piece={option}
                            className={cn(
                              'border-2',
                              isChosen ? 'border-primary ring-2 ring-primary/20' : 'border-border'
                            )}
                          />
                          {isChosen && (
                            <div className="absolute top-1 right-1 rounded-full bg-primary p-0.5">
                              <Check className="h-3 w-3 text-primary-foreground" />
                            </div>
                          )}
                        </div>
                        <p className="text-[10px] text-muted-foreground mt-1 truncate">
                          {option.name || typeLabel(option.type)}
                        </p>
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {tc('cancel')}
          </Button>
          <Button onClick={handleConfirm} disabled={pending}>
            {pending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            {t('wearConfirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
