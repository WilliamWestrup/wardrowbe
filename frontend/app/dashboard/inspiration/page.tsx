'use client';

import { useState } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { useTranslations } from 'next-intl';
import { Heart, ImageIcon, Plus, ThumbsUp } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { InspirationUploadDialog } from '@/components/inspiration/inspiration-upload-dialog';
import { OUTFIT_TAG_OPTIONS } from '@/components/outfits/outfit-situations';
import { cn } from '@/lib/utils';
import { useOutfitTagLabel } from '@/lib/hooks/use-translated-constants';
import {
  type InspirationLook,
  type InspirationVote,
  useInspirationLooks,
} from '@/lib/hooks/use-inspiration';

const VOTE_FILTERS: (InspirationVote | undefined)[] = [undefined, 'love', 'like'];

function LookCard({ look }: { look: InspirationLook }) {
  const t = useTranslations('inspiration');
  const tagLabel = useOutfitTagLabel();
  const src = look.photo_thumbnail_url || look.photo_medium_url;
  const VoteIcon = look.vote === 'love' ? Heart : look.vote === 'like' ? ThumbsUp : null;

  return (
    <Link href={`/dashboard/inspiration/${look.id}`} className="group">
      <Card className="overflow-hidden transition-shadow group-hover:shadow-md">
        <div className="relative aspect-[3/4] bg-muted">
          {src ? (
            <Image
              src={src}
              alt={look.title || t('untitled')}
              fill
              className="object-cover"
              sizes="(max-width: 640px) 50vw, (max-width: 1024px) 33vw, 240px"
            />
          ) : (
            <ImageIcon className="absolute inset-0 m-auto h-8 w-8 text-muted-foreground" />
          )}
          {VoteIcon && (
            <span
              className="absolute right-2 top-2 rounded-full bg-background/90 p-1.5"
              title={t(`vote.${look.vote}`)}
            >
              <VoteIcon className="h-4 w-4 fill-current text-primary" />
            </span>
          )}
        </div>
        <CardContent className="space-y-1.5 p-3">
          <p className="truncate text-sm font-medium">{look.title || t('untitled')}</p>
          {look.tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {look.tags.slice(0, 3).map((tag) => (
                <Badge key={tag} variant="secondary" className="text-[10px] font-normal">
                  {tagLabel(tag)}
                </Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}

export default function InspirationPage() {
  const t = useTranslations('inspiration');
  const tagLabel = useOutfitTagLabel();
  const [vote, setVote] = useState<InspirationVote | undefined>();
  const [tag, setTag] = useState('');
  const [uploadOpen, setUploadOpen] = useState(false);
  const { data, isLoading } = useInspirationLooks({ vote, tag: tag || undefined });
  const looks = data?.looks ?? [];
  const filtered = vote !== undefined || tag !== '';

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t('title')}</h1>
          <p className="text-muted-foreground">{t('subtitle')}</p>
        </div>
        <Button onClick={() => setUploadOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />
          {t('add')}
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {VOTE_FILTERS.map((value) => (
          <Button
            key={value ?? 'all'}
            size="sm"
            variant={vote === value ? 'default' : 'outline'}
            aria-pressed={vote === value}
            className={cn('rounded-full')}
            onClick={() => setVote(value)}
          >
            {t(`filters.${value ?? 'all'}`)}
          </Button>
        ))}
        <select
          aria-label={t('filters.tagLabel')}
          value={tag}
          onChange={(e) => setTag(e.target.value)}
          className="h-9 rounded-md border border-input bg-background px-3 text-sm"
        >
          <option value="">{t('filters.allTags')}</option>
          {OUTFIT_TAG_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {tagLabel(option)}
            </option>
          ))}
        </select>
        {data && (
          <Badge variant="outline" className="ml-auto">
            {t('totalCount', { count: data.total })}
          </Badge>
        )}
      </div>

      {isLoading ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="aspect-[3/4]" />
          ))}
        </div>
      ) : looks.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
            <ImageIcon className="h-10 w-10 text-muted-foreground" />
            <p className="font-medium">{filtered ? t('noMatches') : t('empty')}</p>
            {!filtered && <p className="max-w-sm text-sm text-muted-foreground">{t('emptyHint')}</p>}
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {looks.map((look) => (
            <LookCard key={look.id} look={look} />
          ))}
        </div>
      )}

      <InspirationUploadDialog open={uploadOpen} onOpenChange={setUploadOpen} />
    </div>
  );
}
