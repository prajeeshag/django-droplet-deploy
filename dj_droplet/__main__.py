from PyInquirer import prompt
from examples import custom_style_1, custom_style_2, custom_style_3

from dj_droplet.githubconfig import get_github_config
from dj_droplet.env import get_env_vars, edit_env_vars
import dotenv

if __name__ == "__main__":
    gitConfig = get_github_config()
    repoObj = gitConfig['repoObj']
    repoObj.git.checkout(gitConfig['branch'])
    envd = get_env_vars(repoObj.working_dir)
    res = edit_env_vars(envd)
    if res == 'quit':
        exit()
