import { useEffect, useRef, useState } from 'react'
import { Search, X } from 'lucide-react'
import { usersApi } from '@/api/modules/users'
import { Input } from '@/components/ui/input'
import type { UserSearchItem } from '@/api/types'

interface UserComboboxProps {
  value: UserSearchItem | null
  onSelect: (user: UserSearchItem) => void
  placeholder?: string
  disabled?: boolean
}

export function UserCombobox({
  value,
  onSelect,
  placeholder = '输入用户名搜索成员',
  disabled,
}: UserComboboxProps) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<UserSearchItem[]>([])
  const [loading, setLoading] = useState(false)
  const [active, setActive] = useState(0)
  const rootRef = useRef<HTMLDivElement>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    const q = query.trim()
    if (!q) {
      setResults([])
      setLoading(false)
      return
    }
    setLoading(true)
    timerRef.current = setTimeout(() => {
      usersApi
        .search(q)
        .then((items) => {
          setResults(items)
          setActive(0)
        })
        .catch(() => setResults([]))
        .finally(() => setLoading(false))
    }, 250)
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [query])

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((v) => Math.min(v + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((v) => Math.max(v - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const item = results[active]
      if (item) {
        onSelect(item)
        setOpen(false)
      }
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  function clear() {
    setQuery('')
    setResults([])
    onSelect({ id: '', username: '', full_name: null, department: null, email: null })
  }

  return (
    <div ref={rootRef} className="relative">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          disabled={disabled}
          onChange={(e) => {
            setQuery(e.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder={value?.username ? `已选择：@${value.username}` : placeholder}
          className="pl-9 pr-9"
        />
        {value?.username ? (
          <button
            type="button"
            onClick={clear}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground transition-colors hover:text-destructive"
            aria-label="清除选择"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>

      {open && query.trim() ? (
        <div className="animate-scale-in absolute left-0 right-0 z-50 mt-1.5 max-h-64 overflow-auto rounded-xl border border-border bg-card p-1 shadow-modal">
          {loading && results.length === 0 ? (
            <p className="px-3 py-3 text-center text-xs text-muted-foreground">搜索中...</p>
          ) : results.length === 0 ? (
            <p className="px-3 py-3 text-center text-xs text-muted-foreground">
              未找到匹配用户（仅可添加系统内现有用户）
            </p>
          ) : (
            results.map((u, index) => (
              <button
                key={u.id}
                type="button"
                onMouseEnter={() => setActive(index)}
                onClick={() => {
                  onSelect(u)
                  setOpen(false)
                }}
                className={`flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors ${
                  index === active ? 'bg-accent' : 'hover:bg-muted'
                }`}
              >
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-emerald-100 to-teal-50 text-xs font-semibold text-primary-strong">
                  {(u.full_name || u.username || 'U').slice(0, 1).toUpperCase()}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{u.full_name || u.username}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    @{u.username}
                    {u.department ? ` · ${u.department}` : ''}
                  </span>
                </span>
                {u.email ? (
                  <span className="hidden shrink-0 text-xs text-muted-foreground sm:block">{u.email}</span>
                ) : null}
              </button>
            ))
          )}
        </div>
      ) : null}
    </div>
  )
}
