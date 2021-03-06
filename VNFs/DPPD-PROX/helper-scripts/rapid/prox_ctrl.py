##
## Copyright (c) 2010-2020 Intel Corporation
##
## Licensed under the Apache License, Version 2.0 (the "License");
## you may not use this file except in compliance with the License.
## You may obtain a copy of the License at
##
##     http://www.apache.org/licenses/LICENSE-2.0
##
## Unless required by applicable law or agreed to in writing, software
## distributed under the License is distributed on an "AS IS" BASIS,
## WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
## See the License for the specific language governing permissions and
## limitations under the License.
##

from __future__ import print_function
from __future__ import division

from builtins import map
from builtins import range
from past.utils import old_div
from builtins import object
import os
import time
import subprocess
import socket
from rapid_log import RapidLog 

class prox_ctrl(object):
    def __init__(self, ip, key=None, user=None):
        self._ip   = ip
        self._key  = key
        self._user = user
        self._children = []
        self._proxsock = []

    def __del__(self):
        self.close()

    def ip(self):
        return self._ip

    def test_connect(self):
        """Simply try to run 'true' over ssh on remote system.
        On failure, raise RuntimeWarning exception when possibly worth
        retrying, and raise RuntimeError exception otherwise.
        """
        return self.run_cmd('test -e /opt/rapid/system_ready_for_rapid', True)

    def connect(self):
        attempts = 1
        RapidLog.debug("Trying to connect to instance which was just launched \
                on %s, attempt: %d" % (self._ip, attempts))
        while True:
            try:
                self.test_connect()
                break
            except RuntimeWarning as ex:
                attempts += 1
                if attempts > 20:
                    RapidLog.exception("Failed to connect to instance after %d\
                            attempts:\n%s" % (attempts, ex))
                    raise Exception("Failed to connect to instance after %d \
                            attempts:\n%s" % (attempts, ex))
                time.sleep(2)
                RapidLog.debug("Trying to connect to instance which was just \
                        launched on %s, attempt: %d" % (self._ip, attempts))
        RapidLog.debug("Connected to instance on %s" % self._ip)

    def connect_socket(self):
        attempts = 1
        RapidLog.debug("Trying to connect to PROX (just launched) on %s, \
                attempt: %d" % (self._ip, attempts))
        sock = None
        while True:
            sock = self.prox_sock()
            if sock is not None:
                break
            attempts += 1
            if attempts > 20:
                RapidLog.exception("Failed to connect to PROX on %s after %d \
                        attempts" % (self._ip, attempts))
                raise Exception("Failed to connect to PROX on %s after %d \
                        attempts" % (self._ip, attempts))
            time.sleep(2)
            RapidLog.debug("Trying to connect to PROX (just launched) on %s, \
                    attempt: %d" % (self._ip, attempts))
        RapidLog.info("Connected to PROX on %s" % self._ip)
        return sock

    def close(self):
        """Must be called before program termination."""
        for sock in self._proxsock:
            sock.quit()
        children = len(self._children)
        if children == 0:
            return
        if children > 1:
            print('Waiting for %d child processes to complete ...' % children)
        for child in self._children:
            ret = os.waitpid(child[0], os.WNOHANG)
            if ret[0] == 0:
                print("Waiting for child process '%s' to complete ..." 
                        % child[1])
                ret = os.waitpid(child[0], 0)
            rc = ret[1]
            if os.WIFEXITED(rc):
                if os.WEXITSTATUS(rc) == 0:
                    print("Child process '%s' completed successfully" 
                            % child[1])
                else:
                    print("Child process '%s' returned exit status %d" % (
                            child[1], os.WEXITSTATUS(rc)))
            elif os.WIFSIGNALED(rc):
                print("Child process '%s' exited on signal %d" % (
                        child[1], os.WTERMSIG(rc)))
            else:
                print("Wait status for child process '%s' is 0x%04x" % (
                        child[1], rc))

    def run_cmd(self, command, _connect=False):
        """Execute command over ssh on remote system.
        Wait for remote command completion.
        Return command output (combined stdout and stderr).
        _connect argument is reserved for connect() method.
        """
        cmd = self._build_ssh(command)
        try:
            return subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as ex:
            #if _connect and ex.returncode == 255:
            if _connect:
                raise RuntimeWarning(ex.output.strip())
            raise RuntimeError('ssh returned exit status %d:\n%s'
                    % (ex.returncode, ex.output.strip()))

    def fork_cmd(self, command, name=None):
        """Execute command over ssh on remote system, in a child process.
        Do not wait for remote command completion.
        Return child process id.
        """
        if name is None:
            name = command
        cmd = self._build_ssh(command)
        pid = os.fork()
        if (pid != 0):
            # In the parent process
            self._children.append((pid, name))
            return pid
        # In the child process: use os._exit to terminate
        try:
            # Actually ignore output on success, but capture stderr on failure
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as ex:
            raise RuntimeError("Child process '%s' failed:\n"
                    'ssh returned exit status %d:\n%s'
                    % (name, ex.returncode, ex.output.strip()))
        os._exit(0)

    def prox_sock(self, port=8474):
        """Connect to the PROX instance on remote system.
        Return a prox_sock object on success, None on failure.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect((self._ip, port))
            prox = prox_sock(sock)
            self._proxsock.append(prox)
            return prox
        except:
            return None

    def scp_put(self, src, dst):
        """Copy src file from local system to dst on remote system."""
        cmd = [ 'scp',
                '-B',
                '-oStrictHostKeyChecking=no',
                '-oUserKnownHostsFile=/dev/null',
                '-oLogLevel=ERROR' ]
        if self._key is not None:
            cmd.extend(['-i', self._key])
        cmd.append(src)
        remote = ''
        if self._user is not None:
            remote += self._user + '@'
        remote += self._ip + ':' + dst
        cmd.append(remote)
        try:
            # Actually ignore output on success, but capture stderr on failure
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as ex:
            raise RuntimeError('scp returned exit status %d:\n%s'
                    % (ex.returncode, ex.output.strip()))

    def _build_ssh(self, command):
        cmd = [ 'ssh',
                '-oBatchMode=yes',
                '-oStrictHostKeyChecking=no',
                '-oUserKnownHostsFile=/dev/null',
                '-oLogLevel=ERROR' ]
        if self._key is not None:
            cmd.extend(['-i', self._key])
        remote = ''
        if self._user is not None:
            remote += self._user + '@'
        remote += self._ip
        cmd.append(remote)
        cmd.append(command)
        return cmd

class prox_sock(object):
    def __init__(self, sock):
        self._sock = sock
        self._rcvd = b''

    def __del__(self):
        self.quit()

    def quit(self):
        if self._sock is not None:
            self._send('quit')
            self._sock.close()
            self._sock = None

    def start(self, cores):
        self._send('start %s' % ','.join(map(str, cores)))

    def stop(self, cores):
        self._send('stop %s' % ','.join(map(str, cores)))

    def speed(self, speed, cores, tasks=[0]):
        for core in cores:
            for task in tasks:
                self._send('speed %s %s %s' % (core, task, speed))

    def reset_stats(self):
        self._send('reset stats')

    def lat_stats(self, cores, tasks=[0]):
        min_lat = 999999999
        max_lat = avg_lat = 0
        number_tasks_returning_stats = 0
        buckets = [0] * 128
        self._send('lat all stats %s %s' % (','.join(map(str, cores)),
            ','.join(map(str, tasks))))
        for core in cores:
            for task in tasks:
                stats = self._recv().split(',')
            if 'is not measuring' in stats[0]:
                continue
            if stats[0].startswith('error'):
                RapidLog.critical("lat stats error: unexpected reply from PROX\
                        (potential incompatibility between scripts and PROX)")
                raise Exception("lat stats error")
            number_tasks_returning_stats += 1
            min_lat = min(int(stats[0]),min_lat)
            max_lat = max(int(stats[1]),max_lat)
            avg_lat += int(stats[2])
            #min_since begin = int(stats[3])
            #max_since_begin = int(stats[4])
            tsc = int(stats[5]) # Taking the last tsc as the timestamp since
                                # PROX will return the same tsc for each 
                                # core/task combination 
            hz = int(stats[6])
            #coreid = int(stats[7])
            #taskid = int(stats[8])
            stats = self._recv().split(':')
            if stats[0].startswith('error'):
                RapidLog.critical("lat stats error: unexpected lat bucket \
                        reply (potential incompatibility between scripts \
                        and PROX)")
                raise Exception("lat bucket reply error")
            buckets[0] = int(stats[1])
            for i in range(1, 128):
                stats = self._recv().split(':')
                buckets[i] = int(stats[1])
        avg_lat = old_div(avg_lat,number_tasks_returning_stats)
        self._send('stats latency(0).used')
        used = float(self._recv())
        self._send('stats latency(0).total')
        total = float(self._recv())
        return (min_lat, max_lat, avg_lat, (old_div(used,total)), tsc, hz,
                buckets)

    def irq_stats(self, core, bucket, task=0):
        self._send('stats task.core(%s).task(%s).irq(%s)' % 
                (core, task, bucket))
        stats = self._recv().split(',')
        return int(stats[0])

    def show_irq_buckets(self, core, task=0):
        rx = tx = drop = tsc = hz = 0
        self._send('show irq buckets %s %s' % (core,task))
        buckets = self._recv().split(';')
        buckets = buckets[:-1]
        return buckets

    def core_stats(self, cores, tasks=[0]):
        rx = tx = drop = tsc = hz = rx_non_dp = tx_non_dp = tx_fail = 0
        self._send('dp core stats %s %s' % (','.join(map(str, cores)), 
            ','.join(map(str, tasks))))
        for core in cores:
            for task in tasks:
                stats = self._recv().split(',')
                if stats[0].startswith('error'):  
                    if stats[0].startswith('error: invalid syntax'):
                        RapidLog.critical("dp core stats error: unexpected \
                                invalid syntax (potential incompatibility \
                                between scripts and PROX)")
                        raise Exception("dp core stats error")
                    continue
                rx += int(stats[0])
                tx += int(stats[1])
                rx_non_dp += int(stats[2])
                tx_non_dp += int(stats[3])
                drop += int(stats[4])
                tx_fail += int(stats[5])
                tsc = int(stats[6])
                hz = int(stats[7])
        return rx, rx_non_dp, tx, tx_non_dp, drop, tx_fail, tsc, hz

    def multi_port_stats(self, ports=[0]):
        rx = tx = port_id = tsc = no_mbufs = errors = 0
        self._send('multi port stats %s' % (','.join(map(str, ports))))
        result = self._recv().split(';')
        if result[0].startswith('error'):  
            RapidLog.critical("multi port stats error: unexpected invalid \
                    syntax (potential incompatibility between scripts and \
                    PROX)")
            raise Exception("multi port stats error")
        for statistics in result:
            stats = statistics.split(',')
            port_id = int(stats[0])
            rx += int(stats[1])
            tx += int(stats[2])
            no_mbufs += int(stats[3])
            errors += int(stats[4])
            tsc = int(stats[5])
        return rx, tx, no_mbufs, errors, tsc

    def set_random(self, cores, task, offset, mask, length):
        self._send('set random %s %s %s %s %s' % (','.join(map(str, cores)), 
            task, offset, mask, length))

    def set_size(self, cores, task, pkt_size):
        self._send('pkt_size %s %s %s' % (','.join(map(str, cores)), task, 
            pkt_size))

    def set_imix(self, cores, task, imix):
        self._send('imix %s %s %s' % (','.join(map(str, cores)), task, 
            ','.join(map(str,imix))))

    def set_value(self, cores, task, offset, value, length):
        self._send('set value %s %s %s %s %s' % (','.join(map(str, cores)), 
            task, offset, value, length))

    def _send(self, cmd):
        """Append LF and send command to the PROX instance."""
        if self._sock is None:
            raise RuntimeError("PROX socket closed, cannot send '%s'" % cmd)
        self._sock.sendall(cmd.encode() + b'\n')

    def _recv(self):
        """Receive response from PROX instance, return it with LF removed."""
        if self._sock is None:
            raise RuntimeError("PROX socket closed, cannot receive anymore")
        pos = self._rcvd.find(b'\n')
        while pos == -1:
            self._rcvd += self._sock.recv(256)
            pos = self._rcvd.find(b'\n')
        rsp = self._rcvd[:pos]
        self._rcvd = self._rcvd[pos+1:]
        return rsp.decode()
