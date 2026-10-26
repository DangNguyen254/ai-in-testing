"""Report list: search and export. An older file: 4-space indent, single quotes, a star import
of the report helpers, and one test that runs another test's steps by calling it."""

import pytest

from framework.base_test import BaseTest
from framework.decorators import browsers, data_driven, environments
from framework.report_helpers import *


@browsers('chrome', 'firefox')
@environments('cloud', 'on_prem')
@data_driven
@pytest.mark.project('example-project')
@pytest.mark.component('reports')
class TestReportsList(BaseTest):
    def setup(self):
        self.base_setup(fresh_driver=False, policy_wait=False)

    @pytest.mark.priority('p2')
    @pytest.mark.suite('regression')
    def test_reports_list_search(self):
        reports = self.nav.reports.list
        reports.open()
        reports.search_text = self.params['query']
        reports.search()
        self.check.assertEqual(self.params['expected_names'], reports.report_names)

    @pytest.mark.priority('p3')
    @pytest.mark.suite('regression')
    def test_reports_list_count(self):
        reports = self.nav.reports.list
        reports.open()
        self.check.assertEqual(self.params['total'], reports.total_count)

    @pytest.mark.priority('p3')
    @pytest.mark.suite('regression')
    def test_reports_list_export(self):
        self.test_reports_list_search()
        reports = self.nav.reports.list
        reports.export()
        view = self.nav.reports.view
        self.check.assertEqual(report_title(self.params['expected_names'][0]), view.title)
