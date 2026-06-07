import pytest
import google.generativeai
from unittest.mock import patch, MagicMock
from datetime import datetime
from ava.conversation.time_parser import NLTimeParser

@pytest.mark.asyncio
async def test_nl_time_parser_success():
    with patch("google.generativeai.GenerativeModel") as MockModel:
        mock_instance = MockModel.return_value
        mock_response = MagicMock()
        mock_response.text = '{"start_time": "2026-06-04T14:00:00", "end_time": null}'
        mock_instance.generate_content.return_value = mock_response
        
        parser = NLTimeParser()
        current = datetime(2026, 6, 3, 10, 0, 0)
        result = await parser.parse("tomorrow at 2pm", current)
        
        assert result["start_time"] == "2026-06-04T14:00:00"
        assert result["end_time"] is None
