import { useEffect, useState } from "react";

import { feedbackApi } from "../../api/feedback";
import { Button } from "../ui/primitives";
import { Dialog } from "../ui/dialog";
import { Field, Select, Textarea } from "../ui/form";
import { useToast } from "../ui/toast";

const CATEGORIES = [
  { value: "missing_measure", label: "内容缺失（漏抽）" },
  { value: "wrong_value", label: "内容不正确" },
  { value: "wrong_unit", label: "单位不正确" },
  { value: "wrong_grade", label: "牌号/条件不正确" },
  { value: "other", label: "其他" }
];

export function FeedbackDialog({
  open,
  runId,
  recipeId,
  initialMeasure = "",
  initialDescription = "",
  onClose,
  onCreated
}: {
  open: boolean;
  runId: string;
  recipeId: string;
  initialMeasure?: string;
  initialDescription?: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { push } = useToast();
  const [category, setCategory] = useState("missing_measure");
  const [measure, setMeasure] = useState(initialMeasure);
  const [description, setDescription] = useState(initialDescription);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    if (initialMeasure) setMeasure(initialMeasure);
    if (initialDescription) setDescription(initialDescription);
  }, [open, initialMeasure, initialDescription]);

  async function submit() {
    if (!description.trim()) {
      push("error", "请填写问题描述");
      return;
    }
    setBusy(true);
    try {
      await feedbackApi.create({
        run_id: runId,
        category,
        target: {
          recipe_id: recipeId,
          measure: measure.trim()
        },
        description: description.trim()
      });
      push("success", "反馈已记录", "可在问题台账中查看和导出");
      setMeasure("");
      setDescription("");
      onCreated();
      onClose();
    } catch (error) {
      push("error", "创建反馈失败", (error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      title="反馈解析问题"
      description="反馈只登记到问题台账，不会自动触发修复或重新解析"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            取消
          </Button>
          <Button loading={busy} onClick={() => void submit()}>
            提交反馈
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="问题类型">
          <Select value={category} onChange={(event) => setCategory(event.target.value)}>
            {CATEGORIES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field
          label="问题描述"
          hint="例如：室温拉伸标准要求抽取不正确、化学成分试验方法没有抽取出来、弯曲项目没有抽取"
        >
          <Textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="描述哪里不对或缺少什么，不需要填写表号、字段名或期望值"
          />
        </Field>
        <p className="text-[11px] text-muted-foreground">
          目标配方：{recipeId || "未识别"}（系统会自动判断需要改表、改配方还是补规则）
        </p>
      </div>
    </Dialog>
  );
}
