from pathlib import Path
from codegenerator.api.service import generate_from_file

def test_import_and_examples_exist():
    assert Path('examples/generation_request.json').exists()
