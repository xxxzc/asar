"""Interact with Rasa Model"""

from pathlib import Path

from rasa.cli.scaffold import create_initial_project
from rasa.model import get_latest_model
from typing import Optional

import utils


def get_path(name: str):
    return utils.MODEL_DIR / name


def full_path(name: str):
    return get_path(name).absolute().as_posix()


def init(name: str) -> bool:
    """Initialize model"""
    path = get_path(name)
    if not path.exists():
        create_initial_project(full_path(name))
        (path / 'models').mkdir(exist_ok=True, parents=True)
        return True
    return False


def latest(name: str) -> Optional[Path]:
    """Latest model, return model path if exists else None"""
    model_path = get_latest_model(full_path(name))
    if model_path is None:
        return None
    return Path(model_path)


def status(name: str):
    """Use supervisor to check model status"""
    return


def run(name: str):
    """Use supervisor to run rasa model"""


def train(name: str, **kwargs):
    """Train model with arguments"""
    return
