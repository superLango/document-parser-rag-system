import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode
} from "react";

import { cn } from "../../lib/utils";

type ToastTone = "success" | "error" | "info";
type ToastItem = { id: number; tone: ToastTone; title: string; description?: string };

type ToastContextValue = {
  push: (tone: ToastTone, title: string, description?: string) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast must be used inside ToastProvider");
  return value;
}

const TONE_STYLES: Record<ToastTone, string> = {
  success: "border-emerald-200 bg-white text-emerald-800",
  error: "border-rose-200 bg-white text-rose-700",
  info: "border-sky-200 bg-white text-sky-700"
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const push = useCallback((tone: ToastTone, title: string, description?: string) => {
    const id = nextId.current++;
    setItems((prev) => [...prev, { id, tone, title, description }]);
    window.setTimeout(() => {
      setItems((prev) => prev.filter((item) => item.id !== id));
    }, 4200);
  }, []);

  const value = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-80 flex-col gap-2">
        {items.map((item) => (
          <div
            key={item.id}
            className={cn(
              "animate-fade-up pointer-events-auto rounded-xl border px-4 py-3 shadow-lift",
              TONE_STYLES[item.tone]
            )}
            role="status"
          >
            <p className="text-sm font-medium">{item.title}</p>
            {item.description ? (
              <p className="mt-0.5 text-xs opacity-80">{item.description}</p>
            ) : null}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
