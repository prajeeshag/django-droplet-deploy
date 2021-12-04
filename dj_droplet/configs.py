from re import I
from PyInquirer import prompt, Separator
from examples import custom_style_1, custom_style_2, custom_style_3
from prompt_toolkit.validation import ValidationError, Validator

import requests
import json
import git
from git.exc import InvalidGitRepositoryError
import tempfile
import logging

logger = logging.getLogger(__name__)

CONFIG = {}


class ReposNotFound(Exception):
    pass


def is_pwd_project_dir():
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


def choose_github_repo(repos):
    if len(repos) == 1:
        return repos[0]
    ques = [
        {
            'type': 'list',
            'message': 'Choose the GitHub repo',
            'name': 'github_repo',
            'choices': repos,
            'default': repos[0],

        }
    ]
    ans = prompt(ques, style=custom_style_1)
    return ans['github_repo']


def get_branches(repo, token=None):
    res = get_branches_resp(repo, token=token)
    if res.status_code != 200:
        logger.info(f'{repo} not accesible')
        return []
    branches = [item['name'] for item in res.json()]
    return branches


def is_repo_accessible(repo, token=None):
    if repo_access_html(repo):
        return True
    res = get_branches_resp(repo, token=token)
    return res.status_code == 200


def repo_access_html(repo):
    res = requests.get(f'https://github.com/{repo}.git')
    return res.status_code == 200


def get_branches_resp(repo, token=None):
    headers = {"Accept": "application/vnd.github.v3+json", }
    if token:
        headers["Authorization"] = f"token {token}"
    res = requests.get(
        f'https://api.github.com/repos/{repo}/branches', headers=headers)
    return res


def get_github_repo_from_pwd():
    """ Get the GitHub remote repos from pwd """
    repos = []
    try:
        repo = git.Repo()
    except InvalidGitRepositoryError:
        return repos
    for remote in repo.remotes:
        repo = repo_from_github_url(remote.url)
        if repo:
            repos.append(repo)
    return repos


def repo_from_github_url(url):
    githuburl = 'github.com'
    dotgit = '.git'
    strt = url.find(githuburl)
    end = url.find(dotgit)
    if strt < 0:
        return None
    if end < 0:
        return None
    strt += len(githuburl)+1
    return url[strt:end]


def create_github_config():
    repos = get_github_repo_from_pwd()
    if not repos:
        raise ReposNotFound(
            'Could not find any GitHub remotes for the current directory.'
        )
    repo = choose_github_repo(repos)
    CONFIG['repo'] = repo
    repo_access_without_token = is_repo_accessible(repo)
    CONFIG['repo_access_without_token'] = repo_access_without_token


if __name__ == '__main__':
    # create_github_config()
    create_github_config()
