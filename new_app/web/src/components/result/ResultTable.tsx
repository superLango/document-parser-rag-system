import { ChevronDown, ChevronRight, MessageSquarePlus } from "lucide-react";
import { useMemo, useState } from "react";

import type { RecordItem } from "../../api/types";
import { Badge } from "../ui/primitives";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow
} from "../ui/table";
import { cn } from "../../lib/utils";

/**
 * 最终 schema 视图：固定输出标准信息与全部 schema 字段。
 * 字段无值时保留空单元格，不裁剪列。
 */

const SCHEMA_COLUMNS: Array<{ label: string; keys: string[] }> = [
  { label: "项目名称", keys: [] },
  { label: "材料牌号", keys: [] },
  { label: "标准要求", keys: [] },
  { label: "单位", keys: [] },
  { label: "试验方法", keys: ["试验方法", "方法"] },
  { label: "试验温度", keys: ["试验温度", "温度"] },
  { label: "位置", keys: ["位置", "取样位置"] },
  { label: "方向", keys: ["方向"] },
  { label: "尺寸厚度", keys: ["尺寸厚度", "厚度", "规格"] },
  { label: "试样状态", keys: ["试样状态", "状态", "交货状态"] },
  { label: "取样数量", keys: ["取样数量", "取样数"] },
  { label: "取样说明", keys: ["取样说明"] },
  { label: "锻件类型", keys: ["锻件类型"] }
];

const HEAT_COLUMNS = [
  "工序名称",
  "工艺名称",
  "材料牌号",
  "项目大类",
  "保温温度",
  "保温时间",
  "升温速率",
  "降温速率",
  "装炉温度",
  "出炉温度",
  "冷却介质",
  "介质温度"
];

// 分组标题使用业务词典的项目大类；未命中的大类排在最后并置灰。
const CATEGORY_ORDER = [
  "化学成分",
  "室温拉伸",
  "高温拉伸",
  "冲击试验",
  "硬度试验",
  "弯曲",
  "弯曲试验",
  "平面应变断裂韧度",
  "持久试验",
  "热处理制度",
  "正文/定性项目",
  "其他"
];

const STANDARD_RE = /(GB\s*\/\s*T|GBT|GB|GJB|JB|HB|YS\s*\/\s*T|YST|YB|ASTM|ASME|AMS|ISO|EN|DIN|API|NB)[\s_-]*([A-Z]{0,2})[\s_-]*(\d+(?:\.\d+)?)(?:[\s_-]+(\d{4}|[A-Z]|\d{2})|([A-Z]))?/i;
const PARTS_RE = /(ISO|EN|DIN)[\s_-]*(\d+(?:\.\d+)?)[\s_-]*-[\s_-]*(\d+)(?:[\s_-]+(\d{4}))?/i;

export type SchemaRow = {
  key: string;
  record: RecordItem;
  measure: string;
  name: string;
  cross: string;
  crossQuote: string;
  crossPage: number;
  grade: string;
  requirement: string;
  unit: string;
  category: string;
  matched: boolean;
  conditions: Record<string, string>;
  fields: Record<string, string>;
};

type CategoryGroup = {
  category: string;
  matched: boolean;
  rows: SchemaRow[];
};

function categoryOf(record: RecordItem): string {
  if (record.profile === "qualitative") return "正文/定性项目";
  if (record.profile === "chemical_composition") return "化学成分";
  if (record.profile === "heat_treatment") return "热处理制度";
  if (record.profile !== "mechanical_properties") return "其他";
  const keys = Object.keys(record.properties);
  const has = (...names: string[]) => names.some((name) => keys.includes(name));
  if (has("KV2", "KU2", "KV8", "KU8", "冲击吸收能量", "侧向膨胀值")) return "冲击";
  if (has("HB", "HBW", "HBS")) return "布氏硬度";
  if (has("HRC", "HRB")) return "洛氏硬度";
  if (has("HV")) return "维氏硬度";
  if (has("KIC", "断裂韧度")) return "断裂韧度";
  if (has("持久应力", "初始应力", "持久时间", "持久强度")) return "高温持久";
  if (keys.some((key) => key.includes("弯曲") || key.toLowerCase().startsWith("bend"))) {
    return "弯曲";
  }
  const temperature = record.conditions["试验温度"] || record.conditions["温度"] || "";
  const match = temperature.match(/(\d{2,4})\s*(?:℃|°C)/);
  if (match && Number(match[1]) >= 100) return "高温拉伸";
  return "室温拉伸";
}

function conditionValue(fields: Record<string, string>, keys: string[]): string {
  for (const key of keys) {
    const value = fields[key];
    if (value) return value;
  }
  return "";
}

/**
 * 项目大类以业务词典为准：优先取属性上的 business_category；
 * 老运行没有该字段时退回内部展示分类。
 */
function recordCategory(record: RecordItem): { category: string; matched: boolean } {
  const properties = Object.values(record.properties || {});
  for (const property of properties) {
    if (property?.business_category) {
      return {
        category: property.business_category,
        matched: property.feature_in_dictionary !== false
      };
    }
  }
  const unmatched = properties.find(
    (property) => property?.feature_in_dictionary === false
  );
  if (unmatched) {
    return { category: unmatched.feature || categoryOf(record), matched: false };
  }
  return { category: categoryOf(record), matched: true };
}

function displayRequirement(property: RecordItem["properties"][string]): string {
  const raw = property.raw || (property.value == null ? "" : String(property.value));
  const operator = (property.operator || "").trim();
  if (!raw || !operator) return raw;
  if (operator === "text" || operator === "~" || operator === "～" || operator === "range") {
    return raw;
  }
  // A range already carries its own notation; never prepend a limit sign.
  if (/[≥≤<>~～]/.test(raw) || /\d\s*[-–—]\s*\d/.test(raw)) return raw;
  return `${operator}${raw}`;
}

function propertyCategory(
  record: RecordItem,
  property: RecordItem["properties"][string]
): { category: string; matched: boolean } {
  if (property?.business_category) {
    return {
      category: property.business_category,
      matched: property.feature_in_dictionary !== false
    };
  }
  if (property?.feature && property.feature_in_dictionary === false) {
    return { category: property.feature, matched: false };
  }
  return recordCategory(record);
}

export function buildRows(records: RecordItem[]): SchemaRow[] {
  const rows: SchemaRow[] = [];
  for (const record of records) {
    for (const [measure, property] of Object.entries(record.properties || {})) {
      const requirement = displayRequirement(property);
      if (!requirement && !property.unit) continue;
      const source = property.source;
      const cross =
        property.meta?.["跨标准来源"] ||
        (source?.kind === "cross_standard"
          ? source.label ||
            [source.standard_no, source.edition].filter(Boolean).join("-")
          : "");
      const { category, matched } = propertyCategory(record, property);
      rows.push({
        key: `${record.record_id}-${measure}`,
        record,
        measure,
        name: property.business_item || measure,
        cross,
        crossQuote: source?.quote || "",
        crossPage: Number(source?.page_no || 0),
        grade: record.grade || "",
        requirement,
        unit: property.unit || "",
        category,
        matched,
        conditions: record.conditions || {},
        fields: { ...(record.conditions || {}), ...(property.meta || {}) }
      });
    }
  }
  return rows;
}

function cleanMarkdown(text: string): string {
  return text
    .replace(/ﬁ/g, "fi")
    .replace(/ﬂ/g, "fl")
    .replace(/<[^>]+>/g, "\n")
    .replace(/[ \t]+/g, " ")
    .trim();
}

function standardNumber(filename: string): string {
  const stem = filename.replace(/\.(pdf|md|markdown|txt)$/i, "").replace(/[-_—]?过期$/u, "");
  const parts = stem.match(PARTS_RE);
  if (parts) {
    const prefix = parts[1].toUpperCase();
    const edition = parts[4] ? `-${parts[4]}` : "";
    return `${prefix} ${parts[2]}-${parts[3]}${edition}`;
  }
  const match = stem.match(STANDARD_RE);
  if (!match) return stem;
  let prefix = match[1].replace(/\s+/g, "").toUpperCase();
  prefix = prefix === "GBT" ? "GB/T" : prefix === "YST" ? "YS/T" : prefix;
  const letter = match[2] ? match[2].toUpperCase() : "";
  const edition = match[4] ? `-${match[4].toUpperCase()}` : "";
  const attached = match[5] ? match[5].toUpperCase() : "";
  return `${prefix} ${letter}${match[3]}${edition}${attached}`.trim();
}

function filenameTitle(filename: string): string {
  const stem = filename.replace(/\.(pdf|md|markdown|txt)$/i, "").replace(/[-_—]?过期$/u, "");
  const match = stem.match(STANDARD_RE);
  if (!match) return stem;
  const rest = stem.slice((match.index ?? 0) + match[0].length).replace(/^[\s\-_—:：]+/u, "").trim();
  return /[\u4e00-\u9fff]/.test(rest) ? rest : "";
}

function plausibleTitle(value: string): boolean {
  const text = value.trim();
  if (text.length < 4 || text.length > 200) return false;
  if (/[\u0000-\u001f\u007f-\u009f]/.test(text)) return false;
  if (/[\u4e00-\u9fff]/.test(text)) return commonCjkRatio(text) >= 0.3;
  const printable = [...text].filter((ch) => /[A-Za-z0-9 .,;:()/&+'’\-–—%]/.test(ch)).length;
  return printable / text.length >= 0.9;
}

const COMMON_CJK = new Set(
  "的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会可主发年动同工也能下过子说产种面而方后多定行学法所民得经十之进着等部度家电力里如水化高自二理起小物现实加量都两体制机当使点从业本去把性好应开它合还因由其些然前外天政四日那社义事平形相全表间样与关各重新线内数正心反你明看原又么利比或但质气第向道命此变条只没结解问意建月公无系军很情者最立代想已通并提直题程展五果料象员革位入常文总次品式活设及管特件长求老头基资边流路级少图山统接知较将组见计别她手角期根论运农指几九区强放决西被干做必战先回则任取据处队南给色光门即保治北造百规热领七海口东导器压志世金增争济阶油思术极交受联什认六权收证改清己美再采转更单风切打白教速花带安场身车例真务具万每目至达走积示议声报斗完类八离华名确才科张信马节话米整空元况今集温传土许步群广石记需段研界拉林律叫且究观越织装影算低持音众书布复容儿须际商非验连断深难近矿千周委素技备半办青省列习响约支般史感劳便团往酸历市克何除消构府称太准精值号率族维划选标写存候毛亲快效斯院查江型眼王按格养易置派层片始却专状育厂京识适属圆包火住调满县局照参红细引听该铁价严龙飞"
);

function commonCjkRatio(text: string): number {
  const chars = [...text].filter((ch) => /[\u4e00-\u9fff]/.test(ch));
  if (!chars.length) return 0;
  return chars.filter((ch) => COMMON_CJK.has(ch)).length / chars.length;
}

const TITLE_SKIP_RE = /^(?:ICS|CCS|犐犆犛|犆犆犛|中华人民共和国|国家标准|代替|发布|实施|前\s*言|目\s*次|本文件|本标准|标准化工作导则|国家市场监督管理总局|国家标准化管理委员会|COPYRIGHT|©|AEROSPACE|MATERIAL\s+SPECIFICATION|REV\.|Issued|Revised|Reaffirmed|Superseding|Supersedes|Replaces|表\s*\d|图\s*\d|注)/i;
const NUMBER_ONLY_RE = /^(?:GB\s*\/?\s*T?|GB|GJB|JB|YB|YS|HB|ASTM|ASME|AMS|ISO|EN|DIN)\s*[A-Z]?\s*\d+(?:\.\d+)*(?:[-—–]\d{2,4})?$/i;
const CONTINUATION_RE = /^(?:Part\s+\d|Tubes?|Billets?|Bars?|Wire|Plate|Sheet|Strip|Titanium|Nickel|Steel|Aluminum|Cobalt|Copper|Tantalum|Zirconium|Alloy|and\b|[a-z])/;

function markdownTitle(markdown: string): string {
  const text = cleanMarkdown(markdown.slice(0, 3000));
  if (!text) return "";
  const lines = text
    .split("\n")
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean);
  const usable = (line: string) =>
    Boolean(line) &&
    !TITLE_SKIP_RE.test(line) &&
    !NUMBER_ONLY_RE.test(line.replace(/\s+/g, ""));
  // AMS 封面表格：标题在最后一个单元格里，可能跨多行。
  if (/AEROSPACE/i.test(text)) {
    const start = lines.findIndex(
      (line) =>
        usable(line) &&
        /^(Titanium|Nickel|Steel|Aluminum|Cobalt|Copper)\b/.test(line)
    );
    if (start >= 0) {
      const parts: string[] = [];
      for (let index = start; index < lines.length && parts.length < 4; index += 1) {
        const line = lines[index];
        if (!line || line.startsWith("(") || /RATIONALE/i.test(line)) break;
        parts.push(line);
      }
      const title = parts.join(" ").replace(/[,\s]+$/, "").replace(/\s+/g, " ").trim();
      if (plausibleTitle(title)) return title;
    }
  }
  // ASTM/ASME：Standard Specification/Practice/Test Method for ...
  const spec = text.match(/Standard\s+(?:Specification|Practice|Test\s+Method)\s+for\s+([\s\S]{5,220}?)(?:\.\s|\n\n|1\.\s*Scope)/i);
  if (spec) {
    let title = `Standard Specification for ${spec[1]}`
      .replace(/\s+/g, " ")
      .replace(/(?<=[a-z])\d+(?=\s|[A-Z])/g, "")
      .replace(/[,\s]+$/, "")
      .trim();
    // 版面把标题首词挤到行首时（"... Bars and" + 前置 "Billets"）还原语序。
    const displaced = title.match(
      /^Standard Specification for ([A-Z][A-Za-z0-9-]+)\s+(.+?)\s+(and|or)$/
    );
    if (displaced) {
      title = `Standard Specification for ${displaced[2]} ${displaced[3]} ${displaced[1]}`;
    }
    const tail = text.slice((spec.index ?? 0) + spec[0].length).trimStart();
    const nextLine = tail.split("\n")[0]?.trim() ?? "";
    if (/^(?:Tubes?|Billets?|Bars?|Wire|Plate|Sheet|Strip)\b/i.test(nextLine)) {
      title = `${title} ${nextLine}`;
    }
    if (plausibleTitle(title)) return title;
  }
  // 中文标题：跳过 ICS/CCS/标准号/前言/发布信息后，取第一条正常中文行。
  const chinese = lines.find((line) => {
    if (!usable(line) || !/[\u4e00-\u9fff]/.test(line)) return false;
    if (/质量分数|%/.test(line)) return false;
    const cjkCount = [...line].filter((ch) => /[\u4e00-\u9fff]/.test(ch)).length;
    return (
      /^[\u4e00-\u9fff]/.test(line) &&
      cjkCount >= 4 &&
      cjkCount <= 40 &&
      !/[。，；,]/.test(line) &&
      commonCjkRatio(line) >= 0.2
    );
  });
  if (chinese) return chinese.slice(0, 160);
  // 英文标题：跳过封面识别码和标准号，允许标题跨行。
  const start = lines.findIndex((line) => {
    if (!usable(line) || !/^[A-Za-z]/.test(line)) return false;
    if (/[\u4e00-\u9fff]/.test(line)) return false;
    if (/^[a-z][).]\s/i.test(line)) return false;
    if (/^SPECIFICATION\s+FOR\s+/i.test(line)) return true;
    return (
      line.includes(" ") &&
      line.length >= 8 &&
      line.length <= 220 &&
      plausibleTitle(line) &&
      !/^(?:SPECIFICATION|MATERIAL|AEROSPACE|ISSUED|REVISED)$/i.test(line) &&
      !/^AMS[- ]?[A-Z0-9/]/i.test(line)
    );
  });
  if (start >= 0) {
    let title = lines[start];
    for (let index = start + 1; index < Math.min(start + 4, lines.length); index += 1) {
      const next = lines[index];
      if (!CONTINUATION_RE.test(next)) break;
      title = `${title} ${next}`;
    }
    return title.replace(/\s+/g, " ").slice(0, 200);
  }
  return "";
}

export function standardInfo(filename: string, markdown: string): { name: string; number: string } {
  const number = standardNumber(filename);
  const name = filenameTitle(filename) || markdownTitle(markdown) || number;
  return { name, number };
}

export function ResultTable({
  records,
  filename = "",
  markdown = "",
  onFeedback
}: {
  records: RecordItem[];
  filename?: string;
  markdown?: string;
  onFeedback?: (record: RecordItem, measure: string) => void;
}) {
  const groups = useMemo(() => {
    const map = new Map<string, CategoryGroup>();
    for (const row of buildRows(records)) {
      const group = map.get(row.category) ?? {
        category: row.category,
        matched: row.matched,
        rows: []
      };
      if (!row.matched) group.matched = false;
      group.rows.push(row);
      map.set(row.category, group);
    }
    const rank = (name: string) => {
      const index = CATEGORY_ORDER.indexOf(name);
      return index < 0 ? CATEGORY_ORDER.length : index;
    };
    return [...map.values()].sort(
      (left, right) => rank(left.category) - rank(right.category)
    );
  }, [records]);

  const standard = useMemo(() => standardInfo(filename, markdown), [filename, markdown]);

  return (
    <div className="divide-y divide-border">
      <StandardInfoSection name={standard.name} number={standard.number} />
      {records.length === 0 ? (
        <p className="px-5 py-8 text-center text-sm text-muted-foreground">
          当前运行没有结构化记录。
        </p>
      ) : (
        groups.map((group) => (
          <CategorySection
            key={group.category}
            category={group.category}
            matched={group.matched}
            rows={group.rows}
            defaultOpen={false}
            onFeedback={onFeedback}
          />
        ))
      )}
    </div>
  );
}

function StandardInfoSection({ name, number }: { name: string; number: string }) {
  const [open, setOpen] = useState(true);
  return (
    <section>
      <button
        type="button"
        className="flex w-full items-center gap-2 px-5 py-3 text-left transition-colors hover:bg-muted/50"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        )}
        <span className="text-sm font-semibold">标准信息</span>
        <Badge tone="neutral">1 条记录</Badge>
      </button>
      {open ? (
        <Table>
          <TableHead>
            <TableRow>
              <TableHeaderCell>标准名称</TableHeaderCell>
              <TableHeaderCell>标准编号</TableHeaderCell>
            </TableRow>
          </TableHead>
          <TableBody>
            <TableRow>
              <TableCell className="font-medium">{name || ""}</TableCell>
              <TableCell className="font-mono">{number || ""}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      ) : null}
    </section>
  );
}

function CategorySection({
  category,
  matched,
  rows,
  defaultOpen,
  onFeedback
}: {
  category: string;
  matched: boolean;
  rows: SchemaRow[];
  defaultOpen: boolean;
  onFeedback?: (record: RecordItem, measure: string) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const isHeat = category === "热处理制度";
  const heatRecords = useMemo(() => {
    const byId = new Map<string, RecordItem>();
    for (const row of rows) byId.set(row.record.record_id, row.record);
    return [...byId.values()];
  }, [rows]);
  const crossLabels = useMemo(
    () => [...new Set(rows.map((row) => row.cross).filter(Boolean))],
    [rows]
  );

  return (
    <section>
      <button
        type="button"
        className="flex w-full items-center gap-2 px-5 py-3 text-left transition-colors hover:bg-muted/50"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        )}
        <span
          className={cn(
            "text-sm font-semibold",
            matched ? "text-foreground" : "text-muted-foreground/40"
          )}
          title={matched ? category : `${category}（未在业务词典中）`}
        >
          {category}
        </span>
        {crossLabels.length > 0 ? (
          <span
            className="inline-flex items-center gap-1 rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-medium text-indigo-700 ring-1 ring-inset ring-indigo-200"
            title={`跨标准补全：${crossLabels.join("、")}`}
          >
            跨标准 · {crossLabels.length > 1 ? `${crossLabels.length} 项` : crossLabels[0]}
          </span>
        ) : null}
        <Badge tone="info">
          {isHeat ? `${heatRecords.length} 条记录` : `${rows.length} 条要求`}
        </Badge>
      </button>
      {open ? (
        isHeat ? (
          <HeatTable records={heatRecords} />
        ) : (
          <Table className="max-h-[520px] overflow-auto" tableClassName="min-w-max">
            <TableHead>
              <TableRow>
                {SCHEMA_COLUMNS.map((column) => (
                  <TableHeaderCell
                    key={column.label}
                    className="sticky top-0 z-10 bg-background-soft"
                  >
                    {column.label}
                  </TableHeaderCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.key}>
                  {SCHEMA_COLUMNS.map((column) => {
                    if (column.label === "项目名称") {
                      return (
                        <TableCell key={column.label} className="font-medium" title={row.name}>
                          <span className="flex items-center gap-1.5">
                            {row.cross ? (
                              <span
                                className="shrink-0 rounded bg-indigo-50 px-1 py-0.5 text-[10px] font-medium text-indigo-700 ring-1 ring-inset ring-indigo-200"
                                title={`引自 ${row.cross}${row.crossPage ? ` 第 ${row.crossPage} 页` : ""}`}
                              >
                                引自
                              </span>
                            ) : null}
                            <span className="block max-w-[180px] truncate">{row.name}</span>
                          </span>
                        </TableCell>
                      );
                    }
                    if (column.label === "材料牌号") {
                      return (
                        <TableCell key={column.label} className="whitespace-nowrap" title={row.grade}>
                          {row.grade}
                        </TableCell>
                      );
                    }
                    if (column.label === "标准要求") {
                      return (
                        <TableCell
                          key={column.label}
                          className={row.cross ? "bg-indigo-50/50" : undefined}
                        >
                          <button
                            type="button"
                            className={cn(
                              "group inline-flex max-w-[360px] items-start gap-1.5 rounded-md px-1 py-0.5 text-left",
                              row.cross ? "hover:bg-indigo-100/60" : "hover:bg-amber-50"
                            )}
                            title={
                              row.cross
                                ? `引自 ${row.cross}${row.crossPage ? ` 第 ${row.crossPage} 页` : ""}${row.crossQuote ? `\n${row.crossQuote}` : ""}`
                                : "反馈此字段"
                            }
                            onClick={() => onFeedback?.(row.record, row.measure)}
                          >
                            <span
                              className="line-clamp-2 min-w-0 break-words font-mono text-[13px]"
                              title={row.requirement}
                            >
                              {row.requirement}
                            </span>
                            <MessageSquarePlus
                              className={cn(
                                "mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500",
                                onFeedback ? "opacity-0 group-hover:opacity-100" : "hidden"
                              )}
                            />
                          </button>
                        </TableCell>
                      );
                    }
                    if (column.label === "单位") {
                      return (
                        <TableCell
                          key={column.label}
                          className="whitespace-nowrap text-muted-foreground"
                        >
                          {row.unit}
                        </TableCell>
                      );
                    }
                    const value = conditionValue(row.fields, column.keys);
                    return (
                      <TableCell key={column.label} className="text-muted-foreground">
                        <span className="block max-w-[160px] truncate" title={value}>
                          {value}
                        </span>
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )
      ) : null}
    </section>
  );
}

function HeatTable({ records }: { records: RecordItem[] }) {
  return (
    <Table className="max-h-[520px] overflow-auto" tableClassName="min-w-max">
      <TableHead>
        <TableRow>
          {HEAT_COLUMNS.map((column) => (
            <TableHeaderCell
              key={column}
              className="sticky top-0 z-10 bg-background-soft"
            >
              {column}
            </TableHeaderCell>
          ))}
        </TableRow>
      </TableHead>
      <TableBody>
        {records.map((record) => {
          const processName =
            record.conditions["工序名称"] || record.conditions["工序"] || "";
          const craft = record.properties["工艺名称"];
          return (
            <TableRow key={record.record_id}>
              {HEAT_COLUMNS.map((column) => {
                if (column === "工序名称") {
                  return (
                    <TableCell key={column} className="font-medium">
                      {processName}
                    </TableCell>
                  );
                }
                if (column === "材料牌号") {
                  return <TableCell key={column}>{record.grade || ""}</TableCell>;
                }
                if (column === "项目大类") {
                  return (
                    <TableCell key={column} className="text-muted-foreground">
                      {record.conditions["项目大类"] || "热处理制度"}
                    </TableCell>
                  );
                }
                if (column === "工艺名称") {
                  const text = craft
                    ? craft.raw || (craft.value == null ? "" : String(craft.value))
                    : record.conditions["工艺名称"] || "";
                  return <TableCell key={column}>{text}</TableCell>;
                }
                const item = record.properties[column];
                if (!item) {
                  return <TableCell key={column} />;
                }
                const text = item.raw || (item.value == null ? "" : String(item.value));
                return (
                  <TableCell key={column}>
                    <span className="font-mono text-[13px]">
                      {text}
                      {item.unit ? (
                        <span className="ml-1 text-[11px] text-muted-foreground">
                          {item.unit}
                        </span>
                      ) : null}
                    </span>
                  </TableCell>
                );
              })}
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
