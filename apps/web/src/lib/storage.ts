/**
 * 安全存储：第三方 iframe / 无痕模式下浏览器可能禁用 localStorage。
 * 访问失败时回退到内存，保证页面仍能渲染（刷新后不保留登录态）。
 */

type StorageLike = {
  getItem: (key: string) => string | null
  setItem: (key: string, value: string) => void
  removeItem: (key: string) => void
}

const memory = new Map<string, string>()
let cached: Storage | null | undefined

function nativeStorage(): Storage | null {
  if (cached !== undefined) return cached
  try {
    if (typeof window === 'undefined' || !window.localStorage) {
      cached = null
      return cached
    }
    const probe = '__hanson_storage_probe__'
    window.localStorage.setItem(probe, '1')
    window.localStorage.removeItem(probe)
    cached = window.localStorage
  } catch {
    cached = null
  }
  return cached
}

export const safeStorage: StorageLike = {
  getItem(key: string): string | null {
    try {
      const storage = nativeStorage()
      if (storage) return storage.getItem(key)
    } catch {
      // fall through to memory
    }
    return memory.get(key) ?? null
  },
  setItem(key: string, value: string): void {
    try {
      const storage = nativeStorage()
      if (storage) {
        storage.setItem(key, value)
        return
      }
    } catch {
      // fall through to memory
    }
    memory.set(key, value)
  },
  removeItem(key: string): void {
    try {
      const storage = nativeStorage()
      if (storage) storage.removeItem(key)
    } catch {
      // ignore and clear memory below
    }
    memory.delete(key)
  },
}
