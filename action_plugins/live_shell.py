#!/usr/bin/env python

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


import os
import subprocess
import stat
import sys
import tempfile
import time


from ansible.module_utils._text import to_bytes, to_native, to_text
from ansible.plugins.action import ActionBase
from ansible.plugins.connection.ssh import Connection as SSHConnection
from ansible.module_utils.six.moves import shlex_quote

from pprint import pprint


class ActionModule(ActionBase):

    def run(self, tmp=None, task_vars=None):

        if self._play_context.become:
            raise Exception('The live module does not support ansible\'s builtin become. Please add sudo to the command.')

        # def __init__(self, play_context, new_stdin, shell=None, *args, **kwargs):
        sshconn = SSHConnection(self._play_context, None)
        sshcmd = sshconn._build_command('ssh')
        sshcmd = [x.decode('utf-8') for x in sshcmd]

        # disable controlpersist to prevent hangs
        for idx,x in enumerate(sshcmd):
            if 'ControlMaster=auto' in x:
                sshcmd[idx] = 'ControlMaster=no'

        # force tty
        #if '-tt' not in sshcmd:
        #    sshcmd.append('-tt')

        if self._play_context.remote_user:
            sshcmd.append('-o')
            sshcmd.append('User=%s' % to_text(self._play_context.remote_user))

        sshcmd.append(to_text(self._play_context.remote_addr))

        task_args = self._task.args.copy()
        fh, src = tempfile.mkstemp(prefix='live_script_', suffix='.sh')
        with open(src, 'w') as f:
            f.write('#!/bin/bash\n')
            f.write(task_args['command'].replace(' \ ', ' \\n'))

        st = os.stat(src)
        os.chmod(src, st.st_mode | stat.S_IEXEC)

        dst = '~/%s' % os.path.basename(src)
        sshconn.put_file(src, dst)
        sshconn.exec_command('chmod +x %s' % dst)


        #sshcmd.append(b"'" + b'/bin/bash ' + to_bytes(task_args['command']) + b"'")
        #sshcmd.append(shlex_quote('/bin/bash -c ' + "'" + to_text(task_args['command']) + "'"))

        cmd = sshcmd[:] + [shlex_quote('/bin/bash -c ' + "'" + dst + "'")]


        print(sshcmd)
        #import epdb; epdb.st()

        process = subprocess.Popen(' '.join(cmd), shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for c in iter(lambda: process.stdout.readline(), ''):
            sys.stdout.write(c.decode('utf-8'))
            #import q; q(process.poll())
            #import q; q(process.returncode)
            if process.returncode is not None:
                break
            #import q; q(process.poll())
            process.poll()

        process.stdout.close()
        process.kill()
        sys.stdout.flush()

        return {'stdout': ''}


