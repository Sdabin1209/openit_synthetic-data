"""시험 자료로 쓰는 QuestionBank(tests/doubles.py)가 문진 스키마 3.0.0(칸 data_type 필수, 선택지 규칙, 필수 고정 문장, ID 패턴)을 통과하는지 본다."""
import pytest

import doubles
from conftest import SURVEY_DIR
from synthetic_data.wiring.survey import Survey


@pytest.mark.parametrize("flavor", ["main", "other"])
def test_double_question_banks_pass_the_installed_survey_schema(flavor):
    assert Survey(SURVEY_DIR).check("QuestionBank", doubles.make_bank(flavor)) == []
