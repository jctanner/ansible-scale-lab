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

    '''
    logger.info('calculate hosts remaining')
    # calculate remaining
    obskeys = sorted(obs.keys())
    for idkts,kts in enumerate(obskeys):
        kd = obs[kts]
        obsix = obskeys.index(kts)

        for idhqs,hqs in enumerate(host_queue_starts):

            if hqs['task_uuid'] == kd['task_uuid']:
                if hqs['time'] >= kd['time']:

                    # remove the hosts from all future timestamps
                    for key in obskeys[obsix:]:
                        #if key < hqs['time']:
                        #    continue
                        if obs[key]['task_uuid'] != kd['task_uuid']:
                            continue
                        if key < hqs['time']:
                            continue
                        print('%s %s %s %s' % (idkts, kts, key, idhqs))
                        for hn in kd['hosts_active']:
                            if hn in obs[key]['hosts_remaining']:
                                obs[key]['hosts_remaining'].remove(hn)
    '''

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
    for kts,kd in obs.items():
        obs[kts]['forks'] = meta['forks']
        obs[kts]['hosts_active'] = len(kd['hosts_active'])
        obs[kts]['hosts_remaining'] = len(kd['hosts_remaining'])
        tn = list(tasks.keys()).index(kd['task_uuid'])
        obs[kts]['task_number'] = tn

    return obs


def main():
    files = glob.glob('benchmark_results/*.json') 
    obs = process_files(files)

    logger.info('writing observations.json')
    with open('observations.json', 'w') as f:
        f.write(json.dumps(list(obs.values())))


if __name__ == "__main__":
    main()
