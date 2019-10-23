# Copyright (c) 2012, Michael DeHaan <michael.dehaan@gmail.com>
# Copyright 2015 Abhijit Menon-Sen <ams@2ndQuadrant.com>
# Copyright 2017 Toshio Kuratomi <tkuratomi@ansible.com>
# Copyright (c) 2017 Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = '''
    connection: noop
    short_description: connect via ssh client binary
    description:
        - This connection plugin allows ansible to communicate to the target machines via normal ssh command line.
        - Ansible does not expose a channel to allow communication between the user and the ssh process to accept
          a password manually to decrypt an ssh key when using this connection plugin (which is the default). The
          use of ``ssh-agent`` is highly recommended.
    author: ansible (@core)
    version_added: historical
'''

import errno
import fcntl
import hashlib
import os
import pty
import re
import subprocess
import time

from functools import wraps
from ansible import constants as C
from ansible.errors import (
    AnsibleAuthenticationFailure,
    AnsibleConnectionFailure,
    AnsibleError,
    AnsibleFileNotFound,
)
from ansible.errors import AnsibleOptionsError
from ansible.compat import selectors
from ansible.module_utils.six import PY3, text_type, binary_type
from ansible.module_utils.six.moves import shlex_quote
from ansible.module_utils._text import to_bytes, to_native, to_text
from ansible.module_utils.parsing.convert_bool import BOOLEANS, boolean
from ansible.plugins.connection import ConnectionBase, BUFSIZE
from ansible.plugins.shell.powershell import _parse_clixml
from ansible.utils.display import Display
from ansible.utils.path import unfrackpath, makedirs_safe

display = Display()


class Connection(ConnectionBase):
    ''' ssh based connections '''

    transport = 'noop'
    has_pipelining = True

    def __init__(self, play_context, new_stdin, *args, **kwargs):
        super(Connection, self).__init__(play_context, new_stdin, *args, **kwargs)
        self.host = self._play_context.remote_addr

    def _connect(self):
        self._connected = True
        return self

    #
    # Main public methods
    #
    def exec_command(self, cmd, in_data=None, sudoable=True):
        ''' run a command on the remote host '''

        super(Connection, self).exec_command(cmd, in_data=in_data, sudoable=sudoable)

        display.vvv(u"ESTABLISH SSH CONNECTION FOR USER: {0}".format(self._play_context.remote_user), host=self._play_context.remote_addr)
        #display.display(u"ESTABLISH SSH CONNECTION FOR USER: {0}".format(self._play_context.remote_user))

        #if 'python' in cmd and 'AnsiballZ' in cmd:
        #    time.sleep(2)

        return (0, '{}', '')

    def put_file(self, in_path, out_path):
        ''' transfer a file from local to remote '''

        super(Connection, self).put_file(in_path, out_path)

        display.vvv(u"PUT {0} TO {1}".format(in_path, out_path), host=self.host)
        #display.display(u"PUT {0} TO {1}".format(in_path, out_path))
        return (0, '{}', '')

    def fetch_file(self, in_path, out_path):
        ''' fetch a file from remote to local '''

        super(Connection, self).fetch_file(in_path, out_path)

        display.vvv(u"FETCH {0} TO {1}".format(in_path, out_path), host=self.host)
        #display.display(u"FETCH {0} TO {1}".format(in_path, out_path))

        return (0, '{}', '')

    def close(self):
        pass
