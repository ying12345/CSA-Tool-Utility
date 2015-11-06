__author__ = 'tianheng'

import time
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.alert import Alert
from selenium.webdriver.support.ui import Select
import re


class Functions:

    def __init__(self, *args):
        self.driver = webdriver.Chrome('/Users/tianheng/Downloads/chromedriver')
        self.account_id = args[0]
        self.fj_num_id = args[1]

    def csa(self, account_id):
        self.account_id = account_id
        self.driver.get('https://gfiber-support-staging.corp.google.com/fiber/AccountView?account_id='+self.account_id)
        WebDriverWait(self.driver, 120).until(EC.title_is('Customer Support'))

    def acs(self):
        self.driver.get('https://gfiber-acs-staging.corp.google.com/account/'+self.account_id)
        WebDriverWait(self.driver, 120).until(EC.title_is('Google Fiber Fleet Dashboard'))

    def csa_contact_page(self):

        self.driver.get('https://gfiber-support-staging.corp.google.com/fiber/#page=contacts_tab')
        WebDriverWait(self.driver, 120).until(EC.title_is('Customer Support'))

    def user_by_email_search(self, username):
        search_user_box_xpath = "//input[@placeholder='Email']"
        search_user_box = self.driver.find_element_by_xpath(search_user_box_xpath)
        search_user_box.send_keys(username)
        search_user_box.submit()

    def get_gaia_id(self):
        xpath_gaia = "//tbody[@id = 'gaia_info_table_expander_body']/tr[1]/td[2]"
        if "GetAccessReason" in self.driver.current_url:
            self.input_reason_box_submit()
            status_output = self.check_account_status()
            return status_output
        else:
            WebDriverWait(self.driver, 120).until(EC.presence_of_element_located((By.XPATH, xpath_gaia)))
            gaia_id = self.driver.find_element_by_xpath(xpath_gaia).text
            return gaia_id

    def check_account_status(self):
        table_id = "portal_account_info_table_expander_body"
        WebDriverWait(self.driver, 120).until(EC.presence_of_element_located((By.ID, table_id)))
        text_account_id = self.driver.find_element_by_id(table_id).text.splitlines()[0]
        text_account_status = self.driver.find_element_by_id(table_id).text.splitlines()[1]
        text_email = self.driver.find_element_by_id(table_id).text.splitlines()[3]
        status_output = text_account_id+" "+text_account_status+" "+text_email
        return status_output

    def check_account_id(self):
        self.input_reason_box_submit()
        table_id = "portal_account_info_table_expander_body"
        WebDriverWait(self.driver, 120).until(EC.presence_of_element_located((By.ID, table_id)))
        text_account_id = self.driver.find_element_by_id(table_id).text.splitlines()[0]
        text_account_id = re.search(r'\d+', text_account_id).group()
        return text_account_id

    def click_address_tab(self):
        time.sleep(3)
        WebDriverWait(self.driver, 120).until(EC.presence_of_element_located((By.ID, 'address_tab_link')))
        address_tab = self.driver.find_element_by_id('address_tab_link')
        ActionChains(self.driver).click(address_tab).perform()

    def click_install_tab(self):
        time.sleep(5)  # for page to load completely, otherwise it'll throw no such element exception
        # when try to locate the element
        install_tab = self.driver.find_element_by_id('installation_tab_link')
        ActionChains(self.driver).click(install_tab).perform()

    def check_address_id(self):
        self.input_reason_box_submit()
        self.click_address_tab()
        text_address_id = ""
        xpath = "//tbody[@id='portal_address_info_table_expander_body']/tr[2]/td[2]"
        WebDriverWait(self.driver, 120).until(EC.presence_of_element_located((By.XPATH, xpath)))
        while 1:
            if self.driver.find_element_by_xpath(xpath).text == "":
                print(self.driver.find_element_by_xpath(xpath).text)
                continue
            else:
                text_address_id = self.driver.find_element_by_xpath(xpath).text
                break
        return text_address_id

    def input_reason_box_submit(self):
        reason_box = self.driver.find_element_by_name('reason')
        reason_box.send_keys('a')
        reason_box.submit()

    def input_qr_box_submit(self,fj_num):
        self.fj_num_id = fj_num
        qr_box = self.driver.find_element_by_xpath("//tbody[@id='install_new_devices_table_expander_body']/tr[2]/td[1]")
        ActionChains(self.driver).move_to_element(qr_box).click(qr_box).send_keys('?sn='+self.fj_num_id).perform()
        save_bottom = self.driver.find_element_by_xpath("//input[@type='button'][@value='Save'][@onclick='validateSerialNumbers()']")
        save_bottom.click()

    def fj_verification(self):
        time.sleep(3)
        xpath1 = "//tbody[@id='plan_devices_table_installation_tab_expander_body']/tr[2]"
        WebDriverWait(self.driver, 120).until(EC.presence_of_element_located((By.XPATH, xpath1)))
        fj_num_text = self.driver.find_element_by_xpath(xpath1).text
        if self.fj_num_id in fj_num_text:
            print('Fiber Jacket has been added.')
            print('FJ matches')
            return 1
        else:
            print('The SN is mismatch, Please check.')
            return 0