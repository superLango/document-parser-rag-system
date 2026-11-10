"""Full platform UI/API smoke test against a running deployment.

Covers every route in the web app, the module workspace flows, the document
lifecycle (upload -> parse -> extraction -> share/export -> delete) and the
platform API endpoints used by those pages.

Environment (defaults match the production compose stack):
    E2E_BASE_URL   http://127.0.0.1:8080
    E2E_USERNAME   e2e_prod
    E2E_PASSWORD   E2E-Prod-2026!
    E2E_UPLOAD_PDF <repo>/metal-doc-agent/runs/qdu_p5.pdf
"""

from __future__ import annotations

import json
import os
import re
import time
import unittest
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8080")
USERNAME = os.environ.get("E2E_USERNAME", "e2e_prod")
PASSWORD = os.environ.get("E2E_PASSWORD", "E2E-Prod-2026!")
UPLOAD_PDF = Path(
    os.environ.get(
        "E2E_UPLOAD_PDF",
        str(
            Path(__file__).resolve().parents[1]
            / "metal-doc-agent"
            / "runs"
            / "qdu_p5.pdf"
        ),
    )
)
PARSE_TIMEOUT = float(os.environ.get("E2E_PARSE_TIMEOUT", "420"))


class FullPlatformE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.playwright = sync_playwright().start()
        cls.browser = cls._launch(cls.playwright)
        cls.context = cls.browser.new_context(accept_downloads=True)
        cls.page = cls.context.new_page()
        cls.page.set_default_timeout(20000)
        cls.page_errors: list[str] = []
        cls.failed_responses: list[tuple[int, str]] = []
        cls.page.on("pageerror", lambda error: cls.page_errors.append(str(error)))
        cls.page.on(
            "console",
            lambda message: cls.page_errors.append(f"console: {message.text}")
            if message.type == "error"
            else None,
        )
        cls.page.on(
            "response",
            lambda response: cls.failed_responses.append(
                (response.status, response.url)
            )
            if response.status >= 400 and "favicon" not in response.url
            else None,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.context.close()
            cls.browser.close()
        finally:
            cls.playwright.stop()

    def test_00_all_features(self) -> None:
        page = self.page

        # ---------------------------------------------------------- auth
        page.goto(f"{BASE_URL}/standard", wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="欢迎回来").first).to_be_visible(timeout=20000)
        self.assertIn("/login", page.url)

        page.locator("#username").fill(USERNAME)
        page.locator("#password").fill("wrong-password")
        page.get_by_role("button", name=re.compile("登\\s*录")).click()
        expect(page.get_by_text("登录失败").first).to_be_visible(timeout=15000)
        self.failed_responses.clear()
        self.page_errors.clear()

        page.locator("#password").fill(PASSWORD)
        page.get_by_role("button", name=re.compile("登\\s*录")).click()
        # RequireAuth preserves the original /standard target in ?redirect.
        expect(page.get_by_role("heading", name="标准拆分概览").first).to_be_visible(
            timeout=20000
        )
        self.assertIn("/standard", page.url)

        # ------------------------------------------------------ dashboard
        page.goto(BASE_URL + "/", wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="工作台").first).to_be_visible(
            timeout=20000
        )
        expect(page.get_by_role("button", name=re.compile("进入标准拆分"))).to_be_visible(
            timeout=20000
        )
        self._assert_clean("工作台")

        for name in ("标准拆分", "委托单解析", "质保书解析", "委外报告解析"):
            expect(page.get_by_text(name).first).to_be_visible(timeout=20000)
        expect(page.get_by_text("标准文档").first).to_be_visible(timeout=20000)

        # ------------------------------------------------- standard module
        page.get_by_role("link", name="标准拆分", exact=True).first.click()
        expect(page.get_by_role("heading", name="标准拆分概览").first).to_be_visible(timeout=20000)
        self._assert_clean("标准拆分概览")

        # documents + viewer
        page.get_by_role("link", name="文档解析", exact=True).first.click()
        expect(page.get_by_role("heading", name="文档解析").first).to_be_visible(timeout=20000)
        rows = page.locator('[data-testid^="doc-row-"]')
        expect(rows.first).to_be_visible(timeout=30000)
        self.assertGreater(rows.count(), 0)
        first_doc_id = rows.first.get_attribute("data-testid").removeprefix("doc-row-")

        keyboard = page.get_by_placeholder("搜索文件名")
        keyboard.fill("gbt")
        page.get_by_role("button", name="搜索", exact=True).first.click()
        expect(page.get_by_text(re.compile("gbt", re.I)).first).to_be_visible(timeout=20000)
        keyboard.fill("")
        page.get_by_role("button", name="搜索", exact=True).first.click()

        page.goto(
            f"{BASE_URL}/standard/documents/{first_doc_id}/viewer",
            wait_until="domcontentloaded",
        )
        expect(page.get_by_text("← 返回文档解析")).to_be_visible(timeout=20000)
        expect(page.get_by_role("button", name="下一页")).to_be_visible(timeout=20000)
        self._assert_clean("文档查看器")

        # extraction list + detail + export + share
        page.goto(f"{BASE_URL}/standard/extraction", wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="结构化抽取").first).to_be_visible(timeout=20000)
        extract_buttons = page.locator('[data-testid^="btn-extract-"]')
        expect(extract_buttons.first).to_be_visible(timeout=30000)
        self.assertGreater(extract_buttons.count(), 0)
        extract_buttons.first.click()
        expect(page).to_have_url(re.compile(r"/standard/extraction/[^/]+$"), timeout=20000)
        expect(page.get_by_text("抽取结果").first).to_be_visible(timeout=30000)
        expect(page.get_by_text("JSON 视图").first).to_be_visible(timeout=20000)
        self.assertNotIn(
            "暂无抽取结果", page.inner_text("body"), "抽取结果为空，无法验证详情"
        )

        page.get_by_role("button", name="JSON 视图").click()
        expect(page.locator("pre").first).to_contain_text("schema_template_id", timeout=20000)
        page.get_by_role("button", name="表格视图").click()

        page.get_by_role("button", name="历史", exact=True).click()
        expect(page.get_by_role("dialog").first).to_be_visible(timeout=10000)
        page.get_by_role("button", name="关闭").click()

        with page.expect_download(timeout=30000) as download_info:
            page.get_by_role("button", name="Schema JSON").click()
        download = download_info.value
        self.assertGreater(Path(download.path()).stat().st_size, 200)

        page.get_by_role("button", name="分享", exact=True).click()
        share_input = page.locator("input[readonly]").first
        expect(share_input).to_be_visible(timeout=20000)
        share_url = share_input.input_value()
        self.assertIn("/share/", share_url)

        share_page = self.context.new_page()
        share_page.goto(share_url, wait_until="domcontentloaded")
        expect(share_page.get_by_text("只读分享", exact=True)).to_be_visible(
            timeout=20000
        )
        with share_page.expect_download(timeout=30000) as share_download:
            share_page.get_by_role("button", name="Schema JSON").click()
        self.assertGreater(Path(share_download.value.path()).stat().st_size, 200)
        share_page.close()

        # dictionary (three independent dictionaries)
        page.goto(f"{BASE_URL}/standard/dictionary", wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="业务词典").first).to_be_visible(
            timeout=20000
        )
        expect(page.get_by_text(re.compile("词典 ")).first).to_be_visible(
            timeout=30000
        )
        for tab, heading in (
            ("categories", "项目大类"),
            ("items", "检测项目"),
            ("methods", "试验方法"),
        ):
            page.get_by_role("link", name=re.compile(heading)).first.click()
            expect(page).to_have_url(
                re.compile(f"/standard/dictionary/{tab}$"), timeout=20000
            )
            dictionary_rows = page.locator("table tbody tr")
            expect(dictionary_rows.first).to_be_visible(timeout=30000)
        page.goto(f"{BASE_URL}/standard/dictionary/categories", wait_until="domcontentloaded")
        expect(page.get_by_text(re.compile("词典 ")).first).to_be_visible(
            timeout=30000
        )
        search = page.get_by_placeholder("搜索名称或别名")
        search.fill("拉伸")
        page.get_by_role("button", name="搜索", exact=True).first.click()
        page.wait_for_timeout(1000)
        if page.get_by_role("button", name="别名", exact=True).count():
            page.get_by_role("button", name="别名", exact=True).first.click()
            expect(page.get_by_role("dialog").first).to_be_visible(timeout=10000)
            page.get_by_role("button", name="关闭").click()
        self._assert_clean("业务词典")

        # tasks
        page.get_by_role("link", name="任务列表", exact=True).first.click()
        expect(page.get_by_role("heading", name="任务列表").first).to_be_visible(timeout=20000)
        task_rows = page.locator('[data-testid^="task-row-"]')
        expect(task_rows.first).to_be_visible(timeout=30000)
        self.assertGreater(task_rows.count(), 0)

        # ------------------------------------------------- other modules
        for path, title in (
            ("/orders", "委托单解析"),
            ("/certificates", "质保书解析"),
            ("/outsource", "委外报告解析"),
        ):
            page.goto(BASE_URL + path, wait_until="domcontentloaded")
            expect(page.get_by_role("heading", name=title).first).to_be_visible(timeout=20000)
            expect(page.get_by_text("规划中").first).to_be_visible(timeout=20000)
            self._assert_clean(title)

        # ------------------------------------------------------- account
        page.goto(f"{BASE_URL}/profile", wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="个人中心").first).to_be_visible(
            timeout=20000
        )
        expect(page.get_by_text("基本信息").first).to_be_visible(timeout=20000)
        expect(page.get_by_text("修改密码").first).to_be_visible(timeout=20000)
        page.get_by_role("button", name="保存资料").click()
        expect(page.get_by_text("资料已更新").first).to_be_visible(timeout=20000)

        page.goto(f"{BASE_URL}/api-keys", wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="API 密钥").first).to_be_visible(
            timeout=20000
        )
        key_name = f"e2e-smoke-{int(time.time())}"
        page.get_by_role("button", name="新建密钥").click()
        expect(page.get_by_role("dialog").first).to_be_visible(timeout=10000)
        page.locator("#key-name").fill(key_name)
        page.get_by_role("button", name="创建密钥").click()
        expect(page.get_by_text("此密钥不会再次展示")).to_be_visible(timeout=20000)
        page.get_by_role("button", name="我已保存").click()
        key_label = page.get_by_text(key_name, exact=True).first
        expect(key_label).to_be_visible(timeout=20000)
        key_card = key_label.locator(
            "xpath=ancestor::div[contains(@class,'rounded-xl')][1]"
        )
        key_card.get_by_role("button", name="撤销").click()
        expect(page.get_by_text("API Key 已撤销").first).to_be_visible(timeout=20000)

        page.goto(f"{BASE_URL}/admin/users", wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="用户管理").first).to_be_visible(
            timeout=20000
        )
        expect(page.get_by_text(USERNAME).first).to_be_visible(timeout=20000)
        page.get_by_role("button", name="新建用户").click()
        expect(page.get_by_role("dialog").first).to_be_visible(timeout=10000)
        page.get_by_role("button", name="取消").click()

        page.goto(f"{BASE_URL}/admin/audit-logs", wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="审计日志").first).to_be_visible(
            timeout=20000
        )
        audit_rows = page.locator("table tbody tr")
        expect(audit_rows.first).to_be_visible(timeout=30000)
        with page.expect_download(timeout=30000) as audit_download:
            page.get_by_role("button", name="导出 CSV").click()
        self.assertGreater(Path(audit_download.value.path()).stat().st_size, 10)
        page.get_by_role("button", name="查看详情").first.click()
        expect(page.get_by_role("dialog").first).to_be_visible(timeout=10000)
        page.get_by_role("button", name="关闭").click()

        page.goto(f"{BASE_URL}/help", wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="帮助文档").first).to_be_visible(timeout=20000)
        page.goto(f"{BASE_URL}/about", wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="关于").first).to_be_visible(timeout=20000)

        page.goto(f"{BASE_URL}/403", wait_until="domcontentloaded")
        expect(page.get_by_text("403 · 权限不足")).to_be_visible(timeout=20000)
        page.goto(f"{BASE_URL}/not-a-real-page", wait_until="domcontentloaded")
        expect(page.get_by_text("404 · 页面不存在")).to_be_visible(timeout=20000)

        # ---------------------------------------------- upload/parse flow
        page.goto(f"{BASE_URL}/standard/documents", wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="文档解析").first).to_be_visible(timeout=20000)
        page.get_by_role("button", name="上传 PDF").click()
        page.set_input_files('[data-testid="upload-input"]', str(UPLOAD_PDF))
        expect(page.get_by_test_id("upload-filename")).to_have_text(UPLOAD_PDF.name)
        page.get_by_test_id("confirm-upload").click()
        expect(page.get_by_text("文档已上传").first).to_be_visible(timeout=20000)

        upload_row = page.locator('[data-testid^="doc-row-"]').filter(
            has_text=UPLOAD_PDF.name
        ).first
        expect(upload_row).to_be_visible(timeout=30000)
        upload_doc_id = upload_row.get_attribute("data-testid").removeprefix(
            "doc-row-"
        )
        upload_row.get_by_test_id(f"start-{upload_doc_id}").click()
        expect(page.get_by_text("解析已开始").first).to_be_visible(timeout=20000)

        self._wait_for_parse(upload_doc_id)

        page.goto(
            f"{BASE_URL}/standard/extraction/{upload_doc_id}",
            wait_until="domcontentloaded",
        )
        expect(page.get_by_text("抽取结果").first).to_be_visible(timeout=30000)
        self.assertNotIn(
            "暂无抽取结果", page.inner_text("body"), "上传文档解析后没有抽取结果"
        )

        # delete the test document
        page.goto(f"{BASE_URL}/standard/documents", wait_until="domcontentloaded")
        upload_row = page.locator(f'[data-testid="doc-row-{upload_doc_id}"]')
        expect(upload_row).to_be_visible(timeout=30000)
        upload_row.get_by_test_id(f"delete-{upload_doc_id}").click()
        page.get_by_role("button", name="确认删除").click()
        expect(page.get_by_text("文档已删除").first).to_be_visible(timeout=20000)
        expect(page.locator(f'[data-testid="doc-row-{upload_doc_id}"]')).to_have_count(
            0, timeout=20000
        )

        # -------------------------------------------------- API endpoints
        self._api_sweep(first_doc_id, share_url)

        self.assertEqual(self.page_errors, [], f"page errors: {self.page_errors}")
        self.assertEqual(
            self.failed_responses,
            [],
            f"failed responses: {self.failed_responses}",
        )

    # ------------------------------------------------------------- helpers
    def _assert_clean(self, label: str) -> None:
        body = self.page.inner_text("body")
        self.assertNotIn("模块加载失败", body, f"{label}: 模块加载失败")
        self.assertNotIn("加载失败", body, f"{label}: 加载失败")

    def _wait_for_parse(self, doc_id: str) -> None:
        row = self.page.locator(f'[data-testid="doc-row-{doc_id}"]')
        deadline = time.time() + PARSE_TIMEOUT
        last_text = ""
        while time.time() < deadline:
            try:
                last_text = row.inner_text()
            except Exception:  # noqa: BLE001 - row may be re-rendered
                pass
            if "已完成" in last_text:
                return
            if "失败" in last_text:
                self.fail(f"解析失败：{last_text[:400]}")
            self.page.wait_for_timeout(2000)
        self.fail(f"解析超时（{PARSE_TIMEOUT:.0f}s）：{last_text[:400]}")

    def _api_sweep(self, doc_id: str, share_url: str) -> None:
        token = self.page.evaluate("localStorage.getItem('access_token')")
        self.assertTrue(token, "access token missing")
        share_token = share_url.rstrip("/").split("/")[-1]

        checks = [
            ("/health", False, 200),
            ("/platform/ready", False, 200),
            ("/v1/auth/me", True, 200),
            ("/v1/modules", True, 200),
            ("/v1/modules/standard_split", True, 200),
            ("/v1/modules/order_parse", True, 200),
            ("/v1/documents?module=standard_split&limit=50&offset=0", True, 200),
            ("/v1/tasks?module=standard_split&limit=50&offset=0", True, 200),
            ("/v1/modules/standard_split/dictionary", True, 200),
            ("/v1/modules/standard_split/dictionary/pending", True, 200),
            ("/v1/modules/standard_split/dictionaries/coverage", True, 200),
            ("/v1/modules/standard_split/dictionaries/categories", True, 200),
            ("/v1/modules/standard_split/dictionaries/items", True, 200),
            ("/v1/modules/standard_split/dictionaries/methods", True, 200),
            (f"/v1/documents/{doc_id}", True, 200),
            (f"/v1/documents/{doc_id}/preview", True, 200),
            (f"/v1/documents/{doc_id}/result/schema", True, 200),
            (f"/v1/documents/{doc_id}/result/versions", True, 200),
            (f"/v1/documents/{doc_id}/items", True, 200),
            (f"/v1/documents/{doc_id}/records", True, 200),
            (f"/v1/documents/{doc_id}/alignment", True, 200),
            (f"/v1/documents/{doc_id}/evidence", True, 200),
            (f"/v1/documents/{doc_id}/clauses", True, 200),
            (f"/v1/documents/{doc_id}/links", True, 200),
            (f"/v1/documents/{doc_id}/coverage-audit", True, 200),
            (f"/v1/documents/{doc_id}/new-terms", True, 200),
            ("/v1/users?limit=20&offset=0", True, 200),
            ("/v1/audit-logs?limit=20&offset=0", True, 200),
            ("/v1/api-keys", True, 200),
            (f"/v1/share/{share_token}", False, 200),
        ]
        for path, auth, expected in checks:
            request = urllib.request.Request(BASE_URL + path)
            if auth:
                request.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(request, timeout=30) as response:
                self.assertEqual(
                    response.status, expected, f"{path} -> {response.status}"
                )
                if path.endswith("/result/schema"):
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertIn("categories", payload)
                    self.assertTrue(payload["categories"], f"{path} 无类别")

        for fmt in ("hanson", "json", "csv", "xlsx"):
            request = urllib.request.Request(
                f"{BASE_URL}/v1/documents/{doc_id}/export?format={fmt}"
            )
            request.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(request, timeout=60) as response:
                self.assertEqual(response.status, 200, f"export {fmt}")
                self.assertGreater(len(response.read()), 100, f"export {fmt} 为空")

    @staticmethod
    def _launch(playwright):
        executable = os.environ.get("E2E_CHROMIUM_EXECUTABLE")
        if executable:
            return playwright.chromium.launch(headless=True, executable_path=executable)
        try:
            return playwright.chromium.launch(headless=True)
        except Exception:
            cache = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
            candidates = sorted(cache.glob("chromium-*/chrome-win/chrome.exe"))
            if not candidates:
                raise
            return playwright.chromium.launch(
                headless=True, executable_path=str(candidates[-1])
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
