__author__ = 'tianheng'

import time
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from utility.modules import Functions as func
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.alert import Alert
from selenium.webdriver.support.ui import WebDriverWait as wait
import sys
num_lines = sum(1 for line in open('email'))
print(num_lines)
# first argument is for account_id, second one is for fj serial number.
test = func("", "")
# with open('fj') as fj, open('account') as account:
#     for fj_line, account_line in zip(fj, account):
#         account_id = account_line.rstrip()
#         fj_num = fj_line.rstrip()
#         test.csa(account_id)
#         if "GetAccessReason" in test.driver.current_url:
#             test.input_reason_box_submit()
#         test.click_install_tab()
#         test.input_qr_box_submit(fj_num)
#         test.fj_verification()

for line in open('email'):
    test.csa_contact_page()
    user_email = line.rstrip()
#     # print(user_email)
    test.user_by_email_search(user_email)
    test.get_gaia_id()
    account_id = test.check_account_id()
#     # address_id = test.check_address_id()
#     print(account_id)
#     # print(address_id)