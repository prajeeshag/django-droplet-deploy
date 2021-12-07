import os
from enum import Enum

exclude = ['.git', '__pycache__', 'templates', 'static', 'node_modules']


def find(name, path):
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in exclude]
        dirs[:] = [d for d in dirs if d[0] != '.']
        dirs[:] = [d for d in dirs if os.path.isfile(
            os.path.join(root, d, '__init__.py'))]
        if name in files:
            return os.path.join(root, name)
