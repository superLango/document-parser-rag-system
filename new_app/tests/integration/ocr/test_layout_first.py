from __future__ import annotations

import asyncio

import pymupdf

from services.ocr.adapters import layout_first as module
from services.ocr.adapters.layout_first import LayoutFirstOcrAdapter
from services.ocr.contracts import LayoutBlock, OcrRequest


def _pdf_with_table_text() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    lines = [
        "Q355B tensile strength 470 MPa elongation 22 percent",
        "Q235B tensile strength 400 MPa elongation 26 percent",
        "Q345B tensile strength 450 MPa elongation 21 percent",
        "Q390B tensile strength 430 MPa elongation 20 percent",
        "Q420B tensile strength 410 MPa elongation 19 percent",
        "Q460C tensile strength 400 MPa elongation 18 percent",
        "Q355C tensile strength 470 MPa elongation 23 percent",
        "Q355D tensile strength 470 MPa elongation 24 percent",
    ]
    for index, line in enumerate(lines):
        page.insert_text((72, 72 + index * 18), line, fontsize=12)
    data = document.tobytes()
    document.close()
    return data


def _request() -> OcrRequest:
    return OcrRequest(
        document_id="doc-layout",
        storage_key="documents/doc-layout/file.pdf",
        filename="file.pdf",
        content_type="application/pdf",
    )


def test_layout_first_uses_table_block_and_text_fallback(monkeypatch) -> None:
    async def fake_analyze(self, **kwargs):  # noqa: ANN001 - test stub
        return (
            [
                LayoutBlock(
                    block_id="P1-B1",
                    page_no=kwargs["page_no"],
                    type="table",
                    bbox=[0.05, 0.05, 0.95, 0.5],
                )
            ],
            [],
            {},
        )

    monkeypatch.setattr(module.LayoutClient, "analyze", fake_analyze)
    monkeypatch.setattr(module.settings, "layout_base_url", "http://layout.test")
    monkeypatch.setattr(module.settings, "glm_ocr_base_url", "")
    monkeypatch.setattr(module.settings, "glm_ocr_model", "")
    output = asyncio.run(
        LayoutFirstOcrAdapter().parse(_pdf_with_table_text(), _request())
    )
    result = output.result
    assert result.backend == "layout_first"
    assert result.layout and result.layout[0].type == "table"
    assert "Q355B" in result.markdown
    assert any("GLM unavailable" in item for item in result.warnings)


def test_layout_failure_falls_back_to_native(monkeypatch) -> None:
    from services.ocr.adapters.base import OcrBackendError

    async def fail_analyze(self, **kwargs):  # noqa: ANN001 - test stub
        raise OcrBackendError("OCR_LAYOUT_UNAVAILABLE", "layout down")

    monkeypatch.setattr(module.LayoutClient, "analyze", fail_analyze)
    monkeypatch.setattr(module.settings, "layout_base_url", "http://layout.test")
    monkeypatch.setattr(module.settings, "glm_ocr_base_url", "")
    monkeypatch.setattr(module.settings, "glm_ocr_model", "")
    output = asyncio.run(
        LayoutFirstOcrAdapter().parse(_pdf_with_table_text(), _request())
    )
    assert output.result.backend in {"pdf", "pdf_fallback"}
    assert any("layout-first fallback" in item for item in output.result.warnings)
    assert output.result.pages


def test_garbled_text_layer_is_ocrd_instead_of_reused(monkeypatch) -> None:
    """Broken font cmaps must not be preferred over GLM OCR."""

    async def fake_analyze(self, **kwargs):  # noqa: ANN001 - test stub
        return (
            [
                LayoutBlock(
                    block_id="P1-B1",
                    page_no=kwargs["page_no"],
                    type="text",
                    bbox=[0.05, 0.05, 0.95, 0.9],
                )
            ],
            [],
            {},
        )

    async def fake_ocr_block(self, crop, prompt=None, **kwargs):  # noqa: ANN001
        return "OCR-TEXT"

    monkeypatch.setattr(module.LayoutClient, "analyze", fake_analyze)
    monkeypatch.setattr(module.GlmOcrAdapter, "ocr_block", fake_ocr_block)
    monkeypatch.setattr(module, "_document_garbled_pages", lambda data: {1})
    monkeypatch.setattr(module.settings, "layout_base_url", "http://layout.test")
    monkeypatch.setattr(module.settings, "glm_ocr_base_url", "http://glm.test")
    monkeypatch.setattr(module.settings, "glm_ocr_model", "glm-test")
    output = asyncio.run(
        LayoutFirstOcrAdapter().parse(_pdf_with_table_text(), _request())
    )
    assert "OCR-TEXT" in output.result.markdown
    assert "Q355B" not in output.result.markdown
    assert any("garbled text layer" in item for item in output.result.warnings)


def test_garbled_detector_ignores_normal_text() -> None:
    assert not module._looks_garbled("本标准规定了热轧钢板和钢带的尺寸、外形及允许偏差。")
    assert module._looks_garbled("犐犆犛７０．１４０．５０犎４６犌犅／犜３２７４—２０１７" * 20)
    # 无 Unicode 映射的文本层：ASCII 符号噪声 + 控制字符。
    noise = '!!!"#$%&\'()*+,!-$./$&"#0123456,%067\x81\x7fyz+~\x7f6,' * 8
    assert module._looks_garbled(noise)
    table = "Table 3 Tensile properties\nGrade Rm Rp0.2 A\nTA1 240 140 30\n" * 6
    assert not module._looks_garbled(table)


def _degenerate_table() -> str:
    rows = "".join(f"<tr><td>5.1.{index} 镍</td></tr>" for index in range(1, 101))
    return f"<table border='1'>{rows}</table>"


def test_degenerate_detector_catches_numbered_loop() -> None:
    assert module._is_degenerate_ocr(_degenerate_table())
    assert not module._is_degenerate_ocr(
        "<table><tr><th>牌号</th><th>Rm/MPa</th></tr>"
        "<tr><td>Q355B</td><td>470</td></tr></table>"
    )


def test_degenerate_table_block_uses_full_page_ocr(monkeypatch) -> None:
    async def fake_analyze(self, **kwargs):  # noqa: ANN001 - test stub
        return (
            [
                LayoutBlock(
                    block_id="P1-B1",
                    page_no=kwargs["page_no"],
                    type="table",
                    bbox=[0.05, 0.05, 0.95, 0.9],
                )
            ],
            [],
            {},
        )

    async def fake_ocr_block(self, crop, prompt=None, **kwargs):  # noqa: ANN001
        if prompt == module.TABLE_PROMPT:
            return _degenerate_table()
        return "<table><tr><th>牌号</th><th>Rm/MPa</th></tr></table>"

    monkeypatch.setattr(module.LayoutClient, "analyze", fake_analyze)
    monkeypatch.setattr(module.GlmOcrAdapter, "ocr_block", fake_ocr_block)
    monkeypatch.setattr(module.settings, "layout_base_url", "http://layout.test")
    monkeypatch.setattr(module.settings, "glm_ocr_base_url", "http://glm.test")
    monkeypatch.setattr(module.settings, "glm_ocr_model", "glm-test")
    output = asyncio.run(
        LayoutFirstOcrAdapter().parse(_pdf_with_table_text(), _request())
    )
    assert "牌号" in output.result.markdown
    assert "5.1.100" not in output.result.markdown
    assert any("degenerate block OCR" in item for item in output.result.warnings)
