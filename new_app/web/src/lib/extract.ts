/** 文档库「提取」：每份文档一个文件夹（以 LIMS task_id 命名），内含 PDF、OCR Markdown、抽取 JSON。 */

import { ApiError } from "../api/client";
import type { DocumentItem } from "../api/types";
import { RUN_TERMINAL } from "./status";

// 可按最近运行状态筛选提取的状态（解析已结束的）。
export const EXTRACT_STATUSES = [...RUN_TERMINAL];
// 默认勾选：与一站式对接接口的成功状态一致，这些运行已产出可用的抽取结果。
export const EXTRACT_DEFAULT = ["HUMAN_REVIEW", "HUMAN_APPROVED", "STRUCTURED_READY"];

/** 产物不存在（如未路由没有抽取结果、OCR 失败没有 Markdown）时返回 null，其余错误照常抛出。 */
export async function orMissing<T>(request: Promise<T>): Promise<T | null> {
  try {
    return await request;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

const BAD_CHARS = /[<>:"/\\|?*\u0000-\u001f]/g;

/** Windows 不允许的字符替换为 _，去掉首尾空格与结尾的点。 */
export function safeName(name: string): string {
  return name.replace(BAD_CHARS, "_").trim().replace(/\.+$/, "") || "未命名";
}

export function stemOf(filename: string): string {
  const base = safeName(filename);
  const dot = base.lastIndexOf(".");
  // 去掉扩展名后再清理一次："xx C版 .pdf" 会剩下结尾空格，Windows 无法创建这样的文件夹
  return safeName(dot > 0 ? base.slice(0, dot) : base);
}

/**
 * 按上传时间筛选；from/to 为本地时间 YYYY-MM-DDTHH:mm（datetime-local 输入），空表示不限。
 * 结束时间包含该分钟内上传的文档。
 */
export function uploadedWithin(document: DocumentItem, from: string, to: string): boolean {
  const at = new Date(document.created_at).getTime();
  return (
    (!from || at >= new Date(from).getTime()) &&
    (!to || at < new Date(to).getTime() + 60_000)
  );
}

// Windows 资源管理器按字节限制 ZIP 条目路径（约 260 字节，实测中文 125 字符即整包无法识别）；
// 文件夹用 task_id 后「task_id/原文件名」基本都在限制内，超长的原文件名再截短兜底。
export const MAX_ENTRY_BYTES = 240;
const encoder = new TextEncoder();
const byteLength = (text: string) => encoder.encode(text).length;

function truncateBytes(text: string, max: number): string {
  const chars = Array.from(text);
  while (chars.length > 1 && byteLength(chars.join("")) > max) chars.pop();
  return safeName(chars.join(""));
}

/** 文件夹内的文件名：整条「文件夹/文件名」超长时截短主体部分，保留扩展名。 */
export function fitFileName(folder: string, name: string): string {
  const budget = MAX_ENTRY_BYTES - byteLength(folder) - 1;
  if (byteLength(name) <= budget) return name;
  const dot = name.lastIndexOf(".");
  const ext = dot > 0 ? name.slice(dot) : "";
  return truncateBytes(name.slice(0, name.length - ext.length), budget - byteLength(ext)) + ext;
}

/** 文件夹名：LIMS 对接任务的 task_id，与 LIMS 记录一一对应；页面手动上传的文档没有 task_id，用文档 ID。 */
export const folderOf = (document: DocumentItem): string => safeName(document.task_id || document.id);
