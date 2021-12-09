import json
import os
import pickle
from abc import ABC, abstractclassmethod
from enum import Enum
from typing import List

import paramiko
from paramiko import sftp
from PyInquirer import prompt

from droplet import choose_droplet
from github import GitHub
from util import hash_string, get_wsgi_app
from util import get_random_string
import validators

# CommandBlocks are the basic components, Each CommandBlocks can have dependencies
# Each command in a command block will have a status property
# Status property will have a status value and info
#


class CmdException(Exception):
    pass


class Status(Enum):
    NOT_EXEC = 'not_exec'
    EXECUTING = 'executing'
    DONE = 'done'
    FAILED = 'failed'
    CANCELED = 'canceled'


class Component:
    CONFIG_DIR = '.django_applet'
    DEFAULT_APT_PACKAGES = []
    SETUP_COMMANDS = []

    def _dump_self(self, client):
        fname = self._get_dump_file_name()
        sftp = client.open_sftp()
        data = pickle.dumps(self)
        with sftp.open(fname, 'w') as file:
            pickle.dump(self, file)
        sftp.close()

    def _load_self(self, client):
        fname = self._get_dump_file_name()
        sftp = client.open_sftp()
        try:
            sftp.stat(fname)
        except IOError:
            return
        with sftp.open(fname, 'r') as file:
            obj = pickle.load(file)
        sftp.close()

        check_fields = getattr(self, '_check_field', [])
        for index in check_fields:
            fld_self = getattr(self, index, None)
            fld_obj = getattr(obj, index, None)
            if fld_self is None and fld_obj is None:
                continue
            if fld_self != fld_obj:
                return
        for index, value in obj.__dict__.items():
            setattr(self, index, value)

    def _get_dump_file_name(self):
        name = self._get_file_name()
        return f'{self.CONFIG_DIR}/{name}.{self.__class__.__name__}'

    def _list_dumps(self, client):
        cmd = f'cd {self.CONFIG_DIR} && ls *.{self.__class__.__name__}'
        _, stdout, stderr = client.exec_command(cmd)
        exit_status = stdout.channel.recv_exit_status()
        if exit_status == 0:
            return stdout.read().decode('utf-8')
        return ''

    def _get_file_name(self):
        return self.name

    def _create_config_dir(self, client):
        if not self._config_dir_exist(client):
            sftp = client.open_sftp()
            sftp.mkdir(self.CONFIG_DIR)
            sftp.close()

    def _config_dir_exist(self, client):
        sftp = client.open_sftp()
        try:
            sftp.stat(self.CONFIG_DIR)  # Test if remote_path exists
        except IOError:
            sftp.close()
            return False
        sftp.close()
        return True

    def _setup_ssh(self, ipaddr, user='root') -> None:
        self._ssh = paramiko.SSHClient()
        self._ssh.load_system_host_keys()
        self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._ssh.connect(hostname=ipaddr, username=user)

    def _install_packages(self):
        cmd = 'sudo apt-get update && sudo apt-get install -y ' + \
            ' '.join(self.DEFAULT_APT_PACKAGES)
        Command(cmd).exec(self._ssh)

    def _setup(self, **kwargs):
        for cmd in self.SETUP_COMMANDS:
            Command(cmd).exec(self._ssh, obj=self, **kwargs)

    def _get_input_from_user(self, msg, validate=None, default=''):
        if validate is None:
            def validate(x): return True
        ques = [{
            'type': 'input',
            'message': msg,
            'name': 'name',
            'validate': validate,
            'default': default,
        }]
        ans = prompt(ques)
        return ans['name']

    def __getstate__(self):
        state = {key: value for key, value in self.__dict__.items()
                 if not key.startswith('_')}
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)


class Command(Component):

    def __init__(self, cmd: str, depend=None) -> None:
        self.cmd, self.depend = cmd, depend
        self._check_field = ['full_cmd', ]
        self.full_cmd = None
        self.status = Status.NOT_EXEC
        self.exit_status = None
        self._out = None
        self._err = None
        self._stdout = None
        self._stderr = None

    def exec(self, client, force=False, return_stdout=False, **kwargs) -> None:
        self.full_cmd = self.cmd.format(**kwargs)
        if not force:
            self._load_self(client)

        # if completed then return
        if self.is_done:
            print(f'{self.full_cmd} skipping... already done...')
            return
        print(f'{self.full_cmd}')
        _, self._out, self._err = client.exec_command(self.full_cmd)
        self.exit_status = self._out.channel.recv_exit_status()
        self._stdout = self._out.read().decode('utf-8')
        self._stderr = self._err.read().decode('utf-8')

        if self.exit_status == 0:
            self.status = Status.DONE
            self._dump_self(client)
        else:
            self.status = Status.FAILED
            raise CmdException(
                (f'Command failed: {self.full_cmd} \n'
                 f'stderr: {self._stderr} \n'
                 f'stdout: {self._stdout} \n')
            )

    def _get_file_name(self):
        string = self.full_cmd
        string = ''.join(string.split())
        filename = hash_string(string)
        return filename


def assign_status_attr(name, cls, fn):
    def fn1(self):
        return getattr(self, f'_{name}')

    def fn2(self):
        return self.status == name
    if fn == 'fn2':
        setattr(cls, f'is_{name.value}', property(fn2))
    else:
        setattr(cls, name, property(fn1))


for name in Status:
    assign_status_attr(name, Command, fn='fn2')

for name in ('stdout', 'stderr'):
    assign_status_attr(name, Command, fn='fn1')


class UnAuthorizedDroplet(Exception):
    pass


class MultipleAppsException(Exception):
    pass


class DjangoApp(Component):
    DEFAULT_APT_PACKAGES = [
        'python3-pip', 'python3-dev', 'nginx', 'curl', 'certbot',
        'python3-certbot-nginx', 'git', 'libpq-dev', 'python3-venv',
    ]
    # gunicorn.socket
    GUNICORN_SOCKET_CONTENT = (
        "[Unit]\nDescription = {obj.name} socket\n\n"
        "[Socket]\nListenStream=/run/{obj.name}.sock\n\n"
        "[Install]\nWantedBy = sockets.target\n"
    )

    # gunicorn.service
    GUNICORN_SERVICE_CONTENT = (
        "[Unit]\nDescription={obj.name} daemon\nRequires={obj.name}.socket\nAfter=network.target\n\n"
        "[Service]\nUser={obj.name}\nGroup=www-data\nWorkingDirectory=/home/{obj.name}/ROOT/\n"
        "ExecStart=/home/{obj.name}/venv/bin/gunicorn "
        "--access-logfile /home/{obj.name}/gunicorn_access.log "
        "--error-logfile /home/{obj.name}/gunicorn_error.log "
        "--workers {obj.gunicorn_workers} "
        "--bind unix:/run/{obj.name}.sock "
        "{obj.wsgi_application}\n"
        "EnvironmentFile=/home/{obj.name}/ROOT/.env \n\n"
        "[Install]\nWantedBy=multi-user.target\n"
    )

    # scp /etc/nginx/sites-available/default
    NGINX_CONTENT = (
        "server {{\n\tlisten 80;\n\tserver_name {obj.domain_name} www.{obj.domain_name};\n"
        "\tlocation = /favicon.ico {{\n\t\taccess_log off; log_not_found off; \n\t}}\n"
        "\tlocation /staticfiles/ {{\n\t\troot /home/{obj.name}/ROOT/; \n\t}}\n"
        "\tlocation /media/ {{\n\t\troot /home/{obj.name}/ROOT/; \n\t}}\n"
        "\tlocation / {{\n\t\tinclude proxy_params; proxy_pass http://unix:/run/{obj.name}.sock; \n\t}}\n}}"
    )

    SETUP_COMMANDS = [
        'adduser {obj.name} --gecos "First Last,RoomNumber,WorkPhone,HomePhone" --disabled-password',
        'echo "{obj.name}:{obj.password}" | sudo chpasswd',
        'usermod -aG sudo {obj.name}',
        'cp -r .ssh /home/{obj.name}/',
        'chown -R {obj.name}:{obj.name} /home/{obj.name}/.ssh',
        'sudo -H -u {obj.name} bash -c "python3 -m venv /home/{obj.name}/venv"',
        'sudo -H -u {obj.name} bash -c "git clone -b {obj.github.branch} {obj.github.url} /home/{obj.name}/ROOT"',
        'sudo -H -u {obj.name} bash -c "/home/{obj.name}/venv/bin/pip install -r /home/{obj.name}/ROOT/requirements.txt"',
        'sudo -H -u {obj.name} bash -c "/home/{obj.name}/venv/bin/pip install gunicorn psycopg2"',
        f'echo -e "{GUNICORN_SOCKET_CONTENT}" > ' +
        '/etc/systemd/system/{obj.name}.socket',
        f'echo -e "{GUNICORN_SERVICE_CONTENT}" > ' +
        '/etc/systemd/system/{obj.name}.service',
        f'echo -e "{NGINX_CONTENT}" > ' +
        '/etc/nginx/sites-available/{obj.domain_name}',
        'ln -s /etc/nginx/sites-available/{obj.domain_name} /etc/nginx/sites-enabled/{obj.domain_name}',
    ]

    def __init__(self) -> None:
        self.password = get_random_string(14)
        self.gunicorn_workers = 3
        self._setup_droplet()

    def _setup_droplet(self):
        (self.droplet, droplet_created) = choose_droplet()
        self._setup_ssh(self.droplet.publicIp4)
        if droplet_created:
            self._init_droplet()
        else:
            self._init_existing_droplet()

    def _init_droplet(self):
        if not getattr(self, 'initialized', False):
            self._create_config_dir(self._ssh)
            if not getattr(self, 'name', None):
                self.name = self._get_app_name_from_user()
            if not getattr(self, 'domain_name', None):
                self.domain_name = self._get_domain_name_from_user()
            if not getattr(self, 'github', None):
                self.github = GitHub()
            if not getattr(self, 'wsgi_module', None):
                self.wsgi_application = self._get_wsgi_application()

            self._dump_self(self._ssh)
            self._install_packages()
            self._setup()
            self.initialized = True
            self._dump_self(self._ssh)

    def _init_existing_droplet(self):
        # TODO: load app configuration if existing
        if not self._config_dir_exist(self._ssh):
            if (self._confirm_proceed_existing_droplet()):
                self._init_droplet()
                return
            else:
                raise UnAuthorizedDroplet()
        dumps = self._list_dumps(self._ssh).split()
        if len(dumps) > 1:
            raise MultipleAppsException()
        if len(dumps) < 1:
            return self._init_droplet()
        dumps = dumps[0]
        self.name = dumps[:dumps.index('.')]
        self._load_self(self._ssh)
        self._init_droplet()

    def _confirm_proceed_existing_droplet(self):
        ques = [{
            'type': 'confirm',
            'message': ('This droplet is not created or maintained by Django Applet, '
                        'Do you want to proceed with this droplet? (Warning: Not recommended) '),
            'name': 'name',
            'default': False,
        }]
        ans = prompt(ques)
        return ans['name']

    def _get_wsgi_application(self):
        wsgiapp = get_wsgi_app(self.github.working_dir)

        if not wsgiapp:
            wsgiapp = ''

        def validate(x):
            if '.' not in x or ':' not in x:
                return 'Enter a valid wsgi module name!!'
            return True
        msg = 'Enter the python path to wsgi module'
        return self._get_input_from_user(msg, validate, default=wsgiapp)

    def _get_domain_name_from_user(self):
        def validate(x):
            if not validators.domain(x):
                return 'Enter valid domain name!!'
            return True
        msg = 'Enter a domain name for your app'
        return self._get_input_from_user(msg, validate)

    def _get_app_name_from_user(self):
        def validate(x):
            if len(x) < 3:
                return 'Name should contain atleast 3 characters'
            if not x.isidentifier():
                return 'Name should only contain alphanumeric and underscore'
            return True
        msg = 'Enter a name for your app'
        return self._get_input_from_user(msg, validate)


class DataBase(Component):
    DEFAULT_APT_PACKAGES = [
        'libpq-dev', 'postgresql', 'postgresql-contrib', 'libjson-perl',
    ]
    DATABASE_URL = 'postgres://{self.dbuser}:{self.passwd}@{hostname}/{self.db}',
    dbc_cmd_prefix = 'cd /tmp && sudo -u postgres psql -c'
    DB_CREATE_COMMANDS = (
        dbc_cmd_prefix + ' "CREATE DATABASE {self.db};"',
        dbc_cmd_prefix +
        ' "CREATE USER {self.dbuser} WITH PASSWORD \'{self.passwd}\';"',
        dbc_cmd_prefix +
        ' "ALTER ROLE {self.dbuser} SET client_encoding TO \'utf8\';"',
        dbc_cmd_prefix +
        ' "ALTER ROLE {self.dbuser} SET default_transaction_isolation TO \'read committed\';"',
        dbc_cmd_prefix +
        ' "ALTER ROLE {self.dbuser} SET timezone TO \'UTC\';"',
    )

    DB_ROOT_DIR = '/database/backup'
    DB_ARCHIVE_DIR = f'{DB_ROOT_DIR}/archive'
    DB_BACKUP_DIR = f'{DB_ROOT_DIR}/backup'
    DB_BACKUP_COMMAND = f'cd /tmp && sudo -u postgres pg_basebackup -D {DB_BACKUP_DIR}'
    DB_ARCHIVE_SETUP_COMMANDS = (
        ('mkdir -p ' + DB_ARCHIVE_DIR, False),
        ('mkdir -p ' + DB_BACKUP_DIR, False),
        ('chown -R postgres:postgres ' + DB_ROOT_DIR, False),
        ('echo "archive_mode = on" >>  {config}', False),
        (f'echo "archive_command = \'test ! -f {DB_ARCHIVE_DIR}/%f && cp %p {DB_ARCHIVE_DIR}/%f\'"' + ' >> {config}', False),
        ('echo "wal_level = replica" >> {config}', False),
        ('systemctl restart postgresql', False),
        (DB_BACKUP_COMMAND, False),
    )

    def __init__(self, ipaddr, db='db', backup=True) -> None:
        self.db = db
        self.dbuser = f'{db}user'
        self.passwd = f'{db}passwd'
        self.backup = backup
        self._setup_ssh(ipaddr)
        self._install_packages()
        cmd = Command('pg_lsclusters --json')
        cmd.exec(self._ssh)
        data = json.loads(cmd.stdout)[0]
        self.pgdata = data['pgdata']
        self.pgconfigdir = data['configdir']
        self._create_db()
        if self.backup:
            self._setup_backup()

    def _create_db(self):
        for cmd in self.DB_CREATE_COMMANDS:
            Command(cmd).exec(self._ssh, db=self.db,
                              dbuser=self.dbuser,
                              passwd=self.passwd)

    def _setup_backup(self):
        for cmd in self.DB_ARCHIVE_SETUP_COMMANDS:
            Command(cmd[0]).exec(self._ssh, force=cmd[1], config=os.path.join(
                self.pgconfigdir, 'postgresql.conf'))

    @ property
    def url(self):
        return self.DATABASE_URL.format(
            dbuser=self.dbuser,
            passwd=self.passwd,
            hostname='localhost',
            db=self.db)


class RedisCache:
    def __init__(self) -> None:
        pass


if __name__ == '__main__':
    app = DjangoApp()
