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

import requests

from alignak_test import AlignakTest, time_hacker
from alignak.modulesmanager import ModulesManager
from alignak.objects.module import Module
from alignak.basemodule import BaseModule

# Set environment variable to ask code Coverage collection
os.environ['COVERAGE_PROCESS_START'] = '.coveragerc'

import alignak_module_ws


class TestModules(AlignakTest):
    """This class contains the tests for the module"""

    def test_module_loading(self):
        """
        Test arbiter, broker, ... auto-generated modules

        Alignak module loading

        :return:
        """
        self.print_header()
        self.setup_with_file('./cfg/cfg_default.cfg')
        self.assertTrue(self.conf_is_correct)
        self.show_configuration_logs()

        # No arbiter modules created
        modules = [m.module_alias for m in self.arbiter.myself.modules]
        self.assertListEqual(modules, [])

        # The only existing broker module is logs declared in the configuration
        modules = [m.module_alias for m in self.brokers['broker-master'].modules]
        self.assertListEqual(modules, [])

        # No poller module
        modules = [m.module_alias for m in self.pollers['poller-master'].modules]
        self.assertListEqual(modules, [])

        # No receiver module
        modules = [m.module_alias for m in self.receivers['receiver-master'].modules]
        self.assertListEqual(modules, ['web-services'])

        # No reactionner module
        modules = [m.module_alias for m in self.reactionners['reactionner-master'].modules]
        self.assertListEqual(modules, [])

        # No scheduler modules
        modules = [m.module_alias for m in self.schedulers['scheduler-master'].modules]
        self.assertListEqual(modules, [])

    def test_module_manager(self):
        """
        Test if the module manager manages correctly all the modules
        :return:
        """
        self.print_header()
        self.setup_with_file('cfg/cfg_default.cfg')
        self.assertTrue(self.conf_is_correct)

        time_hacker.set_real_time()

        # Create an Alignak module
        mod = Module({
            'module_alias': 'web-services',
            'module_types': 'web-services',
            'python_name': 'alignak_module_ws',
            # Set Arbiter address as empty to not poll the Arbiter else the test will fail!
            'alignak_host': '',
            'alignak_port': 7770,
        })

        # Create the modules manager for a daemon type
        self.modulemanager = ModulesManager('receiver', None)

        # Load and initialize the modules:
        #  - load python module
        #  - get module properties and instances
        self.modulemanager.load_and_init([mod])

        # Loading module logs
        self.assert_any_log_match(re.escape(
            "Importing Python module 'alignak_module_ws' for web-services..."
        ))
        self.assert_any_log_match(re.escape(
            "Module properties: {'daemons': ['receiver'], 'phases': ['running'], "
            "'type': 'web-services', 'external': True}"
        ))
        self.assert_any_log_match(re.escape(
            "Imported 'alignak_module_ws' for web-services"
        ))
        self.assert_any_log_match(re.escape(
            "Loaded Python module 'alignak_module_ws' (web-services)"
        ))
        self.assert_any_log_match(re.escape(
            "Give an instance of alignak_module_ws for alias: web-services"
        ))

        my_module = self.modulemanager.instances[0]

        # Get list of not external modules
        self.assertListEqual([], self.modulemanager.get_internal_instances())
        for phase in ['configuration', 'late_configuration', 'running', 'retention']:
            self.assertListEqual([], self.modulemanager.get_internal_instances(phase))

        # Get list of external modules
        self.assertListEqual([my_module], self.modulemanager.get_external_instances())
        for phase in ['configuration', 'late_configuration', 'retention']:
            self.assertListEqual([], self.modulemanager.get_external_instances(phase))
        for phase in ['running']:
            self.assertListEqual([my_module], self.modulemanager.get_external_instances(phase))

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

        # Clear logs
        self.clear_logs()

        # Kill the external module (normal stop is .stop_process)
        my_module.kill()
        time.sleep(0.1)
        self.assert_log_match("Killing external module", 0)
        self.assert_log_match("External module killed", 1)

        # Should be dead (not normally stopped...) but we still know a process for this module!
        self.assertIsNotNone(my_module.process)

        # Nothing special ...
        self.modulemanager.check_alive_instances()
        self.assert_log_match("The external module web-services died unexpectedly!", 2)
        self.assert_log_match("Setting the module web-services to restart", 3)

        # Try to restart the dead modules
        self.modulemanager.try_to_restart_deads()
        self.assert_log_match("Trying to initialize module: web-services", 4)

        # In fact it's too early, so it won't do it
        # The module instance is still dead
        self.assertFalse(my_module.process.is_alive())

        # So we lie, on the restart tries ...
        my_module.last_init_try = -5
        self.modulemanager.check_alive_instances()
        self.modulemanager.try_to_restart_deads()
        self.assert_log_match("Trying to initialize module: web-services", 5)

        # The module instance is now alive again
        self.assertTrue(my_module.process.is_alive())
        self.assert_log_match("I'm stopping module 'web-services'", 6)
        self.assert_log_match("Starting external process for module web-services", 7)
        self.assert_log_match("web-services is now started", 8)

        # There is nothing else to restart in the module manager
        self.assertEqual([], self.modulemanager.to_restart)

        # Clear logs
        self.clear_logs()

        # Now we look for time restart so we kill it again
        my_module.kill()
        time.sleep(0.2)
        self.assertFalse(my_module.process.is_alive())
        self.assert_log_match("Killing external module", 0)
        self.assert_log_match("External module killed", 1)

        # Should be too early
        self.modulemanager.check_alive_instances()
        self.assert_log_match("The external module web-services died unexpectedly!", 2)
        self.assert_log_match("Setting the module web-services to restart", 3)

        self.modulemanager.try_to_restart_deads()
        self.assert_log_match("Trying to initialize module: web-services", 4)

        # In fact it's too early, so it won't do it
        # The module instance is still dead
        self.assertFalse(my_module.process.is_alive())

        # So we lie, on the restart tries ...
        my_module.last_init_try = -5
        self.modulemanager.check_alive_instances()
        self.modulemanager.try_to_restart_deads()
        self.assert_log_match("Trying to initialize module: web-services", 5)

        # The module instance is now alive again
        self.assertTrue(my_module.process.is_alive())
        self.assert_log_match("I'm stopping module 'web-services'", 6)
        self.assert_log_match("Starting external process for module web-services", 7)
        self.assert_log_match("web-services is now started", 8)

        # And we clear all now
        self.modulemanager.stop_all()
        # Stopping module logs

        self.assert_log_match("Request external process to stop for web-services", 9)
        self.assert_log_match(re.escape("I'm stopping module 'web-services' (pid="), 10)
        self.assert_log_match(
            re.escape("'web-services' is still alive after normal kill, I help it to die"), 11
        )
        self.assert_log_match("Killing external module ", 12)
        self.assert_log_match("External module killed", 13)
        self.assert_log_match("External process stopped.", 14)

    def test_module_start_default(self):
        """
        Test the module initialization function, no parameters, using default
        :return:
        """
        self.print_header()
        # Obliged to call to get a self.logger...
        self.setup_with_file('cfg/cfg_default.cfg')
        self.assertTrue(self.conf_is_correct)

        # -----
        # Default initialization
        # -----
        # Clear logs
        self.clear_logs()

        # Create an Alignak module
        mod = Module({
            'module_alias': 'web-services',
            'module_types': 'web-services',
            'python_name': 'alignak_module_ws'
        })

        instance = alignak_module_ws.get_instance(mod)
        self.assertIsInstance(instance, BaseModule)

        self.assert_log_match(
            re.escape("Give an instance of alignak_module_ws for "
                      "alias: web-services"), 0)
        self.assert_log_match(
            re.escape("Alignak Backend is not configured. "
                      "Some module features will not be available."), 1)
        self.assert_log_match(
            re.escape("Alignak Arbiter configuration: 127.0.0.1:7770"), 2)
        self.assert_log_match(
            re.escape("Alignak Arbiter polling period: 1"), 3)
        self.assert_log_match(
            re.escape("Alignak daemons get status period: 10"), 4)
        self.assert_log_match(
            re.escape("SSL is not enabled, this is not recommended. "
                      "You should consider enabling SSL!"), 5)
        self.assert_log_match(
            re.escape("configuration, listening on: http://0.0.0.0:8888"), 6)

    def test_module_start_parameters(self):
        """
        Test the module initialization function, no parameters, provide parameters
        :return:
        """
        self.print_header()
        # Obliged to call to get a self.logger...
        self.setup_with_file('cfg/cfg_default.cfg')
        self.assertTrue(self.conf_is_correct)

        # -----
        # Provide parameters
        # -----
        # Clear logs
        self.clear_logs()

        # Create an Alignak module
        mod = Module({
            'module_alias': 'web-services',
            'module_types': 'web-services',
            'python_name': 'alignak_module_ws',
            'use_ssl': '1',
            'alignak_host': 'my_host',
            'alignak_port': 80,
            'host': 'me',
            'port': 8080,
        })

        instance = alignak_module_ws.get_instance(mod)
        self.assertIsInstance(instance, BaseModule)

        self.assert_log_match(
            re.escape("Give an instance of alignak_module_ws for "
                      "alias: web-services"), 0)
        self.assert_log_match(
            re.escape("Alignak Backend is not configured. "
                      "Some module features will not be available."), 1)
        self.assert_log_match(
            re.escape("Alignak Arbiter configuration: my_host:80"), 2)
        self.assert_log_match(
            re.escape("Alignak Arbiter polling period: 1"), 3)
        self.assert_log_match(
            re.escape("Alignak daemons get status period: 10"), 4)
        self.assert_log_match(
            re.escape("The CA certificate /usr/local/etc/alignak/certs/ca.pem is missing "
                      "(ca_cert). Please fix it in your configuration"), 5)
        self.assert_log_match(
            re.escape("SSL is not enabled, this is not recommended. "
                      "You should consider enabling SSL!"), 6)
        self.assert_log_match(
            re.escape("configuration, listening on: http://me:8080"), 7)

    def test_module_zzz_basic_ws(self):
        """Test the module basic API

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

        # Get the module API list and request on each endpoint
        response = requests.get('http://127.0.0.1:8888')
        api_list = response.json()
        for endpoint in api_list:
            print("Trying %s" % (endpoint))
            response = requests.get('http://127.0.0.1:8888/' + endpoint)
            print("Response %d: %s" % (response.status_code, response.content))
            self.assertEqual(response.status_code, 200)
            if response.status_code == 200:
                print("Got %s: %s" % (endpoint, response.json()))
            else:
                print("Error %s: %s" % (response.status_code, response.content))

        self.modulemanager.stop_all()

    def test_module_zzz_command(self):
        """ Test the module /command API
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

        # Do not allow GET request on /command
        response = requests.get('http://127.0.0.1:8888/command')
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'ERR')
        self.assertEqual(result['_error'], 'You must only POST on this endpoint.')

        self.assertEqual(my_module.received_commands, 0)

        # You must have parameters when POSTing on /command
        headers = {'Content-Type': 'application/json'}
        data = {}
        response = requests.post('http://127.0.0.1:8888/command', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'ERR')
        self.assertEqual(result['_error'], 'You must POST parameters on this endpoint.')

        self.assertEqual(my_module.received_commands, 0)

        # Request to execute an external command
        headers = {'Content-Type': 'application/json'}
        data = {
            "command": "Command",
            "element": "test_host",
            "parameters": "abc;1"
        }
        self.assertEqual(my_module.received_commands, 0)
        response = requests.post('http://127.0.0.1:8888/command', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'OK')
        # Result is uppercase command, parameters are ordered
        self.assertEqual(result['_command'], 'COMMAND;test_host;abc;1')

        # Not during unit tests ... because module queues are not functional!
        # time.sleep(1)
        # self.assertEqual(my_module.received_commands, 1)

        # Request to execute an external command
        headers = {'Content-Type': 'application/json'}
        data = {
            "command": "command_command",
            "element": "test_host;test_service",
            "parameters": "1;abc;2"
        }
        response = requests.post('http://127.0.0.1:8888/command', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'OK')
        # Result is uppercase command, parameters are ordered
        self.assertEqual(result['_command'], 'COMMAND_COMMAND;test_host;test_service;1;abc;2')

        # Request to execute an external command
        headers = {'Content-Type': 'application/json'}
        data = {
            "command": "command_command",
            "element": "test_host/test_service",    # Accept / as an host/service separator
            "parameters": "1;abc;2"
        }
        response = requests.post('http://127.0.0.1:8888/command', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'OK')
        # Result is uppercase command, parameters are ordered
        self.assertEqual(result['_command'], 'COMMAND_COMMAND;test_host;test_service;1;abc;2')

        # Request to execute an external command (Alignak modern syntax)
        headers = {'Content-Type': 'application/json'}
        data = {
            "command": "command_command",
            "host": "test_host",
            "service": "test_service",
            "parameters": "1;abc;2"
        }
        response = requests.post('http://127.0.0.1:8888/command', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'OK')
        # Result is uppercase command, parameters are ordered
        self.assertEqual(result['_command'], 'COMMAND_COMMAND;test_host;test_service;1;abc;2')

        # Request to execute an external command (Alignak modern syntax)
        headers = {'Content-Type': 'application/json'}
        data = {
            "command": "command_command",
            "host": "test_host",
            "service": "test_service",
            "user": "test_user",
            "parameters": "1;abc;2"
        }
        response = requests.post('http://127.0.0.1:8888/command', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'OK')
        # Result is uppercase command, parameters are ordered
        self.assertEqual(result['_command'],
                         'COMMAND_COMMAND;test_host;test_service;test_user;1;abc;2')

        self.modulemanager.stop_all()

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

        # Do not allow GET request on /host
        response = requests.get('http://127.0.0.1:8888/host')
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'ERR')
        self.assertEqual(result['_error'], 'You must only PATCH on this endpoint.')

        # You must have parameters when POSTing on /host
        headers = {'Content-Type': 'application/json'}
        data = {}
        response = requests.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'ERR')
        self.assertEqual(result['_error'], 'You must send parameters on this endpoint.')

        # Host name may be the last part of the URI
        headers = {'Content-Type': 'application/json'}
        data = {
            "fake": ""
        }
        response = requests.patch('http://127.0.0.1:8888/host/test_host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {u'_status': u'OK', u'_result': [u'test_host is alive :)']})

        # Host name may be in the POSTed data
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host",
        }
        response = requests.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {u'_status': u'OK', u'_result': [u'test_host is alive :)']})

        # Host name must be somewhere !
        headers = {'Content-Type': 'application/json'}
        data = {
            "fake": "test_host",
        }
        response = requests.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['_status'], 'ERR')
        self.assertEqual(result['_issues'], [u'Missing targeted element.'])

        # Update host livestate (heartbeat / host is alive): empty livestate
        headers = {'Content-Type': 'application/json'}
        data = {
            "livestate": "",
            "name": "test_host",
        }
        self.assertEqual(my_module.received_commands, 0)
        response = requests.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {u'_status': u'OK', u'_result': [u'test_host is alive :)']})

        # Update host livestate (heartbeat / host is alive): livestate must have an accepted state
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host",
            "livestate": {
                "state": "",
                "output": "Output...",
                "long_output": "Long output...",
                "perf_data": "'counter':1",
            }
        }
        self.assertEqual(my_module.received_commands, 0)
        response = requests.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {u'_status': u'ERR',
                                  u'_result': [u'test_host is alive :)'],
                                  u'_issues': [u'Host state must be UP, DOWN or UNREACHABLE.']})

        # Update host livestate (heartbeat / host is alive): livestate
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host",
            "livestate": {
                "state": "UP",
                "output": "Output...",
                "long_output": "Long output...",
                "perf_data": "'counter':1",
            }
        }
        self.assertEqual(my_module.received_commands, 0)
        response = requests.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {u'_status': u'OK',
                                  u'_result': [u'test_host is alive :)',
                                               u"PROCESS_HOST_CHECK_RESULT;test_host;UP;"
                                               u"Output...|'counter':1\nLong output..."]})

        # Update host livestate (heartbeat / host is alive): livestate
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host",
            "livestate": {
                "state": "unreachable",
                "output": "Output...",
                "long_output": "Long output...",
                "perf_data": "'counter':1",
            }
        }
        self.assertEqual(my_module.received_commands, 0)
        response = requests.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result, {u'_status': u'OK',
                                  u'_result': [u'test_host is alive :)',
                                               u"PROCESS_HOST_CHECK_RESULT;test_host;UNREACHABLE;"
                                               u"Output...|'counter':1\nLong output..."]})

        # Update host services livestate
        headers = {'Content-Type': 'application/json'}
        data = {
            "name": "test_host",
            "livestate": {
                "state": "up",
                "output": "Output...",
                "long_output": "Long output...",
                "perf_data": "'counter':1"
            },
            "services": {
                "test_service": {
                    "name": "test_service",
                    "livestate": {
                        "state": "ok",
                        "output": "Output...",
                        "long_output": "Long output...",
                        "perf_data": "'counter':1"
                    }
                },
                "test_service2": {
                    "name": "test_service2",
                    "livestate": {
                        "state": "warning",
                        "output": "Output...",
                        "long_output": "Long output...",
                        "perf_data": "'counter':1"
                    }
                },
                "test_service3": {
                    "name": "test_service3",
                    "livestate": {
                        "state": "critical",
                        "output": "Output...",
                        "long_output": "Long output...",
                        "perf_data": "'counter':1"
                    }
                },
            },
        }
        response = requests.patch('http://127.0.0.1:8888/host', json=data, headers=headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        print(result)
        self.assertEqual(result, {
            u'_status': u'OK', u'_result': [u'test_host is alive :)',
                                            u"PROCESS_HOST_CHECK_RESULT;test_host;UP;Output...|'counter':1\nLong output...",
                                            u"PROCESS_SERVICE_CHECK_RESULT;test_host;test_service;OK;Output...|'counter':1\nLong output...",
                                            u"PROCESS_SERVICE_CHECK_RESULT;test_host;test_service3;CRITICAL;Output...|'counter':1\nLong output...",
                                            u"PROCESS_SERVICE_CHECK_RESULT;test_host;test_service2;WARNING;Output...|'counter':1\nLong output..."]
        })

        self.modulemanager.stop_all()

