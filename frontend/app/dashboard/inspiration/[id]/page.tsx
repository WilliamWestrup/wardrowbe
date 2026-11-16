'use client';

import { useRef, useState } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { useParams, useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';
import {
  Camera,
  ChevronLeft,
  ExternalLink,
  Loader2,
  Pencil,
  RefreshCw,
  Trash2,
} from 'lucide-react';
import { toast } from 'sonner';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  InspirationDetailsForm,
  InspirationNotes,
  InspirationTags,
  InspirationVoteToggle,
} from '@/components/inspiration/inspiration-fields';
import { InspirationGarments } from '@/components/inspiration/inspiration-garments';
import { getErrorMessage } from '@/lib/api';
import { useAiUiEnabled } from '@/lib/hooks/use-features';
import {
  type InspirationLook,
  isAnalysisRunning,
  useDeleteInspirationLook,
  useInspirationLook,
  useReanalyzeInspirationLook,
  useReplaceInspirationPhoto,
} from '@/lib/hooks/use-inspiration';

const ACCEPT = 'image/jpeg,image/png,image/webp,image/heic,image/heif';

function sourceHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

function AnalysisStatus({ look }: { look: InspirationLook }) {
  const t = useTranslations('inspiration.analysis');
  const aiUiEnabled = useAiUiEnabled();
  const reanalyze = useReanalyzeInspirationLook(look.id);

  if (isAnalysisRunning(look)) {
    return (
      <Alert>
        <AlertDescription className="flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('running')}
        </AlertDescription>
      </Alert>
    );
  }
  if (look.status !== 'error') return null;

  return (
    <Alert>
      <AlertDescription className="space-y-2">
        <p>{t('error')}</p>
        {aiUiEnabled && (
          <Button
            size="sm"
            variant="outline"
            disabled={reanalyze.isPending}
            onClick={async () => {
              try {
                await reanalyze.mutateAsync();
              } catch (error) {
                toast.error(getErrorMessage(error, t('retryError')));
              }
            }}
          >
            <RefreshCw className="h-4 w-4 mr-2" />
            {t('retry')}
          </Button>
        )}
      </AlertDescription>
    </Alert>
  );
}

export default function InspirationDetailPage() {
  const t = useTranslations('inspiration');
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const lookId = params?.id ?? '';
  const { data: look, isLoading, isError } = useInspirationLook(lookId);
  const deleteLook = useDeleteInspirationLook();
  const replacePhoto = useReplaceInspirationPhoto(lookId);
  const photoInput = useRef<HTMLInputElement>(null);
  const [editing, setEditing] = useState(false);

  if (isError) {
    return (
      <div className="space-y-4 max-w-4xl mx-auto">
        <Button variant="ghost" size="sm" asChild>
          <Link href="/dashboard/inspiration">
            <ChevronLeft className="h-4 w-4 mr-1" />
            {t('detail.back')}
          </Link>
        </Button>
        <p className="text-muted-foreground">{t('detail.notFound')}</p>
      </div>
    );
  }

  if (isLoading || !look) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-96" />
      </div>
    );
  }

  const onDelete = async () => {
    if (!confirm(t('detail.deleteConfirm'))) return;
    try {
      await deleteLook.mutateAsync(look.id);
      toast.success(t('detail.deleted'));
      router.push('/dashboard/inspiration');
    } catch (error) {
      toast.error(getErrorMessage(error, t('detail.deleteError')));
    }
  };

  const onPhoto = async (file: File | undefined) => {
    if (!file) return;
    if (look.garments.length > 0 && !confirm(t('detail.replaceConfirm'))) {
      if (photoInput.current) photoInput.current.value = '';
      return;
    }
    try {
      await replacePhoto.mutateAsync(file);
      toast.success(t('detail.photoReplaced'));
    } catch (error) {
      toast.error(getErrorMessage(error, t('detail.photoError')));
    } finally {
      if (photoInput.current) photoInput.current.value = '';
    }
  };

  const photo = look.photo_medium_url || look.photo_url;

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <Button variant="ghost" size="sm" asChild>
        <Link href="/dashboard/inspiration">
          <ChevronLeft className="h-4 w-4 mr-1" />
          {t('detail.back')}
        </Link>
      </Button>

      <div className="grid gap-6 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className="space-y-3">
          <div className="relative aspect-[3/4] w-full overflow-hidden rounded-lg border bg-muted">
            {photo && (
              <a href={look.photo_url ?? photo} target="_blank" rel="noopener noreferrer">
                <Image
                  src={photo}
                  alt={look.title || t('detail.photoAlt')}
                  fill
                  className="object-cover"
                  sizes="(max-width: 768px) 100vw, 400px"
                  priority
                />
              </a>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <input
              ref={photoInput}
              type="file"
              accept={ACCEPT}
              className="hidden"
              onChange={(e) => onPhoto(e.target.files?.[0])}
            />
            <Button
              size="sm"
              variant="outline"
              disabled={replacePhoto.isPending}
              onClick={() => photoInput.current?.click()}
            >
              {replacePhoto.isPending ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Camera className="h-4 w-4 mr-2" />
              )}
              {t('detail.replacePhoto')}
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="text-destructive hover:text-destructive"
              disabled={deleteLook.isPending}
              onClick={onDelete}
            >
              <Trash2 className="h-4 w-4 mr-2" />
              {t('detail.delete')}
            </Button>
          </div>
        </div>

        <div className="space-y-6">
          <Card>
            <CardContent className="space-y-4 p-4">
              {editing ? (
                <InspirationDetailsForm look={look} onDone={() => setEditing(false)} />
              ) : (
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 space-y-1">
                    <h1 className="text-2xl font-bold tracking-tight break-words">
                      {look.title || t('untitled')}
                    </h1>
                    {look.source_url && (
                      <a
                        href={look.source_url}
                        target="_blank"
                        rel="noopener noreferrer nofollow"
                        referrerPolicy="no-referrer"
                        className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                        {sourceHost(look.source_url)}
                      </a>
                    )}
                  </div>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="shrink-0"
                    aria-label={t('detail.editDetails')}
                    onClick={() => setEditing(true)}
                  >
                    <Pencil className="h-4 w-4" />
                  </Button>
                </div>
              )}
              <InspirationVoteToggle look={look} />
            </CardContent>
          </Card>

          <InspirationTags look={look} />
          <AnalysisStatus look={look} />
          <InspirationGarments look={look} />
          <InspirationNotes key={look.id} look={look} />
        </div>
      </div>
    </div>
  );
}
