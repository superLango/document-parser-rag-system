import type { PropertyValue, RecordItem } from "../api/types";
import { buildRows, standardInfo } from "../components/result/ResultTable";

const HEADERS = [
  "标准名称",
  "标准编号",
  "项目大类",
  "记录类型",
  "项目名称",
  "材料牌号",
  "标准要求",
  "单位",
  "试验方法",
  "试验温度",
  "位置",
  "方向",
  "尺寸厚度",
  "试样状态",
  "取样数量",
  "取样说明",
  "锻件类型",
  "工序名称",
  "工艺名称",
  "保温温度",
  "保温时间",
  "升温速率",
  "降温速率",
  "装炉温度",
  "出炉温度",
  "冷却介质",
  "介质温度"
];

const HEAT_KEYS = [
  "保温温度",
  "保温时间",
  "升温速率",
  "降温速率",
  "装炉温度",
  "出炉温度",
  "冷却介质",
  "介质温度"
];

function csvCell(value: unknown): string {
  return `"${String(value ?? "").replace(/"/g, '""')}"`;
}

function propertyText(property?: PropertyValue): string {
  if (!property) return "";
  const raw =
    property.raw ||
    (property.value === null || property.value === undefined
      ? ""
      : String(property.value));
  if (!raw) return "";
  return property.unit ? `${raw} ${property.unit}` : raw;
}

function fieldValue(
  fields: Record<string, string>,
  keys: string[]
): string {
  for (const key of keys) {
    if (fields[key]) return fields[key];
  }
  return "";
}

export function fileTimestamp(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return [
    `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}`,
    `${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`
  ].join("-");
}

export function resultCsvFilename(sourceName: string, at = new Date()): string {
  const stem = sourceName
    .replace(/\.(pdf|md|markdown|txt)$/i, "")
    .replace(/[\\/:*?"<>|]/g, "_")
    .trim();
  return `${stem || "解析结果"}-${fileTimestamp(at)}.csv`;
}

export function buildResultCsv(
  records: RecordItem[],
  filename: string,
  markdown = ""
): string {
  const standard = standardInfo(filename, markdown);
  const standardRecords = records.filter(
    (record) => record.profile !== "heat_treatment"
  );
  const heatRecords = records.filter(
    (record) => record.profile === "heat_treatment"
  );
  const rows: string[][] = [];

  for (const row of buildRows(standardRecords)) {
    rows.push([
      standard.name,
      standard.number,
      row.category,
      "标准要求",
      row.name,
      row.grade,
      row.requirement,
      row.unit,
      fieldValue(row.fields, ["试验方法", "方法"]),
      fieldValue(row.fields, ["试验温度", "温度"]),
      fieldValue(row.fields, ["位置", "取样位置"]),
      fieldValue(row.fields, ["方向"]),
      fieldValue(row.fields, ["尺寸厚度", "厚度", "规格"]),
      fieldValue(row.fields, ["试样状态", "状态", "交货状态"]),
      fieldValue(row.fields, ["取样数量", "取样数"]),
      fieldValue(row.fields, ["取样说明"]),
      fieldValue(row.fields, ["锻件类型"]),
      "",
      "",
      "",
      "",
      "",
      "",
      "",
      "",
      "",
      ""
    ]);
  }

  for (const record of heatRecords) {
    const process =
      record.conditions["工序名称"] || record.conditions["工序"] || "";
    const craft =
      record.conditions["工艺名称"] ||
      propertyText(record.properties["工艺名称"] as PropertyValue | undefined);
    const summary = HEAT_KEYS.map((key) => {
      const value = propertyText(record.properties[key] as PropertyValue | undefined);
      return value ? `${key}=${value}` : "";
    })
      .filter(Boolean)
      .join("；");
    rows.push([
      standard.name,
      standard.number,
      record.conditions["项目大类"] || "热处理项目",
      "热处理制度",
      process || craft || "热处理",
      record.grade || "",
      summary,
      "",
      "",
      "",
      "",
      "",
      "",
      "",
      "",
      "",
      "",
      process,
      craft,
      propertyText(record.properties["保温温度"] as PropertyValue | undefined),
      propertyText(record.properties["保温时间"] as PropertyValue | undefined),
      propertyText(record.properties["升温速率"] as PropertyValue | undefined),
      propertyText(record.properties["降温速率"] as PropertyValue | undefined),
      propertyText(record.properties["装炉温度"] as PropertyValue | undefined),
      propertyText(record.properties["出炉温度"] as PropertyValue | undefined),
      propertyText(record.properties["冷却介质"] as PropertyValue | undefined),
      propertyText(record.properties["介质温度"] as PropertyValue | undefined)
    ]);
  }

  const lines = [
    HEADERS.map(csvCell).join(","),
    ...rows.map((row) => row.map(csvCell).join(","))
  ];
  return `\ufeff${lines.join("\n")}`;
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
