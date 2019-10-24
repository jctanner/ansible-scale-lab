# (c) 2012-2014, Michael DeHaan <michael.dehaan@gmail.com>
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.
# Make coding more python3-ish
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = '''
    strategy: benchmark
    short_description: Executes tasks in a linear fashion
    description:
        - Task execution is in lockstep per host batch as defined by C(serial) (default all).
          Up to the fork limit of hosts will execute each task at the same time and then
          the next series of hosts until the batch is done, before going on to the next task.
    version_added: "2.0"
    notes:
     - This was the default Ansible behaviour before 'strategy plugins' were introduced in 2.0.
    author: Ansible Core Team
'''

import json
import os
import shutil
import subprocess
import time

from collections import OrderedDict

from ansible.errors import AnsibleError, AnsibleAssertionError
from ansible.executor.play_iterator import PlayIterator
from ansible.module_utils.six import iteritems
from ansible.module_utils._text import to_text
from ansible.playbook.block import Block
from ansible.playbook.included_file import IncludedFile
from ansible.playbook.task import Task
from ansible.plugins.loader import action_loader
from ansible.plugins.strategy import StrategyBase
from ansible.template import Templar
from ansible.utils.display import Display

display = Display()

from ansible.plugins.strategy.linear import StrategyModule as LinearStrategyModule


class StrategyModule(LinearStrategyModule):

    br_dir = 'benchmark_results'
    hostcount = None
    host_queue_starts =  None
    concurrent_hosts = None

    def __init__(self, tqm):
        super(StrategyModule, self).__init__(tqm)

        if os.path.exists(self.br_dir):
            shutil.rmtree(self.br_dir)
        os.mkdir(self.br_dir)

        self.hostcount = 1000
        self.host_queue_starts = []
        self.concurrent_hosts = []

        if 'testhosts' not in self._inventory.groups:
            display.display('adding hosts via strategy')

            for x in range(0, self.hostcount):
                host = 'host-' + str(x)
                if host not in self._inventory.hosts:
                    hd = {
                        'host_name': host,
                        'groups': ['testhosts'],
                        'host_vars': {
                            'ansible_python_interpreter': '/usr/bin/python3'
                        }
                    }
                    self._add_host(hd, None)

    def _queue_task(self, *args, **kwargs):
        ts = time.time()
        self.host_queue_starts.append({
            'host': str(args[0]),
            'task_uuid': args[1]._uuid,
            'task_name': args[1].name,
            'time': ts
        })
        self.concurrent_hosts.append({
            'time': ts,
            'task_uuid': args[1]._uuid,
            'task_name': args[1].name,
            'active': list(self._blocked_hosts.keys())
        })
        return super(StrategyModule, self)._queue_task(*args, **kwargs)

    def run(self, *args, **kwargs):
        display.display('[strategy] run')

        pslog = os.path.join(self.br_dir, 'ps.log')
        cmd = "while true; do date +'\n#%%s.%%3N' >> %s; ps xao pid,ppid,pgid,sid,%%cpu,%%mem,cmd -w 512 >> %s; sleep .1; done;" % (pslog, pslog)
        watcher = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        start_time = time.time()
        result = super(StrategyModule, self).run(*args, **kwargs)
        stop_time = time.time()

        watcher.kill()

        display.display('[strategy] writing benchmark results to %s' % self.br_dir)
        ts = str(time.time())
        meta = {
            'start': start_time,
            'stop': stop_time,
            'forks': self._variable_manager.get_vars().get('ansible_forks', None),
            'hosts': self.hostcount,
            'time': ts
        }
        with open(os.path.join(self.br_dir, '%s_meta.json' % ts), 'w') as f:
            f.write(json.dumps(meta, indent=2))
        with open(os.path.join(self.br_dir, '%s_host_queue_starts.json' % ts), 'w') as f:
            f.write(json.dumps(self.host_queue_starts, indent=2))
        with open(os.path.join(self.br_dir, '%s_concurrent_hosts.json' % ts), 'w') as f:
            f.write(json.dumps(self.concurrent_hosts, indent=2))

        return result
