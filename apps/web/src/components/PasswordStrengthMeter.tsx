import { Check, X } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Requirement {
  label: string
  test: (pwd: string) => boolean
}

const requirements: Requirement[] = [
  { label: '至少 8 位', test: (p) => p.length >= 8 },
  { label: '包含大写字母', test: (p) => /[A-Z]/.test(p) },
  { label: '包含小写字母', test: (p) => /[a-z]/.test(p) },
  { label: '包含数字', test: (p) => /\d/.test(p) },
  { label: '包含特殊字符', test: (p) => /[!@#$%^&*()_+\-=\[\]{};':",.<>/?\\|`~]/.test(p) },
]

function strengthLevel(pwd: string): number {
  if (!pwd) return 0
  const count = requirements.filter((r) => r.test(pwd)).length
  if (count <= 2) return 1
  if (count <= 3) return 2
  if (count <= 4) return 3
  return 4
}

const labels = ['', '弱', '中', '强', '很强']
const colors = ['bg-muted', 'bg-warning', 'bg-warning', 'bg-primary', 'bg-success']

export function PasswordStrengthMeter({ password }: { password: string }) {
  if (!password) return null
  const level = strengthLevel(password)
  return (
    <div className="mt-2 space-y-2">
      <div className="flex gap-1">
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className={cn('h-1 flex-1 rounded-full transition-colors', i <= level ? colors[level] : 'bg-muted')}
          />
        ))}
      </div>
      <p
        className={cn(
          'text-xs',
          level === 1 && 'text-warning',
          level === 2 && 'text-warning',
          level === 3 && 'text-primary',
          level === 4 && 'text-success',
          level === 0 && 'text-muted-foreground',
        )}
      >
        密码强度：{labels[level]}
      </p>
      <ul className="space-y-1">
        {requirements.map((r) => {
          const passed = r.test(password)
          return (
            <li
              key={r.label}
              className={cn(
                'flex items-center gap-1.5 text-xs',
                passed ? 'text-success' : 'text-muted-foreground',
              )}
            >
              {passed ? <Check className="h-3 w-3 shrink-0" /> : <X className="h-3 w-3 shrink-0" />}
              {r.label}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
