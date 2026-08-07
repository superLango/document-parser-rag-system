import { cva, type VariantProps } from 'class-variance-authority'

export { default as Badge } from './Badge.vue'

export const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 whitespace-nowrap select-none',
  {
    variants: {
      variant: {
        default:
          'border-transparent bg-primary text-primary-foreground shadow-sm shadow-primary/30 hover:shadow-md hover:shadow-primary/40 hover:bg-primary/90',
        secondary:
          'border-transparent bg-secondary text-secondary-foreground shadow-sm hover:bg-secondary/80',
        destructive:
          'border-transparent bg-destructive text-destructive-foreground shadow-sm shadow-destructive/20 hover:bg-destructive/90',
        outline:
          'text-foreground border-border bg-background/50 hover:bg-accent hover:text-accent-foreground',
        success:
          'border-transparent bg-success/15 text-success shadow-sm shadow-success/20 hover:bg-success/20',
        'success-solid':
          'border-transparent bg-success text-success-foreground shadow-sm shadow-success/30 hover:bg-success/90',
        warning:
          'border-transparent bg-warning/15 text-warning shadow-sm shadow-warning/20 hover:bg-warning/20',
        'warning-solid':
          'border-transparent bg-warning text-warning-foreground shadow-sm shadow-warning/30 hover:bg-warning/90',
        danger:
          'border-transparent bg-danger/15 text-danger shadow-sm shadow-danger/20 hover:bg-danger/20',
        'danger-solid':
          'border-transparent bg-danger text-danger-foreground shadow-sm shadow-danger/30 hover:bg-danger/90',
        info:
          'border-transparent bg-info/15 text-info shadow-sm shadow-info/20 hover:bg-info/20',
        'info-solid':
          'border-transparent bg-info text-info-foreground shadow-sm shadow-info/30 hover:bg-info/90',
        ghost:
          'border-transparent bg-transparent text-muted-foreground hover:bg-accent hover:text-accent-foreground',
        premium:
          'border-transparent bg-gradient-to-r from-primary/90 to-primary/70 text-primary-foreground shadow-md shadow-primary/40 hover:shadow-lg hover:shadow-primary/50',
      },
      size: {
        sm: 'h-5 px-2 text-[10px]',
        default: 'h-6 px-2.5 text-xs',
        lg: 'h-7 px-3 text-sm',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
)

export type BadgeVariants = VariantProps<typeof badgeVariants>
