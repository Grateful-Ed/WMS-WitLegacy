import unittest

from helpers import HostCase, DAY
from legacy_wms.tui import App, ScriptedTerminal, W


class TuiTests(HostCase):
    def run_keys(self, keys):
        term = ScriptedTerminal(keys)
        App(self.h, term, lambda: DAY).run()
        return term

    def test_screens_are_80_columns_and_have_a_menu(self):
        term = self.run_keys(["F3"])
        self.assertIn("MAIN MENU", term.screens[0])
        for scr in term.screens:
            self.assertTrue(all(len(x) <= W for x in scr.splitlines()))
        self.assertIn("11. BATCH CONTROL", term.screens[0])

    def test_online_putaway_changes_host_and_saves(self):
        t = self.run_keys(["2", "SKU-1003", "60", "PAL-001", "ZA-01-03", "W-03", "",  # putaway
                           "F3"])
        self.assertIn("ACT ACCEPTED", t.text())
        self.assertEqual(self.reload().get("PAL", "PAL-001")["PLST"], "PC")

    def test_online_reject_shows_code_text(self):
        t = self.run_keys(["2", "SKU-1003", "61", "PAL-001", "ZA-01-03", "W-03", "", "F3"])
        self.assertIn("REJECT B06 INSUFFICIENT STOCK", t.text())

    def test_f12_backs_out_of_a_form(self):
        t = self.run_keys(["1", "ASN-1003", "F12", "F3"])
        self.assertNotIn("ACT ACCEPTED", t.text())

    def test_operator_runs_batch_and_sees_gap_alarm(self):
        self.drop(3, [dict(ACT="RLSE", DOC="SO-5005")])
        t = self.run_keys(["11", "1", "", "4", "", "F12", "F3"])
        self.assertIn("HELD 1", t.text())
        self.assertIn("A01", t.text())
        self.assertIn("EXPECTED 1 GOT 3", t.text())

    def test_batch_menu_extract_and_queues(self):
        t = self.run_keys(["11", "3", "", "8", "", "F12", "F3"])
        self.assertIn("23 EXTRACT FILES WRITTEN", t.text())
        self.assertIn("OUT", t.text())


if __name__ == "__main__":
    unittest.main()
