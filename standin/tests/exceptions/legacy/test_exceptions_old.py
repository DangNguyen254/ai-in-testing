# Python 2 leftover from before the migration; not collected (see conftest.py).
from framework.base_test import BaseTest


class TestExceptionsOld(BaseTest):
   def test_exceptions_old_list_loads(self):
      print "exceptions list"
      exceptions = self.nav.exceptions.list
      exceptions.open()
