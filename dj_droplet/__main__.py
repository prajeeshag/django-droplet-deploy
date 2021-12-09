from PyInquirer import prompt
from examples import custom_style_1, custom_style_2, custom_style_3
from dj_droplet.droplet import choose_droplet

from dj_droplet.github import get_github_config
from dj_droplet.env import get_env_vars, edit_env_vars
import dotenv
from dj_droplet.components import DataBase, DjangoApp


class AB:
    sldk = 'sdl'

    def __init__(self) -> None:
        self.a = 'a'
        self.b = 'b'
        self.c = 'c'

    def something(self):
        pass


if __name__ == "__main__":
    print(AB().__dict__)
