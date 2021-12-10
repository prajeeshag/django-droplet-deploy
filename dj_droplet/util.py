import collections
import hashlib
import json
import logging
import os
import random
import string
import tempfile

import dotenv
import git
import requests
from examples import custom_style_1, custom_style_2, custom_style_3
from git.exc import GitCommandError, InvalidGitRepositoryError
from PyInquirer import Separator, prompt

logger = logging.getLogger(__name__)

EXCLUDE = ['.git', '__pycache__', 'templates', 'static', 'node_modules']


def find(name, path):
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in EXCLUDE]
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


def _find_env_vars(path='.'):
    env_vars = []
    for (root, dirs, files) in os.walk(path, topdown=True):
        dirs[:] = [d for d in dirs if d not in EXCLUDE]
        dirs[:] = [d for d in dirs if d[0] != '.']
        dirs[:] = [d for d in dirs if os.path.isfile(
            os.path.join(root, d, '__init__.py'))]
        for file in files:
            if file.endswith('.py'):
                env_vars += _find_env_vars_from_file(os.path.join(root, file))
    vars = collections.OrderedDict()
    for var in env_vars:
        vars[var] = ''
    return vars


def _find_env_vars_from_file(file):
    env_vars = []
    with open(file, 'r') as f:
        for line in f.readlines():
            env_vars += _find_env_vars_from_line(line)
    return env_vars


def _find_env_vars_from_line(line):
    # replase all double quotes with single quotes
    line1 = line.replace('"', "'")

    osenv1 = 'os.getenv'
    osenv2 = 'os.environ.get'
    strt = line1.find(osenv1)
    if strt < 0:
        strt = line1.find(osenv2)
    if strt < 0:
        return []
    strt = line1.find("'", strt)
    if strt < 0:
        return []
    strt += 1
    end = line1.find("'", strt)
    if end < 0:
        return []
    return [line1[strt:end]]


def _values_from_dotenv():
    ques = [
        {
            'type': 'input',
            'message': f' \n Enter ".env" file paths (leave empty to skip)',
            'name': 'envfile',
        }
    ]
    ans = prompt(ques, style=custom_style_1)
    envvars = collections.OrderedDict()
    if ans['envfile']:
        envfiles = ans['envfile'].split()
        for f in envfiles:
            envvars.update(dotenv.dotenv_values(ans['envfile']))
        return envvars
    return envvars


def _list_edit_env_var(vars, default=None):
    def list_choices(vars):
        choices = [
            {'name': 'Save and exit..', 'value': 'save'},
            {'name': 'Add a new variable', 'value': 'add'},
            Separator(),
        ]
        for (var, val) in vars.items():
            val1 = val
            if len(val) >= 100:
                val1 = val1[1:100] + ' .....'
            choices += [{'name': f'  {var} = {val1}', 'value': var}]
        return choices

    choices = list_choices(vars)
    ques = [
        {
            'type': 'list',
            'message': 'Select to edit: ',
            'name': 'response',
            'choices': choices,
            'default': default,
        }
    ]
    ans = prompt(ques, style=custom_style_1)
    return ans['response']


def _get_env_val_from_user(var, default=''):
    ques = [
        {
            'type': 'input',
            'message': f'Enter a value or leave empty to ignore {var} = ',
            'default': default,
            'name': var,
        }
    ]
    ans = prompt(ques, style=custom_style_1)
    return ans.get(var)


def _get_env_from_user():
    ques = [
        {
            'type': 'input',
            'message': 'Enter the variable name',
            'name': 'name',
        }
    ]
    ans = prompt(ques, style=custom_style_1)
    key = ans['name']
    if not key:
        return None, None
    return key, _get_env_val_from_user(key)


def _edit_env_vars(envd):
    res = 'save'
    while True:
        res = _list_edit_env_var(envd, default=res)
        if res == 'save':
            return
        elif res == 'add':
            key, val = _get_env_from_user()
            if not key:
                continue
            envd[key] = val
        else:
            envd[res] = _get_env_val_from_user(res, envd[res])


class Env:
    def __init__(self, working_dir=None) -> None:
        envvars = collections.OrderedDict()
        if working_dir:
            envvars.update(_find_env_vars(working_dir))
        envvars.update(_values_from_dotenv())
        self.vars = envvars
        self.edit()

    def edit(self):
        _edit_env_vars(self.vars)


class ReposNotFound(Exception):
    pass


class GitError(Exception):
    pass


def _is_pwd_project_dir():
    ques = [
        {
            'type': 'confirm',
            'message': 'Is your present working directory your django project directory?',
            'name': 'is_pwd_project_dir',
            'default': True,

        }
    ]
    ans = prompt(ques, style=custom_style_1)
    return ans('is_pwd_project_dir')


def _choose_github_repo(repos):
    if len(repos) < 1:
        return _get_github_repo_from_user()
    enter_manually = 'Enter GitHub repo manually'
    choices = [enter_manually, ] + repos
    ques = [
        {
            'type': 'list',
            'message': 'Choose the GitHub repo',
            'name': 'github_repo',
            'choices': choices,
        }
    ]
    ans = prompt(ques, style=custom_style_1)

    if ans['github_repo'] == enter_manually:
        return _get_github_repo_from_user()
    return ans['github_repo']


def _is_repo_public(repo):
    res = requests.get(_make_github_url(repo))
    return res.status_code == 200


def _clone_from(repo, working_dir, token=None):
    url = _make_github_url(repo, token)
    try:
        return git.Repo.clone_from(url, working_dir)
    except GitCommandError:
        return None


def _make_github_url(repo, token=None, *args, **kwargs):
    if token:
        url = f'https://username:{token}@github.com/{repo}.git'
    else:
        url = f'https://github.com/{repo}.git'
    return url


def _get_github_repo_from_pwd():
    """ Get the GitHub remote repos from pwd """
    repos = []
    try:
        repo = git.Repo()
    except InvalidGitRepositoryError:
        return repos
    for remote in repo.remotes:
        repo = _repo_from_github_url(remote.url)
        if repo:
            repos.append(repo)
    return repos


def _get_github_repo_from_user():
    """Get the GitHub repository path from user input"""
    ques = [{
        'type': 'input',
        'name': 'repo',
        'message': 'Enter the GitHub repository path'
    }]
    ans = prompt(ques, style=custom_style_1)

    repo = _repo_from_github_url(ans['repo'])
    if repo:
        return repo
    return ans['repo']


def _repo_from_github_url(url):
    githuburl = 'github.com'
    dotgit = '.git'
    strt = url.find(githuburl)
    end = url.find(dotgit)
    if strt < 0:
        return None
    strt += len(githuburl)+1
    repo = url[strt:]
    if end < 0:
        return repo
    return url[strt:end]


def _get_github_token_from_user():
    ques = [
        {
            'type': 'input',
            'name': 'token',
            'message': '\n  Enter GitHub token:',
            'validate': lambda x: len(x) > 0,
        }
    ]
    ans = prompt(ques, style=custom_style_1)
    return ans['token']


def _select_branch(repo):
    choices = _get_branches(repo)
    ques = [{
        'type': 'list',
        'message': 'Select a branch',
        'choices': choices,
        'name': 'branch'
    }]
    ans = prompt(ques, style=custom_style_1)
    return ans['branch']


def _get_branches(repo):
    branches = []
    for ref in repo.remote().refs:
        strt = ref.name.find('/')
        if strt < 0:
            continue
        if 'HEAD' in ref.name:
            continue
        branches.append(ref.name[strt+1:])
    return branches


class GitHub():
    def __init__(self, repo=None, token=None, branch=None) -> None:
        self.repo, self.token, self.branch = repo, token, branch
        self.working_dir = tempfile.TemporaryDirectory().name

        if not self.repo:
            repo_paths = _get_github_repo_from_pwd()
            self.repo = _choose_github_repo(repo_paths)

        git_repo = None
        if not _is_repo_public(self.repo):
            if self.token is not None:
                git_repo = _clone_from(self.repo, self.working_dir, self.token)
            while not git_repo:
                print((
                    f'\n GitHub repo {self.repo} is not accessible!!'
                    '\n if it is private repo enter your github token'
                    '\n enter "q" to quit'))
                self.token = _get_github_token_from_user()
                if self.token == 'q':
                    self.token = None
                    break
                git_repo = _clone_from(self.repo, self.working_dir, self.token)
        else:
            git_repo = _clone_from(self.repo, self.working_dir)
            self.token = None

        if not git_repo:
            raise GitError(
                f'GitHub repo {self.repo} is not accessible!!'
            )
        self.branch = _select_branch(git_repo)
        if not self.branch:
            raise GitError(
                f'GitHub repo {self.repo} no branch found!!'
            )

    @property
    def url(self):
        return _make_github_url(self.repo, token=self.token)


if __name__ == '__main__':
    github = GitHub()
if __name__ == "__main__":
    env = Env(working_dir='../uduthuni/')
