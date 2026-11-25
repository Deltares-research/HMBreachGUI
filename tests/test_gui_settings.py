import unittest

from GUI.app import CaseWindow
from GUI.case_io import load_case
from GUI.prototype import ROOT


def select(combo, value):
    for index, (_label, current) in enumerate(combo._choice_values):
        if type(current) is type(value) and current == value:
            combo.current(index)
            return
    raise AssertionError(f"Missing selection: {value!r}")


class SettingsEditorTests(unittest.TestCase):
    def setUp(self):
        self.window = CaseWindow()
        self.window.withdraw()

    def tearDown(self):
        self.window.update_idletasks()
        self.window.destroy()

    def test_round_trip_explicit_settings_and_width_geometry(self):
        original = load_case(ROOT / "examples" / "turbulence_input.json")
        original["initial_conditions"]["initial_width_m"] = 1.0
        original["settings"].update({
            "width_model": "geometry",
            "width_geometry": [{"s_m": 1.0, "width_m": 1.5}],
            "physical_constants": {"g": 9.7, "erosion_variant": "variant_1", "phi_deg": 31},
            "model_options": {"max_steps": 100000, "adaptive_step_sizing": True},
        })
        self.window.editor.set_case(original)
        self.assertEqual(self.window.editor.case(), original)

    def test_width_settings_and_integer_validation(self):
        editor = self.window.editor
        settings = editor.settings
        select(settings.mode, "breach")
        select(settings.width_model, "b_fit")
        select(settings.fit_type, "poly2")
        settings.fit_iterations.set("120")
        editor.initial_fields["initial_width_m"].set("1")
        for row, width in zip(editor.table.get_children(), ("1.2", "1.4")):
            values = list(editor.table.item(row, "values"))
            values[8] = width
            editor.table.item(row, values=values)
        case = editor.case()
        self.assertEqual(case["settings"]["mode"], "breach")
        self.assertEqual(case["settings"]["width_fit_type"], "poly2")
        self.assertEqual(case["settings"]["width_fit_max_iterations"], 120)
        self.assertEqual([layer["flow_width_m"] for layer in case["layers"]], [1.2, 1.4])

        settings.option_fields["max_steps"].set("1.5")
        with self.assertRaisesRegex(ValueError, "integer"):
            editor.case()

    def test_width_geometry_and_invalid_constants_preserve_input(self):
        editor = self.window.editor
        settings = editor.settings
        select(settings.width_model, "geometry")
        editor.initial_fields["initial_width_m"].set("1")
        settings.add_width_point()
        item = settings.width_table.get_children()[0]
        settings.width_table.item(item, values=("1", "2"))
        self.assertEqual(
            editor.case()["settings"]["width_geometry"],
            [{"s_m": 1.0, "width_m": 2.0}],
        )
        settings.physical_fields["g"].set("bad")
        with self.assertRaisesRegex(ValueError, "Gravity"):
            editor.case()
        self.assertEqual(settings.physical_fields["g"].get(), "bad")


if __name__ == "__main__":
    unittest.main()
