#!/usr/bin/env python3


import copy
import datetime
import glob
import json
import os
import re
import subprocess

import pytz

from collections import OrderedDict
from pprint import pprint
from logzero import logger

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.style
import matplotlib as mpl
mpl.style.use('ggplot')


class BaselineParser:

    # baseline timestamps are all UTC

    hostnames = None
    tasks_count = None
    plays_count = None
    timestamps = None
    playbook_start = None
    playbook_stop = None
    taskmap = {}
    rows = None

    def __init__(self, filepath):
        self.rows = []
        self.hostnames = set()
        self.timestamps = set()
        self._filepath = filepath
        self._data = self.load_baseline(self._filepath)
        self.process_meta()
        self.build_rows()

    def load_baseline(self, baseline_file):
        if not os.path.exists(baseline_file):
            return []
        with open(baseline_file, 'r') as f:
            baseline = json.loads(f.read())
        return baseline

    def process_meta(self):
        logger.debug('baseline')

        # collection all the timestamps
        tasks_starts = {}
        playcount = -1
        taskcount = -1
        for play in self._data:
            playcount += 1

            self.timestamps.add(play['play']['duration']['start'])
            if 'end' in play['play']['duration']:
                self.timestamps.add(play['play']['duration']['end'])

            for task in play['tasks']:
                taskcount += 1

                self.taskmap[task['task']['id']] = {
                    'task_uuid': task['task']['id'],
                    'task_name': task['task']['name'],
                    'task_number': taskcount,
                    'play_uuid': play['play']['id'],
                    'play_name': play['play']['name'],
                    'play_number': playcount,
                }

                self.timestamps.add(task['task']['duration']['start'])
                self.timestamps.add(task['task']['duration']['end'])

                tasks_starts[task['task']['id']] = task['task']['duration']['start']

                for hn,hdata in task['hosts'].items():
                    self.hostnames.add(hn)
                    self.timestamps.add(hdata['duration']['start'])
                    self.timestamps.add(hdata['duration']['end'])
                    self.timestamps.add(hdata['offset']['start'])
                    self.timestamps.add(hdata['offset']['end'])

        # helpful for other functions
        self.tasks_count = taskcount
        self.plays_count = playcount

        # store the min and max
        self.timestamps = sorted(set(self.timestamps), key=lambda x: to_datetime(x))
        if self.timestamps:
            self.playbook_start = self.timestamps[0]
            self.playbook_stop = self.timestamps[-1]

    def build_rows(self):

        rows = []
        for ts in self.timestamps:
            row = {
                'time': to_datetime(ts),
                'plays_count': self.plays_count,
                'tasks_count': self.tasks_count,
                'play_number': None,
                'task_number': None,
                'hosts_active': set(),
                'hosts_remaining': set()
            }
            rows.append(copy.deepcopy(row))

        # add play and task to the rows for that timespan
        playcount = -1
        taskcount = -1
        for play in self._data:
            playcount += 1
            pstart = to_datetime(play['play']['duration']['start'])
            for idr,row in enumerate(rows):
                if row['time'] >= pstart:
                    rows[idr]['play_number'] = playcount

            for task in play['tasks']:
                taskcount += 1
                tstart = to_datetime(task['task']['duration']['start'])
                for idr,row in enumerate(rows):
                    if row['time'] >= tstart:
                        rows[idr]['task_number'] = taskcount

        '''
        # add each active host to the rows for that timespan
        playcount = -1
        taskcount = -1
        for play in self._data:
            playcount += 1
            for task in play['tasks']:
                taskcount += 1
                for hn,hdata in task['hosts'].items():

                    hstart = to_datetime(hdata['duration']['start'])
                    hstop = to_datetime(hdata['duration']['end'])

                    #hstart = to_datetime(hdata['offset']['start'])
                    #hstop = to_datetime(hdata['offset']['end'])

                    for idr,row in enumerate(rows):

                        ts = row['time']

                        if ts >= hstart and ts <= hstop:
                            rows[idr]['hosts_active'].add(hn)

        # calculate hosts remaining
        for idr,row in enumerate(rows):
            if row['task_number'] is not None:
                rows[idr]['hosts_remaining'] = set(list(self.hostnames)[:])
        pn = None
        tn = None
        for idr,row in enumerate(rows):
            pn = row['play_number']
            tn = row['task_number']
            for _idr,_row in enumerate(rows):

                if _row['task_number'] is None:
                    continue

                if _row['task_number'] != tn:
                    continue
                if _row['task_number'] > tn:
                    break

                if _row['time'] >= row['time']:
                    for hn in row['hosts_active']:
                        #print(hn)
                        if hn in rows[_idr]['hosts_remaining']:
                            #print(hn)
                            rows[_idr]['hosts_remaining'].remove(hn)
        '''

        # set counts instead of lists
        for idr,row in enumerate(rows):
            rows[idr]['hosts_active'] = len(row['hosts_active'])
            rows[idr]['hosts_remaining'] = len(row['hosts_remaining'])

        for idr,row in enumerate(rows):
            row['time']= to_iso(row['time'])
            rows[idr] = row

        self.rows = rows[:]



def to_iso(ts, YMD=None):
    __ts = ts
    if isinstance(ts, float):
        # local time ...
        # 1568610146.120834 -> 2019-09-16T05:02:57.942911
        _ts = datetime.datetime.fromtimestamp(ts)
        #import epdb; epdb.st()
        ts = _ts.isoformat()
    elif isinstance(ts, datetime.datetime):
        ts = ts.isoformat()
    elif ',' in ts:
        parts = ts.split(',')
        import epdb; epdb.st()
    elif 'T' not in ts:
        ts = YMD + 'T' + ts + '.000000'
    elif '.' not in ts:
        ts += '.000000'
    else:
        #import epdb; epdb.st()
        pass

    if '.' not in ts:
        ts += '.000000'
        #import epdb; epdb.st()

    return ts


def to_datetime(ts):
    return iso_to_datetime(ts)


def iso_to_datetime(ts):
    return datetime.datetime.strptime(to_iso(ts), '%Y-%m-%dT%H:%M:%S.%f')


def iso_add_delta(ts, delta):
    ts = iso_to_datetime(ts)
    ts = ts + delta
    ts = ts.isoformat()
    return ts


def split_executor_line(line, level=None):
    '''Chop all of the info from a taskexecutor log entry'''

    # 2018-10-12 01:29:39,173 p=5489 u=vagrant |    7705 1539307779.17295:
    #   running TaskExecutor() for sshd_145/TASK: Check for /usr/local/sync (Target Directory)
    # 2018-10-12 01:29:39,654 p=5489 u=vagrant |    7591 1539307779.65405:
    #   done running TaskExecutor() for sshd_60/TASK: Check for /usr/local/sync (Target Directory) [525400a6-0421-65e9-9a84-000000000032]
    # 5502 1539307714.25537: done running TaskExecutor() for sshd_250/TASK: wipe out the rules [525400a6-0421-65e9-9a84-00000000002e]

    host = None
    date = None
    time = None
    ts = None
    ppid = None
    pid = None
    uid = None
    uuid = None
    task_name = None
    task = None

    parts = line.split()
    if parts[4] != '|' and not parts[0].isdigit():
        orig_parts = parts[:]
        teidx = parts.index('TaskExecutor()')
        if 'done running TaskExecutor' in line:
            parts = parts[teidx-4:]
        else:
            parts = parts[teidx-3:]
        if not parts[0].isdigit():
            badchars = [x for x in parts[0] if not x.isdigit()]
            #safechars = parts[0].split(badchars[-1])[-1]
            parts[0] = parts[0].split(badchars[-1])[-1]
            #import epdb; epdb.st()

    # sometimes in -syslog- the lines are mixed
    if len(parts) > 20 and level is None:
        starts = re.findall(r'\d+-\d+-\d+\ \d+:\d+:\d+,\d+\ p=\d+\ u=\w+\ \|\W+ ', line)
        if len(starts) > 1:
            newlines = []
            starts = OrderedDict(((x,None) for x in starts))
            for k,v in starts.items():
                starts[k] = line.index(k)
            items = list(starts.items())
            for idi,item in enumerate(starts.items()):
                end = None
                try:
                    end = items[idi+1][1]
                except IndexError:
                    pass
                newlines.append(line[item[1]:end])
            for idnl,nl in enumerate(newlines):
                ldata = split_executor_line(nl, level=1)
                newlines[idnl] = ldata
                #import epdb; epdb.st()
            #print(newlines)
            #import epdb; epdb.st()
            return newlines

    if parts[4] == '|':
        # pylogging
        date = parts[0]
        time = parts[1]
        ppid = int(parts[2].replace('p=', ''))
        uid = parts[3].replace('u=', '')

        # pre 2.8 
        if parts[5].isdigit():
            pid = int(parts[5])
            ts = float(parts[6].replace(':', ''))

        # 2.8
        if parts[5].startswith('<') and parts[5].endswith('>'):
            host = parts[5].replace('<', '').replace('>', '')
            #print(parts[:10])
            #def isfloat(a, ignore=None):
            #import epdb; epdb.st()

        # locate the pid
        if pid is None:
            pids = [x for x in parts if x.isdigit()] 
            if pids:
                pid = int(pids[0])

        # locate the timestamp
        if ts is None:
            timestamps = [x for x in parts if x.endswith(':') and isfloat(x, ignore=':')]
            if timestamps:
                ts = float(timestamps[0].replace(':', ''))

    else:
        # stdout+stderr
        pid = int(parts[0])
        ts = float(parts[1].replace(':', ''))

    if parts[-1].startswith('[') and parts[-1].endswith(']'):
        uuid = parts[-1].replace('[', '').replace(']', '')

    # this is a special place in the line
    for_index = None
    if 'for' in parts:
        for_index = parts.index('for')
        if uuid:
            task = ' '.join(parts[for_index+2:-1])
        else:
            task = ' '.join(parts[for_index+2:])

    # this may have been found earlier
    if host is None and for_index:
        host = parts[for_index+1].split('/', 1)[0]

    return {
        'date': date,
        'time': time,
        'ts': ts,
        'ppid': ppid,
        'pid': pid,
        'uid': uid,
        'uuid': uuid,
        'host': host,
        'task_name': task
    }


def parse_syslog_line(filename, linenumber, line):
    # just get the pid
    #pid = re.search(r'p=\d+', line).group()
    #pid = int(pid.replace('p=', ''))

    pid = None
    ts = None
    try:
        pidts = re.search(r'\d+ \d+\.\d+\:', line).group()
        pid = int(pidts.split()[0])
        ts = float(pidts.split()[1].rstrip(':'))
    except Exception as e:
        pass

    

    data = {
        'ppid': None,
        'pid': pid,
        'ts': ts,
        'filename': filename,
        'linenumber': linenumber
    }


    # pylogging entries
    if ': running TaskExecutor() for ' in line:
        #data = split_executor_line(line)
        ldata = split_executor_line(line)
        if not isinstance(ldata, list):
            data.update(split_executor_line(line))
        else:
            datasets = []
            for ld in ldata:
                newdata = data.copy()
                newdata.update(ld)
                datasets.append(newdata)
            return datasets

    elif ': done running TaskExecutor() for ' in line:
        ldata = split_executor_line(line)
        if not isinstance(ldata, list):
            data.update(split_executor_line(line))
        else:
            datasets = []
            for ld in ldata:
                newdata = data.copy()
                newdata.update(ld)
                datasets.append(newdata)
            return datasets

    return data


def parse_stdout_log(filename, linenumber, line, current_task_name=None):

    task_name = current_task_name
    task_uuid = None
    sshdata = {}
    pid = None
    ts = None

    #if 'Loaded config def from plugin ' in line:
    #    import epdb; epdb.st()

    m = re.search(r'\ \d+\ \d+\.\d+\:', line)
    if m is not None:
        pidts = m.group().strip()
        pid = int(pidts.split()[0])
        ts = float(pidts.split()[1].rstrip(':'))
        #import epdb; epdb.st()

    if line.startswith('TASK'):
        task_name = re.search(r"(?<=TASK \[).*?(?=\])", line).group(0)

    elif 'SSH: EXEC' in line:
        sshdata = split_ssh_exec(line)
        #import epdb; epdb.st()

    elif re.search(r"\ [0-9]+\.[0-9]+\:", line):
        numbers = re.findall(r"[0-9]+", line)

        if 'worker is' in line and 'out of' in line:
            total_forks = int(numbers[-1])

        #ts = float(numbers[1] + '.' + numbers[2])
        pid = int(numbers[0])

    data = {
        'ts': ts,
        'ppid': None,
        'pid': pid,
        'filename': filename,
        'linenumber': linenumber,
        'task_name': task_name,
        'task_uuid': task_uuid,
        'sshdata': sshdata
    }

    return data


def parse_vmstat_line(line, VMSTAT_TIMEZONE=None):
    # procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu----- -----timestamp-----
    #  r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st                 UTC
    #  2  0  43836 1524804  31152 278956  148   75   154    83   21    8  0  0 98  2  0 2019-02-11 16:13:04
    #  0  1  2     3        4     5       6    7     8     9    10   11 12 13 14 15 16  17         18
    cols = line.split()
    data = {
        'vmstat_r': int(cols[0]),
        'vmstat_b': int(cols[1]),
        'vmstat_swpd': int(cols[2]),
        'vmstat_free': int(cols[3]),
        'vmstat_buff': int(cols[4]),
        'vmstat_cache': int(cols[5]),
        'vmstat_si': int(cols[6]),
        'vmstat_so': int(cols[7]),
        'vmstat_bi': int(cols[8]),
        'vmstat_bo': int(cols[9]),
        'vmstat_in': int(cols[10]),
        'vmstat_cs': int(cols[11]),
        'vmstat_us': int(cols[12]),
        'vmstat_sy': int(cols[13]),
        'vmstat_id': int(cols[14]),
        'vmstat_wa': int(cols[15]),
        'vmstat_st': int(cols[16]),
    }

    '''
    ts = datetime.datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
    ts = ts.timestamp()
    data['ts'] = ts
    '''

    ts = cols[17] + ' ' + cols[18]
    tstmp = datetime.datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')

    try:
        tz = getattr(pytz, VMSTAT_TIMEZONE.lower())
    except AttributeError as e:
        tz = pytz.timezone(VMSTAT_TIMEZONE.upper())

    # datetime.datetime(2019,2,11,16,13,4, tzinfo=pytz.utc).timestamp()
    tzts = datetime.datetime(tstmp.year, tstmp.month, tstmp.day, tstmp.hour, tstmp.minute, tstmp.second, tzinfo=tz)

    data['ts'] = tzts.timestamp()

    return data


def parse_top_line(line, dd):
    # top - 16:13:04 up 17 days, 21:39,  1 user,  load average: 0.08, 0.03, 0.05
    # Tasks:  84 total,   2 running,  77 sleeping,   2 stopped,   2 zombie
    # KiB Mem :  1882220 total,  1513532 free,    56916 used,   311772 buff/cache
    # KiB Swap:  2097148 total,  2053312 free,    43836 used.  1597056 avail Mem

    ## EL7 ...
    # top - 17:27:17 up 1 day, 16:34,  2 users,  load average: 0.00, 0.01, 0.05
    # Tasks: 136 total,   2 running, 134 sleeping,   0 stopped,   0 zombie
    # %Cpu(s): 10.3 us,  3.7 sy,  0.0 ni, 86.0 id,  0.0 wa,  0.0 hi,  0.0 si,  0.0 st
    # KiB Mem : 32779228 total, 28919652 free,   320076 used,  3539500 buff/cache
    # KiB Swap:        0 total,        0 free,        0 used. 31971600 avail Mem

    data = {}
    if line.startswith('top -'):
        # top - 05:02:57 up  4:10,  3 users,  load average: 0.18, 0.82, 1.11
        line = line.replace(',', '')
        cols = line.split()
        data = {
            'users': cols[5],
            'load_1': cols[9],
            'load_5': cols[10],
            'load_15': cols[11],
            'tasks': None,
            'running': None,
            'sleeping': None,
            'stopped': None,
            'zombie': None,
            'kib_mem_total': None,
            'kib_mem_free': None,
            'kib_mem_used': None,
            'kib_mem_buff/cache': None,
        }

        # FIXME - value is negative...
        ts = cols[2]
        #ts = datetime.datetime.strptime(ts, '%H:%M:%S')
        #ts = ts.timestamp()
        data['ts'] = ts
        dd.update(data)

    elif line.startswith('%Cpu'):
        line = line.replace(',', '')
        parts = line.strip().split()
        for idx,x in enumerate(parts):
            #print(x)
            if x.replace('.', '').isnumeric():
                thisval = float(x)
                thiskey = parts[idx+1]
                dd[thiskey] = thisval

    elif line.startswith('Tasks:'):
        cols = line.split()
        data = {
            'tasks': int(cols[1]),
            'running': int(cols[3]),
            'sleeping': int(cols[5]),
            'stopped': int(cols[7]),
            'zombie': int(cols[9])
        }
        dd.update(data)

    elif line.startswith('KiB Mem'):
        cols = line.split()
        data = {
            'kib_mem_total': int(cols[3]),
            'kib_mem_free': int(cols[5]),
            'kib_mem_used': int(cols[7]),
            'kib_mem_buff/cache': int(cols[9]),
        }
        dd.update(data)
    elif line.startswith('KiB Swap'):
        #print(line)
        cols = line.split()
        #print(list(zip(range(0,10), cols)))
        data = {
            'kib_swap_total': int(cols[2]),
            'kib_swap_free': int(cols[4]),
            'kib_swap_used': int(cols[6]),
            'kib_swap_avail': int(cols[8]),
        }
        dd.update(data)

    return dd


def load_cgroup_data(resdir):

    cgd = {}

    filenames = glob.glob('%s/cgroup_data/*' % resdir)
    filenames = sorted(filenames)
    for fn in filenames:

        # 7-0654e32d-bf38-1fea-7039-000000000016-pids.json
        basefn = os.path.basename(fn)

        cgd[basefn] = {
            'rows': [],
            'type': basefn.replace('.json', '').split('-')[-1],
            'task_name': None,
            'task_num': basefn.split('-')[0],
            'task_uuid': None,
        }

        with open(fn, 'r') as f:
            lines = f.read()
        lines = lines.split('\n')

        for lid,line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            try:
                ld = json.loads(line)
            except Exception as e:
                logger.error(e)
                continue
            cgd[basefn]['rows'].append(ld)
            cgd[basefn]['task_name'] = ld['task_name']
            cgd[basefn]['task_uuid'] = ld['task_uuid']

    return cgd


'''
def load_baseline(resdir):
    baseline_file = os.path.join(resdir, 'baseline.json')
    if not os.path.exists(baseline_file):
        return []
    with open(baseline_file, 'r') as f:
        baseline = json.loads(f.read())
    return baseline
'''

def load_top(resdir):

    rows = []

    _td = {
        'pids_playbook_cpu': 0,
        'pids_playbook_mem': 0,
        'pids_playbook': 0,
        'pids_sshpass': 0,
        'pids_sshpass_cpu': 0,
        'pids_sshpass_mem': 0,
        'pids_sshmux': 0,
        'pids_sshmux_cpu': 0.0,
        'pids_sshmux_mem': 0.0,
        'pids_ssh': 0,
        'pids_ssh_cpu': 0.0,
        'pids_ssh_mem': 0.0,
    }

    top_file = os.path.join(resdir, 'top.log')
    with open(top_file, 'r') as f:
        lines = f.readlines()

    td = None
    for line in lines:
        #print(line.strip())
        if not line:
            continue
        if line.startswith('top -'):
            # top - 05:02:57 up  4:10,  3 users,  load average: 0.18, 0.82, 1.11
            if td:
                rows.append(td)
            td = parse_top_line(line, _td.copy())
        elif line.startswith('Tasks:'):
            # Tasks: 158 total,   1 running, 157 sleeping,   0 stopped,   0 zombie
            td = parse_top_line(line, td)
        elif line.startswith('%Cpu'):
            # %Cpu(s):  1.1 us,  0.9 sy,  0.0 ni, 98.0 id,  0.0 wa,  0.0 hi,  0.0 si,  0.0 st
            td = parse_top_line(line, td)
            #import epdb; epdb.st()
        elif line.startswith('KiB Mem'):
            # KiB Mem : 32779228 total, 30566664 free,   403272 used,  1809292 buff/cache
            td = parse_top_line(line, td)
        elif line.startswith('KiB Swap'):
            # KiB Swap:        0 total,        0 free,        0 used. 31822080 avail Mem
            td = parse_top_line(line, td)
        elif line.startswith('PID'):
            pass
        else:
            # PID USER      PR  NI    VIRT    RES    SHR S  %CPU %MEM     TIME+ COMMAND
            # 22933 centos    20   0  229176  18900   4328 R  87.5  0.1   0:00.14
            parts = line.split()
            parts = [x.strip() for x in parts if x.strip()]
            if 'ansible-playbook' in line:
                td['pids_playbook'] += 1
                td['pids_playbook_cpu'] += float(parts[8])
                td['pids_playbook_mem'] += float(parts[9])
            if 'sshpass' in line:
                td['pids_sshpass'] += 1
                td['pids_sshpass_cpu'] += float(parts[8])
                td['pids_sshpass_mem'] += float(parts[9])
            elif 'ssh:' in line and '.ansible/cp' in line and '[mux]' in line:
                # ssh: /home/centos/.ansible/cp/1e6775b5cb [mux]
                td['pids_sshmux'] += 1
                td['pids_sshmux_cpu'] += float(parts[8])
                td['pids_sshmux_mem'] += float(parts[9])
            elif ' ssh ' in line:
                td['pids_ssh'] += 1
                td['pids_ssh_cpu'] += float(parts[8])
                td['pids_ssh_mem'] += float(parts[9])

    return rows


def load_stdout_log(resdir):

    meta = {
        'playbook': None,
        'inventory': None,
        'limit': None,
        'forks': None,
        'env': {}
    }

    stdout_file = os.path.join(resdir, 'stdout.log')
    with open(stdout_file, 'r') as f:
        for line in f.readlines():
            #print(line)
            parts = [x.strip() for x in line.split() if x.strip()]
            #print(list(zip(range(0, 20), parts)))

            if not line.startswith('#'):
                key = parts[0].split('=')[0]    
                val = parts[0].split('=')[1]    

                meta['env'][key] = val

            elif 'FULLCMD' in line:
                # FULLCMD:  cgexec -g cpuacct,memory,pids:ansible_profile ansible-playbook \
                #   -vvvv -i cluster_inventory.yml --limit=all[0:1000] --forks=20 benchmark_1.yml
                meta['playbook'] = parts[-1]
                pbix = parts.index('ansible-playbook')
                for idx,x in enumerate(parts[pbix:]):
                    if '--limit' in x:
                        meta['limit'] = int(x.split(':')[-1].replace(']', '').replace('"', ''))
                    elif '--forks' in x:
                        meta['forks'] = int(x.split('=')[-1])
                    elif x == '-i':
                        meta['inventory'] = parts[idx+1]
                break

    if meta['limit'] is None and meta['env'].get('CONTAINER_COUNT'):
        meta['limit'] = int(meta['env']['CONTAINER_COUNT'])

    return meta


def load_cpuinfo(resdir):

    meta = {
        'processors': 0,
        'processor_model': None,
        'processor_mhz': None
    }

    cpufile = os.path.join(resdir, 'proc.cpuinfo.txt')
    with open(cpufile, 'r') as f:
        for line in f.readlines():
            if line.startswith('processor'):
                meta['processors'] += 1
            if line.startswith('model name'):
                meta['processor_model'] = line.split(':')[-1].strip()
            if line.startswith('cpu MHz'):
                meta['processor_mhz'] = float(line.split(':')[-1].strip())

    return meta


def load_meminfo(resdir):

    meta = {
    }

    memfile = os.path.join(resdir, 'proc.meminfo.txt')
    with open(memfile, 'r') as f:
        for line in f.readlines():
            line = line.replace(':', '')
            line = line.replace('kB', '')
            parts = line.split()
            parts = [x.strip() for x in parts if x.strip()]
            if not parts:
                continue
            meta['meminfo_' + parts[0]] = int(parts[-1])

    return meta


def load_vmstat(resdir):
    vmstat_file = os.path.join(resdir, 'vmstat.log')
    with open(vmstat_file, 'r') as f:
        lines = f.readlines()

    tz = None
    for idl,line in enumerate(lines):
        if line.strip().startswith('procs'):
            #  r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st                 UTC\n
            parts = lines[idl+1].strip().split()
            tz = parts[-1]
            break

    rows = []
    for line in lines:
        line = line.strip()
        if re.match(r'[0-9]', line):
            vd = parse_vmstat_line(line, VMSTAT_TIMEZONE=tz)
            rows.append(vd)
    return rows


def load_syslog(resdir):

    meta = {}
    task_starts = {}
    host_markers = []
    hostnames = set()

    timestamps = set()
    syslog_file = os.path.join(resdir, 'syslog.log')
    with open(syslog_file, 'r') as f:
        tn = None
        for line in f.readlines():
            line = line.strip()
            if not line:
                continue
            if not line[:4].isdigit():
                continue
            parts = line.split()

            # 2019-09-17 14:30:24,660
            ts = parts[0] + 'T' + parts[1].replace(',', '.')
            try:
                ts = datetime.datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S.%f')
            except Exception as e:
                import epdb; epdb.st()
            ts = ts.isoformat() 
            timestamps.add(ts)

            if 'PLAY' in parts:
                continue
            elif 'TASK' in parts:
                ti = parts.index('TASK')
                tn = parts[ti+1].replace('[', '').replace(']', '')
                task_starts[tn] = ts

            else:
                if 'changed:' in parts or 'ok:' in parts:
                    hn = parts[-1].replace('[', '').replace(']', '')
                    hostnames.add(hn)
                    host_markers.append([ts, tn, hn, 'end'])

    meta['timestamps'] = list(timestamps)
    meta['task_starts'] = task_starts.copy()
    meta['host_markers'] = host_markers[:]
    meta['hostnames'] = list(hostnames)[:]

    return meta


def load_netdev(resdir):

    '''
    1570072473
    Inter-|   Receive                                                |  Transmit
     face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
      eth0: 294830289  225911    0    4    0     0          0         0  5348537   65950    0    0    0     0       0          0
      eth1: 84383376  192518    0 5117    0     0          0         0 234408595  178496    0    0    0     0       0          0
        lo:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0
    '''

    netdev_file = os.path.join(resdir, 'netdev.log')
    with open(netdev_file, 'r') as f:
        flines = f.readlines()

    rows = {}
    ts = None
    colnames = None
    for line in flines:
        if not line.strip():
            continue
        if line.strip().isdigit():
            ts = int(line.strip())
            rows[ts] = {'time': ts}
        if line.startswith('Inter'):
            continue
        if line.strip().startswith('face'):
            colnames = line.replace('|', ' ').split()
            colanmes = [x.strip() for x in colnames if x.strip()]
            colnames.remove('face')

            prefix = 'rx_'
            for idx,cn in enumerate(colnames):
                if idx > 0 and cn == 'bytes':
                    prefix = 'tx_'
                colnames[idx] = prefix + cn

            continue

        cols = line.replace(':', '').split()[1:]
        for idc,col in enumerate(cols):
            key = colnames[idc]
            if key not in rows[ts]:
                rows[ts][key] = 0
            rows[ts][key] += int(col)

    rows = list(rows.values())
    for idr,row in enumerate(rows):
        ts = datetime.datetime.fromtimestamp(row['time'])
        rows[idr]['time'] = ts.isoformat()

    return rows



def load_results_directory(resdir):

    logger.info(resdir)

    cachefile = os.path.join('.cache', os.path.basename(resdir) + '.json')
    if os.path.exists(cachefile):
        with open(cachefile, 'r') as f:
            dd = json.loads(f.read())
    else:
        dd = {}
        dd['meta'] = load_stdout_log(resdir)
        dd['meta'].update(load_cpuinfo(resdir))
        dd['meta'].update(load_meminfo(resdir))
        dd['cgdata'] = load_cgroup_data(resdir)
        dd['baseline'] = BaselineParser(os.path.join(resdir, 'baseline.json'))
        dd['top'] = load_top(resdir)
        dd['vmstat'] = load_vmstat(resdir)
        dd['syslog'] = load_syslog(resdir)
        dd['netdev'] = load_netdev(resdir)

        '''
        cachedir = os.path.dirname(cachefile)
        if not os.path.exists(cachedir):
            os.makedirs(cachedir)
        with open(cachefile, 'w') as f:
            f.write(json.dumps(dd))
        '''

    return dd


def results_to_rows(rd, resdir=None):

    logger.debug('results to rows ...')

    _row = {
        'time': None,
        'src': None,
        'mem_total': None,
        'cpus_total': rd['meta']['processors'],
        'cpus_mhz': rd['meta']['processor_mhz'],
        'cpus_model': rd['meta']['processor_model'],
        'hosts': rd['meta']['limit'],
        'forks': rd['meta']['forks'],
        'playbook': rd['meta']['playbook'],
        'inventory': rd['meta']['inventory'],
        'task_uuid': None,
        'task_name': None,
        'tasks_count': None,
        'task_number': None,
    }

    rows = []
    ts_blocks = {}
    pbstart = None
    pbstop = None

    # OOMKILLs prevent baseline.json writes
    #if not rd['baseline']:
    #    return rows

    # START NETDEV
    logger.debug('netdev to rows ...')
    for row in rd['netdev']:
        thisrow = {}
        thisrow['src'] = 'netdev'
        for k,v in row.items():
            if k == 'time':
                thisrow[k] = v
            else:
                thisrow['netdev_' + k] = v
        rows.append(thisrow)

    # END NETDEV

    ###########################
    # START BASELINE
    ###########################
    baseline = rd['baseline']
    _row['hosts'] = len(baseline.hostnames)
    for blr in baseline.rows:
        blr['src'] = 'baseline'
        rows.append(blr)

    ###########################
    # START SYSLOG
    ###########################
    '''
    tasks = rd['syslog']['task_starts'].items()
    tasks = sorted(tasks, key=lambda x: x[1])
    if not rd['baseline']:
        tasks_count = len(tasks)
        ts_blocks = {'baseline': [rd['syslog']['timestamps'][0]]}

        tasks_index = {}
        for idt,task in enumerate(tasks):
            tasks_index[task[0]] = idt

    for tts in sorted(rd['syslog']['timestamps']):
        trow = copy.deepcopy(_row)
        trow['time'] = tts
        trow['tasks_count'] = tasks_count

        taskname = None
        tasknum = None
        for idt,task in enumerate(tasks):
            if tts >= task[1]:
                taskname = task[0]
                tasknum = idt
        trow['task_name'] = taskname
        trow['task_number'] = tasknum
        rows.append(trow)

    if not rd['baseline']:
        for idr,row in enumerate(rows):
            rows[idr]['hosts_remaining'] = list(rd['syslog']['hostnames'])

        # iterate through host markers and remove the host from all previous timestamps for the task
        for hm in rd['syslog']['host_markers']:
            for idr,row in enumerate(rows):
                if row['task_name'] != hm[1]:
                    continue
                if row['time'] >= hm[0] and hm[2] in rows[idr]['hosts_remaining']:
                    rows[idr]['hosts_remaining'].remove(hm[2])
    # END SYSLOG
    '''

    '''
    # validate order ...
    ltn = None
    for idr,row in enumerate(rows):
        if ltn is None and row['task_number']:
            ltn = row['task_number']
            continue
        if ltn and ltn > row['task_number']:
            print("BASELINE: OUT OF ORDER!!!")
            import epdb; epdb.st()
    '''

    ###########################
    # START CGROUPS
    ###########################
    logger.debug('cgroups')
    #bts = ts_blocks['baseline'][0]
    bts = None
    bts_offset = None
    if baseline.timestamps:
        bts = baseline.timestamps[0]
        bts = datetime.datetime.strptime(bts, '%Y-%m-%dT%H:%M:%S.%f')
        bts_offset = None
    cgroup_timestamps = set()
    #import epdb; epdb.st()

    '''
    cgrows = []
    for cfile,cdata in rd['cgdata'].items():

        if not cdata['rows']:
            continue

        ctype = cdata['type']
        if ctype == 'cpu':
            ctype = 'cgroup_cpu_used'
        elif ctype == 'pids':
            ctype = 'cgroup_pids_running'
        elif ctype == 'memory':
            ctype = 'cgroup_mem_used'
        tid = cdata['task_uuid']
        tname = cdata['task_name']

        tnumber = baseline.taskmap[tid]['task_number']

        for crow in cdata['rows']:
            row = copy.deepcopy(_row)
            row['task_uuid'] = tid
            row['task_name'] = tname
            row['task_number'] = tnumber
            row[ctype] = crow['value']

            # local time ...
            # 1568610146.120834 -> 2019-09-16T05:02:57.942911
            ts = crow['timestamp']
            ts = datetime.datetime.fromtimestamp(ts)

            #import epdb; epdb.st()

            # offset using baseline's tz
            #if bts_offset is None:
            #    bts_offset = bts.hour - ts.hour
            bts_offset = bts.hour - ts.hour

            try:
                ts = ts.replace(day=bts.day, hour=ts.hour + bts_offset)
            except Exception as e:
                print(e)
                import epdb; epdb.st()

            ts = ts.isoformat()
            row['time'] = ts
            #import epdb; epdb.st()

            #rows.append(row)
            cgrows.append(row)
            cgroup_timestamps.add(ts)
    rows += cgrows[:]
    '''
    # END CGROUPS

    # START TOP
    logger.debug('top')
    if rows:
        YMD = rows[-1]['time'].split('T')[0]
    else:
        YMD = resdir.split('.')[-2].split('T')[0]

    if bts is None and rows:
        bts = to_datetime(rows[0]['time'])
        baseline.playbook_start = to_iso(bts)
        baseline.playbook_stop = to_iso(to_datetime(rows[-1]['time']))
    
    bts_offset = None
    for trow in rd['top']:
        row = copy.deepcopy(_row)
        row['src'] = 'top'
        for k,v in trow.items():
            if k == 'ts':
                ts = YMD + 'T' + v + '.000000'
                ts = datetime.datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S.%f')
                if baseline.rows:
                    if bts_offset is None:
                        bts_offset = bts.hour - ts.hour
                    try:
                        toff = ts.hour + bts_offset
                        if toff >= 24:
                            toff = toff - 24
                        ts = ts.replace(hour=toff)
                    except ValueError as e:
                        print(e)
                        import epdb; epdb.st()
                row['time'] = ts.isoformat()
            else:
                row['top_' + k] = v
        rows.append(row)
    # END TOP

    '''
    # START VMSTAT
    logger.debug('vmstat')
    bts_offset = None
    for vrow in rd['vmstat']:
        row = copy.deepcopy(_row)
        row['src'] = 'vmstat'
        for k,v in vrow.items():
            if k == 'ts':
                ts = datetime.datetime.fromtimestamp(v)
                #if bts_offset is None:
                #    bts_offset = bts.hour - ts.hour
                bts_offset = bts.hour - ts.hour
                try:
                    ts = ts.replace(hour=ts.hour + bts_offset)
                except Exception as e:
                    print(e)
                    import epdb; epdb.st()
                ts = ts.isoformat()
                row['time'] = ts
                continue
            if not k.startswith('vmstat'):
                row['vmstat_' + k] = v
            else:
                row[k] = v
        rows.append(row)
    # END VMSTAT
    '''

    # ensure all timestamps have microseconds
    for idr,row in enumerate(rows):
        # 2019-10-03T03:17:28.998000
        if len(row['time']) < 26:
            if len(row['time']) == 19:
                rows[idr]['time'] += '.000000'
                continue
            import epdb; epdb.st()

    # fill in missing keys
    logger.debug('fill missing keys')
    allkeys = set()
    for row in rows:
        for key in row.keys():
            allkeys.add(key)
    for idr,row in enumerate(rows):
        for key in allkeys:
            if key not in row:
                rows[idr][key] = None

    # sort by time
    logger.debug('sort')
    rows = sorted(rows, key=lambda x: x['time'])

    # forward fill
    logger.debug('ffill')
    for ak in allkeys:
        if ak == 'time':
            continue
        if 'top' in ak:
            continue
        if ak == 'task_number':
            continue
        lv = None
        for idr,row in enumerate(rows):
            if lv is None and row[ak] is not None:
                lv = row[ak]
                continue
            if row[ak] is not None:
                lv = row[ak]
                continue
            if row[ak] is None and lv is not None:
                rows[idr][ak] = lv
                continue

    # reduce by identical timestamps
    logger.debug('reduce rows')
    timestamps = {}
    for row in rows:
        ts = row['time']
        if ts not in timestamps:
            timestamps[ts] = copy.deepcopy(row)
        else:
            for k,v in row.items():
                if v is not None and timestamps[ts][k] is None:
                    timestamps[ts][k] = v

    logger.debug('reassemble and resort rows')
    rows = list(timestamps.values())
    rows = sorted(rows, key=lambda x: x['time'])

    # validate order ...
    ltn = None
    for idr,row in enumerate(rows):
        if ltn is None and row['task_number']:
            ltn = row['task_number']
            continue
        if row['task_number'] and ltn and ltn > row['task_number']:
            import epdb; epdb.st()

    if baseline.timestamps:
        rows = [x for x in rows if x['time'] >= baseline.playbook_start and x['time'] <= baseline.playbook_stop]
    else:
        start = None
        stop = None
        #key = 'top_pids_playbook'
        key = 'netdev_tx_bytes'
        for x in rows:
            if x['src'] != 'top':
                continue
            if x[key] and x[key] > 0 and x['time']:
                start = x['time']
                break
        for x in rows[::-1]:
            if x['src'] != 'top':
                continue
            if x[key] and x[key] > 0 and x['time']:
                stop = x['time']
                break

        start_dt = to_datetime(start)
        stop_dt = to_datetime(stop)
        import epdb; epdb.st()

        rows = [x for x in rows if x['time'] >= start and x['time'] <= stop]
        #import epdb; epdb.st()

    return rows


def main():
    resdirs = glob.glob('jobresults/*/*')
    resdirs = sorted(resdirs)
    logger.info(resdirs)

    #rows = []
    for resdir in resdirs[::-1]:

        baseline_file = os.path.join(resdir, 'baseline.json')
        #if not os.path.isfile(baseline_file):
        #    logger.error('%s has no baseline.json' % resdir)
        #    continue
        #if os.path.isfile(baseline_file):
        #    continue

        #if not resdir.endswith('7668'):
        #    continue    

        #if '2.8.5' not in resdir:
        #    continue

        #fn = os.path.join('plots', '%s_plot.png' % os.path.basename(resdir))
        #if os.path.exists(fn):
        #    continue

        logger.info(resdir)
        rd = load_results_directory(resdir)
        _rows = results_to_rows(rd, resdir=resdir)
        logger.info('rows: %s' % len(_rows))
        if len(_rows) < 1:
            continue

        #logger.info(fn)
        try:

            df = pd.DataFrame.from_records(_rows, index='time')
            df.index = pd.to_datetime(df.index)
            df.sort_index(axis=1, inplace=True)
            #df.fillna(value=pd.np.nan, inplace=True)
            #df.dropna(inplace=True, how='all')

            # forward fill values
            cols = list(df.columns)
            cols = [x for x in cols if not 'task' in x]
            df.loc[:,cols] = df.loc[:,cols].ffill()

            # fill Nones with nan
            df.fillna(value=pd.np.nan, inplace=True)

            # drop columns with all nan
            df.dropna(axis=1, how='all', inplace=True)

            '''
            colnames = list(df.columns)
            toremove = [
                x for x in colnames if not x.startswith('host') and
                not x.startswith('task') and
                not x.startswith('fork') and
                not x.startswith('cgroup')
            ]
            df.drop(toremove, axis=1, inplace=True)
            #import epdb; epdb.st()
            '''

            ######################################
            # all-in-one plot
            ######################################
            '''
            fn = os.path.join('plots', '%s_plot.png' % os.path.basename(resdir))
            logger.info(fn)
            df1 = df.copy(deep=True)
            df1 = df1.sample(n=300)
            df1.sort_index(inplace=True)
            logger.info('shape: %s' % str(df1.shape))

            ax = plt.gca()
            logger.debug('.plot')
            splts = df1.plot(kind='bar', figsize=(24,100), subplots=True)
            #for splt in splts:
            #    plt.plot(splt)
            #splt.tofile(fn)
            logger.debug('tight_layout')
            plt.tight_layout()
            logger.debug('savefig')
            plt.savefig(fn)
            plt.clf()
            plt.cla()
            plt.close()
            '''

            ######################################
            # interesting bits
            ######################################
            title = '%s hosts %s forks %s tasks %s cpus %s cpuMHZ %s memGB' % \
                    (
                        _rows[0]['hosts'],
                        _rows[0]['forks'],
                        _rows[0]['tasks_count'],
                        rd['meta']['processors'],
                        rd['meta']['processor_mhz'],
                        (rd['meta']['meminfo_MemTotal'] / float((1024 * 1024))),
                    )
            fn2 = os.path.join('plots', '%s_plot_highlights.png' % os.path.basename(resdir))
            logger.info(fn2)
            df2 = df.copy(deep=True)
            #import epdb; epdb.st()
            if 'hosts_remaining' in df2.columns:
                df2['hosts_remaining_%'] = (df2['hosts_remaining'] / df2['hosts']) * 100
            if 'hosts_active' in df2.columns:
                df2['forks_active_%'] = (df2['hosts_active'] / df2['forks']) * 100
            df2['playbook_pids_fork_%'] = (df2['top_pids_playbook'] / (df2['forks'] + 1)) * 100
            if 'task_number' in df2.columns:
                df2['task_count_%'] = (df2['task_number'] / df2['tasks_count']) * 100
            df2['mem_used_%'] = (df2['top_kib_mem_used'] / df2['top_kib_mem_total']) * 100
            colnames = list(df2.columns)
            toremove = [
                x for x in colnames if 
                #not x.startswith('host') and
                #not x == 'hosts_remaining_%' and
                #not x.startswith('task') and
                #not x.startswith('fork') and
                #not x.startswith('forks_active_%') and
                not x.startswith('cgroup') and 
                #not ('mem' in x and 'top' in x and 'free' in x) and 
                not  x == 'mem_used_%' and 
                not ('cpu' in x and 'top' in x) and
                not 'playbook_pids_fork' in x and 
                not x == 'task_count_%'
                #not 'netdev' in x
            ]
            df2.drop(toremove, axis=1, inplace=True)
            ax = df2.plot(kind='line', figsize=(20,12), title=title, ylim=(0,400))
            #ax.annotate('ANNOTATION!', (1,1))
            #ax.annotate((1,1), 'ANNOTATION!')
            #ax.text(0,0, 'TEST TEST TEST')

            #f = plt.figure()
            #plt.legend(loc='center left', bbox_to_anchor=(1.0, 0.5))
            #plt.legend(loc='center left', bbox_to_anchor=(.5, 1.0))
            plt.legend(loc='center left', bbox_to_anchor=(1.0, .9))
            plt.subplots_adjust(right=0.8)

            plt.savefig(fn2)
            plt.clf()
            plt.cla()
            plt.close()
            #import epdb; epdb.st()

        except Exception as e:
            print(e)
            #import epdb; epdb.st()
            pass

        '''
        fn2 = os.path.join(
            'plots',
            'h%s_f%s_%s_plot.png' % (
                #str(rd['meta']['limit']),
                str(len(rd['baseline'].hostnames)),
                str(rd['meta']['forks']),
                os.path.basename(resdir)
            )
        )
        pid = subprocess.Popen(
            'cd plots; ln -s %s %s' % (os.path.basename(fn), os.path.basename(fn2)),
            shell=True,
        )
        (so, se) = pid.communicate()
        logger.debug(str(so) + str(se))
        #import epdb; epdb.st()
        '''


if __name__ == "__main__":
    main()
