import { useEffect, useState } from "react";

// 像 useState，但存在本标签页的 sessionStorage 里：离开页面（进详情、切菜单）再回来时页码、筛选不丢。
export function useSessionState<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const saved: unknown = JSON.parse(sessionStorage.getItem(key) ?? "null");
      return typeof saved === typeof initial ? (saved as T) : initial;
    } catch {
      return initial;
    }
  });
  useEffect(() => {
    try {
      sessionStorage.setItem(key, JSON.stringify(value));
    } catch {
      // 存储被禁用（如 iframe 隐私设置）时只是不恢复
    }
  }, [key, value]);
  return [value, setValue] as const;
}
