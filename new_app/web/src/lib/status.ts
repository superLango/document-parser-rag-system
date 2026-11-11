export type Tone = "success" | "warning" | "danger" | "info" | "neutral";

export const RUN_TERMINAL = new Set([
  "STRUCTURED_READY",
  "REVIEW_FAILED",
  "FAILED",
  "CANCELLED"
]);

const RUN_STATUS: Record<string, { label: string; tone: Tone }> = {
  RECEIVED: { label: "已接收", tone: "neutral" },
  OCR_RUNNING: { label: "OCR 中", tone: "info" },
  OCR_DONE: { label: "OCR 完成", tone: "info" },
  ROUTING: { label: "路由中", tone: "info" },
  ROUTED: { label: "路由完成", tone: "info" },
  SANDBOX_RUNNING: { label: "沙箱解析中", tone: "info" },
  PARSED: { label: "解析完成", tone: "info" },
  REVIEWING: { label: "审核中", tone: "info" },
  REVIEW_PASSED: { label: "审核通过", tone: "info" },
  REVIEW_FAILED: { label: "审核未通过", tone: "danger" },
  STRUCTURED_READY: { label: "结构化就绪", tone: "success" },
  FAILED: { label: "失败", tone: "danger" },
  CANCELLED: { label: "已取消", tone: "neutral" }
};

export function runStatusMeta(status: string): { label: string; tone: Tone } {
  return RUN_STATUS[status] ?? { label: status, tone: "neutral" };
}

export const STAGE_LABELS: Record<string, string> = {
  ocr: "OCR",
  routing: "配方路由",
  sandbox: "沙箱解析",
  review: "规则审核"
};

export const FEEDBACK_STATUS: Record<string, { label: string; tone: Tone }> = {
  open: { label: "待处理", tone: "warning" },
  processing: { label: "处理中", tone: "info" },
  proposed: { label: "已提案", tone: "info" },
  verifying: { label: "验证中", tone: "info" },
  verified: { label: "待决策", tone: "warning" },
  promoted: { label: "已晋升", tone: "success" },
  discarded: { label: "已丢弃", tone: "neutral" },
  needs_more_info: { label: "需补充", tone: "danger" }
};

export const ROOT_CAUSE_LABELS: Record<string, string> = {
  ocr_error: "OCR 错误",
  table_structure: "表格结构",
  recipe_binding: "配方绑定",
  template_schema: "模板 Schema",
  model_extraction: "模型抽取",
  dictionary: "业务词典",
  display: "展示映射",
  unknown: "未知"
};

export const SEVERITY_META: Record<string, { label: string; tone: Tone }> = {
  info: { label: "提示", tone: "info" },
  warning: { label: "警告", tone: "warning" },
  error: { label: "错误", tone: "danger" }
};

export const REVIEW_STATUS: Record<string, { label: string; tone: Tone }> = {
  pass: { label: "通过", tone: "success" },
  warn: { label: "有警告", tone: "warning" },
  fail: { label: "未通过", tone: "danger" }
};

export const CHANNEL_LABELS: Record<string, string> = {
  stable: "stable",
  candidate: "candidate",
  shadow: "shadow",
  deprecated: "deprecated"
};
