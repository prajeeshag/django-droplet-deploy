from PyInquirer import prompt, Separator
from .util import find
from paramiko.client import SSHClient
import paramiko
from scp import SCPClient
import sys
from .githubconfig import make_github_url

DB_ARCHIVE = '/database/db_backup/archive'
DB_BACKUP = '/database/db_backup/backup'

DEFAULT_INSTALL_PACKAGES = ['python3-pip', 'python3-dev',
                            'nginx', 'curl', 'certbot', 'python3-certbot-nginx',
                            'redis-server', 'git'
                            ]

DEFAULT_POST_INSTALL_JOBS = (
    'sudo apt update && sudo apt upgrade -y',
    'pip3 install gunicorn psycopg2',
)

DEFAULT_POST_DEPLOY_JOBS = (
    'python3 manage.py migrate',
    'python3 manage.py collectstatic --no-input'
)

USER_CREATE_COMMANDS = (
    'adduser {user} --gecos "First Last,RoomNumber,WorkPhone,HomePhone" --disabled-password',
    'echo "{user}:{password}" | sudo chpasswd',
    'usermod -aG sudo {user}',
    'cp -r .ssh /home/{user}/',
    'chown -R {user}:{user} /home/{user}/.ssh',
)

PROJECT_SETUP_COMMANDS = (
    'rm -rf /home/{user}/ROOT',
    'git clone -b {branch} {github_url} /home/{user}/ROOT',
    'chown -R {user}:{user} /home/{user}/ROOT',
    'pip3 install -r /home/{user}/ROOT/requirements.txt',
)

SETUP_DATABASE_BACKUP = (
    'mkdir -p ' + DB_ARCHIVE,
    'mkdir -p ' + DB_BACKUP,
    'sudo chown postgres:postgres '+DB_ARCHIVE,
    'sudo chown postgres:postgres '+DB_BACKUP,
    'cp /etc/postgresql'
)


def get_post_deploy_jobs_from_user(default=''):
    ques = [
        {
            'type': 'input',
            'message': ' Enter the command ',
            'name': 'command',
            'default': default,
        }
    ]
    ans = prompt(ques)
    return ans['command']


def list_post_deploy_jobs(jobs):
    choices = [{'name': 'Continue', 'value': 'Continue'},
               {'name': 'Add a new job', 'value': 'Add'},
               Separator()] + jobs
    ques = [
        {
            'type': 'list',
            'message': '-- Add post deploy jobs -- ',
            'name': 'response',
            'choices': choices,
        }
    ]
    ans = prompt(ques)
    return ans['response']


def get_post_deploy_jobs():
    postjobs = DEFAULT_POST_DEPLOY_JOBS.copy()

    while True:
        res = list_post_deploy_jobs(postjobs)
        if res == 'Continue':
            return postjobs
        elif res == 'Add':
            job = get_post_deploy_jobs_from_user()
            if job:
                postjobs.append(job)
                postjobs = list(set(postjobs))
        else:
            postjobs.remove(res)
            job = get_post_deploy_jobs_from_user(default=res)
            if job:
                postjobs.append(job)
                postjobs = list(set(postjobs))


def find_gunicorn_wsgi(path):
    wsgipath = find('wsgi.py', path)
    wsgiapp = wsgipath.replace(path, '', 1).replace(
        '.py', ':application').replace('/', '.')
    while wsgiapp.startswith("."):
        wsgiapp = wsgiapp[1:]
    return wsgiapp


class DropletSSHClient(SSHClient):
    def __init__(self, droplet, username) -> None:
        super().__init__()
        self.load_system_host_keys()
        self.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.droplet = droplet
        self.connect(hostname=droplet.publicIp4, username=username)
        self.username = username
        self.scp = SCPClient(self.get_transport(),
                             progress=DropletSSHClient.progress)

    @staticmethod
    def progress(filename, size, sent):
        percentage = int(float(sent)/float(size) * 100)
        print(f"{filename}'s progress: {percentage}%")

    def is_alive(self):
        if not self.get_transport().is_active():
            return False
        try:
            self.get_transport().send_ignore()
        except EOFError as e:
            return False
        return True

    def execute_command(self, command):
        channel = self.get_transport().open_session()
        channel.set_combine_stderr(True)
        print(f'{self.username}@{self.droplet.name}:> {command}')
        channel.exec_command(command)
        self.print_stdout(channel)
        if channel.recv_exit_status() != 0:
            channel.close()
            return False
        channel.close()
        return True

    def print_stdout(self, channel):
        while not channel.exit_status_ready():
            if channel.recv_ready():
                data = channel.recv(1024)
                while data:
                    print(
                        f"{self.username}@{self.droplet.name}: {data.decode('utf-8')} ")
                    data = channel.recv(1024)


class DropletApp:
    def __init__(self, droplet, ghbconfig, dotenv) -> None:
        self.droplet = droplet
        self.ghbconfig = ghbconfig
        self.dotenv = dotenv
        self.rootSSH = DropletSSHClient(
            droplet=droplet,
            username='root')

    def init_userSSH(self, user):
        self.rootSSH = DropletSSHClient(
            droplet=self.droplet,
            username=user)

    def run_post_install_jobs(self):
        # for command in DEFAULT_POST_INSTALL_JOBS:
        #     if not self.rootSSH.execute_command(command):
        #         return False
        # command = 'sudo apt install -y '+' '.join(DEFAULT_INSTALL_PACKAGES)
        # if not self.rootSSH.execute_command(command):
        #     return False
        # if not self.create_user():
        #     return False
        # if not self.setup_project():
        #    return False
        return True

    def create_user(self, user='myuser', password='password'):
        for command in USER_CREATE_COMMANDS:
            if not self.rootSSH.execute_command(command.format(user=user, password=password)):
                return False
        self.init_userSSH(user)

    def setup_project(self, user='myuser'):
        github_url = make_github_url(
            self.ghbconfig['repo'], self.ghbconfig['token'])
        for command in PROJECT_SETUP_COMMANDS:
            cmd = command.format(
                user=user, github_url=github_url,
                branch=self.ghbconfig['branch'])
            if not self.rootSSH.execute_command(cmd):
                return False
        return True


if __name__ == "__main__":
    print(get_post_deploy_jobs())
