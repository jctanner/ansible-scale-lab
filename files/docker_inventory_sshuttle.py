#!/usr/bin/python

# On the controller, run ...
#   iptables -F ; sshuttle -v -r root@<dockerhost> 172.17.0.0/16
# Inventory should point at the IPs of the containers [172.17.x.x] and not use the ports

import argparse
import json
import os
import subprocess
from pprint import pprint


DOCKER_USERNAME = "root"
DOCKER_PASSWORD = "vagrant"
CONTAINER_USERNAME = "root"
CONTAINER_PASSWORD = "root"

CONTAINER_COUNT = os.environ.get('CONTAINER_COUNT', -1)
CONTAINER_COUNT = int(CONTAINER_COUNT)


def run_command(cmd):
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True
    ) 
    (so,se) = p.communicate()
    return (p.returncode, so, se)


def get_docker_hosts():
    # '10.0.0.102\tdockerhost\n',
    with open('/etc/hosts', 'r') as f:
        flines = f.readlines()
    dockerhosts = [x.strip() for x in flines if 'dockerhost' in x]
    dockerhosts = [x.replace('\t', '\n') for x in dockerhosts]
    dockerhosts = [x.split()[1].strip() for x in dockerhosts]
    return dockerhosts


def get_containers_for_host(hostname):

    cachefile = '/tmp/docker_inventory_cache.txt'
    if not os.path.exists(cachefile):

        # get the internal IPs
        cmd = 'ssh -o StrictHostkeyChecking=no'
        cmd += ' %s@%s' % (DOCKER_USERNAME,hostname)

        dockercmd = \
            "docker ps -a | egrep -v ^CONTAINER | awk '{print \$1}' | xargs -I {} docker inspect {} | jq -M '.[]| .Id, .NetworkSettings.IPAddress'"
        cmd += ' "' + dockercmd + '"'
        (rc, so, se) = run_command(cmd)
        with open(cachefile, 'w') as f:
            f.write(so)

        lines = so.split('\n')

    else:
        with open(cachefile, 'r') as f:
            lines = f.readlines()

    containers = {}

    total = 0
    thisid = None
    for line in lines:
        if not line.strip():
            continue
        line = line.replace('"', '').strip()
        if not line.startswith('1'):
            thisid = line
            continue

        if thisid:
            if CONTAINER_COUNT >= 0 and total >= CONTAINER_COUNT:
                continue
            if not line.startswith('172.'):
                continue
            containers[thisid] = {
                'id': thisid,
                'name': 'node-%s' % total,
                'ansible_host': line,
                'ansible_user': CONTAINER_USERNAME,
                'ansible_ssh_pass': CONTAINER_PASSWORD,
                'ansible_python_interpreter': '/usr/bin/python3',
                'ansible_ssh_common_args': '-o StrictHostKeyChecking=no'
            }
            total += 1

    return containers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--host', default=None)

    docker_hosts = get_docker_hosts()

    containers = {}
    for dh in docker_hosts:
        containers.update(get_containers_for_host(dh))

    INV = {'_meta': {'hostvars': {}}}
    INV['all'] = {'hosts': []}

    for k,v in containers.items():
        INV['_meta']['hostvars'][v['name']] = v.copy()
        INV['all']['hosts'].append(v['name'])

    print(json.dumps(INV, indent=2))


if __name__ == "__main__":
    main()
