'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { Plus, ShoppingBag, Archive } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { DeclutterCard } from '@/components/shopping/declutter-card';
import { GapCard } from '@/components/shopping/gap-card';
import { GapDialog } from '@/components/shopping/gap-dialog';
import {
  DECLUTTER_ACTIONS,
  DECLUTTER_STATUSES,
  type DeclutterStatus,
  GAP_PRIORITIES,
  GAP_STATUSES,
  type GapStatus,
  useDeclutterSuggestions,
  useWardrobeGaps,
} from '@/lib/hooks/use-shopping';

function StatusFilter<S extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: S[];
  value: S | undefined;
  onChange: (value: S | undefined) => void;
  label: (value: S | 'all') => string;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {[undefined, ...options].map((option) => (
        <Button
          key={option ?? 'all'}
          size="sm"
          variant={value === option ? 'default' : 'outline'}
          aria-pressed={value === option}
          className="rounded-full"
          onClick={() => onChange(option)}
        >
          {label(option ?? 'all')}
        </Button>
      ))}
    </div>
  );
}

function ListSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 3 }, (_, i) => (
        <Skeleton key={i} className="h-32" />
      ))}
    </div>
  );
}

function EmptyState({ icon: Icon, title, hint }: { icon: typeof ShoppingBag; title: string; hint?: string }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
        <Icon className="h-10 w-10 text-muted-foreground" />
        <p className="font-medium">{title}</p>
        {hint && <p className="max-w-sm text-sm text-muted-foreground">{hint}</p>}
      </CardContent>
    </Card>
  );
}

function GapsTab() {
  const t = useTranslations('shopping');
  const [status, setStatus] = useState<GapStatus | undefined>('open');
  const [creating, setCreating] = useState(false);
  const { data, isLoading } = useWardrobeGaps({ status });
  const gaps = data?.gaps ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <StatusFilter
          options={GAP_STATUSES}
          value={status}
          onChange={setStatus}
          label={(value) => t(`gapStatus.${value}`)}
        />
        <Button onClick={() => setCreating(true)}>
          <Plus className="h-4 w-4 mr-2" />
          {t('gaps.add')}
        </Button>
      </div>

      {isLoading ? (
        <ListSkeleton />
      ) : gaps.length === 0 ? (
        <EmptyState
          icon={ShoppingBag}
          title={status === 'open' ? t('gaps.empty') : t('noMatches')}
          hint={status === 'open' ? t('gaps.emptyHint') : undefined}
        />
      ) : (
        GAP_PRIORITIES.map((priority) => {
          const group = gaps.filter((gap) => gap.priority === priority);
          if (group.length === 0) return null;
          return (
            <section key={priority} className="space-y-3">
              <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                {t(`priorityGroup.${priority}`)}
                <Badge variant="outline">{group.length}</Badge>
              </h2>
              {group.map((gap) => (
                <GapCard key={gap.id} gap={gap} />
              ))}
            </section>
          );
        })
      )}

      {creating && <GapDialog open={creating} onOpenChange={setCreating} />}
    </div>
  );
}

function DeclutterTab() {
  const t = useTranslations('shopping');
  const [status, setStatus] = useState<DeclutterStatus | undefined>('open');
  const { data, isLoading } = useDeclutterSuggestions({ status });
  const suggestions = data?.suggestions ?? [];

  return (
    <div className="space-y-4">
      <StatusFilter
        options={DECLUTTER_STATUSES}
        value={status}
        onChange={setStatus}
        label={(value) => t(`declutterStatus.${value}`)}
      />
      <p className="text-sm text-muted-foreground">{t('declutter.hint')}</p>

      {isLoading ? (
        <ListSkeleton />
      ) : suggestions.length === 0 ? (
        <EmptyState
          icon={Archive}
          title={status === 'open' ? t('declutter.empty') : t('noMatches')}
          hint={status === 'open' ? t('declutter.emptyHint') : undefined}
        />
      ) : (
        DECLUTTER_ACTIONS.map((action) => {
          const group = suggestions.filter((s) => s.action === action);
          if (group.length === 0) return null;
          return (
            <section key={action} className="space-y-3">
              <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                {t(`action.${action}`)}
                <Badge variant="outline">{group.length}</Badge>
              </h2>
              {group.map((suggestion) => (
                <DeclutterCard key={suggestion.id} suggestion={suggestion} />
              ))}
            </section>
          );
        })
      )}
    </div>
  );
}

export default function ShoppingPage() {
  const t = useTranslations('shopping');

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{t('title')}</h1>
        <p className="text-muted-foreground">{t('subtitle')}</p>
      </div>

      <Tabs defaultValue="gaps" className="space-y-4">
        <TabsList>
          <TabsTrigger value="gaps">{t('tabs.gaps')}</TabsTrigger>
          <TabsTrigger value="declutter">{t('tabs.declutter')}</TabsTrigger>
        </TabsList>
        <TabsContent value="gaps">
          <GapsTab />
        </TabsContent>
        <TabsContent value="declutter">
          <DeclutterTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
