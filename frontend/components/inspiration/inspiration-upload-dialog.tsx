'use client';

import { useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';
import { ImagePlus, Loader2 } from 'lucide-react';
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
import { getErrorMessage } from '@/lib/api';
import { useCreateInspirationLook } from '@/lib/hooks/use-inspiration';

const ACCEPT = 'image/jpeg,image/png,image/webp,image/heic,image/heif';

export function InspirationUploadDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations('inspiration.upload');
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const create = useCreateInspirationLook();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [sourceUrl, setSourceUrl] = useState('');

  const reset = () => {
    setFile(null);
    setTitle('');
    setSourceUrl('');
    if (input.current) input.current.value = '';
  };

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!file) return;
    try {
      const look = await create.mutateAsync({ file, title, sourceUrl });
      toast.success(t('success'));
      reset();
      onOpenChange(false);
      router.push(`/dashboard/inspiration/${look.id}`);
    } catch (error) {
      toast.error(getErrorMessage(error, t('error')));
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-md">
        <form onSubmit={onSubmit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{t('title')}</DialogTitle>
            <DialogDescription>{t('description')}</DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label>{t('photo')}</Label>
            <input
              ref={input}
              type="file"
              accept={ACCEPT}
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <Button
              type="button"
              variant="outline"
              className="w-full justify-start"
              onClick={() => input.current?.click()}
            >
              <ImagePlus className="h-4 w-4 mr-2" />
              <span className="truncate">{file ? file.name : t('choose')}</span>
            </Button>
          </div>

          <div className="space-y-2">
            <Label htmlFor="inspiration-title">{t('titleLabel')}</Label>
            <Input
              id="inspiration-title"
              value={title}
              maxLength={200}
              placeholder={t('titlePlaceholder')}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="inspiration-source">{t('sourceLabel')}</Label>
            <Input
              id="inspiration-source"
              type="url"
              inputMode="url"
              value={sourceUrl}
              maxLength={2000}
              placeholder={t('sourcePlaceholder')}
              onChange={(e) => setSourceUrl(e.target.value)}
            />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('cancel')}
            </Button>
            <Button type="submit" disabled={!file || create.isPending}>
              {create.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              {t('save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
