import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-primary text-primary-foreground',
        success: 'border-transparent bg-emerald-50 text-success',
        warning: 'border-transparent bg-amber-50 text-warning',
        destructive: 'border-transparent bg-rose-50 text-destructive',
        info: 'border-transparent bg-sky-50 text-info',
        secondary: 'border-transparent bg-secondary text-secondary-foreground',
        outline: 'border-border bg-card text-muted-foreground',
      },
      dot: {
        true: 'before:size-1.5 before:rounded-full before:bg-current before:content-[""]',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, dot, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant, dot }), className)} {...props} />
}
