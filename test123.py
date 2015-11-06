__author__ = 'tianheng'
__author__ = 'Srinivasan Krishnaraj (srinivkr@google.com)'

import fileinput
import linecache
import os
from random import randint
import re
import time

import google3
import yaml

from google3.pyglib import flags
from google3.pyglib import logging
from google3.testing.pybase import googletest
from google3.isp.fiber.testing.platform_testing.base_test_case import e2e_base
from google3.isp.fiber.testing.platform_testing.tools.connection import alu_connection
from google3.isp.fiber.testing.platform_testing.tools.fds_client import fds_client
from google3.isp.fiber.testing.platform_testing.tools.scm_client import scm_client
from google3.isp.fiber.testing.platform_testing.tools.telnet_client import telnet_client

flags.DEFINE_string('accounts_config_file', None, 'absolute path to csv_file '
                    '(with valid account numbers) and service plans')
flags.DEFINE_string('alu_bng_addr', None, 'Hostname of the BNG ')
flags.DEFINE_string('alu_bng_user', None, 'Username to login to BNG ')
flags.DEFINE_string('alu_bng_passwd', None, 'Password used when logging in '
                    'to BNG')

FLAGS = flags.FLAGS


class NetworkProvError(Exception):
  """Network Provision test related exception class."""


class NetworkProvTest(e2e_base.E2eBaseTestCase):
  """This test class performs CPE Device network provisioning test cases.

  Script name: adtran_network_prov_test.py

  Topology1:

          BNG
           |
          OLT (ADTRAN)
           |
          ONT------Network Box ------TV Box

  Topology2:

          BNG
           |
          OLT (ALU)
           |
          ONT------Network Box------TV Box

  Topology3:

          BNG
           |
          OLT (ALU/ADTRAN)
           |
          ONT------Network Box
                    ||
                    ||
       STG Box------  -----TV Box


  Test cases and steps:
   1) Get FDS Account from user provided accounts config file
   2) Verify Account in REGISTERED state
   3) Associate FJ with address using stubby call to FDS
   4) Login to SSCDU , Power up FJ
   5) Verify FREE service plan Provisioned on SCM
   6) Login to SSCDU , Power UP RG
   7) Verify RG gets added to the account
   8) Verify actual service gets provisioned on SCM
   9) Powerup TVBox and STGBox , based on service plan and RG
   10) Verify Account becomes active
   11) Verify Devices are added to the account
   12) Verify SLA profile on BNG matches with service plan

  Test Plan: Network Provisioning 2.0 Test Plan
  Test Plan Link:
  http://goto.google.com/network_provision_2.0_automation_test_plan
  """

  def setUp(self):
    self.server = 'staging'
    # config_file = resources.GetResourceFilename(self.yaml_config_str)
    self.config_file = FLAGS.tb_config_file
    if os.path.isfile(self.config_file):
      logging.info('User specified Config File: %s', self.config_file)
    else:
      logging.info('Locating yaml Config File %s ', self.config_file)
      self.config_file = ('/google/src/head/depot/google3/isp/fiber/testing'
                          '/platform_testing/test_bed_config/%s' %
                          self.config_file)
    with open(self.config_file, 'r') as f:
      test_config = yaml.safe_load(f)
    # Try to get the BNG hostname from user or , if not ,
    # set it runtime to staging BNG
    self.alu_bng_hostname = FLAGS.alu_bng_addr
    if not self.alu_bng_hostname:
      self.alu_bng_hostname = test_config['alu_bng_addr']

    self.alu_bng_user = FLAGS.alu_bng_user
    if not self.alu_bng_user:
      self.alu_bng_user = test_config['alu_bng_user']

    self.alu_bng_passwd = FLAGS.alu_bng_passwd
    if not self.alu_bng_passwd:
      self.alu_bng_passwd = test_config['alu_bng_passwd']

    self.jmp_name = FLAGS.jmp_host
    self.jmp_user = FLAGS.jmp_user
    self.jmp_pwd = FLAGS.jmp_pwd
    self.jmp_key = FLAGS.jmp_key
    self.jmp_key_passphrase = FLAGS.jmp_key_passphrase

    # Fetch account_number and service_plan from accounts_config file
    self.account_file = FLAGS.accounts_config_file
    if not self.account_file:
      self.account_file = test_config['accounts_config_file']
    if not os.path.isfile(self.account_file):
      raise NetworkProvError('Please Provide File With Test Accounts',
                             self.account_file)
    self.second_line = linecache.getline(self.account_file, 2)
    if not self.second_line:
      raise NetworkProvError('Test Accounts UnAvailable, Please Check',
                             self.account_file)

    # Using SED causes core dump on x20, whereas it works on google3,
    # but still moving to python from sed
    # *** glibc detected *** sed: double free or corruption
    # (!prev): 0x000000000087fb80 ***
    # if os.system("sed --in-place '2d' " + self.account_file):
    # raise NetworkProvError('Deleting Test Account From Test File Fails',
    # self.account_file)

    # Used account will be deleted from the accounts config file
    for line in fileinput.input(self.account_file, inplace=True):
      if fileinput.lineno() != 2:
        print line.rstrip('\n')

    self.account_number, self.service_plan = self.second_line.split(',')
    self.service_plan = self.service_plan.strip()
    logging.info('Subscriber Test Account and Test Service are : %s , %s',
                 self.account_number, self.service_plan)

    logging.info('Open A Handle To FDS and SCM')
    self.fiber_data_client = fds_client.FDSClient()
    self.scm_client = scm_client.SCMClient()

    # [self.account_init_state, 1] account in REGISTERED state
    self.account_init_state = 1
    # [self.account_final_state, 2] account in ACTIVE state
    self.account_final_state = 2
    # [self.initial_service_plan, 3], initial FREE service
    self.initial_service_plan = '3'
    # [self.final_sub_ser, $userprovided], actual subscriber service
    self.final_sub_ser = self.scm_client.convertServicePlanTONumber(
        self.service_plan)
    # Initialize stg box exist to 0, so that
    # later we dont have to do multiple checks
    self.is_stgb_exist = 0

    logging.info('# Test Setup : Login To SSCDU, POWERDOWN DUTs       ')
    self.pwrsupply_address = test_config['pwrsupply_addr']
    self.pwrsupply_user = test_config['pwrsupply_uname']
    self.pwrsupply_passwd = test_config['pwrsupply_passwd']
    self.pwrsupply_port = test_config['pwrsupply_tcp_port']
    self.pwrsupply_lgn_prmpt = test_config['pwrsupply_prompt']
    self.pwrsupply_lgn_tmout = test_config['pwrsupply_login_timeout']
    logging.info('Power Supply IP : %s , Username : %s , Port : %s'
                 'Login Prompt: %s , Login Timeout : %s',
                 self.pwrsupply_address, self.pwrsupply_user,
                 self.pwrsupply_port, self.pwrsupply_lgn_prmpt,
                 self.pwrsupply_lgn_tmout)
    self.telnet_power_supply = self.loginTOPowerSupply(self.pwrsupply_address,
                                                       self.pwrsupply_user,
                                                       self.pwrsupply_passwd,
                                                       self.pwrsupply_port,
                                                       self.pwrsupply_lgn_prmpt,
                                                       self.pwrsupply_lgn_tmout)
    self.ont_sn = str(test_config['ont_sn'])
    self.ont_fake_sn = self.getDeviceFakeSerialNumber('ONT')
    self.ont_pwr_outlet = test_config['ont_pwr_outlet']
    self.flipCpeDevicePower(self.telnet_power_supply, 'ONT', self.ont_sn, 'off',
                            self.ont_pwr_outlet, 5)
    self.r_status = self.checkAndReplaceDevIfExistInAcc(self.ont_sn,
                                                        self.ont_fake_sn, 'ONT')
    if all([self.r_status is True, self.r_status is not 0]):
      self.ont_fake_sn = self.getDeviceFakeSerialNumber('ONT')
    elif self.r_status is False:
      raise NetworkProvError('FDS - ONT Replacement Failed')
    logging.info('REAL ONT SN --> %s, FAKE ONT SN --> %s, POWER OUTLET --> %s',
                 self.ont_sn, self.ont_fake_sn, self.ont_pwr_outlet)

    self.rg_sn = str(test_config['rg_sn'])
    self.rg_fake_sn = self.getDeviceFakeSerialNumber('RG')
    self.rg_pwr_outlet = test_config['rg_pwr_outlet']
    self.flipCpeDevicePower(self.telnet_power_supply, 'RG', self.rg_sn, 'off',
                            self.rg_pwr_outlet, 5)
    self.r_status = self.checkAndReplaceDevIfExistInAcc(self.rg_sn,
                                                        self.rg_fake_sn, 'RG')
    if all([self.r_status is True, self.r_status is not 0]):
      self.rg_fake_sn = self.getDeviceFakeSerialNumber('RG')
    elif self.r_status is False:
      raise NetworkProvError('FDS - RG Replacement Failed')
    logging.info('REAL RG SN --> %s, FAKE RG SN --> %s, POWER OUTLET --> %s',
                 self.rg_sn, self.rg_fake_sn, self.rg_pwr_outlet)
    self.sn_lst = [self.ont_sn, self.rg_sn]

    # Check if service plan is TV and RG serial number not of GFRG210
    if self.final_sub_ser is '5' and not re.search(r'^GSA', self.rg_sn):
      self.stgb_sn = str(test_config['stgb_sn'])
      self.sn_lst.append(self.stgb_sn)
      self.stgb_fake_sn = self.getDeviceFakeSerialNumber('STGBox')
      self.stgb_pwr_outlet = test_config['stgb_pwr_outlet']
      self.flipCpeDevicePower(self.telnet_power_supply, 'STGBox', self.stgb_sn,
                              'off', self.stgb_pwr_outlet, 5)
      self.r_status = self.checkAndReplaceDevIfExistInAcc(self.stgb_sn,
                                                          self.stgb_fake_sn,
                                                          'STGBox')
      if all([self.r_status is True, self.r_status is not 0]):
        self.stgb_fake_sn = self.getDeviceFakeSerialNumber('STGBox')
      elif self.r_status is False:
        raise NetworkProvError('FDS - STGBox Replacement Failed')
      self.is_stgb_exist = 1
      logging.info('REAL STG BOX SN : %s, FAKE STG BOX SN : %s,'
                   'STGBOX POWER OUTLET: %s', self.stgb_sn, self.stgb_fake_sn,
                   self.stgb_pwr_outlet)
    # Check if service plan is TV
    if self.final_sub_ser == '5':
      self.tvb_sn = str(test_config['tvb_sn'])
      self.sn_lst.append(self.tvb_sn)
      self.tvb_fake_sn = self.getDeviceFakeSerialNumber('TVBox')
      self.tvb_pwr_outlet = test_config['tvb_pwr_outlet']
      self.flipCpeDevicePower(self.telnet_power_supply, 'TVBox', self.tvb_sn,
                              'off', self.tvb_pwr_outlet, 5)
      self.r_status = self.checkAndReplaceDevIfExistInAcc(self.tvb_sn,
                                                          self.tvb_fake_sn,
                                                          'TVBox')
      if all([self.r_status is True, self.r_status is not 0]):
        self.tvb_fake_sn = self.getDeviceFakeSerialNumber('TVBox')
      elif self.r_status is False:
        raise NetworkProvError('FDS - TVBox Replacement Failed')
      logging.info('REAL TV BOX SN --> %s, FAKE TV BOX SN --> %s'
                   'TVBox POWER OUTLET --> %s',
                   self.tvb_sn, self.tvb_fake_sn, self.tvb_pwr_outlet)

  @classmethod
  def setUpClass(cls):
    # this method overrides setUpClass method in base class
    pass

  def testNetworkProvision(self):
    logging.info('#===========================================================')
    logging.info('# Test Step 1: Verify Account [%s] in REGISTERED state',
                 self.account_number)
    logging.info('#=========================================================\n')
    act_rsp = self.fiber_data_client.GetAccountInfo(self.account_number)
    logging.info('Actual Response From FDS %s', act_rsp.account.account_state)
    logging.info('FDS Accounts Expected State %s', self.account_init_state)
    # Verify Account is in REGISTERED State
    if self.account_init_state == act_rsp.account.account_state:
      self.address_id = act_rsp.account.address_id + '0001'
      logging.info('Address Id Associated With Account [%s] is [%s] ',
                   self.account_number, self.address_id)
      logging.info('#=========================================================')
      logging.info('# Test Step 2: Add ONT [%s] To Account [%s]',
                   self.ont_sn, self.account_number)
      logging.info('#=========================================================')
      dev_add_status, dev_add_resp = self.fiber_data_client.AddDeviceToAccount(
          self.account_number, self.ont_sn)
      logging.info('ONT Add Status %s , %s', dev_add_status, dev_add_resp)
      # Verify device ONT added to the account successfully
      if dev_add_status:
        logging.info('#=======================================================')
        logging.info('# Test Step 3: Login to SSCDU,Power up ONT,wait 200 secs')
        logging.info('#=======================================================')
        self.flipCpeDevicePower(self.telnet_power_supply, 'ONT', self.ont_sn,
                                'on', self.ont_pwr_outlet, 200)
        logging.info('#=======================================================')
        logging.info('# Test Step 4: Verify FREE Service Provisioned On SCM   ')
        logging.info('#=======================================================')
        sp = self.scm_client.GetCircuits(self.address_id)
        # Verify Service Plan FREE is provisioned Initially
        if self.initial_service_plan == sp:
          logging.info('Subscriber Service - FREE Provisioned On SCM          ')
          logging.info('#=====================================================')
          logging.info('# Test Step 5: Power UP RG, wait till RG is up        ')
          logging.info('#=====================================================')
          self.flipCpeDevicePower(self.telnet_power_supply, 'RG', self.rg_sn,
                                  'on', self.rg_pwr_outlet, 240)
          # Here we have to wait static time, since gflog uploads data after
          # a minute and using timer also we have to wait for atleast a minute
          # before using timer
          # Check if Subscriber Service is TV, yes, then turn STG and TV Box on
          if self.final_sub_ser == '5':
            logging.info('#===================================================')
            if self.is_stgb_exist:
              logging.info('# Test Step 5a: Powerup STGBox Wait 120 Seconds   ')
              self.flipCpeDevicePower(self.telnet_power_supply, 'STGBox',
                                      self.stgb_sn, 'on', self.stgb_pwr_outlet,
                                      120)
              logging.info('# Test Step 5b: Powerup TVBox Wait 120 Seconds    ')
            else:
              logging.info('# Test Step 5a: Powerup TVBox Wait 120 Seconds    ')
              logging.info('#=================================================')
            self.flipCpeDevicePower(self.telnet_power_supply, 'TVBox',
                                    self.tvb_sn, 'on', self.tvb_pwr_outlet, 120)

          # Check service plan on SCM after RG added to the account
          logging.info('#=====================================================')
          logging.info('# Test Step 6: Verify SCM Has Actual Service Plan     ')
          logging.info('#=====================================================')
          sp = self.scm_client.GetCircuits(self.address_id)
          # Verify SCM has the final subscriber service provisioned
          if self.final_sub_ser == sp:
            logging.info('Provided SubscriberService %s Provisioned ON SCM', sp)
            logging.info('#===================================================')
            logging.info('# Test Step 7: Verify Account %s is ACTIVE',
                         self.account_number)
            logging.info('#===================================================')
            act_rsp = self.fiber_data_client.GetAccountInfo(self.account_number)
            if act_rsp.account.account_state == self.account_final_state:
              logging.info('#=================================================')
              logging.info('# Test Step 8: Verify All Device Exist In Account ')
              logging.info('#=================================================')
              self.dev_topo = self.fiber_data_client.GetDeviceTopology(
                  self.account_number, self.server)[1]
              self.dev_topo = self.fiber_data_client.RemoveDisconnectedDevices(
                  self.dev_topo)
              logging.info('Devices %s', self.dev_topo.devices)
              for device in self.dev_topo.devices:
                logging.info('Checking %s ', device.device_info.serial_number)
                if not device.device_info.serial_number:
                  continue
                if all([self.final_sub_ser == '5',
                        device.device_info.serial_number not in self.sn_lst]):
                  raise NetworkProvError('Device Not in Account',
                                         device.device_info.serial_number)
                if all([self.final_sub_ser in ['3', '4'],
                        device.device_info.serial_number not in self.sn_lst]):
                  raise NetworkProvError('Device Not In Account',
                                         device.device_info.serial_number)
              # BUG in RG where after sp upgrade, need to wait for 30 or so mins
              # or Reboot RG to get the new service, hence Rebooting RG
              if self.final_sub_ser != '3':
                self.telnet_power_supply = self.loginTOPowerSupply(
                    self.pwrsupply_address, self.pwrsupply_user,
                    self.pwrsupply_passwd, self.pwrsupply_port,
                    self.pwrsupply_lgn_prmpt, self.pwrsupply_lgn_tmout)
                self.flipCpeDevicePower(self.telnet_pwr_supply, 'RG',
                                        self.rg_sn, 'off', self.rg_pwr_outlet,
                                        5)
                self.flipCpeDevicePower(self.telnet_pwr_supply, 'RG',
                                        self.rg_sn, 'on', self.rg_pwr_outlet,
                                        200)
              # Login to BNG, verify sla profile name and subscriber existence
              logging.info('Logging In To BNG')
              self.alu_connect = alu_connection.AluSSHConnection(
                  self.alu_bng_hostname, user=self.alu_bng_user,
                  password=self.alu_bng_passwd, jmp_name=self.jmp_name,
                  jmp_user=self.jmp_user, jmp_password=self.jmp_pwd,
                  jmp_key=self.jmp_key,
                  jmp_key_passphrase=self.jmp_key_passphrase, timeout=60)
              bng_plan = self.scm_client.setBngProfPlan(sp)
              logging.info('BNG SLA Profile Should Be sla-prof-%s', bng_plan)
              active_subscriber = self.alu_connect.SendCmd(
                  'show service active-subscribers subscriber ' +
                  self.address_id + ' | match sla:sla-prof-' + bng_plan)
              logging.info('Active Subsriber SLA %s', active_subscriber)
              if (not active_subscriber) or (
                  'MINOR: CLI No Such Subscriber Found' in active_subscriber):
                logging.info('Active Subscriber Not Found On BNG')
                raise NetworkProvError('On BNG SLA Profile Not Found ',
                                       active_subscriber)
              # For now we complete here, later we have to add
              # If service plan is Free or Gig, add Speed test
              # If service plan is TV, add Speed test and tv channel change
            else:
              logging.info('In FDS, Account NOT ACTIVE %s', self.account_number)
              raise NetworkProvError('Account Should Have Been Active By'
                                     'Now,Pls Check', self.account_number)
          else:
            logging.info('Actual Service Not Pushed To SCM By FDS %s',
                         self.account_number)
            raise NetworkProvError('Actual Service Plan on SCM Dont Match',
                                   self.account_number)
        else:
          logging.info('Initial Service Plan On SCM Is %s', sp)
          raise NetworkProvError('Initial Service Plan On SCM Does Not'
                                 'Match For Account', self.account_number)
      else:
        logging.info('Could Not Add ONT  %s To Account %s ',
                     self.account_number, self.ont_sn)
        raise NetworkProvError('ONT Addition To Account Failed ',
                               self.account_number)
    else:
      logging.info('State Of Account In FDS %s Is %s', self.account_number,
                   self.account_init_state)
      raise NetworkProvError('In FDS, Account State IS NOT REGISTERED'
                             'Account Number Is', self.account_number)

  def tearDown(self):
    logging.info('#===========================================================')
    logging.info('# Cleanup Testbed: Replace Devices IN FDS, POWERDOWN DUTs   ')
    logging.info('#===========================================================')
    self.telnet_power_supply_off = self.loginTOPowerSupply(
        self.pwrsupply_address, self.pwrsupply_user, self.pwrsupply_passwd,
        self.pwrsupply_port, self.pwrsupply_lgn_prmpt,
        self.pwrsupply_lgn_tmout)

    # Replace real ONT with fake in fds account using fds api, SCM reprovision
    logging.info('Test ONT SN:%s,Fake ONT SN:%s', self.ont_sn, self.ont_fake_sn)
    if self.checkAndReplaceDevIfExistInAcc(self.ont_sn, self.ont_fake_sn,
                                           'ONT') is False:
      raise NetworkProvError('FDS - ONT Replacement Failed')
    reset_status, reset_resp = self.scm_client.ResetCircuit(self.address_id)
    if reset_status is False:
      raise NetworkProvError('SCM - Circuit Cud Not Be Reset', reset_resp)
    time.sleep(20)
    self.flipCpeDevicePower(self.telnet_power_supply_off, 'ONT', self.ont_sn,
                            'off', self.ont_pwr_outlet, 5)
    # Replace Real RG with fake in fds account using fds api
    logging.info('Test RG SN:%s,Fake RG SN:%s', self.rg_sn, self.rg_fake_sn)
    if self.checkAndReplaceDevIfExistInAcc(self.rg_sn, self.rg_fake_sn,
                                           'RG') is False:
      raise NetworkProvError('FDS - RG Replacement Failed')
    self.flipCpeDevicePower(self.telnet_power_supply_off, 'RG', self.rg_sn,
                            'off', self.rg_pwr_outlet, 5)
    # Replace Real STGBox with fake in fds account using fds api
    if self.is_stgb_exist:
      self.flipCpeDevicePower(self.telnet_power_supply, 'STGBox', self.stgb_sn,
                              'off', self.stgb_pwr_outlet, 240)
      if self.checkAndReplaceDevIfExistInAcc(self.stgb_sn, self.rg_stgb_fake_sn,
                                             'STGBox') is False:
        raise NetworkProvError('FDS - STGBox Replacement Failed')
        # Replace Real RG with fake in fds account using fds api
    if self.final_sub_ser is '5':
      self.flipCpeDevicePower(self.telnet_power_supply_off,
                              'TVBox', self.tvb_sn, 'off', self.tvb_pwr_outlet,
                              5)
      if self.checkAndReplaceDevIfExistInAcc(self.tvb_sn, self.rg_tvb_fake_sn,
                                             'TVBox') is False:
        raise NetworkProvError('FDS - TVBox Replacement Failed')
    logging.info('########### Test-bed CleanedUP Successfully ################')

  def loginTOPowerSupply(self, pwrsupply_ip, user_name, pass_word, tcp_port,
                         login_prompt, timeout=10):
    """Telnet to power supply.

    Args:
      pwrsupply_ip: pwr supply ip address
      user_name: username to login to power supply
      pass_word: password to login to power supply
      tcp_port: tcp port to be used when login
      login_prompt: expected login prompt
      timeout: login timeout, by default set to 10 seconds

    Returns:
      telnet_session: returns telnet session handle
    """
    telnet_session = telnet_client.TelnetClient(pwrsupply_ip, tcp_port, timeout,
                                                login_prompt, logger=logging)
    telnet_session.Login(user_name, pass_word)
    return telnet_session

  def flipCpeDevicePower(self, telnet_connect, device, device_sn, state, outlet,
                         wait_time):
    """Changes power state of the device.

    Args:
      telnet_connect: handle to telnet session
      device: ONT or RG or STG Box or TV Box
      device_sn: Device Serial Number
      state: on or off
      outlet: outlet id from the power supply
      wait_time: Wait time after changing power state

    """
    logging.info('Power %s Device %s With SN %s', state, device, device_sn)
    telnet_connect.SendCmd('%s %s' % (state, outlet))
    time.sleep(wait_time)

  def getRandomNumber(self, digit):
    """Generates Random Number With Number Digits Requested.

    Args:
      digit: Number of digits in random number, to be used for fake SN

    Returns:
      Returns generated random number.
    """
    start = 10**(digit-1)
    end = (10**digit)-1
    return randint(start, end)

  def getDeviceFakeSerialNumber(self, dev_type):
    """Generates Fake Serial Number For the Provided Device Type.

    Args:
     dev_type: Device type, ONT, RG, STGBox or TVBox

    Returns:
     dev_fake_sn: Device Fake Serial Number

    """
    fake_sn = {
        'ont': 'JAAG%s' % self.getRandomNumber(8),
        'rg': 'GSAFNS%sP0%s' % (self.getRandomNumber(4),
                                self.getRandomNumber(3)),
        'stgbox': 'G%s' % self.getRandomNumber(11),
        'tvbox': 'GTAFNS%sP1%s' % (self.getRandomNumber(4),
                                   self.getRandomNumber(3))
    }
    if dev_type.lower() in fake_sn:
      return fake_sn[dev_type.lower()]

  def checkAndReplaceDevIfExistInAcc(self, dev_sn, dev_fake_sn, dev_type):
    """Check if device exists in any account and replace if yes.

    Args:
      dev_sn: Device Serial Number
      dev_fake_sn: Device Fake Serial Number
      dev_type: Device type, ONT, RG, STGBox or TVBox

    Returns:
      In Successful returns status [True].
      If Replace failed, returns False.
      If device does not exist in any account, returns 0.
    """
    succ, result = self.fiber_data_client.GetDevices(dev_sn)
    self.assertTrue(succ, 'GetDevice RPC call failed on FDS.')
    account_temp = self.fiber_data_client.ParseDeviceAccountID(result)
    if account_temp is not None:
      dev_re_status, dev_re_resp = self.fiber_data_client.ReplaceDevice(
          account_temp, dev_sn, dev_fake_sn)
      logging.info('%s Replace Status %s , %s', dev_type, dev_re_status,
                   dev_re_resp)
      if dev_re_status:
        return dev_re_status
      else:
        return False
    else:
      return 0

if __name__ == '__main__':
  googletest.main()
