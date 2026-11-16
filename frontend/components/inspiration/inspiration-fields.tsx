'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { Heart, Loader2, ThumbsUp } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { OUTFIT_TAG_OPTIONS } from '@/components/outfits/outfit-situations';
import { getErrorMessage } from '@/lib/api';
import { cn } from '@/lib/utils';
import { useOutfitTagLabel } from '@/lib/hooks/use-translated-constants';
import {
  type InspirationLook,
  type InspirationLookUpdate,
  type InspirationVote,
  useUpdateInspirationLook,
} from '@/lib/hooks/use-inspiration';

const VOTES: { value: InspirationVote; icon: typeof Heart }[] = [
  { value: 'love', icon: Heart },
  { value: 'like', icon: ThumbsUp },
];

function useSave(look: InspirationLook) {
  const t = useTranslations('inspiration.detail');
  const update = useUpdateInspirationLook(look.id);
  const save = async (payload: InspirationLookUpdate) => {
    try {
      await update.mutateAsync(payload);
      return true;
    } catch (error) {
      toast.error(getErrorMessage(error, t('saveError')));
      return false;
    }
  };
  return { save, pending: update.isPending };
}

export function InspirationVoteToggle({ look }: { look: InspirationLook }) {
  const t = useTranslations('inspiration.vote');
  const { save, pending } = useSave(look);

  return (
    <div className="flex gap-2" role="group" aria-label={t('label')}>
      {VOTES.map(({ value, icon: Icon }) => {
        const on = look.vote === value;
        return (
          <Button
            key={value}
            type="button"
            size="sm"
            variant={on ? 'default' : 'outline'}
            aria-pressed={on}
            disabled={pending}
            onClick={() => save({ vote: on ? null : value })}
          >
            <Icon className={cn('h-4 w-4 mr-2', on && 'fill-current')} />
            {t(value)}
          </Button>
        );
      })}
    </div>
  );
}

export function InspirationTags({ look }: { look: InspirationLook }) {
  const t = useTranslations('inspiration.tags');
  const tagLabel = useOutfitTagLabel();
  const { save, pending } = useSave(look);
  const selected = look.tags;
  const options = [...OUTFIT_TAG_OPTIONS, ...selected.filter((tag) => !OUTFIT_TAG_OPTIONS.includes(tag))];

  const toggle = (tag: string) =>
    save({ tags: selected.includes(tag) ? selected.filter((s) => s !== tag) : [...selected, tag] });

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
              disabled={pending}
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

export function InspirationNotes({ look }: { look: InspirationLook }) {
  const t = useTranslations('inspiration.notes');
  const { save, pending } = useSave(look);
  const [draft, setDraft] = useState(look.notes ?? '');
  const dirty = draft.trim() !== (look.notes ?? '');

  return (
    <div className="space-y-2">
      <Label
        htmlFor="inspiration-notes"
        className="text-sm font-semibold text-muted-foreground uppercase tracking-wide"
      >
        {t('title')}
      </Label>
      <Textarea
        id="inspiration-notes"
        value={draft}
        maxLength={5000}
        rows={4}
        placeholder={t('placeholder')}
        onChange={(e) => setDraft(e.target.value)}
      />
      <Button
        size="sm"
        variant="outline"
        disabled={!dirty || pending}
        onClick={async () => {
          if (await save({ notes: draft })) toast.success(t('saved'));
        }}
      >
        {pending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
        {t('save')}
      </Button>
    </div>
  );
}

export function InspirationDetailsForm({
  look,
  onDone,
}: {
  look: InspirationLook;
  onDone: () => void;
}) {
  const t = useTranslations('inspiration.detail');
  const tu = useTranslations('inspiration.upload');
  const { save, pending } = useSave(look);
  const [title, setTitle] = useState(look.title ?? '');
  const [sourceUrl, setSourceUrl] = useState(look.source_url ?? '');

  return (
    <form
      className="space-y-3"
      onSubmit={async (event) => {
        event.preventDefault();
        if (await save({ title, source_url: sourceUrl })) onDone();
      }}
    >
      <div className="space-y-1">
        <Label htmlFor="inspiration-edit-title">{tu('titleLabel')}</Label>
        <Input
          id="inspiration-edit-title"
          value={title}
          maxLength={200}
          placeholder={tu('titlePlaceholder')}
          onChange={(e) => setTitle(e.target.value)}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor="inspiration-edit-source">{tu('sourceLabel')}</Label>
        <Input
          id="inspiration-edit-source"
          type="url"
          inputMode="url"
          value={sourceUrl}
          maxLength={2000}
          placeholder={tu('sourcePlaceholder')}
          onChange={(e) => setSourceUrl(e.target.value)}
        />
      </div>
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={pending}>
          {t('save')}
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onDone}>
          {tu('cancel')}
        </Button>
      </div>
    </form>
  );
}
