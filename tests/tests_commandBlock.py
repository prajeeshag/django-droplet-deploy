
from os import name
import unittest
from dj_droplet.components import CommandBlock, CmdException
import paramiko
import getpass
import time


class CommandBlockTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        username = getpass.getuser()
        self.ssh.connect('localhost', username=username)

    def test_CommandBlockParallel(self):
        times = 5
        cmd = 'echo {i} && date && sleep 1 && date'
        cmdblk1 = CommandBlock(
            name='parallel10sec',
            commands=[cmd.format(i=i) for i in range(times)],
            serial=False)
        cmdblk2 = CommandBlock(
            name='serial10sec',
            commands=[cmd.format(i=i+times) for i in range(times)],
            depend=cmdblk1)
        print(cmdblk2.depend._status)
        self.assertRaises(CmdException, cmdblk2.exec, self.ssh)
        st = time.time()
        cmdblk1.exec(self.ssh)
        cmdblk1.update_status()
        for cmd in cmdblk1.commands:
            print(cmd.stdout)
        et = time.time()
        tt = et - st
        self.assertLess(
            tt, times/2, msg='Parallel block should finish in < 5 seconds')
        st = time.time()
        cmdblk2.exec(self.ssh)
        cmdblk2.update_status()
        et = time.time()
        tt = et - st
        self.assertGreaterEqual(
            tt, times, msg='Serial block should take >= 10 seconds')
