import type { CSSProperties, ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'

interface StatCardProps {
  title: string
  value: ReactNode
  hint?: string
  icon: LucideIcon
  tone?: 'green' | 'blue' | 'amber' | 'violet' | 'rose'
  delay?: number
}

const tones: Record<string, { tile: string; bar: string }> = {
  green: { tile: 'from-emerald-100 to-teal-50 text-emerald-600', bar: 'bg-emerald-500' },
  blue: { tile: 'from-sky-100 to-cyan-50 text-sky-600', bar: 'bg-sky-500' },
  amber: { tile: 'from-amber-100 to-orange-50 text-amber-600', bar: 'bg-amber-500' },
  violet: { tile: 'from-violet-100 to-purple-50 text-violet-600', bar: 'bg-violet-500' },
  rose: { tile: 'from-rose-100 to-pink-50 text-rose-600', bar: 'bg-rose-500' },
}

export function StatCard({ title, value, hint, icon: Icon, tone = 'green', delay = 0 }: StatCardProps) {
  const t = tones[tone]
  return (
    <Card
      interactive
      className="animate-fade-up relative overflow-hidden"
      style={{ animationDelay: `${delay}ms` } as CSSProperties}
    >
      <div className={cn('absolute inset-y-0 left-0 w-0.5', t.bar)} />
      <CardContent className="flex items-start justify-between gap-4 p-5">
        <div className="space-y-1">
          <p className="text-sm text-muted-foreground">{title}</p>
          <p className="font-display text-2xl font-semibold tracking-tight">{value}</p>
          {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
        </div>
        <div
          className={cn(
            'flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br shadow-soft',
            t.tile,
          )}
        >
          <Icon className="h-5 w-5" strokeWidth={1.8} />
        </div>
      </CardContent>
    </Card>
  )
}
