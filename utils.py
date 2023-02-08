from pathlib import Path

SVCTL = "supervisorctl"

ROOT = Path(__file__).parent
DATA_DIR = ROOT.parent / 'data'
MODEL_DIR = DATA_DIR / 'model'
