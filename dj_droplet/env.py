import json
import os

from examples import custom_style_1, custom_style_2, custom_style_3
from PyInquirer import prompt, Separator
import dotenv
from .util import find, exclude

ENV_DEFAULTS = {
    'DEBUG': 'False',
    'DEVMODE': 'False',
    'CACHE_URL': 'redis://127.0.0.1:6379/1',
    'ALLOWED_HOSTS': '{DOMAIN_NAME},{IPADDR}'
}


def override_env_var_defaults(vars, defaults):
    for (idx, val) in defaults.items():
        if idx in vars:
            vars[idx] = val


def extract_env_var(line):
    line1 = line.strip()

    if not line1 or line1.strip()[0] == '#':
        return None
    eqc = line1.find('=')
    if eqc < 0:
        return None
    idx = line1[0:eqc].strip()
    val = line1[eqc+1:].strip()
    val = strip_quote(val)
    return (idx, val)


def strip_quote(string):
    if (string.startswith('"') and string.endswith('"') or
            string.startswith("'") and string.endswith("'")):
        return string[1:-1]
    return string


def find_env_vars(path='.'):
    env_vars = []
    for (root, dirs, files) in os.walk(path, topdown=True):
        dirs[:] = [d for d in dirs if d not in exclude]
        dirs[:] = [d for d in dirs if d[0] != '.']
        dirs[:] = [d for d in dirs if os.path.isfile(
            os.path.join(root, d, '__init__.py'))]
        for file in files:
            if file.endswith('.py'):
                env_vars += find_env_vars_from_file(os.path.join(root, file))

    return {var: '' for var in env_vars}


def find_env_vars_from_file(file):
    env_vars = []
    with open(file, 'r') as f:
        for line in f.readlines():
            env_vars += find_env_vars_from_line(line)
    return env_vars


def find_env_vars_from_line(line):
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


def get_env_vars(path='.'):
    envvars = find_env_vars(path)
    envdot = values_from_dotenv()
    envvars.update(envdot)
    override_env_var_defaults(envvars, ENV_DEFAULTS)
    return envvars


def values_from_dotenv():
    ques = [
        {
            'type': 'input',
            'message': f' \n Enter .env file path (leave empty to skip)',
            'name': 'envfile',
        }
    ]
    ans = prompt(ques, style=custom_style_1)
    if ans['envfile']:
        return dotenv.dotenv_values(ans['envfile'])
    return {}


def get_env_val_from_user(var, default=''):
    ques = [
        {
            'type': 'input',
            'message': f'Enter a value or leave empty to ignore this variable {var} = ',
            'default': default,
            'name': var,
        }
    ]
    ans = prompt(ques, style=custom_style_1)
    return ans.get(var)


def build_env_list_choices(vars):
    choices = [
        {'name': 'Save and Continue..', 'value': 'save'},
        {'name': 'Exit', 'value': 'quit'},
        Separator(),
    ]
    for (var, val) in vars.items():
        val1 = val
        if len(val) >= 100:
            val1 = val1[1:100] + ' .....'
        choices += [{'name': f'  {var} = {val1}', 'value': var}]
    return choices


def list_edit_env_var(vars, default=None):
    choices = build_env_list_choices(vars)
    ques = [
        {
            'type': 'list',
            'message': '\n  Select to edit: ',
            'name': 'response',
            'choices': choices,
            'default': default,
        }
    ]
    ans = prompt(ques, style=custom_style_1)
    return ans['response']


def edit_env_vars(envd):
    res = 'save'
    while True:
        res = list_edit_env_var(envd, default=res)
        if res == 'quit':
            return 'quit'
        elif res == 'save':
            return 'save'
        envd[res] = get_env_val_from_user(res, envd[res])


if __name__ == "__main__":
    envd = get_env_vars()
    edit_env_vars(envd)
