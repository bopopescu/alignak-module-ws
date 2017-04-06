#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2015-2016: Alignak team, see AUTHORS.txt file for contributors
#
# This file is part of Alignak.
#
# Alignak is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Alignak is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with Alignak.  If not, see <http://www.gnu.org/licenses/>.
#
"""
Test the module
"""

import os
import re
import time
import json

import shlex
import subprocess

import logging

import requests

from alignak_test import AlignakTest, time_hacker
from alignak.modulesmanager import ModulesManager
from alignak.objects.module import Module
from alignak.basemodule import BaseModule

# Set environment variable to ask code Coverage collection
os.environ['COVERAGE_PROCESS_START'] = '.coveragerc'

import alignak_module_ws

# # Activate debug logs for the alignak backend client library
# logging.getLogger("alignak_backend_client.client").setLevel(logging.DEBUG)
#
# # Activate debug logs for the module
# logging.getLogger("alignak.module.web-services").setLevel(logging.DEBUG)


class TestModuleWs(AlignakTest):
    """This class contains the tests for the module"""

    @classmethod
    def setUpClass(cls):

        # Set test mode for alignak backend
        os.environ['TEST_ALIGNAK_BACKEND'] = '1'
        os.environ['ALIGNAK_BACKEND_MONGO_DBNAME'] = 'alignak-module-ws-backend-test'

        # Delete used mongo DBs
        print ("Deleting Alignak backend DB...")
        exit_code = subprocess.call(
            shlex.split(
                'mongo %s --eval "db.dropDatabase()"' % os.environ['ALIGNAK_BACKEND_MONGO_DBNAME'])
        )
        assert exit_code == 0

        fnull = open(os.devnull, 'w')
        cls.p = subprocess.Popen(['uwsgi', '--plugin', 'python', '-w', 'alignakbackend:app',
                                  '--socket', '0.0.0.0:5000',
                                  '--protocol=http', '--enable-threads', '--pidfile',
                                  '/tmp/uwsgi.pid'],
                                 stdout=fnull, stderr=fnull)
        time.sleep(3)

        endpoint = 'http://127.0.0.1:5000'

        test_dir = os.path.dirname(os.path.realpath(__file__))
        print("Current test directory: %s" % test_dir)

        print("Feeding Alignak backend... %s" % test_dir)
        exit_code = subprocess.call(
            shlex.split('alignak-backend-import --delete %s/cfg/cfg_default.cfg' % test_dir),
            stdout=fnull, stderr=fnull
        )
        assert exit_code == 0
        print("Fed")

        # Backend authentication
        headers = {'Content-Type': 'application/json'}
        params = {'username': 'admin', 'password': 'admin'}
        # Get admin user token (force regenerate)
        response = requests.post(endpoint + '/login', json=params, headers=headers)
        resp = response.json()
        cls.token = resp['token']
        cls.auth = requests.auth.HTTPBasicAuth(cls.token, '')

        # Get admin user
        response = requests.get(endpoint + '/user', auth=cls.auth)
        resp = response.json()
        cls.user_admin = resp['_items'][0]

        # Get realms
        response = requests.get(endpoint + '/realm', auth=cls.auth)
        resp = response.json()
        cls.realmAll_id = resp['_items'][0]['_id']

        # Add a user
        data = {'name': 'test', 'password': 'test', 'back_role_super_admin': False,
                'host_notification_period': cls.user_admin['host_notification_period'],
                'service_notification_period': cls.user_admin['service_notification_period'],
                '_realm': cls.realmAll_id}
        response = requests.post(endpoint + '/user', json=data, headers=headers,
                                 auth=cls.auth)
        resp = response.json()
        print("Created a new user: %s" % resp)

    @classmethod
    def tearDownClass(cls):
        cls.p.kill()

    def test_module_zzz_host(self):
        """Test the module /host API
        :return:
        """
        self.print_header()
        # Obliged to call to get a self.logger...
        self.setup_with_file('cfg/cfg_default.cfg')
        self.assertTrue(self.conf_is_correct)

        # -----
        # Provide parameters - logger configuration file (exists)
        # -----
        # Clear logs
        self.clear_logs()

        # Create an Alignak module
        mod = Module({
            'module_alias': 'web-services',
            'module_types': 'web-services',
            'python_name': 'alignak_module_ws',
            # Alignak backend
            'alignak_backend': 'http://127.0.0.1:5000',
            'username': 'admin',
            'password': 'admin',
            # Do not set a timestamp in the built external commands
            'set_timestamp': '0',
            # Set Arbiter address as empty to not poll the Arbiter else the test will fail!
            'alignak_host': '',
            'alignak_port': 7770,
        })

        # Create the modules manager for a daemon type
        self.modulemanager = ModulesManager('receiver', None)

        # Load an initialize the modules:
        #  - load python module
        #  - get module properties and instances
        self.modulemanager.load_and_init([mod])

        my_module = self.modulemanager.instances[0]

        # Clear logs
        self.clear_logs()

        # Start external modules
        self.modulemanager.start_external_instances()

        # Starting external module logs
        self.assert_log_match("Trying to initialize module: web-services", 0)
        self.assert_log_match("Starting external module web-services", 1)
        self.assert_log_match("Starting external process for module web-services", 2)
        self.assert_log_match("web-services is now started", 3)

        # Check alive
        self.assertIsNotNone(my_module.process)
        self.assertTrue(my_module.process.is_alive())

        time.sleep(1)

        # Do not allow GET request on /host - not authorized
        response = requests.get('http://127.0.0.1:8888/host')
        self.assertEqual(response.status_code, 401)

        session = requests.Session()

        # Login with username/password (real backend login)
        headers = {'Content-Type': 'application/json'}
        params = {'username': 'admin', 'password': 'admin'}
        response = session.post('http://127.0.0.1:8888/login', json=params, headers=headers)
        assert response.status_code == 200
        resp = response.json()

        # Allowed GET request on /host - forbidden to GET
        response = session.get('http://127.0.0.1:8888/host')
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'ERR')
        self.assertEqual(result['_error'], 'You must only PATCH on this endpoint.')

        # You must have parameters when POSTing on /host
        headers = {'Content-Type': 'application/json'}
        data = {}
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'ERR')
        self.assertEqual(result['_error'], 'You must send parameters on this endpoint.')

        # When host does not exist...
        data = {
            "fake": ""
        }
        response = session.patch('http://127.0.0.1:8888/host/test_host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {u'_status': u'ERR',
                                  u'_result': [u'test_host is alive :)'],
                                  u'_feedback': {},
                                  u'_issues': [u"Requested host 'test_host' does not exist"]})

        # Host name may be the last part of the URI
        data = {
            "fake": ""
        }
        response = session.patch('http://127.0.0.1:8888/host/test_host_0', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)'],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': True,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Host name may be in the POSTed data
        data = {
            "name": "test_host_0",
        }
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)'],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': True,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Host name in the POSTed data takes precedence over URI
        data = {
            "name": "test_host_0",
        }
        response = session.patch('http://127.0.0.1:8888/host/other_host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)'],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': True,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Host name must be somewhere !
        headers = {'Content-Type': 'application/json'}
        data = {
            "fake": "test_host",
        }
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'ERR')
        self.assertEqual(result['_issues'], [u'Missing targeted element.'])

        # Update host livestate (heartbeat / host is alive): empty livestate
        headers = {'Content-Type': 'application/json'}
        data = {
            "livestate": "",
            "name": "test_host_0",
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)'],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': True,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Update host livestate (heartbeat / host is alive): missing state in the livestate
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "livestate": {
                "output": "Output...",
                "long_output": "Long output...",
                "perf_data": "'counter'=1",
            }
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {u'_status': u'ERR',
                                  u'_result': [u'test_host_0 is alive :)',
                                               u"Host 'test_host_0' unchanged."],
                                  u'_feedback': {},
                                  u'_issues': [u'Missing state in the livestate.']})

        # Update host livestate (heartbeat / host is alive): livestate must have an accepted state
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "livestate": {
                "state": "",
                "output": "Output...",
                "long_output": "Long output...",
                "perf_data": "'counter'=1",
            }
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {u'_status': u'ERR',
                                  u'_result': [u'test_host_0 is alive :)',
                                               u"Host 'test_host_0' unchanged."],
                                  u'_feedback': {},
                                  u'_issues': [u"Host state must be UP, DOWN or UNREACHABLE, "
                                               u"and not ''."]})

        # Update host livestate (heartbeat / host is alive): livestate
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "livestate": {
                "state": "UP",
                "output": "Output...",
                "long_output": "Long output...",
                "perf_data": "'counter'=1",
            }
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)',
                         u"PROCESS_HOST_CHECK_RESULT;test_host_0;0;"
                         u"Output...|'counter'=1\nLong output...",
                         u"Host 'test_host_0' unchanged."],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': True,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Update host livestate (heartbeat / host is alive): livestate
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "livestate": {
                "state": "unreachable",
                "output": "Output...",
                "long_output": "Long output...",
                "perf_data": "'counter'=1",
            }
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)',
                         u"PROCESS_HOST_CHECK_RESULT;test_host_0;2;"
                         u"Output...|'counter'=1\nLong output...",
                         u"Host 'test_host_0' unchanged."],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': True,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Update host services livestate
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "livestate": {
                "state": "up",
                "output": "Output...",
                "long_output": "Long output...",
                "perf_data": "'counter'=1"
            },
            "services": {
                "test_service": {
                    "name": "test_ok_0",
                    "livestate": {
                        "state": "ok",
                        "output": "Output...",
                        "long_output": "Long output...",
                        "perf_data": "'counter'=1"
                    }
                },
                "test_service2": {
                    "name": "test_ok_1",
                    "livestate": {
                        "state": "warning",
                        "output": "Output...",
                        "long_output": "Long output...",
                        "perf_data": "'counter'=1"
                    }
                },
                "test_service3": {
                    "name": "test_ok_2",
                    "livestate": {
                        "state": "critical",
                        "output": "Output...",
                        "long_output": "Long output...",
                        "perf_data": "'counter'=1"
                    }
                },
            },
        }
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK', u'_result': [
                u'test_host_0 is alive :)',
                u"PROCESS_HOST_CHECK_RESULT;test_host_0;0;Output...|'counter'=1\nLong output...",
                u"PROCESS_SERVICE_CHECK_RESULT;test_host_0;test_ok_0;0;Output...|'counter'=1\nLong output...",
                u"Service 'test_host_0/test_ok_0' unchanged.",
                u"PROCESS_SERVICE_CHECK_RESULT;test_host_0;test_ok_2;2;Output...|'counter'=1\nLong output...",
                u"Service 'test_host_0/test_ok_2' unchanged.",
                u"PROCESS_SERVICE_CHECK_RESULT;test_host_0;test_ok_1;1;Output...|'counter'=1\nLong output...",
                u"Service 'test_host_0/test_ok_1' unchanged.",
                u"Host 'test_host_0' unchanged."
            ],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': True,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1,
                u'services': {
                    u'test_service': {
                        u'_overall_state_id': 3,
                        u'active_checks_enabled': True,
                        u'alias': u'',
                        u'check_freshness': False,
                        u'check_interval': 1,
                        u'freshness_state': u'x',
                        u'freshness_threshold': -1,
                        u'max_check_attempts': 2,
                        u'notes': u'just a notes string',
                        u'passive_checks_enabled': True,
                        u'retry_interval': 1
                    },
                    u'test_service2': {
                        u'_overall_state_id': 3,
                        u'active_checks_enabled': True,
                        u'alias': u'',
                        u'check_freshness': False,
                        u'check_interval': 1,
                        u'freshness_state': u'x',
                        u'freshness_threshold': -1,
                        u'max_check_attempts': 2,
                        u'notes': u'just a notes string',
                        u'passive_checks_enabled': True,
                        u'retry_interval': 1
                    },
                    u'test_service3': {
                        u'_overall_state_id': 3,
                        u'active_checks_enabled': True,
                        u'alias': u'',
                        u'check_freshness': False,
                        u'check_interval': 1,
                        u'freshness_state': u'x',
                        u'freshness_threshold': -1,
                        u'max_check_attempts': 2,
                        u'notes': u'just a notes string',
                        u'passive_checks_enabled': True,
                        u'retry_interval': 1
                    }
                }
            }
        })

        # Logout
        response = session.get('http://127.0.0.1:8888/logout')
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'OK')
        self.assertEqual(result['_result'], 'Logged out')

        self.modulemanager.stop_all()

    def test_module_zzz_host_timestamp(self):
        """Test the module /host API
        :return:
        """
        self.print_header()
        # Obliged to call to get a self.logger...
        self.setup_with_file('cfg/cfg_default.cfg')
        self.assertTrue(self.conf_is_correct)

        # -----
        # Provide parameters - logger configuration file (exists)
        # -----
        # Clear logs
        self.clear_logs()

        # Create an Alignak module
        mod = Module({
            'module_alias': 'web-services',
            'module_types': 'web-services',
            'python_name': 'alignak_module_ws',
            # Alignak backend
            'alignak_backend': 'http://127.0.0.1:5000',
            'username': 'admin',
            'password': 'admin',
            # Timestamp
            'set_timestamp': '1',
            # Set Arbiter address as empty to not poll the Arbiter else the test will fail!
            'alignak_host': '',
            'alignak_port': 7770,
        })

        # Create the modules manager for a daemon type
        self.modulemanager = ModulesManager('receiver', None)

        # Load an initialize the modules:
        #  - load python module
        #  - get module properties and instances
        self.modulemanager.load_and_init([mod])

        my_module = self.modulemanager.instances[0]

        # Clear logs
        self.clear_logs()

        # Start external modules
        self.modulemanager.start_external_instances()

        # Starting external module logs
        self.assert_log_match("Trying to initialize module: web-services", 0)
        self.assert_log_match("Starting external module web-services", 1)
        self.assert_log_match("Starting external process for module web-services", 2)
        self.assert_log_match("web-services is now started", 3)

        # Check alive
        self.assertIsNotNone(my_module.process)
        self.assertTrue(my_module.process.is_alive())

        time.sleep(1)

        # Do not allow GET request on /host - not authorized
        response = requests.get('http://127.0.0.1:8888/host')
        self.assertEqual(response.status_code, 401)

        session = requests.Session()

        # Login with username/password (real backend login)
        headers = {'Content-Type': 'application/json'}
        params = {'username': 'admin', 'password': 'admin'}
        response = session.post('http://127.0.0.1:8888/login', json=params, headers=headers)
        assert response.status_code == 200
        resp = response.json()

        # Allowed GET request on /host - forbidden to GET
        response = session.get('http://127.0.0.1:8888/host')
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'ERR')
        self.assertEqual(result['_error'], 'You must only PATCH on this endpoint.')

        # You must have parameters when POSTing on /host
        headers = {'Content-Type': 'application/json'}
        data = {}
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'ERR')
        self.assertEqual(result['_error'], 'You must send parameters on this endpoint.')

        # When host does not exist...
        headers = {'Content-Type': 'application/json'}
        data = {
            "fake": ""
        }
        response = session.patch('http://127.0.0.1:8888/host/test_host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {u'_status': u'ERR',
                                  u'_result': [u'test_host is alive :)'],
                                  u'_feedback': {},
                                  u'_issues': [u"Requested host 'test_host' does not exist"]})

        # Host name may be the last part of the URI
        headers = {'Content-Type': 'application/json'}
        data = {
            "fake": ""
        }
        response = session.patch('http://127.0.0.1:8888/host/test_host_0', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)'],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': False,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Host name may be in the POSTed data
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
        }
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)'],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': False,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Host name in the POSTed data takes precedence over URI
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
        }
        response = session.patch('http://127.0.0.1:8888/host/other_host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)'],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': False,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Host name must be somewhere !
        headers = {'Content-Type': 'application/json'}
        data = {
            "fake": "test_host",
        }
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'ERR')
        self.assertEqual(result['_issues'], [u'Missing targeted element.'])

        # Update host livestate (heartbeat / host is alive): empty livestate
        headers = {'Content-Type': 'application/json'}
        data = {
            "livestate": "",
            "name": "test_host_0",
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)'],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': False,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Update host livestate (heartbeat / host is alive): missing state in the livestate
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "livestate": {
                "output": "Output...",
                "long_output": "Long output...",
                "perf_data": "'counter'=1",
            }
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'ERR',
            u'_result': [u'test_host_0 is alive :)', u"Host 'test_host_0' unchanged."],
            u'_feedback': {},
            u'_issues': [u'Missing state in the livestate.']
        })

        # Update host livestate (heartbeat / host is alive): livestate must have an accepted state
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "livestate": {
                "state": "",
                "output": "Output...",
                "long_output": "Long output...",
                "perf_data": "'counter'=1",
            }
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'ERR',
            u'_result': [u'test_host_0 is alive :)', u"Host 'test_host_0' unchanged."],
            u'_feedback': {},
            u'_issues': [u"Host state must be UP, DOWN or UNREACHABLE, and not ''."]})

        # Update host livestate (heartbeat / host is alive): livestate must have an accepted state
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "livestate": {
                "state": "XxX",
                "output": "Output...",
                "long_output": "Long output...",
                "perf_data": "'counter'=1",
            }
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'ERR',
            u'_result': [u'test_host_0 is alive :)', u"Host 'test_host_0' unchanged."],
            u'_feedback': {},
            u'_issues': [u"Host state must be UP, DOWN or UNREACHABLE, and not 'XXX'."]})

        # Update host livestate (heartbeat / host is alive): livestate, no timestamp
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "livestate": {
                "state": "UP",
                "output": "Output...",
                "long_output": "Long output...",
                "perf_data": "'counter'=1",
            }
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)',
                         u"[%d] PROCESS_HOST_CHECK_RESULT;test_host_0;0;"
                         u"Output...|'counter'=1\nLong output..." % time.time(),
                         u"Host 'test_host_0' unchanged."],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': False,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Update host livestate (heartbeat / host is alive): livestate, provided timestamp
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "livestate": {
                "timestamp": 123456789,
                "state": "UP",
                "output": "Output...",
                "long_output": "Long output...",
                "perf_data": "'counter'=1",
            }
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)',
                         u"[%d] PROCESS_HOST_CHECK_RESULT;test_host_0;0;"
                         u"Output...|'counter'=1\nLong output..." % 123456789,
                         u"Host 'test_host_0' unchanged."],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': False,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Update host livestate (heartbeat / host is alive): livestate, invalid provided timestamp
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "livestate": {
                "timestamp": "ABC", # Invalid!
                "state": "UP",
                "output": "Output...",
                "long_output": "Long output...",
                "perf_data": "'counter'=1",
            }
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        # A timestamp is set because the module is configured to set a timestamp,
        # even if the provided one is not valid!
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)',
                         u"[%d] PROCESS_HOST_CHECK_RESULT;test_host_0;0;"
                         u"Output...|'counter'=1\nLong output..." % time.time(),
                         u"Host 'test_host_0' unchanged."],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': False,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Update host livestate (heartbeat / host is alive): livestate
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "livestate": {
                "state": "unreachable",
                "output": "Output...",
                "long_output": "Long output...",
                "perf_data": "'counter'=1",
            }
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)',
                         u"[%d] PROCESS_HOST_CHECK_RESULT;test_host_0;2;"
                         u"Output...|'counter'=1\nLong output..." % time.time(),
                         u"Host 'test_host_0' unchanged."],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': False,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Update host services livestate
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "livestate": {
                "state": "up",
                "output": "Output...",
                "long_output": "Long output...",
                "perf_data": "'counter'=1"
            },
            "services": {
                "test_service": {
                    "name": "test_ok_0",
                    "livestate": {
                        "state": "ok",
                        "output": "Output...",
                        "long_output": "Long output...",
                        "perf_data": "'counter'=1"
                    }
                },
                "test_service2": {
                    "name": "test_ok_1",
                    "livestate": {
                        "state": "warning",
                        "output": "Output...",
                        "long_output": "Long output...",
                        "perf_data": "'counter'=1"
                    }
                },
                "test_service3": {
                    "name": "test_ok_2",
                    "livestate": {
                        "state": "critical",
                        "output": "Output...",
                        "long_output": "Long output...",
                        "perf_data": "'counter'=1"
                    }
                },
            },
        }
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        now = time.time()
        self.assertEqual(result, {
            u'_status': u'OK', u'_result': [
                u'test_host_0 is alive :)',
                u"[%d] PROCESS_HOST_CHECK_RESULT;test_host_0;0;Output...|'counter'=1\nLong output..." % now,
                u"[%d] PROCESS_SERVICE_CHECK_RESULT;test_host_0;test_ok_0;0;Output...|'counter'=1\nLong output..." % now,
                u"Service 'test_host_0/test_ok_0' unchanged.",
                u"[%d] PROCESS_SERVICE_CHECK_RESULT;test_host_0;test_ok_2;2;Output...|'counter'=1\nLong output..." % now,
                u"Service 'test_host_0/test_ok_2' unchanged.",
                u"[%d] PROCESS_SERVICE_CHECK_RESULT;test_host_0;test_ok_1;1;Output...|'counter'=1\nLong output..." % now,
                u"Service 'test_host_0/test_ok_1' unchanged.",
                u"Host 'test_host_0' unchanged."
            ],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': False,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1,
                u'services': {
                    u'test_service': {
                        u'_overall_state_id': 3,
                        u'active_checks_enabled': False,
                        u'alias': u'',
                        u'check_freshness': False,
                        u'check_interval': 1,
                        u'freshness_state': u'x',
                        u'freshness_threshold': -1,
                        u'max_check_attempts': 2,
                        u'notes': u'just a notes string',
                        u'passive_checks_enabled': False,
                        u'retry_interval': 1
                    },
                    u'test_service2': {
                        u'_overall_state_id': 3,
                        u'active_checks_enabled': True,
                        u'alias': u'',
                        u'check_freshness': False,
                        u'check_interval': 1,
                        u'freshness_state': u'x',
                        u'freshness_threshold': -1,
                        u'max_check_attempts': 2,
                        u'notes': u'just a notes string',
                        u'passive_checks_enabled': True,
                        u'retry_interval': 1
                    },
                    u'test_service3': {
                        u'_overall_state_id': 3,
                        u'active_checks_enabled': False,
                        u'alias': u'',
                        u'check_freshness': False,
                        u'check_interval': 1,
                        u'freshness_state': u'x',
                        u'freshness_threshold': -1,
                        u'max_check_attempts': 2,
                        u'notes': u'just a notes string',
                        u'passive_checks_enabled': True,
                        u'retry_interval': 1
                    }
                }
            }
        })

        # Update host services livestate - provided timestamp
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "livestate": {
                "state": "up",
                "output": "Output...",
                "long_output": "Long output...",
                "perf_data": "'counter'=1"
            },
            "services": {
                "test_service": {
                    "name": "test_ok_0",
                    "livestate": {
                        "timestamp": 123456789,
                        "state": "ok",
                        "output": "Output...",
                        "long_output": "Long output...",
                        "perf_data": "'counter'=1"
                    }
                },
                "test_service2": {
                    "name": "test_ok_1",
                    "livestate": {
                        "state": "warning",
                        "output": "Output...",
                        "long_output": "Long output...",
                        "perf_data": "'counter'=1"
                    }
                },
                "test_service3": {
                    "name": "test_ok_2",
                    "livestate": {
                        "state": "critical",
                        "output": "Output...",
                        "long_output": "Long output...",
                        "perf_data": "'counter'=1"
                    }
                },
            },
        }
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        now = time.time()
        self.assertEqual(result, {
            u'_status': u'OK', u'_result': [
                u'test_host_0 is alive :)',
                u"[%d] PROCESS_HOST_CHECK_RESULT;test_host_0;0;Output...|'counter'=1\nLong output..." % now,
                u"[%d] PROCESS_SERVICE_CHECK_RESULT;test_host_0;test_ok_0;0;Output...|'counter'=1\nLong output..." % 123456789,
                u"Service 'test_host_0/test_ok_0' unchanged.",
                u"[%d] PROCESS_SERVICE_CHECK_RESULT;test_host_0;test_ok_2;2;Output...|'counter'=1\nLong output..." % now,
                u"Service 'test_host_0/test_ok_2' unchanged.",
                u"[%d] PROCESS_SERVICE_CHECK_RESULT;test_host_0;test_ok_1;1;Output...|'counter'=1\nLong output..." % now,
                u"Service 'test_host_0/test_ok_1' unchanged.",
                u"Host 'test_host_0' unchanged."
            ],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': False,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1,
                u'services': {
                    u'test_service': {
                        u'_overall_state_id': 3,
                        u'active_checks_enabled': False,
                        u'alias': u'',
                        u'check_freshness': False,
                        u'check_interval': 1,
                        u'freshness_state': u'x',
                        u'freshness_threshold': -1,
                        u'max_check_attempts': 2,
                        u'notes': u'just a notes string',
                        u'passive_checks_enabled': False,
                        u'retry_interval': 1
                    },
                    u'test_service2': {
                        u'_overall_state_id': 3,
                        u'active_checks_enabled': True,
                        u'alias': u'',
                        u'check_freshness': False,
                        u'check_interval': 1,
                        u'freshness_state': u'x',
                        u'freshness_threshold': -1,
                        u'max_check_attempts': 2,
                        u'notes': u'just a notes string',
                        u'passive_checks_enabled': True,
                        u'retry_interval': 1
                    },
                    u'test_service3': {
                        u'_overall_state_id': 3,
                        u'active_checks_enabled': False,
                        u'alias': u'',
                        u'check_freshness': False,
                        u'check_interval': 1,
                        u'freshness_state': u'x',
                        u'freshness_threshold': -1,
                        u'max_check_attempts': 2,
                        u'notes': u'just a notes string',
                        u'passive_checks_enabled': True,
                        u'retry_interval': 1
                    }
                }
            }
        })

        # Logout
        response = session.get('http://127.0.0.1:8888/logout')
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'OK')
        self.assertEqual(result['_result'], 'Logged out')

        self.modulemanager.stop_all()

    def test_module_zzz_host_variables(self):
        """Test the module /host API * create/update custom variables
        :return:
        """
        self.print_header()
        # Obliged to call to get a self.logger...
        self.setup_with_file('cfg/cfg_default.cfg')
        self.assertTrue(self.conf_is_correct)

        # Create an Alignak module
        mod = Module({
            'module_alias': 'web-services',
            'module_types': 'web-services',
            'python_name': 'alignak_module_ws',
            # Alignak backend
            'alignak_backend': 'http://127.0.0.1:5000',
            'username': 'admin',
            'password': 'admin',
            # Do not set a timestamp in the built external commands
            'set_timestamp': '0',
            # Set Arbiter address as empty to not poll the Arbiter else the test will fail!
            'alignak_host': '',
            'alignak_port': 7770,
        })

        # Create the modules manager for a daemon type
        self.modulemanager = ModulesManager('receiver', None)

        # Load an initialize the modules:
        #  - load python module
        #  - get module properties and instances
        self.modulemanager.load_and_init([mod])

        my_module = self.modulemanager.instances[0]

        # Clear logs
        self.clear_logs()

        # Start external modules
        self.modulemanager.start_external_instances()

        # Starting external module logs
        self.assert_log_match("Trying to initialize module: web-services", 0)
        self.assert_log_match("Starting external module web-services", 1)
        self.assert_log_match("Starting external process for module web-services", 2)
        self.assert_log_match("web-services is now started", 3)

        # Check alive
        self.assertIsNotNone(my_module.process)
        self.assertTrue(my_module.process.is_alive())

        time.sleep(1)

        # Get host data to confirm backend update
        # ---
        response = requests.get('http://127.0.0.1:5000/host', auth=self.auth,
                                params={'where': json.dumps({'name': 'test_host_0'})})
        resp = response.json()
        test_host_0 = resp['_items'][0]
        # ---

        # Do not allow GET request on /host - not authorized
        response = requests.get('http://127.0.0.1:8888/host')
        self.assertEqual(response.status_code, 401)

        session = requests.Session()

        # Login with username/password (real backend login)
        headers = {'Content-Type': 'application/json'}
        params = {'username': 'admin', 'password': 'admin'}
        response = session.post('http://127.0.0.1:8888/login', json=params, headers=headers)
        assert response.status_code == 200
        resp = response.json()

        # Do not allow GET request on /host
        response = session.get('http://127.0.0.1:8888/host')
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'ERR')
        self.assertEqual(result['_error'], 'You must only PATCH on this endpoint.')

        # You must have parameters when POSTing on /host
        headers = {'Content-Type': 'application/json'}
        data = {}
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'ERR')
        self.assertEqual(result['_error'], 'You must send parameters on this endpoint.')

        # Update host variables - empty variables
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "variables": "",
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)'],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': False,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # ----------
        # Host does not exist
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "unknown_host",
            "variables": {
                'test1': 'string',
                'test2': 1,
                'test3': 5.0
            },
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {u'_status': u'ERR',
                                  u'_result': [u'unknown_host is alive :)'],
                                  u'_feedback': {},
                                  u'_issues': [u"Requested host 'unknown_host' does not exist"]})


        # ----------
        # Create host variables
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "variables": {
                'test1': 'string',
                'test2': 1,
                'test3': 5.0
            },
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u"test_host_0 is alive :)",
                         u"Host 'test_host_0' updated."],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': False,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Get host data to confirm update
        response = session.get('http://127.0.0.1:5000/host', auth=self.auth,
                                params={'where': json.dumps({'name': 'test_host_0'})})
        resp = response.json()
        test_host_0 = resp['_items'][0]
        expected = {
            u'_TEMPLATE': u'generic',
            u'_OSLICENSE': u'gpl', u'_OSTYPE': u'gnulinux',
            u'_TEST3': 5.0, u'_TEST2': 1, u'_TEST1': u'string'
        }
        self.assertEqual(expected, test_host_0['customs'])
        # ----------

        # ----------
        # Unchanged host variables
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "variables": {
                'test1': 'string',
                'test2': 1,
                'test3': 5.0
            },
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)', u"Host 'test_host_0' unchanged."],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': False,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Get host data to confirm there was not update
        response = session.get('http://127.0.0.1:5000/host', auth=self.auth,
                                params={'where': json.dumps({'name': 'test_host_0'})})
        resp = response.json()
        test_host_0 = resp['_items'][0]
        expected = {
            u'_TEMPLATE': u'generic',
            u'_OSLICENSE': u'gpl', u'_OSTYPE': u'gnulinux',
            u'_TEST3': 5.0, u'_TEST2': 1, u'_TEST1': u'string'
        }
        self.assertEqual(expected, test_host_0['customs'])
        # ----------

        # ----------
        # Update host variables
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "variables": {
                'test1': 'string modified',
                'test2': 12,
                'test3': 15055.0,
                'test4': "new!"
            },
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)', u"Host 'test_host_0' updated."],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': False,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Get host data to confirm update
        response = session.get('http://127.0.0.1:5000/host', auth=self.auth,
                                params={'where': json.dumps({'name': 'test_host_0'})})
        resp = response.json()
        test_host_0 = resp['_items'][0]
        expected = {
            u'_TEMPLATE': u'generic',
            u'_OSLICENSE': u'gpl', u'_OSTYPE': u'gnulinux',
            u'_TEST3': 15055.0, u'_TEST2': 12, u'_TEST1': u'string modified', u'_TEST4': u'new!'
        }
        self.assertEqual(expected, test_host_0['customs'])
        # ----------

        # ----------
        # Delete host variables
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "variables": {
                'test1': 'string modified',
                'test2': 12,
                'test3': 15055.0,
                'test4': "__delete__"
            },
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u"test_host_0 is alive :)", u"Host 'test_host_0' updated."],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': False,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Get host data to confirm update
        response = session.get('http://127.0.0.1:5000/host', auth=self.auth,
                                params={'where': json.dumps({'name': 'test_host_0'})})
        resp = response.json()
        test_host_0 = resp['_items'][0]
        # todo: expected should be this:
        # currently it is not possible to update/delete a backend dict property!
        # expected = {
        #     u'_TEST3': 15055.0, u'_TEST2': 12, u'_TEST1': u'string modified'
        # }
        expected = {
            u'_TEMPLATE': u'generic',
            u'_OSLICENSE': u'gpl', u'_OSTYPE': u'gnulinux',
            u'_TEST3': 15055.0, u'_TEST2': 12, u'_TEST1': u'string modified', u'_TEST4': u'new!'
        }
        self.assertEqual(expected, test_host_0['customs'])
        # ----------

        # ----------
        # Create host service variables - unknown service
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",

            "services": {
                "test_service": {
                    "name": "test_service",
                    "variables": {
                        'test1': 'string',
                        'test2': 1,
                        'test3': 5.0
                    },
                },
            }
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'ERR',
            u'_result': [u'test_host_0 is alive :)', u"Host 'test_host_0' unchanged."],
            u'_feedback': {u'services': {}},
            u'_issues': [u"Requested service 'test_host_0/test_service' does not exist"]
        })
        # ----------

        # ----------
        # Create host service variables
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",

            "services": {
                "test_ok_0": {
                    "name": "test_ok_0",
                    "variables": {
                        'test1': 'string',
                        'test2': 1,
                        'test3': 5.0,
                        'test5': 'service specific'
                    },
                },
            }
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)',
                         u"Service 'test_host_0/test_ok_0' updated",
                         u"Host 'test_host_0' unchanged."],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': False,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1,
                u'services': {
                    u'test_ok_0': {
                        u'_overall_state_id': 3,
                        u'active_checks_enabled': False,
                        u'alias': u'',
                        u'check_freshness': False,
                        u'check_interval': 1,
                        u'freshness_state': u'x',
                        u'freshness_threshold': -1,
                        u'max_check_attempts': 2,
                        u'notes': u'just a notes string',
                        u'passive_checks_enabled': False,
                        u'retry_interval': 1
                    },
                }
            }
        })

        # Get host data to confirm update
        response = session.get('http://127.0.0.1:5000/host', auth=self.auth,
                                params={'where': json.dumps({'name': 'test_host_0'})})
        resp = response.json()
        host = resp['_items'][0]
        # Get services data to confirm update
        response = requests.get('http://127.0.0.1:5000/service', auth=self.auth,
                                params={'where': json.dumps({'host': host['_id'],
                                                             'name': 'test_ok_0'})})
        resp = response.json()
        service = resp['_items'][0]
        # The service still had a variable _CUSTNAME and it inherits from the host variables
        expected = {
            u'_TEMPLATE': u'generic',
            u'_OSLICENSE': u'gpl', u'_OSTYPE': u'gnulinux',
            u'_CUSTNAME': u'custvalue',
            u'_TEST3': 5.0, u'_TEST2': 1, u'_TEST1': u'string',
            u'_TEST4': u'new!',
            u'_TEST5': u'service specific'
        }
        self.assertEqual(expected, service['customs'])
        # ----------

        # Logout
        response = session.get('http://127.0.0.1:8888/logout')
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'OK')
        self.assertEqual(result['_result'], 'Logged out')

        self.modulemanager.stop_all()

    def test_module_zzz_host_enable_disable(self):
        """Test the module /host API - enable / disable active / passive checks - manage unchanged
        :return:
        """
        self.print_header()
        # Obliged to call to get a self.logger...
        self.setup_with_file('cfg/cfg_default.cfg')
        self.assertTrue(self.conf_is_correct)

        # Create an Alignak module
        mod = Module({
            'module_alias': 'web-services',
            'module_types': 'web-services',
            'python_name': 'alignak_module_ws',
            # Alignak backend
            'alignak_backend': 'http://127.0.0.1:5000',
            'username': 'admin',
            'password': 'admin',
            # Do not set a timestamp in the built external commands
            'set_timestamp': '0',
            # Set Arbiter address as empty to not poll the Arbiter else the test will fail!
            'alignak_host': '',
            'alignak_port': 7770,
        })

        # Create the modules manager for a daemon type
        self.modulemanager = ModulesManager('receiver', None)

        # Load an initialize the modules:
        #  - load python module
        #  - get module properties and instances
        self.modulemanager.load_and_init([mod])

        my_module = self.modulemanager.instances[0]

        # Clear logs
        self.clear_logs()

        # Start external modules
        self.modulemanager.start_external_instances()

        # Starting external module logs
        self.assert_log_match("Trying to initialize module: web-services", 0)
        self.assert_log_match("Starting external module web-services", 1)
        self.assert_log_match("Starting external process for module web-services", 2)
        self.assert_log_match("web-services is now started", 3)

        # Check alive
        self.assertIsNotNone(my_module.process)
        self.assertTrue(my_module.process.is_alive())

        time.sleep(1)

        # Get host data to confirm backend update
        # ---
        response = requests.get('http://127.0.0.1:5000/host', auth=self.auth,
                                params={'where': json.dumps({'name': 'test_host_0'})})
        resp = response.json()
        dummy_host = resp['_items'][0]
        # ---

        # Do not allow GET request on /host - not yet authorized
        response = requests.get('http://127.0.0.1:8888/host')
        self.assertEqual(response.status_code, 401)

        session = requests.Session()

        # Login with username/password (real backend login)
        headers = {'Content-Type': 'application/json'}
        params = {'username': 'admin', 'password': 'admin'}
        response = session.post('http://127.0.0.1:8888/login', json=params, headers=headers)
        assert response.status_code == 200
        resp = response.json()

        # Update host variables - empty variables
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "active_checks_enabled": "",
            "passive_checks_enabled": ""
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)'],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': True,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # ----------
        # Host does not exist
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "unknown_host",
            "active_checks_enabled": True,
            "passive_checks_enabled": True
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'ERR',
            u'_result': [u'unknown_host is alive :)'],
            u'_feedback': {},
            u'_issues': [u"Requested host 'unknown_host' does not exist"]})

        # ----------
        # Enable all checks
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "active_checks_enabled": True,
            "passive_checks_enabled": True
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)', u"Host 'test_host_0' unchanged."],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': True,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Get host data to confirm update
        response = session.get('http://127.0.0.1:5000/host', auth=self.auth,
                                params={'where': json.dumps({'name': 'test_host_0'})})
        resp = response.json()
        dummy_host = resp['_items'][0]
        self.assertTrue(dummy_host['active_checks_enabled'])
        self.assertTrue(dummy_host['passive_checks_enabled'])
        # ----------

        # ----------
        # Enable all checks - again!
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "active_checks_enabled": True,
            "passive_checks_enabled": True
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [u'test_host_0 is alive :)', u"Host 'test_host_0' unchanged."],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': True,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Get host data to confirm update
        response = session.get('http://127.0.0.1:5000/host', auth=self.auth,
                                params={'where': json.dumps({'name': 'test_host_0'})})
        resp = response.json()
        dummy_host = resp['_items'][0]
        self.assertTrue(dummy_host['active_checks_enabled'])
        self.assertTrue(dummy_host['passive_checks_enabled'])
        # ----------

        # ----------
        # Disable all checks
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "active_checks_enabled": False,
            "passive_checks_enabled": False
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [
                u'test_host_0 is alive :)',
                u'Host test_host_0 active checks will be disabled.',
                u'Sent external command: DISABLE_HOST_CHECK;test_host_0.',
                u'Host test_host_0 passive checks will be disabled.',
                u'Sent external command: DISABLE_PASSIVE_HOST_CHECKS;test_host_0.',
                u"Host 'test_host_0' updated."
            ],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': False,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': False,
                u'retry_interval': 1
            }
        })

        # Get host data to confirm update
        response = session.get('http://127.0.0.1:5000/host', auth=self.auth,
                                params={'where': json.dumps({'name': 'test_host_0'})})
        resp = response.json()
        dummy_host = resp['_items'][0]
        self.assertFalse(dummy_host['active_checks_enabled'])
        self.assertFalse(dummy_host['passive_checks_enabled'])
        # ----------

        # ----------
        # Mixed
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "active_checks_enabled": True,
            "passive_checks_enabled": False
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [
                u'test_host_0 is alive :)',
                u'Host test_host_0 active checks will be enabled.',
                u'Sent external command: ENABLE_HOST_CHECK;test_host_0.',
                u"Host 'test_host_0' updated."
            ],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': True,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': False,
                u'retry_interval': 1
            }
        })

        # Get host data to confirm update
        response = session.get('http://127.0.0.1:5000/host', auth=self.auth,
                                params={'where': json.dumps({'name': 'test_host_0'})})
        resp = response.json()
        dummy_host = resp['_items'][0]
        self.assertTrue(dummy_host['active_checks_enabled'])
        self.assertFalse(dummy_host['passive_checks_enabled'])
        # ----------

        # ----------
        # Mixed
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "active_checks_enabled": False,
            "passive_checks_enabled": True
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [
                u'test_host_0 is alive :)',
                u'Host test_host_0 active checks will be disabled.',
                u'Sent external command: DISABLE_HOST_CHECK;test_host_0.',
                u'Host test_host_0 passive checks will be enabled.',
                u'Sent external command: ENABLE_PASSIVE_HOST_CHECKS;test_host_0.',
                u"Host 'test_host_0' updated."
            ],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': False,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1
            }
        })

        # Get host data to confirm update
        response = session.get('http://127.0.0.1:5000/host', auth=self.auth,
                                params={'where': json.dumps({'name': 'test_host_0'})})
        resp = response.json()
        dummy_host = resp['_items'][0]
        self.assertFalse(dummy_host['active_checks_enabled'])
        self.assertTrue(dummy_host['passive_checks_enabled'])
        # ----------

        # ----------
        # Enable / Disable all host services - unknown services
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "active_checks_enabled": False,
            "passive_checks_enabled": True,
            "services": {
                "test_service": {
                    "name": "test_service",
                    "active_checks_enabled": True,
                    "passive_checks_enabled": True,
                },
                "test_service2": {
                    "name": "test_service2",
                    "active_checks_enabled": False,
                    "passive_checks_enabled": False,
                },
                "test_service3": {
                    "name": "test_service3",
                    "active_checks_enabled": True,
                    "passive_checks_enabled": False,
                },
            }
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'ERR',
            u'_result': [u'test_host_0 is alive :)',
                         u"Host 'test_host_0' unchanged."],
            u'_feedback': {u'services': {}},
            u'_issues': [u"Requested service 'test_host_0/test_service' does not exist",
                         u"Requested service 'test_host_0/test_service3' does not exist",
                         u"Requested service 'test_host_0/test_service2' does not exist"]
        })
        # ----------

        # ----------
        # Enable / Disable all host services
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "active_checks_enabled": False,
            "passive_checks_enabled": True,
            "services": {
                "test_service": {
                    "name": "test_ok_0",
                    "active_checks_enabled": True,
                    "passive_checks_enabled": True,
                },
                "test_service2": {
                    "name": "test_ok_1",
                    "active_checks_enabled": False,
                    "passive_checks_enabled": False,
                },
                "test_service3": {
                    "name": "test_ok_2",
                    "active_checks_enabled": True,
                    "passive_checks_enabled": False,
                },
            }
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [
                u'test_host_0 is alive :)',
                u"Service 'test_host_0/test_ok_0' unchanged.",
                u'Service test_host_0/test_ok_2 passive checks will be disabled.',
                u'Sent external command: DISABLE_PASSIVE_SVC_CHECKS;test_host_0;test_ok_2.',
                u"Service 'test_host_0/test_ok_2' updated",
                u'Service test_host_0/test_ok_1 active checks will be disabled.',
                u'Sent external command: DISABLE_SVC_CHECK;test_host_0;test_ok_1.',
                u'Service test_host_0/test_ok_1 passive checks will be disabled.',
                u'Sent external command: DISABLE_PASSIVE_SVC_CHECKS;test_host_0;test_ok_1.',
                u"Service 'test_host_0/test_ok_1' updated",
                u"Host 'test_host_0' unchanged."
            ],
            u'_feedback': {
                u'_overall_state_id': 3,
                u'active_checks_enabled': False,
                u'alias': u'up_0',
                u'check_freshness': False,
                u'check_interval': 1,
                u'freshness_state': u'x',
                u'freshness_threshold': -1,
                u'location': {u'coordinates': [46.60611, 1.87528],
                              u'type': u'Point'},
                u'max_check_attempts': 3,
                u'notes': u'',
                u'passive_checks_enabled': True,
                u'retry_interval': 1,
                u'services': {
                    u'test_service': {
                        u'_overall_state_id': 3,
                        u'active_checks_enabled': True,
                        u'alias': u'',
                        u'check_freshness': False,
                        u'check_interval': 1,
                        u'freshness_state': u'x',
                        u'freshness_threshold': -1,
                        u'max_check_attempts': 2,
                        u'notes': u'just a notes string',
                        u'passive_checks_enabled': True,
                        u'retry_interval': 1
                    },
                    u'test_service2': {
                        u'_overall_state_id': 3,
                        u'active_checks_enabled': False,
                        u'alias': u'',
                        u'check_freshness': False,
                        u'check_interval': 1,
                        u'freshness_state': u'x',
                        u'freshness_threshold': -1,
                        u'max_check_attempts': 2,
                        u'notes': u'just a notes string',
                        u'passive_checks_enabled': False,
                        u'retry_interval': 1
                    },
                    u'test_service3': {
                        u'_overall_state_id': 3,
                        u'active_checks_enabled': True,
                        u'alias': u'',
                        u'check_freshness': False,
                        u'check_interval': 1,
                        u'freshness_state': u'x',
                        u'freshness_threshold': -1,
                        u'max_check_attempts': 2,
                        u'notes': u'just a notes string',
                        u'passive_checks_enabled': False,
                        u'retry_interval': 1
                    }
                }

            }
        })

        # Get host data to confirm update
        response = session.get('http://127.0.0.1:5000/host', auth=self.auth,
                                params={'where': json.dumps({'name': 'test_host_0'})})
        resp = response.json()
        host = resp['_items'][0]
        self.assertFalse(host['active_checks_enabled'])
        self.assertTrue(host['passive_checks_enabled'])
        # Get services data to confirm update
        response = requests.get('http://127.0.0.1:5000/service', auth=self.auth,
                                params={'where': json.dumps({'host': host['_id'],
                                                             'name': 'test_ok_0'})})
        resp = response.json()
        service = resp['_items'][0]
        self.assertTrue(service['active_checks_enabled'])
        self.assertTrue(service['passive_checks_enabled'])
        response = requests.get('http://127.0.0.1:5000/service', auth=self.auth,
                                params={'where': json.dumps({'host': host['_id'],
                                                             'name': 'test_ok_1'})})
        resp = response.json()
        service = resp['_items'][0]
        self.assertFalse(service['active_checks_enabled'])
        self.assertFalse(service['passive_checks_enabled'])
        response = requests.get('http://127.0.0.1:5000/service', auth=self.auth,
                                params={'where': json.dumps({'host': host['_id'],
                                                             'name': 'test_ok_2'})})
        resp = response.json()
        service = resp['_items'][0]
        self.assertTrue(service['active_checks_enabled'])
        self.assertFalse(service['passive_checks_enabled'])
        # ----------

        # Logout

        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host_0",
            "active_checks_enabled": False,
            "passive_checks_enabled": True,
            "services": {
                "test_service": {
                    "name": "test_ok_0",
                    "active_checks_enabled": False,
                    "passive_checks_enabled": False,
                },
                "test_service2": {
                    "name": "test_ok_1",
                    "active_checks_enabled": True,
                    "passive_checks_enabled": True,
                },
                "test_service3": {
                    "name": "test_ok_2",
                    "active_checks_enabled": False,
                    "passive_checks_enabled": True,
                },
            }
        }
        self.assertEqual(my_module.received_commands, 0)
        response = session.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        print(result)
        self.assertEqual(result, {
            u'_status': u'OK',
            u'_result': [
                u'test_host_0 is alive :)',
                u'Service test_host_0/test_ok_0 active checks will be disabled.',
                u'Sent external command: DISABLE_SVC_CHECK;test_host_0;test_ok_0.',
                u'Service test_host_0/test_ok_0 passive checks will be disabled.',
                u'Sent external command: DISABLE_PASSIVE_SVC_CHECKS;test_host_0;test_ok_0.',
                u"Service 'test_host_0/test_ok_0' updated",
                u'Service test_host_0/test_ok_2 active checks will be disabled.',
                u'Sent external command: DISABLE_SVC_CHECK;test_host_0;test_ok_2.',
                u'Service test_host_0/test_ok_2 passive checks will be enabled.',
                u'Sent external command: ENABLE_PASSIVE_SVC_CHECKS;test_host_0;test_ok_2.',
                u"Service 'test_host_0/test_ok_2' updated",
                u'Service test_host_0/test_ok_1 active checks will be enabled.',
                u'Sent external command: ENABLE_SVC_CHECK;test_host_0;test_ok_1.',
                u'Service test_host_0/test_ok_1 passive checks will be enabled.',
                u'Sent external command: ENABLE_PASSIVE_SVC_CHECKS;test_host_0;test_ok_1.',
                u"Service 'test_host_0/test_ok_1' updated",
                u"Host 'test_host_0' unchanged."
            ],
            u'_feedback': {
                u'active_checks_enabled': False, u'_overall_state_id': 3,
                u'freshness_state': u'x', u'notes': u'', u'retry_interval': 1,
                u'alias': u'up_0', u'freshness_threshold': -1,
                u'check_freshness': False,
                u'location': {u'type': u'Point', u'coordinates': [46.60611, 1.87528]},
                u'passive_checks_enabled': True, u'check_interval': 1,
                u'services': {
                    u'test_service': {u'active_checks_enabled': False, u'alias': u'',
                                      u'freshness_state': u'x', u'notes': u'just a notes string',
                                      u'retry_interval': 1, u'_overall_state_id': 3,
                                      u'freshness_threshold': -1, u'passive_checks_enabled': False,
                                      u'check_interval': 1, u'max_check_attempts': 2,
                                      u'check_freshness': False},
                    u'test_service3': {u'active_checks_enabled': False, u'alias': u'',
                                       u'freshness_state': u'x', u'notes': u'just a notes string',
                                       u'retry_interval': 1, u'_overall_state_id': 3,
                                       u'freshness_threshold': -1, u'passive_checks_enabled': True,
                                       u'check_interval': 1, u'max_check_attempts': 2,
                                       u'check_freshness': False},
                    u'test_service2': {u'active_checks_enabled': True, u'alias': u'',
                                       u'freshness_state': u'x', u'notes': u'just a notes string',
                                       u'retry_interval': 1, u'_overall_state_id': 3,
                                       u'freshness_threshold': -1, u'passive_checks_enabled': True,
                                       u'check_interval': 1, u'max_check_attempts': 2,
                                       u'check_freshness': False}}, u'max_check_attempts': 3,

            }
        })

        response = session.get('http://127.0.0.1:8888/logout')
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'OK')
        self.assertEqual(result['_result'], 'Logged out')

        self.modulemanager.stop_all()
