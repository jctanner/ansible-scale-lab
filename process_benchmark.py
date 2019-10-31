#!/usr/bin/env python

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


import copy
import glob
import json
import os
import shutil
import sys
import time
from collections import OrderedDict
from logzero import logger
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.style
import matplotlib as mpl
#mpl.style.use('ggplot')


def load_perf(fn, meta=None):

    obs = []
    with open(fn, 'r') as f:
        for line in f.readlines():
            if not line.strip():
                continue
            if line.startswith('#'):
                continue        

            cols = line.strip().split(',')
            obs.append(cols)

    for idx,x in enumerate(obs):
        ts = float(x[0])
        ts += meta['start']
        obs[idx][0] = ts

    nobs = OrderedDict()
    for idx,x in enumerate(obs):
        ts = x[0]
        if ts not in nobs:
            nobs[ts] = {'time': ts}
        metric = 'zz_' + x[3]
        if not metric:
            continue
        #if not metric.startswith('task-clock'):
        #    continue
        for idc,col in enumerate(x):
            if idc == 0:
                continue
            if col == 'zz_' + metric:
                continue
            if not col.replace('.', '').isdigit():
                continue
            key = metric + '_' + str(idc)
            nobs[ts][key] = float(col)

    # trim out constant stats
    allkeys = set()
    for k,v in nobs.items():
        for sk in v.keys():
            allkeys.add(sk)
    topop = set()
    for ak in allkeys:
        values = [x[ak] for x in nobs.values()]
        if len(sorted(set(values))) == 1:
            topop.add(ak)
    for tk in topop:
        for k,v in nobs.items():
            nobs[k].pop(tk, None)

    #import epdb; epdb.st()
    return nobs


def process_files(files):

    logger.info('reading files')
    for fn in files:
        if 'host_queue_starts' in fn:
            with open(fn, 'r') as f:
                host_queue_starts = json.loads(f.read())
        elif 'concurrent_hosts' in fn:
            with open(fn, 'r') as f:
                concurrent_hosts = json.loads(f.read())
        elif fn.endswith('ps.log'):
            with open(fn, 'r') as f:
                psraw = f.read()
        elif 'meta' in fn:
            with open(fn, 'r') as f:
                meta = json.loads(f.read())
        elif os.path.basename(fn) == 'perf.csv':
            perfdata = load_perf(fn, meta=meta)

    logger.info('indexing tasks')
    # index all the tasks
    tasks = OrderedDict()
    for hqs in host_queue_starts:
        tuuid = hqs['task_uuid']
        hn = hqs['host']
        tn = hqs['task_name']
        ts = hqs['time']

        if tuuid not in tasks:
            tasks[tuuid] = {}

        tasknum = list(tasks.keys()).index(tuuid)

        tasks[tuuid][hn] = {
            'host': hn,
            'lag': ts - meta['start'],
            'start': ts,
            'stop': meta['stop'],
            'duration': meta['stop'] - ts
        }

        for ch in concurrent_hosts:
            if ch['time'] < ts:
                continue
            if ch['time'] > ts and hn not in ch['active']:
                tasks[tuuid][hn]['stop'] = ch['time']
                tasks[tuuid][hn]['duration'] = ch['time'] - tasks[tuuid][hn]['start']
                break

    logger.info('find all hosts and set obs timestamps')
    # find all hosts and set observation timestamps
    hosts = set()
    obs = OrderedDict()
    for ch in concurrent_hosts:
        for hn in ch['active']:
            hosts.add(hn)
    for ch in concurrent_hosts:
        obs[ch['time']] = {
            'time': ch['time'],
            'task_uuid': ch['task_uuid'],
            'task_name': ch['task_name'],
            'task_number': None,
            'hosts_active': ch['active'],
            'hosts_remaining': list(hosts)[:]
        }

    logger.info('calculate hosts remaining')
    # calculate remaining
    obs_timestamps = sorted(obs.keys())
    this_uuid = None
    remaining = None
    for obtsid,obs_timestamp in enumerate(obs_timestamps):
        observation = obs[obs_timestamp]
        if this_uuid == None or this_uuid != observation['task_uuid']:
            print('reset remaining for new task: %s' % observation['task_name'])
            this_uuid = observation['task_uuid']
            remaining = list(hosts)[:]
        for hn in observation['hosts_active']:
            if hn in remaining:
                remaining.remove(hn)
        obs[obs_timestamp]['hosts_remaining'] = remaining[:]

    logger.info('compute sums')
    tasks_total = None
    for kts,kd in obs.items():
        obs[kts]['forks'] = meta['forks']
        obs[kts]['hosts_active'] = len(kd['hosts_active'])
        obs[kts]['hosts_remaining'] = len(kd['hosts_remaining'])
        if kd['task_uuid'] not in tasks:
            tasks[kd['task_uuid']] = {}
        try:
            tn = list(tasks.keys()).index(kd['task_uuid']) + 1
        except ValueError as e:
            logger.error(e)
            import epdb; epdb.st()
        obs[kts]['task_number'] = tn
        if tasks_total is None or tn > tasks_total:
            tasks_total = tn

    #  PID  PPID  PGID   SID %CPU %MEM CMD
    logger.info('process ps log')
    _obs = None
    for line in psraw.split('\n'):
        line = line.strip()
        if not line:
            continue
        if line.startswith('#'):
            if _obs is not None:
                ts = _obs['time']
                if ts not in obs:
                    obs[ts] = copy.deepcopy(_obs)
                else:
                    obs[ts].update(_obs)
            _obs = {
                'time': float(line.replace('#', '').strip()),
                'playbook_pids': 0,
                'playbook_cpu': 0.0,
                'playbook_mem': 0.0,
                'cpu': 0.0,
                'mem': 0.0,
            }
            continue
        if not line[0].isdigit():
            continue
        cols = line.split(None, 6)
        if len(cols) < 5:
            print(cols)
            import epdb; epdb.st()
        if cols[0] == 'PID':
            continue
        _obs['cpu'] += float(cols[4])
        _obs['mem'] += float(cols[5])

        if 'ansible-playbook' in line:
            _obs['playbook_pids'] += 1
            _obs['playbook_cpu'] += float(cols[4])
            _obs['playbook_mem'] += float(cols[5])

    if _obs:
        ts = _obs['time']
        if ts not in obs:
            obs[ts] = copy.deepcopy(_obs)
        else:
            obs[ts].update(_obs)

    # merge in the perfdata
    for k,v in perfdata.items():
        if k not in obs:
            obs[k] = copy.deepcopy(v)
        else:
            import epdb; epdb.st()

    logger.info('filling in missing keys')
    keys = set()
    for k,v in obs.items():
        for key in v.keys():
            keys.add(key)
    for k,v in obs.items():
        for key in keys:
            if key not in v:
                obs[k][key] = None

    logger.info('sorting observations')
    tuples = list(obs.items())
    tuples = sorted(tuples, key=lambda x: x[0])
    obs = OrderedDict(tuples)

    meta['tasks_total'] = tasks_total
    meta['hosts_total'] = len(list(hosts))

    return meta,list(obs.values())


def graph_observations(meta, obs):

    logger.info('creating plot ...')

    title = '%s hosts, %s forks' % (meta['hosts_total'], meta['forks'])
    logger.info('create dataframe')
    df = pd.DataFrame.from_records(list(obs), index='time')
    logger.info('sort on index')
    df.sort_index(axis=1, inplace=True)

    df.fillna(method='ffill', inplace=True)

    '''
    df.drop(['forks'], axis=1, inplace=True)
    df['task_number'] = (df['task_number'] / meta['tasks_total']) * 100.0
    df['forks_active'] = (df['hosts_active'] / meta['forks']) * 100.0
    df['hosts_active'] = (df['hosts_active'] / meta['hosts_total']) * 100.0
    df['hosts_remaining'] = (df['hosts_remaining'] / meta['hosts_total']) * 100.0

    df.rename(
        inplace=True,
        columns={
            "task_number": "task_number_%",
            "forks_active": "forks_active_%",
            "hosts_active": "hosts_active_%",
            "hosts_remaining": "hosts_remaining_%"
        }
    )

    ax = df.plot(kind='line', figsize=(20,12), title=title)
    plt.savefig('res.png')
    '''

    logger.info('plt.gcq')
    ax = plt.gca()
    #ax.xaxis.set_major_locator(plt.MaxNLocator(25))
    logger.info('.plot')
    splts = df.plot(kind='line', figsize=(30,24), title=title, subplots=True, grid=False)
    #import epdb; epdb.st()
    logger.info('tight layout')
    plt.tight_layout()
    logger.info('savefig')
    plt.savefig('res.png')
    plt.clf()
    plt.cla()
    plt.close()


def main():

    bdir = sys.argv[1]

    ofile = os.path.join(bdir, 'observations.json')
    mfile = os.path.join(bdir, 'meta.json')

    #if os.path.exists(ofile) and os.path.exists(mfile):
    if False:

        logger.info('load %s' % ofile)
        with open(ofile, 'r') as f:
            obs = json.loads(f.read())
        logger.info('load %s' % mfile)
        with open(mfile, 'r') as f:
            meta = json.loads(f.read())
    else:
        files = glob.glob('%s/*.json' % bdir) + ['%s/ps.log' % bdir, '%s/perf.csv' % bdir] 
        meta,obs = process_files(files)

        logger.info('writing observations.json')
        with open(ofile, 'w') as f:
            f.write(json.dumps(obs))
        logger.info('writing meta.json')
        with open(mfile, 'w') as f:
            f.write(json.dumps(meta))

    graph_observations(meta, obs)


if __name__ == "__main__":
    main()
