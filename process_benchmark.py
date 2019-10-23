#!/usr/bin/env python

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


import glob
import json
import os
import shutil
import time
from collections import OrderedDict
from logzero import logger
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.style
import matplotlib as mpl
mpl.style.use('ggplot')


def process_files(files):

    logger.info('reading files')
    for fn in files:
        if 'host_queue_starts' in fn:
            with open(fn, 'r') as f:
                host_queue_starts = json.loads(f.read())
        elif 'concurrent_hosts' in fn:
            with open(fn, 'r') as f:
                concurrent_hosts = json.loads(f.read())
        elif 'meta' in fn:
            with open(fn, 'r') as f:
                meta = json.loads(f.read())

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
        tn = list(tasks.keys()).index(kd['task_uuid']) + 1
        obs[kts]['task_number'] = tn
        if tasks_total is None or tn > tasks_total:
            tasks_total = tn

    meta['tasks_total'] = tasks_total
    meta['hosts_total'] = len(list(hosts))

    return meta,list(obs.values())


def graph_observations(meta, obs):

    logger.info('creating plot ...')

    title = '%s hosts, %s forks' % (meta['hosts_total'], meta['forks'])
    df = pd.DataFrame.from_records(list(obs), index='time')
    df.sort_index(axis=1, inplace=True)

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

    ax = plt.gca()
    splts = df.plot(kind='line', figsize=(20,12), title=title, subplots=True)
    plt.tight_layout()
    plt.savefig('res.png')
    plt.clf()
    plt.cla()
    plt.close()


def main():

    ofile = 'benchmark_results/observations.json'
    mfile = 'benchmark_results/meta.json'

    if os.path.exists(ofile) and os.path.exists(mfile):

        logger.info('load %s' % ofile)
        with open(ofile, 'r') as f:
            obs = json.loads(f.read())
        logger.info('load %s' % mfile)
        with open(mfile, 'r') as f:
            meta = json.loads(f.read())

    else:
        files = glob.glob('benchmark_results/*.json') 
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
