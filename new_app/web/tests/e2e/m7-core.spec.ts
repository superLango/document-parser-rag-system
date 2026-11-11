import { expect, request, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const API = process.env.API_BASE ?? "http://localhost:18000";
const FIXTURE =
  process.env.M7_FIXTURE ??
  resolve(process.cwd(), "../tests/fixtures/mechanical-z.md");
const TERMINAL = new Set(["STRUCTURED_READY", "FAILED", "CANCELLED"]);

let documentId = "";
let runId = "";

test.beforeAll(async () => {
  const context = await request.newContext({ baseURL: API });
  const upload = await context.post("/v1/documents", {
    multipart: {
      file: {
        name: "mechanical-z.md",
        mimeType: "text/markdown",
        buffer: readFileSync(FIXTURE)
      }
    }
  });
  expect(upload.ok()).toBeTruthy();
  const document = await upload.json();
  documentId = document.id;

  const created = await context.post(`/v1/documents/${documentId}/runs`, {
    data: { recipe_channel: "stable", parse_profile: "standard" }
  });
  expect(created.ok()).toBeTruthy();
  let run = await created.json();
  runId = run.id;

  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    const response = await context.get(`/v1/runs/${runId}`);
    run = await response.json();
    if (TERMINAL.has(run.status)) break;
    await new Promise((resolveWait) => setTimeout(resolveWait, 1000));
  }
  expect(run.status).toBe("STRUCTURED_READY");
  await context.dispose();
});

test("文档库展示上传入口与文档列表", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("h1")).toContainText("文档库");
  await expect(page.getByRole("button", { name: "上传文档" }).first()).toBeVisible();
  await expect(page.getByText("mechanical-z.md").first()).toBeVisible();
});

test("解析详情六个 Tab 与结果表可用", async ({ page }) => {
  await page.goto(`/documents/${documentId}?run=${runId}`);
  await expect(page.locator("h1")).toContainText("mechanical-z.md");

  for (const name of ["结果", "审核", "反馈", "时间线", "版本", "原文预览"]) {
    await expect(page.getByRole("tab", { name })).toBeVisible();
  }

  const row = page.getByRole("row").filter({ hasText: "Q355B" });
  await expect(row).toContainText("470");
  await expect(row).toContainText("22");

  await page.getByRole("tab", { name: "审核" }).click();
  await expect(page.getByText("审核摘要")).toBeVisible();

  await page.getByRole("tab", { name: "反馈" }).click();
  await expect(page.getByRole("button", { name: "新建反馈" })).toBeVisible();

  await page.getByRole("tab", { name: "时间线" }).click();
  await expect(page.getByText("运行概览")).toBeVisible();
  await expect(page.getByText("阶段耗时")).toBeVisible();

  await page.getByRole("tab", { name: "版本" }).click();
  await expect(page.getByText("选择对比运行")).toBeVisible();

  await page.getByRole("tab", { name: "原文预览" }).click();
  await expect(page.getByText(/第 \d+ 页/)).toBeVisible();
});

test("运行记录、业务词典与配方版本页面可用", async ({ page }) => {
  await page.goto("/runs");
  await expect(page.locator("h1")).toContainText("运行记录");
  await expect(page.getByText(runId.slice(0, 8))).toBeVisible();

  await page.goto("/dictionary");
  await expect(page.locator("h1")).toContainText("业务词典");
  await expect(page.getByText("项目大类", { exact: false }).first()).toBeVisible();
  await page.getByRole("tab", { name: "检测项目" }).click();
  await expect(page.getByText("HT_ITEM:0179")).toBeVisible();
  await page.getByRole("tab", { name: "分类概览" }).click();
  await expect(page.getByText("拉伸").first()).toBeVisible();

  await page.goto("/recipes");
  await expect(page.locator("h1")).toContainText("配方版本");
  await page.getByText("mechanical_properties_v1").click();
  await expect(page.getByRole("button", { name: "回滚" })).toBeVisible();
});
