import * as React from 'react'
import { CheckCircle2, Info, XCircle, AlertTriangle } from 'lucide-react'
import { cn } from '@/lib/utils'

type ToastKind = 'success' | 'error' | 'warning' | 'info'

interface ToastItem {
  id: number
  kind: ToastKind
  title: string
  description?: string
}

const ToastContext = React.createContext<{
  toast: (kind: ToastKind, title: string, description?: string) => void
} | null>(null)

let toastSeq = 0

const kindStyles: Record<ToastKind, { icon: React.ReactNode; bar: string; text: string }> = {
  success: { icon: <CheckCircle2 className="h-5 w-5 text-success" />, bar: 'bg-success', text: 'text-success' },
  error: { icon: <XCircle className="h-5 w-5 text-destructive" />, bar: 'bg-destructive', text: 'text-destructive' },
  warning: { icon: <AlertTriangle className="h-5 w-5 text-warning" />, bar: 'bg-warning', text: 'text-warning' },
  info: { icon: <Info className="h-5 w-5 text-info" />, bar: 'bg-info', text: 'text-info' },
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = React.useState<ToastItem[]>([])

  const toast = React.useCallback(
    (kind: ToastKind, title: string, description?: string) => {
      const id = ++toastSeq
      setItems((prev) => [...prev.slice(-4), { id, kind, title, description }])
      window.setTimeout(() => {
        setItems((prev) => prev.filter((item) => item.id !== id))
      }, 4000)
    },
    [],
  )

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="pointer-events-none fixed right-4 top-4 z-[100] flex w-96 max-w-[calc(100vw-2rem)] flex-col gap-2">
        {items.map((item) => (
          <div
            key={item.id}
            className="animate-toast-in pointer-events-auto relative overflow-hidden rounded-xl border border-border bg-card p-4 shadow-modal"
          >
            <div className={cn('absolute inset-y-0 left-0 w-1', kindStyles[item.kind].bar)} />
            <div className="flex items-start gap-3 pl-2">
              {kindStyles[item.kind].icon}
              <div>
                <p className={cn('text-sm font-medium', kindStyles[item.kind].text)}>{item.title}</p>
                {item.description ? (
                  <p className="mt-0.5 text-xs text-muted-foreground">{item.description}</p>
                ) : null}
              </div>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = React.useContext(ToastContext)
  if (!ctx) throw new Error('useToast 必须在 ToastProvider 内使用')
  return ctx
}
