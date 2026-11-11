import { useEffect, useState } from "react";

import { feedbackApi } from "../../api/feedback";
import { Button } from "../ui/primitives";
import { Dialog } from "../ui/dialog";
import { Field, Input, Select, Textarea } from "../ui/form";
import { useToast } from "../ui/toast";

const CATEGORIES = [
  { value: "missing_measure", label: "字段缺失" },
  { value: "wrong_value", label: "数值错误" },
  { value: "wrong_unit", label: "单位错误" },
  { value: "wrong_grade", label: "牌号错误" },
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
  const [unit, setUnit] = useState("");
  const [description, setDescription] = useState(initialDescription);
  const [expected, setExpected] = useState("");
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
          measure: measure.trim(),
          unit: unit.trim()
        },
        description: description.trim(),
        expected_value: expected.trim() || undefined
      });
      push("success", "反馈已创建", "可在反馈 Tab 中处理");
      setMeasure("");
      setUnit("");
      setDescription("");
      setExpected("");
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
      description="Triage 会判断根因并尝试生成候选配方，验证通过后由人工决定是否晋升"
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
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="目标字段" hint="例如 Z、Rm、Rp0.2">
            <Input
              value={measure}
              onChange={(event) => setMeasure(event.target.value)}
              placeholder="Z"
            />
          </Field>
          <Field label="期望单位" hint="可留空">
            <Input
              value={unit}
              onChange={(event) => setUnit(event.target.value)}
              placeholder="%"
            />
          </Field>
        </div>
        <Field label="问题描述">
          <Textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="断面收缩率 Z 未抽取"
          />
        </Field>
        <Field label="期望值" hint="可选">
          <Input
            value={expected}
            onChange={(event) => setExpected(event.target.value)}
            placeholder="22"
          />
        </Field>
        <p className="text-[11px] text-muted-foreground">
          目标配方：{recipeId || "未识别"}
        </p>
      </div>
    </Dialog>
  );
}
