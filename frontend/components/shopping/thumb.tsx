'use client';

import Image from 'next/image';
import Link from 'next/link';
import { ImageIcon, Shirt } from 'lucide-react';

import { useTypeLabel } from '@/lib/hooks/use-translated-constants';
import type { ShoppingItemSummary, ShoppingLookSummary } from '@/lib/hooks/use-shopping';

function Thumb({ src, alt, size, look }: { src: string | null; alt: string; size: number; look?: boolean }) {
  const Fallback = look ? ImageIcon : Shirt;
  return (
    <div
      className="relative shrink-0 overflow-hidden rounded-md border bg-muted"
      style={{ width: size, height: size }}
    >
      {src ? (
        <Image src={src} alt={alt} fill className="object-cover" sizes={`${size}px`} />
      ) : (
        <Fallback className="absolute inset-0 m-auto h-1/2 w-1/2 text-muted-foreground" />
      )}
    </div>
  );
}

export function ItemThumbLink({ item, size = 48 }: { item: ShoppingItemSummary; size?: number }) {
  const typeLabel = useTypeLabel();
  const label = item.name || typeLabel(item.type);
  return (
    <Link href={`/dashboard/wardrobe?item=${item.id}`} title={label} className="block">
      <Thumb src={item.thumbnail_url} alt={label} size={size} />
    </Link>
  );
}

export function LookThumbLink({
  look,
  fallbackLabel,
  size = 48,
}: {
  look: ShoppingLookSummary;
  fallbackLabel: string;
  size?: number;
}) {
  const label = look.title || fallbackLabel;
  return (
    <Link href={`/dashboard/inspiration/${look.id}`} title={label} className="block">
      <Thumb src={look.thumbnail_url} alt={label} size={size} look />
    </Link>
  );
}
