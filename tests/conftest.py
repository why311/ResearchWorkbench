import os
from pathlib import Path

# Importing the application during tests must never alter a user's live runs.
os.environ['RESEARCH_DATA_DIR'] = str(Path(__file__).resolve().parents[1] / 'tmp' / 'test-bootstrap')
