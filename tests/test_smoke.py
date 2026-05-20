from pathlib import Path
from codegenerator.api.service import generate_from_file

def test_import_and_examples_exist():
    assert Path('examples/generation_request.json').exists()

from codegenerator.orchestration.generation_service import _normalize_generated_test_review


def test_review_normalization_converts_scalar_fields_to_lists():
    review = _normalize_generated_test_review(
        {
            'verdict': 'environment_or_import_issue',
            'confidence': '0.7',
            'production_code_quality': 'ok',
            'generated_test_quality': 'bad',
            'should_keep_production_code': 'manual_review',
            'recommended_action': 'manual_review',
            'reasons': 'Generated test calls constructor without required positional argument.',
            'production_risks': '',
            'test_issues': 'missing required positional argument: base_dir',
        }
    )

    assert review['reasons'] == ['Generated test calls constructor without required positional argument.']
    assert review['production_risks'] == []
    assert review['test_issues'] == ['missing required positional argument: base_dir']
    assert review['verdict'] == 'production_likely_ok_test_likely_bad'
    assert review['should_keep_production_code'] == 'yes'
    assert review['recommended_action'] == 'keep_production_code_exclude_test'


def test_review_normalization_keeps_manual_review_when_production_risks_exist():
    review = _normalize_generated_test_review(
        {
            'verdict': 'production_likely_ok_test_likely_bad',
            'confidence': 0.9,
            'production_code_quality': 'есть риск',
            'generated_test_quality': 'bad',
            'should_keep_production_code': 'yes',
            'recommended_action': 'keep_production_code_exclude_test',
            'reasons': [],
            'production_risks': ['production risk'],
            'test_issues': [],
        }
    )

    assert review['should_keep_production_code'] == 'manual_review'
    assert review['recommended_action'] == 'manual_review'
