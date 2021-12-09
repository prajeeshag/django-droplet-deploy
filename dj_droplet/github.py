from re import I
from PyInquirer import prompt, Separator
from examples import custom_style_1, custom_style_2, custom_style_3

import requests
import json
import git
from git.exc import InvalidGitRepositoryError, GitCommandError
import tempfile
import logging

logger = logging.getLogger(__name__)


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
