"""Main-path E2E test: login -> knowledge base -> upload -> parse -> result -> logout.

Requires a running API (8765) and web dev server (5173); `run_main_flow.ps1`
starts both with an isolated platform database. The test only uses the mock
OCR/extractor backends so it needs no model service.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:5173")
USERNAME = os.environ.get("E2E_USERNAME", "e2e")
PASSWORD = os.environ.get("E2E_PASSWORD", "e2e-pass")
HEADLESS = os.environ.get("E2E_HEADLESS", "1") not in {"0", "false", "no"}
PARSE_TIMEOUT = float(os.environ.get("E2E_PARSE_TIMEOUT", "120"))

SAMPLE = """# Page 1

## 4.5 室温力学性能

表1 室温力学性能

<table>
  <tr><td rowspan="2">牌号</td><td colspan="3">室温力学性能</td></tr>
  <tr><td>Rm/MPa</td><td>Rp0.2/MPa</td><td>A/%</td></tr>
  <tr><td>2A14</td><td>430</td><td>350</td><td>10</td></tr>
</table>

## 5 检验项目

5.1 化学成分按 GB/T 3190 进行。
"""


class MainFlowE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.sample_path = Path(cls.tmp.name) / "e2e-sample.md"
        cls.sample_path.write_text(SAMPLE, encoding="utf-8")
        cls.kb_name = f"E2E 主链路 {int(time.time())}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_main_flow(self) -> None:
        errors: list[str] = []
        with sync_playwright() as playwright:
            browser = self._launch(playwright)
            context = browser.new_context()
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
                expect(page.get_by_role("heading", name="金属标准拆分工作台")).to_be_visible()

                page.get_by_label("用户名").fill(USERNAME)
                page.get_by_label("密码").fill(PASSWORD)
                page.get_by_role("button", name="登录").click()
                expect(page.get_by_role("link", name="知识库")).to_be_visible()

                page.get_by_role("link", name="知识库").click()
                expect(page.get_by_role("heading", name="知识库")).to_be_visible()
                page.get_by_label("名称").fill(self.kb_name)
                page.get_by_role("button", name="创建知识库").click()
                expect(page.get_by_role("link", name=re.compile(self.kb_name))).to_be_visible()

                page.get_by_role("link", name=re.compile(self.kb_name)).click()
                expect(page.get_by_role("heading", name=self.kb_name)).to_be_visible()
                page.set_input_files("input[type=file]", str(self.sample_path))
                page.get_by_role("button", name="上传文档").click()
                expect(page.get_by_text("e2e-sample.md").first).to_be_visible()

                page.get_by_role("button", name="开始解析").click()
                self._wait_for_parse(page)
                page.get_by_role("link", name="查看结果").first.click()
                expect(page).to_have_url(re.compile(r"/jobs/"))
                expect(page.get_by_role("heading", name="e2e-sample.md")).to_be_visible()

                page.locator('a[href*="tab=records"]').first.click()
                expect(page.get_by_text("2A14").first).to_be_visible()
                expect(page.get_by_text("430").first).to_be_visible()

                # R2: a bare /jobs/<id> URL must resolve document_id via the
                # platform task endpoint instead of engine /v1/jobs.
                job_match = re.search(r"/jobs/([^?]+)", page.url)
                self.assertIsNotNone(job_match)
                page.goto(f"{BASE_URL}/jobs/{job_match.group(1)}", wait_until="domcontentloaded")
                expect(page.get_by_role("heading", name="e2e-sample.md")).to_be_visible()
                expect(page).to_have_url(re.compile(r"/jobs/.*documentId="))
                page.get_by_role("link", name="记录").first.click()
                expect(page.get_by_text("2A14").first).to_be_visible()

                # G4 field-review walkthrough: risks -> evidence deep link ->
                # back -> accept, all in a real browser.
                review_link = page.get_by_role("link", name=re.compile("字段复核"))
                if review_link.count():
                    review_link.first.click()
                else:
                    page.get_by_role("button", name=re.compile("字段复核")).first.click()
                expect(page.get_by_text("文档风险").first).to_be_visible()
                expect(
                    page.get_by_role("button", name="接受", exact=True).first
                ).to_be_visible()
                locate = page.get_by_role("link", name="定位", exact=True).first
                if locate.count():
                    locate.click()
                    expect(page).to_have_url(re.compile(r"/viewer"))
                    expect(page.get_by_text("返回知识库")).to_be_visible()
                    page.go_back()
                    expect(
                        page.get_by_role("button", name="接受", exact=True).first
                    ).to_be_visible()
                page.get_by_role("button", name="接受", exact=True).first.click()
                expect(page.get_by_text(re.compile("已接受")).first).to_be_visible()

                # R5.2: owner creates a short-lived share link, then a
                # read-only visitor opens it and downloads hanson JSON.
                page.get_by_role("button", name="生成分享链接").click()
                share_input = page.locator("input[readonly]").first
                expect(share_input).to_be_visible()
                share_url = share_input.input_value()
                self.assertTrue(share_url, "share url is empty")
                share_page = context.new_page()
                share_page.goto(share_url, wait_until="domcontentloaded")
                expect(
                    share_page.get_by_role("heading", name="e2e-sample.md")
                ).to_be_visible()
                with share_page.expect_download() as download_info:
                    share_page.get_by_role(
                        "button", name="hanson JSON", exact=True
                    ).click()
                download = download_info.value
                self.assertTrue(
                    download.suggested_filename.endswith("-hanson.json"),
                    download.suggested_filename,
                )
                downloaded = Path(download.path())
                self.assertGreater(downloaded.stat().st_size, 500)
                share_page.close()

                page.get_by_role("button", name="退出").click()
                expect(page).to_have_url(re.compile(r"/login"))
                expect(page.get_by_role("heading", name="金属标准拆分工作台")).to_be_visible()
            finally:
                context.close()
                browser.close()

        self.assertEqual(errors, [], f"page errors: {errors}")

    def _wait_for_parse(self, page) -> None:
        deadline = time.time() + PARSE_TIMEOUT
        while time.time() < deadline:
            if page.get_by_role("link", name="查看结果").count():
                body = page.inner_text("body")
                if "failed" in body:
                    self.fail(f"parse failed: {body[:600]}")
                if "succeeded" in body or "review" in body:
                    return
            page.wait_for_timeout(1000)
        self.fail(f"parse did not finish in {PARSE_TIMEOUT:.0f}s")

    @staticmethod
    def _launch(playwright):
        executable = os.environ.get("E2E_CHROMIUM_EXECUTABLE")
        if executable:
            return playwright.chromium.launch(
                headless=HEADLESS, executable_path=executable
            )
        try:
            return playwright.chromium.launch(headless=HEADLESS)
        except Exception:
            cache = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
            candidates = sorted(cache.glob("chromium-*/chrome-win/chrome.exe"))
            if not candidates:
                raise
            return playwright.chromium.launch(
                headless=HEADLESS, executable_path=str(candidates[-1])
            )


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1], verbosity=2)
