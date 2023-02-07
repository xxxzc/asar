from dataclasses import dataclass
from pathlib import Path
from rasa.cli.scaffold import create_initial_project
from argparse import ArgumentParser

"""
data:
  nodes:
    node1:
      data/
        nlu.yml
        stories.yml
        rules.yml
      config.yml
      credentials.yml
      domain.yml
      endpoints.yml
    node2:
    ...
"""

ROOT: Path = Path(__file__).parent.parent / 'data'
NODE: Path = ROOT / 'node'
COMMON: Path = ROOT / 'common'



class Node:

    def __init__(self, name: str) -> None:
        self.root = NODE / name
        if not self.root.exists():
            self.root.parent.mkdir(parents=True, exist_ok=True)
            create_initial_project(self.root.as_posix())

        
        