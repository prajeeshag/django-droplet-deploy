from enum import Enum
import json
import os
import jsonpickle
import paramiko
from typing import List

# CommandBlocks are the basic components, Each CommandBlocks can have dependencies
# Each command in a command block will have a status property
# Status property will have a status value and info
#

APT_PACKAGES = (
    'libpq-dev', 'postgresql', 'postgresql-contrib', 'libjson-perl'
)

dbc_cmd_prefix = 'cd /tmp && sudo -u postgres psql -c'

DB_CREATE_COMMANDS = (
    dbc_cmd_prefix + ' "CREATE DATABASE {db};"',
    dbc_cmd_prefix + ' "CREATE USER {dbuser} WITH PASSWORD \'{passwd}\';"',
    dbc_cmd_prefix + ' "ALTER ROLE {dbuser} SET client_encoding TO \'utf8\';"',
    dbc_cmd_prefix +
    ' "ALTER ROLE {dbuser} SET default_transaction_isolation TO \'read committed\';"',
    dbc_cmd_prefix + ' "ALTER ROLE {dbuser} SET timezone TO \'UTC\';"',
)

DB_ROOT_DIR = os.path.join('/database', 'backup')
DB_ARCHIVE_DIR = os.path.join(DB_ROOT_DIR, 'archive')
DB_BACKUP_DIR = os.path.join(DB_ROOT_DIR, 'backup')
DB_BACKUP_COMMAND = f'sudo -u postgres pg_basebackup -D {DB_BACKUP_DIR}'

DB_ARCHIVE_SETUP_COMMANDS = (
    'mkdir -p ' + DB_ARCHIVE_DIR,
    'chown postgres:postres ' + DB_ARCHIVE_DIR,
    'echo "archive_mode = on" >>  {config}',
    f'echo "archive_command = \'test ! -f {DB_ARCHIVE_DIR}/%f && cp %p {DB_ARCHIVE_DIR}/%f\'"' + ' >> {config}',
    'echo "wal_level = replica" >> {config}',
    'systemctl restart postgresql',
    DB_BACKUP_COMMAND,
)


class CmdException(Exception):
    pass


class Status(Enum):
    NOT_EXEC = 'not_exec'
    EXECUTING = 'executing'
    DONE = 'done'
    FAILED = 'failed'
    CANCELED = 'canceled'


class Command:
    def __init__(self, cmd: str, depend=None) -> None:
        self.cmd, self.depend = cmd, depend
        self._status = Status.NOT_EXEC
        self._exit_status = None
        self._out = None
        self._err = None
        self._stdout = None
        self._stderr = None

    def set_dependency(self, command):
        self.depend = command

    def exec(self, client, **kwargs) -> None:
        # Raise exception if dependancy command [if exist one] is not even executed
        if self.depend and self.depend.is_not_exec:
            raise CmdException(
                (f'Trying to execute command: {self.cmd}'
                 f'before executing its dependacy command {self.depend.cmd}')
            )
        # exec command if it does not have any dependancy or if dependacy command is done
        if not self.depend or self.depend.is_done:
            _, self._out, self._err = client.exec_command(
                self.format(**kwargs))  # async
            self._status = Status.EXECUTING
            return
        # raise exception if dependacy command is still in executing status???
        # as depend.done is accessed before in normal cases status cannot be executing
        if self.depend and self.depend.is_executing:
            raise CmdException(
                (f'Trying to execute command: {self.cmd}'
                 f'dependacy command {self.depend.cmd} is still being executed')
            )
        self._status = Status.CANCELED  # dependancy command failed or cancelled

    def format(self, **kwargs) -> str:
        return self.cmd.format(**kwargs)

    def update_status(self) -> None:
        if getattr(self, '_out'):
            self._exit_status = self._out.channel.recv_exit_status()
            self._stdout = self._out.read().decode('utf-8')
            self._stderr = self._err.read().decode('utf-8')
            if self._exit_status == 0:
                self._status = Status.DONE
            else:
                self._status = Status.FAILED
            self._out = None
            self._err = None


def assign_status_attr(name, cls, fn):
    def fn1(self):
        self.update_status()
        return getattr(self, f'_{name}')

    def fn2(self):
        self.update_status()
        return self._status == name
    if fn == 'fn2':
        setattr(cls, f'is_{name.value}', property(fn2))
    else:
        setattr(cls, name, property(fn1))


for name in Status:
    assign_status_attr(name, Command, fn='fn2')

for name in ('stdout', 'stderr', 'exit_status'):
    assign_status_attr(name, Command, fn='fn1')


class CommandBlock:
    def __init__(self, name, commands: List[str], serial: bool = True, depend=None) -> None:
        self.serial, self.name = serial, name
        self.depend = depend
        self.commands = []
        self._status = Status.NOT_EXEC
        self._stdout = ''
        self._stderr = ''

        for i in range(len(commands)):
            if not self.serial:
                depend = None
            command = Command(commands[i], depend=depend)
            self.commands.append(command)
            depend = command

    def exec(self, client, **kwargs):
        if self.depend and self.depend.is_not_exec:
            raise CmdException(
                'trying to exec command block before executing its dependancy')
        if not self.depend or self.depend.is_done:
            for cmd in self.commands:
                cmd.exec(client, **kwargs)
            self._status = Status.EXECUTING
        if self.depend and self.depend.is_executing:
            raise CmdException(
                (f'Trying to execute commandblock: {self.name}'
                 f'while dependacy commandblock {self.depend.name} is still being executed')
            )
        self._status = Status.CANCELED

    def update_status(self):
        # return failed or canceled if atleast one command failed or canceled
        for cmd in self.commands:
            if cmd.is_failed or cmd.is_canceled:
                self._status = cmd._status
                if cmd.stderr:
                    self._stderr += cmd.stderr + '\n'
                if cmd.stdout:
                    self._stdout += cmd.stdout + '\n'
                return
        # return
        if all([cmd.is_done for cmd in self.commands]):
            self._status = Status.DONE


for name in Status:
    assign_status_attr(name, CommandBlock, fn='fn2')

for name in ('stdout', 'stderr'):
    assign_status_attr(name, CommandBlock, fn='fn1')


class DataBase:
    def __init__(self, sshClient, db='db', dbuser='dbuser', passwd='dbpasswd', backup=True) -> None:
        self.db = 'db'
        self.dbuser = dbuser
        self.passwd = passwd
        self.sshClient = sshClient
        self.created = False
        self.backup = True

        command = 'sudo apt install -y '+' '.join(APT_PACKAGES)
        if not self.sshClient.execute_command(command):
            raise CmdException(
                f'Error while running command {command}')

        command = 'pg_lsclusters --json'
        stdin, stdout, stderr = self.sshClient.exec_command(command)
        if stdout.recv_exit_status() != 0:
            raise CmdException(f'Error while running command {command}')
        data = json.loads(stdout.read().decode('utf-8'))
        self.pgdata = data['pgdata']
        self.pgconfigdir = data['configdir']
        self._create_db()
        if self.backup:
            self._setup_backup()

    def _create_db(self):
        for cmd in DB_CREATE_COMMANDS:
            command = cmd.format(
                db=self.db, dbuser=self.dbuser, passwd=self.passwd)
            if not self.sshClient.execute_command(command):
                raise CmdException(f'Error while running command {command}')

    def _setup_backup(self):
        for cmd in DB_ARCHIVE_SETUP_COMMANDS:
            command = cmd.format(config=os.path.join(
                self.pgconfigdir, 'postgresql.conf'))
            if not self.sshClient.execute_command(command):
                raise CmdException(f'Error while running command {command}')


class RedisCache:
    def __init__(self) -> None:
        pass


class App:
    def __init__(self, ghConfig, sshClient, dataBase=None) -> None:
        self.ghConfig = ghConfig
        self.sshClient = sshClient
        self.dataBase = dataBase


if __name__ == '__main__':
    # cmd = Command('sudo apt update')
    # ssh = paramiko.SSHClient()
    # ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    # ssh.connect('167.71.224.232', username='root')
    # cmd.exec(ssh)
    # print('1')
    # print(cmd.stdout)
    print(Status)
    for stat in Status:
        print(stat.value)
