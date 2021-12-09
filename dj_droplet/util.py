import os
import hashlib
import random
import string

exclude = ['.git', '__pycache__', 'templates', 'static', 'node_modules']


def find(name, path):
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in exclude]
        dirs[:] = [d for d in dirs if d[0] != '.']
        dirs[:] = [d for d in dirs if os.path.isfile(
            os.path.join(root, d, '__init__.py'))]
        if name in files:
            return os.path.join(root, name)


def get_wsgi_app(path):
    wsgipath = find('wsgi.py', path)
    if not wsgipath:
        return
    wsgiapp = wsgipath.replace(path, '', 1).replace(
        '.py', '').replace('/', '.')
    while wsgiapp.startswith("."):
        wsgiapp = wsgiapp[1:]
    return wsgiapp+':application'


def hash_string(string):
    return hashlib.md5(string.encode()).hexdigest()


def get_random_string(length):
    # With combination of lower and upper case
    return ''.join(random.choice(string.ascii_letters)
                   for i in range(length))
