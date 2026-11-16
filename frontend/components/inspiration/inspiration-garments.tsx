'use client';

import { useState } from 'react';
import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { Link2, Loader2, Plus, RefreshCw, Shirt, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ItemPicker } from '@/components/shared/item-picker';
import { getErrorMessage } from '@/lib/api';
import { colorSwatch } from '@/lib/colors';
import { useClothingColors, useClothingTypes, useColorLabel, useTypeLabel } from '@/lib/hooks/use-translated-constants';
import {
  type InspirationGarment,
  type InspirationLook,
  type WardrobeItemSummary,
  isAnalysisRunning,
  useAddInspirationGarment,
  useDeleteInspirationGarment,
  useRematchInspirationLook,
  useSetInspirationMatch,
} from '@/lib/hooks/use-inspiration';

function ItemThumb({ item, size = 56 }: { item: WardrobeItemSummary; size?: number }) {
  const src = item.thumbnail_url || item.image_url;
  return (
    <div
      className="relative shrink-0 overflow-hidden rounded-md border bg-muted"
      style={{ width: size, height: size }}
    >
      {src ? (
        <Image src={src} alt={item.name ?? item.type} fill className="object-cover" sizes={`${size}px`} />
      ) : (
        <Shirt className="m-auto h-1/2 w-1/2 text-muted-foreground" />
      )}
    </div>
  );
}

function PickerDialog({
  garment,
  open,
  onOpenChange,
  onSelect,
}: {
  garment: InspirationGarment;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (itemId: string) => void;
}) {
  const t = useTranslations('inspiration.match');
  const typeLabel = useTypeLabel();
  const [allTypes, setAllTypes] = useState(false);
  const filterType = allTypes || garment.type === 'unknown' ? undefined : garment.type;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setAllTypes(false);
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-xl max-h-[85vh] flex flex-col p-6">
        <DialogHeader>
          <DialogTitle>{t('pickerTitle')}</DialogTitle>
          <DialogDescription>{t('pickerDescription')}</DialogDescription>
        </DialogHeader>
        <div className="flex gap-1.5 py-1">
          <Button
            type="button"
            size="sm"
            variant={allTypes ? 'outline' : 'default'}
            className="h-7 rounded-full px-2.5 text-xs"
            onClick={() => setAllTypes(false)}
          >
            {t('onlyType', { type: typeLabel(garment.type) })}
          </Button>
          <Button
            type="button"
            size="sm"
            variant={allTypes ? 'default' : 'outline'}
            className="h-7 rounded-full px-2.5 text-xs"
            onClick={() => setAllTypes(true)}
          >
            {t('allTypes')}
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-hidden pt-1">
          <ItemPicker
            key={filterType ?? 'all'}
            selectedIds={garment.matched_item_id ? new Set([garment.matched_item_id]) : new Set()}
            onToggle={(item) => {
              onSelect(item.id);
              onOpenChange(false);
            }}
            filterType={filterType}
            hideNeedsWash={false}
            emptyMessage={t('pickerEmpty')}
            heightClass="h-[340px]"
          />
        </div>
      </DialogContent>
    </Dialog>
  );
}

function GarmentRow({ look, garment, locked }: { look: InspirationLook; garment: InspirationGarment; locked: boolean }) {
  const t = useTranslations('inspiration');
  const typeLabel = useTypeLabel();
  const colorLabel = useColorLabel();
  const setMatch = useSetInspirationMatch(look.id);
  const remove = useDeleteInspirationGarment(look.id);
  const [picking, setPicking] = useState(false);
  const busy = setMatch.isPending || remove.isPending;
  const alternatives = garment.suggested_items.filter((item) => item.id !== garment.matched_item_id);

  const link = async (itemId: string | null) => {
    try {
      await setMatch.mutateAsync({ garmentId: garment.id, itemId });
    } catch (error) {
      toast.error(getErrorMessage(error, t('match.error')));
    }
  };

  const onRemove = async () => {
    try {
      await remove.mutateAsync(garment.id);
    } catch (error) {
      toast.error(getErrorMessage(error, t('garments.removeError')));
    }
  };

  return (
    <li className="rounded-lg border p-3 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 font-medium">
            {garment.primary_color && (
              <span
                className="inline-block h-3 w-3 shrink-0 rounded-full border"
                style={{ backgroundColor: colorSwatch(garment.primary_color) }}
                aria-hidden="true"
              />
            )}
            <span>{typeLabel(garment.type)}</span>
            {garment.primary_color && (
              <span className="text-sm font-normal text-muted-foreground">
                {colorLabel(garment.primary_color)}
              </span>
            )}
          </div>
          {garment.description && (
            <p className="text-sm text-muted-foreground">{garment.description}</p>
          )}
        </div>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="h-8 w-8 shrink-0 text-muted-foreground"
          aria-label={t('garments.remove')}
          disabled={busy || locked}
          onClick={onRemove}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>

      <div className="flex items-center gap-3">
        {garment.matched_item ? (
          <>
            <ItemThumb item={garment.matched_item} />
            <div className="min-w-0 flex-1">
              <p className="text-xs text-muted-foreground">{t('match.linked')}</p>
              <p className="truncate text-sm font-medium">
                {garment.matched_item.name || typeLabel(garment.matched_item.type)}
              </p>
            </div>
          </>
        ) : (
          <p className="flex-1 text-sm text-muted-foreground">{t('match.none')}</p>
        )}
        <div className="flex shrink-0 gap-1">
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setPicking(true)}>
            <Link2 className="h-4 w-4 mr-1" />
            {garment.matched_item ? t('match.change') : t('match.choose')}
          </Button>
          {garment.matched_item && (
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="h-9 w-9"
              aria-label={t('match.clear')}
              disabled={busy}
              onClick={() => link(null)}
            >
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>

      {alternatives.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">{t('match.suggestions')}</p>
          <div className="flex gap-2">
            {alternatives.map((item) => (
              <button
                key={item.id}
                type="button"
                disabled={busy}
                title={item.name || typeLabel(item.type)}
                aria-label={item.name || typeLabel(item.type)}
                onClick={() => link(item.id)}
                className="rounded-md ring-offset-background hover:ring-2 hover:ring-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <ItemThumb item={item} size={44} />
              </button>
            ))}
          </div>
        </div>
      )}

      <PickerDialog garment={garment} open={picking} onOpenChange={setPicking} onSelect={link} />
    </li>
  );
}

function AddGarmentForm({ look, onDone }: { look: InspirationLook; onDone: () => void }) {
  const t = useTranslations('inspiration.garments');
  const types = useClothingTypes();
  const colors = useClothingColors();
  const add = useAddInspirationGarment(look.id);
  const [type, setType] = useState('');
  const [color, setColor] = useState('');
  const [description, setDescription] = useState('');

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!type) return;
    try {
      await add.mutateAsync({
        type,
        primary_color: color || null,
        description: description.trim() || null,
      });
      onDone();
    } catch (error) {
      toast.error(getErrorMessage(error, t('addError')));
    }
  };

  const selectClass = 'h-9 w-full rounded-md border border-input bg-background px-3 text-sm';

  return (
    <form onSubmit={onSubmit} className="space-y-3 rounded-lg border border-dashed p-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="garment-type">{t('typeLabel')}</Label>
          <select id="garment-type" required value={type} onChange={(e) => setType(e.target.value)} className={selectClass}>
            <option value="" disabled>
              {t('typePlaceholder')}
            </option>
            {types.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="garment-color">{t('colorLabel')}</Label>
          <select id="garment-color" value={color} onChange={(e) => setColor(e.target.value)} className={selectClass}>
            <option value="">{t('anyColor')}</option>
            {colors.map((option) => (
              <option key={option.value} value={option.value}>
                {option.name}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="space-y-1">
        <Label htmlFor="garment-description">{t('descriptionLabel')}</Label>
        <Input
          id="garment-description"
          value={description}
          maxLength={200}
          placeholder={t('descriptionPlaceholder')}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={!type || add.isPending}>
          {add.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
          {t('save')}
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onDone}>
          {t('cancel')}
        </Button>
      </div>
    </form>
  );
}

export function InspirationGarments({ look }: { look: InspirationLook }) {
  const t = useTranslations('inspiration.garments');
  const rematch = useRematchInspirationLook(look.id);
  const [adding, setAdding] = useState(false);
  const locked = isAnalysisRunning(look);

  const onRematch = async () => {
    if (look.matched_at && !confirm(t('rematchConfirm'))) return;
    try {
      await rematch.mutateAsync();
    } catch (error) {
      toast.error(getErrorMessage(error, t('rematchError')));
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
          {t('title')}
        </h2>
        {look.garments.length > 0 && (
          <Button type="button" size="sm" variant="outline" disabled={locked || rematch.isPending} onClick={onRematch}>
            <RefreshCw className={rematch.isPending ? 'h-4 w-4 mr-2 animate-spin' : 'h-4 w-4 mr-2'} />
            {t('rematch')}
          </Button>
        )}
      </div>

      {look.garments.length === 0 && !locked && (
        <p className="text-sm text-muted-foreground">{t('empty')}</p>
      )}

      <ul className="space-y-3">
        {look.garments.map((garment) => (
          <GarmentRow key={garment.id} look={look} garment={garment} locked={locked} />
        ))}
      </ul>

      {!locked &&
        (adding ? (
          <AddGarmentForm look={look} onDone={() => setAdding(false)} />
        ) : (
          <Button type="button" size="sm" variant="outline" onClick={() => setAdding(true)}>
            <Plus className="h-4 w-4 mr-2" />
            {t('add')}
          </Button>
        ))}
    </div>
  );
}
