from dataclasses import dataclass
from pathlib import Path
from rasa.cli.scaffold import create_initial_project


def log(*args):
    print(*args)

DATA_DIR: Path = Path(__file__).parent.parent / 'data'
NODE_DIR: Path = DATA_DIR / 'node'


def do_command(program: str, kwargs: dict={}):
    pass


def init(name: str):
    """Create node if not exists"""
    node_path = NODE_DIR / name
    if node_path.exists():
        log(f"Node {name} exists")
    else:
        log(f"Init node {name}...")
        create_initial_project(node_path.as_posix())


        
        