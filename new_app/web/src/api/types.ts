export type DocumentItem = {
  id: string;
  filename: string;
  content_type: string;
  size: number;
  sha256: string;
  status: string;
  created_at: string;
};

export type IssueFeedback = {
  id: string;
  created_at: string;
  document_id: string;
  document: string;
  run_id: string;
  category: string;
  status: string;
  description: string;
  measure: string;
  recipe_id: string;
  reporter: string;
};

export type AbnormalDocument = {
  document_id: string;
  document: string;
  run_id: string;
  status: string;
  stage: string;
  error_code: string;
  parsed_at: string;
  recipe_channel: string;
  parser_version: string;
};

export type IssueLedger = {
  feedback: IssueFeedback[];
  abnormal_documents: AbnormalDocument[];
  summary: { feedback: number; open_feedback: number; abnormal_documents: number };
};

export type RunItem = {
  id: string;
  document_id: string;
  document_version: number;
  status: string;
  stage: string;
  progress: number;
  trace_id: string;
  recipe_channel: string;
  engine_version: string;
  parser_version?: string | null;
  result_key: string | null;
  error_code: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type RunStage = {
  id: string;
  run_id: string;
  stage: string;
  status: string;
  input_refs: Record<string, unknown>;
  output_refs: Record<string, unknown>;
  metrics: Record<string, unknown>;
  error_code: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
};

export type RunEvent = {
  id: string;
  run_id: string;
  sequence: number;
  type: string;
  stage: string;
  status: string;
  payload: Record<string, unknown>;
  occurred_at: string;
};

export type RunTimeline = {
  run: RunItem;
  stages: RunStage[];
  events: RunEvent[];
};

export type PropertyValue = {
  value: number | null;
  raw: string;
  operator: string | null;
  unit: string;
  column: string;
  meta?: Record<string, string>;
  business_item?: string;
  business_category?: string;
  dictionary_status?: string;
  feature?: string;
  feature_in_dictionary?: boolean;
  source?: {
    kind?: string;
    standard_no?: string;
    edition?: string;
    label?: string;
    clause_id?: string;
    table_id?: string;
    page_no?: number;
    quote?: string;
  };
};

export type RecordItem = {
  record_id: string;
  table_id: string;
  block_id: string;
  page_no: number;
  row_index: number;
  recipe_id: string;
  recipe_version: string;
  profile: string;
  grade: string;
  conditions: Record<string, string>;
  properties: Record<string, PropertyValue>;
};

export type RecordsPayload = {
  schema_version: string;
  records: RecordItem[];
};

export type InventoryItem = {
  inventory_id: string;
  item: string;
  feature: string;
  family: string;
  sources: string[];
  clause_id: string;
  table_ids: string[];
  requirement: string;
  method: string;
  status: string;
  page_no: number;
  conflicts: string[];
  business_item?: string;
  business_category?: string;
  dictionary_status?: string;
  sampling?: { quantity?: string; location?: string; note?: string };
};

export type ReferenceItem = {
  standard_no: string;
  title: string;
  edition: string;
  relation: string;
  clause_id: string;
  page_no: number;
  resolved: boolean;
};

export type RunIntelligence = {
  document_intelligence: {
    stats?: {
      clauses?: number;
      inventory_items?: number;
      qualitative_items?: number;
      qualitative_records?: number;
      classifications?: number;
      methods_filled?: number;
      coverage?: { aligned_ratio?: number };
      references?: {
        total?: number;
        unresolved?: number;
        resolution_rate?: number;
      };
      dictionary?: {
        version?: string;
        items_checked?: number;
        hit_rate?: number;
        method_hit_rate?: number;
      };
    };
  };
  inventory: { items?: InventoryItem[] };
  references: { references?: ReferenceItem[]; stats?: Record<string, number> };
  clauses: { clauses?: { clause_id?: string; title?: string; kind?: string }[] };
};

export type TableSummary = {
  table_id: string;
  page_no: number;
  caption?: string | null;
  profile?: string;
  orientation?: string;
  n_rows?: number;
  n_cols?: number;
  header_paths?: string[][];
  units?: string[];
  rows?: string[][];
  header_rows?: number;
  blocks?: { block_id: string; header_paths: string[][]; rows: string[][] }[];
};

export type SandboxResult = {
  schema_version?: string;
  status?: string;
  template?: { template_id?: string; version?: string };
  recipes?: { recipe_id: string; version: string; profile?: string }[];
  tables?: TableSummary[];
  stats?: { tables?: number; records?: number; diagnostics?: number };
  outputs?: string[];
};

export type RunResult = {
  run_id: string;
  status: string;
  result: SandboxResult | null;
};

export type OcrPage = {
  page_no: number;
  width: number;
  height: number;
  dpi: number;
  markdown: string;
  image_key: string | null;
  layout_key?: string | null;
};

export type LayoutBlock = {
  block_id: string;
  page_no: number;
  type: string;
  bbox: number[];
  text?: string;
};

export type OcrPayload = {
  document_id: string;
  backend: string;
  pages: OcrPage[];
  markdown: string;
  tables: TableSummary[];
  layout?: LayoutBlock[];
  warnings: string[];
  quality: number;
};

export type ReviewFinding = {
  id?: string;
  source: string;
  category: string;
  severity: "info" | "warning" | "error";
  target: Record<string, unknown>;
  observed: string | null;
  expected: string | null;
  evidence_refs: string[];
  confidence: number;
  status?: string;
};

export type ReviewReport = {
  run_id: string;
  status: "pass" | "warn" | "fail";
  ruleset_version: string;
  stats: Record<string, number>;
  degraded: boolean;
  findings: ReviewFinding[];
};

export type FeedbackMessage = {
  role: "user" | "agent" | "system";
  content: string;
  at: string;
};

export type TriageDecision = {
  root_cause: string;
  repair_scope: string;
  confidence: number;
  evidence: string[];
  summary: string;
  needs_human: boolean;
};

export type RepairProposal = {
  proposal_id: string;
  root_cause: string;
  scope: string;
  summary: string;
  patch: { ops?: { op: string; path: string; value?: unknown }[] };
  test_plan: string[];
  risk: string;
  needs_human: boolean;
  confidence: number;
};

export type CandidateRef = {
  recipe_id: string;
  base_version: string;
  candidate_version: string;
  digest: string;
  patch: { ops?: { op: string; path: string; value?: unknown }[] };
};

export type VerificationPackage = {
  proposal_id: string;
  before_run: string;
  after_run: string;
  diff: {
    added: { record_id: string; measure: string; after: PropertyValue }[];
    removed: { record_id: string; measure: string; before: PropertyValue }[];
    changed: {
      record_id: string;
      measure: string;
      before: PropertyValue;
      after: PropertyValue;
    }[];
  };
  regression: { documents: number; field_f1_delta: number; new_errors: number };
  affected_targets: { recipe_id: string; measure: string; table_id?: string }[];
  user_summary: string;
  artifacts: string[];
  passed: boolean;
};

export type FeedbackIntent = {
  concept_id?: string | null;
  concept?: string | null;
  subject?: string | null;
  field?: string | null;
  measures?: string[];
  category?: string;
  verdict?: string;
  scope?: string;
  confidence?: number;
  assumption?: string;
  candidate_targets?: { table_id?: string; page_no?: number; confidence?: number }[];
  clarifying_question?: string | null;
};

export type FeedbackDetail = {
  id: string;
  run_id: string;
  document_id: string;
  category: string;
  target: {
    recipe_id?: string;
    measure?: string;
    unit?: string;
    family?: string;
    table_id?: string;
    rule_id?: string;
  };
  description: string;
  expected_value: string | null;
  source_quote: string | null;
  status: string;
  messages: FeedbackMessage[];
  root_cause?: {
    intent?: FeedbackIntent;
    target?: { table_id?: string; page_no?: number };
    repairability?: { decision?: string; reason?: string };
    diagnosis?: { root_cause?: string; action?: string; scope?: string };
    applied_run_id?: string;
  };
  suggestions?: {
    action?: string;
    table_id?: string;
    page_no?: number;
    reason?: string;
    columns?: string[];
  }[];
  triage: TriageDecision | null;
  proposal: RepairProposal | null;
  candidate: CandidateRef | null;
  verification: VerificationPackage | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
};

export type RecipeRef = {
  recipe_id: string;
  version: string;
  digest: string;
  channel?: string | null;
};

export type CrossStandardConflict = {
  record_id: string;
  measure: string;
  current?: string;
  imported?: string;
};

export type CrossStandardResolution = {
  document_id: string;
  standard_no: string;
  edition: string;
  title: string;
  status: string;
  page_count: number;
  categories: string[];
  grades: string[];
  latest_run_id: string;
};

export type CrossStandardTask = {
  task_id: string;
  feature: string;
  scope: "category" | "parameter";
  parameter: string;
  standard_no: string;
  edition: string;
  kind: string;
  clause_id: string;
  page_no: number;
  quote: string;
  title?: string;
  status: string;
  gap?: string;
  resolution?: CrossStandardResolution;
  expansion?: {
    records_added?: number;
    properties_added?: number;
    conflicts?: CrossStandardConflict[];
    agent?: boolean;
  };
  current_grades?: string[];
};

export type CrossStandardPayload = {
  schema_version: string;
  enabled?: boolean;
  tasks: CrossStandardTask[];
  stats: Record<string, number>;
  agent?: {
    status?: string;
    accepted?: number;
    imported?: number;
    error?: string;
    rejected?: unknown[];
  };
  imported?: { task_id: string; record_ids: string[] }[];
};

export type RecipeDetail = {
  recipe_id: string;
  channels: Record<string, string>;
  versions: RecipeRef[];
};

export type DictionaryEntry = {
  business_code: string;
  business_name: string;
  type: string;
  family?: string | null;
  facets?: Record<string, unknown>;
  aliases?: string[];
  standard_no?: string | null;
  category_code?: string | null;
  category_name?: string | null;
  status?: string;
  version?: string;
};

export type DictionaryPayload = {
  version: string;
  source: string;
  total: number;
  families: Record<string, number>;
  entries: DictionaryEntry[];
};

export type DictionaryImportResult = {
  version: string;
  total: number;
  created: number;
  updated: number;
  skipped: number;
  families: Record<string, number>;
};
