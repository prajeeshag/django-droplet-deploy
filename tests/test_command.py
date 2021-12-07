import unittest
from dj_droplet.components import Command, CmdException
import paramiko
import getpass


class CommandTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        username = getpass.getuser()
        self.ssh.connect('localhost', username=username)

    def test_command(self):
        strng = 'hello world'
        cmd = 'echo "{strng}"'
        command = Command(cmd)
        command1 = Command('sdalfdal')  # a failing command
        print(command._status)
        self.assertTrue(command.is_not_exec,
                        msg='command.is_not_exec should be True before exec')
        self.assertFalse(
            command.is_failed, msg='command.is_failed should be False before exec')
        self.assertFalse(
            command.is_done, msg='command.is_done should be False before exec')
        command.exec(self.ssh, strng=strng)
        self.assertEqual(command.stdout.rstrip(), strng,
                         msg='Check if exec worked correctly')
        self.assertTrue(
            command.is_done, 'command.is_done should be True after a successfull exec')
        self.assertFalse(
            command.is_failed, 'command.is_done should be False after a successfull exec')
        self.assertFalse(command.is_not_exec,
                         'command.is_done should be False after exec')

        command1.exec(self.ssh)
        self.assertFalse(
            command1.is_done, 'command.is_done should be False after a failing exec')
        self.assertTrue(
            command1.is_failed, 'command.is_done should be True after a failing exec')
        self.assertFalse(
            command1.is_not_exec, 'command.is_not_exec should be True after a failing exec')
        self.assertIn('not found', command1.stderr)
        self.assertTrue(command1.stdout == '')

    def test_command_dependancy(self):
        cmd1 = Command('sleep 3')
        cmd2 = Command('echo done', depend=cmd1)
        cmd3 = Command('lsdfs')
        cmd4 = Command('ls', depend=cmd3)
        cmd5 = Command('ls', depend=cmd4)
        self.assertRaises(CmdException, cmd2.exec, self.ssh)
        cmd1.exec(self.ssh)
        cmd3.exec(self.ssh)
        cmd4.exec(self.ssh)
        cmd2.exec(self.ssh)
        cmd5.exec(self.ssh)
        self.assertTrue(cmd1.is_done)
        self.assertTrue(cmd2.is_done)
        self.assertTrue(cmd3.is_failed)
        self.assertTrue(cmd4.is_canceled)
        self.assertTrue(cmd5.is_canceled)


if __name__ == '__main__':
    unittest.main()
