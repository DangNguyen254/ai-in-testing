"""Settings: timezone, language, and notification preferences."""

from __future__ import annotations

import pytest

from framework.base_test import BaseTest


@pytest.mark.project("example-project")
@pytest.mark.component("settings")
class TestSettings(BaseTest):
    @pytest.mark.priority("p2")
    @pytest.mark.suite("regression")
    @pytest.mark.parametrize("timezone", ["UTC", "Europe/Berlin"])
    def test_change_timezone(self, timezone: str) -> None:
        general = self.nav.settings.general.open()
        general.set_timezone(timezone).save()

        assert general.flash_message == "Settings saved"
        self.assert_backend(self.expected["backend"])

    @pytest.mark.priority("p3")
    @pytest.mark.suite("regression")
    def test_change_language(self) -> None:
        general = self.nav.settings.general.open()
        general.set_language(self.inputs["language"]).save()

        self.assert_backend(self.expected["backend"])

    @pytest.mark.priority("p2")
    @pytest.mark.suite("regression")
    def test_disable_email_notifications(self) -> None:
        notifications = self.nav.settings.notifications.open()
        notifications.set_email(False).save()

        assert notifications.flash_message == "Settings saved"
        self.assert_backend(self.expected["backend"])

    @pytest.mark.priority("p3")
    @pytest.mark.suite("regression")
    def test_enable_weekly_digest(self) -> None:
        notifications = self.nav.settings.notifications.open()
        notifications.set_weekly_digest(True).save()

        self.assert_backend(self.expected["backend"])

    @pytest.mark.priority("p1")
    @pytest.mark.suite("smoke")
    def test_timezone_persists_after_reload(self) -> None:
        general = self.nav.settings.general.open()
        general.set_timezone(self.inputs["timezone"]).save()
        general.open()

        assert general.selected_timezone() == self.inputs["timezone"]
        self.assert_backend(self.expected["backend"])
