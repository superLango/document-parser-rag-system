import { useState } from "react";

import { Button } from "../ui/primitives";

export function ResultJson({ value }: { value: unknown }) {
  const [copied, setCopied] = useState(false);
  const text = JSON.stringify(value, null, 2);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="relative">
      <div className="absolute right-3 top-3">
        <Button variant="secondary" size="sm" onClick={() => void copy()}>
          {copied ? "已复制" : "复制"}
        </Button>
      </div>
      <pre className="max-h-[520px] overflow-auto rounded-lg bg-slate-950 p-4 font-mono text-xs leading-relaxed text-slate-100">
        {text}
      </pre>
    </div>
  );
}
