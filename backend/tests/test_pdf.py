"""Check that successive PDF paragraphs stay inside the page margins."""
import unittest
from unittest.mock import patch

from fpdf import FPDF
import tests  # Initialize the isolated database even when discovery omits -t .

from app.engine.reporting import find_font, to_pdf


class PdfLayoutTest(unittest.TestCase):
    @unittest.skipUnless(find_font(), "Chinese font unavailable")
    def test_paragraphs_stay_in_page(self):
        positions = []
        original = FPDF.multi_cell

        def record(pdf, *args, **kwargs):
            positions.append((pdf.get_x(), pdf.l_margin))
            return original(pdf, *args, **kwargs)

        report = {
            "title": "测试报告", "gen_mode": "模板生成", "created_at": "2026-11-20",
            "sections": [{"title": "一、事件信息", "body": "第一行内容\n第二行内容\n| 项目 | 内容 |\n| 事件 | 食品安全 |"}],
            "disposal_log": [],
        }
        with patch.object(FPDF, "multi_cell", record):
            data = to_pdf(report)
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(positions), 5)
        for x, margin in positions:
            self.assertAlmostEqual(x, margin)
