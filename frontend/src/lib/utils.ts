import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * cn - className 合并工具
 * 结合 clsx 的条件类名与 tailwind-merge 的冲突解决
 * 用法: cn('px-2', isActive && 'bg-primary', 'px-4') => 'bg-primary px-4'
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
