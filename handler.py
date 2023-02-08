from pathlib import Path
from yaml import dump

def dump2yaml(path, data={}):
    with open(path, 'w') as f:
        dump(data, f)


def save_config(path: Path, config: dict):
    for pipe in config.get('pipeline', [{}]):
        for key, value in pipe.items():
            if isinstance(value, str) and value.startswith('.'): # to node path
                pipe[key] = (path / value).absolute().as_posix()


