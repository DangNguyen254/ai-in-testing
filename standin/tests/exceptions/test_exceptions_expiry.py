"""Exception expiry dates. Each test keeps its data in a file named after it."""

import pytest

from framework.decorators import data_driven, environments, retry
from framework.waits import retry_until
from tests.exceptions.exceptions_common import ExceptionsCommon


@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("exceptions")
class TestExceptionsExpiry(ExceptionsCommon):
   def setup_method(self, method):
      self.expiry_format = "YYYY-MM-DD"

   def teardown_method(self, method):
      self.expiry_format = None

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_exceptions_expiry_shown(self):
      exceptions = self.nav.exceptions.list
      exceptions.open()
      shown = retry_until(lambda: exceptions.expires_of(self.unique_name(24)))
      self.check.assertEqual(self.params["expires"], shown)

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_exceptions_expiry_never(self):
      exceptions = self.nav.exceptions.list
      exceptions.open()
      self.check.assertEqual("never", exceptions.expires_of(self.unique_name(24)))

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   @retry(times=1)
   def test_exceptions_expiry_edit(self):
      editor = self.open_exception(self.unique_name(24))
      editor.expires = self.params["new_expires"]
      editor.save()
      self.nav.top_bar.save()
      self.nav.top_bar.publish()
      self.verify_targets()
