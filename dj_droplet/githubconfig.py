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

TEMP_DIR = tempfile.TemporaryDirectory().name


class ReposNotFound(Exception):
    pass


class GitError(Exception):
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
    if len(repos) < 1:
        return get_github_repo_from_user()
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
        return get_github_repo_from_user()
    return ans['github_repo']


def get_branches(repo, token=None):
    res = get_branches_resp(repo, token=token)
    if res.status_code != 200:
        logger.info(f'{repo} not accesible')
        return []
    branches = [item['name'] for item in res.json()]
    return branches


def is_repo_public(repo):
    res = requests.get(make_github_url(repo))
    return res.status_code == 200


def clone_from(repo, token=None):
    url = make_github_url(repo, token)
    try:
        return git.Repo.clone_from(url, TEMP_DIR)
    except GitCommandError:
        return None


def make_github_url(repo, token=None):
    if token:
        url = f'https://username:{token}@github.com/{repo}.git'
    else:
        url = f'https://github.com/{repo}.git'
    return url


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


def get_github_repo_from_user():
    """Get the GitHub repository path from user input"""
    ques = [{
        'type': 'input',
        'name': 'repo',
        'message': 'Enter the GitHub repository path'
    }]
    ans = prompt(ques, style=custom_style_1)

    repo = repo_from_github_url(ans['repo'])
    if repo:
        return repo
    return ans['repo']


def repo_from_github_url(url):
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


def get_github_token_from_user():
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


def select_branch(repo):
    choices = get_branches(repo)
    ques = [{
        'type': 'list',
        'message': 'Select a branch',
        'choices': choices,
        'name': 'branch'
    }]
    ans = prompt(ques, style=custom_style_1)
    return ans['branch']


def get_branches(repo):
    branches = []
    for ref in repo.remote().refs:
        strt = ref.name.find('/')
        if strt < 0:
            continue
        branches.append(ref.name[strt+1:])
    return branches


def get_github_config():
    CONFIG = {}
    repo_paths = get_github_repo_from_pwd()
    repo_path = choose_github_repo(repo_paths)
    CONFIG['repo'] = repo_path
    repo = None
    token = None
    if not is_repo_public(repo_path):
        while not repo:
            print((
                f'\n GitHub repo {repo_path} is not accessible!!'
                '\n if it is private repo enter your github token'
                '\n enter "q" to quit'))
            token = get_github_token_from_user()
            if token == 'q':
                break
            repo = clone_from(repo_path, token)
    else:
        repo = clone_from(repo_path)

    CONFIG['token'] = token

    if not repo:
        raise GitError(
            f'GitHub repo {repo_path} is not accessible!!'
        )
    branch = select_branch(repo)
    if not branch:
        raise GitError(
            f'GitHub repo {repo_path} not branch found!!'
        )
    CONFIG['branch'] = branch
    CONFIG['repoObj'] = repo
    return CONFIG


# if __name__ == '__main__':
    # create_github_config()
    # create_github_config()
    # print(get_github_config())
