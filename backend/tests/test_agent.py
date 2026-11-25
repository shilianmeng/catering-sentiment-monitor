import unittest
from unittest.mock import patch
import tests  # Initialize the isolated database even when discovery omits -t .

from app.engine.agent import report_narrative


class ReportModelTest(unittest.TestCase):
    def test_empty_model_section_falls_back(self):
        event = ({"title": "测试", "level": "S", "intensity_score": 96}, 69, 56, None)
        for text in ("风险研判结论\n风险正文\n===\n应对与处置建议", "风险研判结论\n===\n建议正文"):
            with self.subTest(text=text), patch('app.engine.agent.event_brief', return_value=event), patch('app.engine.agent.call_llm', return_value=text):
                risk, advice, mode, model = report_narrative(None, 'ev001', '模板风险', '模板建议', {'llm_model': 'test'})
            self.assertEqual((risk, advice, mode, model), ('模板风险', '模板建议', '模板生成', None))

    def test_valid_model_sections_are_used(self):
        event = ({"title": "测试", "level": "S", "intensity_score": 96}, 69, 56, None)
        with patch('app.engine.agent.event_brief', return_value=event), patch('app.engine.agent.call_llm', return_value='风险研判结论\n风险正文\n===\n应对与处置建议\n建议正文'):
            value = report_narrative(None, 'ev001', '模板风险', '模板建议', {'llm_model': 'test'})
        self.assertEqual(value, ('风险正文', '建议正文', '模型生成', 'test'))
