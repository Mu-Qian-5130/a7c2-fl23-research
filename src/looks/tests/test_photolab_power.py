"""Explicit owner power confirmation never invents a battery percentage."""
import unittest
from looktool import photobuild, photolab


class ReachedBackupRead(Exception):
    pass


class PhotoLabPowerTests(unittest.TestCase):
    def invoke(self, battery, confirmed=False, revision=None):
        lab=object.__new__(photolab.Lab)
        lab.load=lambda: None
        lab.state={'phase':'PREFLIGHT_VERIFIED',
                   'runtime_patch_revision':photobuild.REVISION if revision is None else revision}
        def original():raise ReachedBackupRead()
        lab.original=original
        return photolab.Lab.install.__wrapped__(lab,battery,power_confirmed=confirmed)

    def test_missing_power_confirmation_stops_before_backup_or_camera(self):
        with self.assertRaises(ValueError):self.invoke(None)

    def test_explicit_adequate_power_needs_no_invented_percentage(self):
        with self.assertRaises(ReachedBackupRead):self.invoke(None,True)

    def test_reported_percentage_still_works(self):
        with self.assertRaises(ReachedBackupRead):self.invoke(80)

    def test_explicit_low_percentage_is_not_overridden(self):
        with self.assertRaises(ValueError):self.invoke(20,True)

    def test_boolean_is_not_a_percentage(self):
        with self.assertRaises(ValueError):self.invoke(True)

    def test_text_is_not_silently_converted_to_a_percentage(self):
        with self.assertRaises(ValueError):self.invoke('plenty')

    def test_confirmation_does_not_bypass_builder_revision(self):
        with self.assertRaisesRegex(ValueError,'builder changed'):self.invoke(None,True,'old')
