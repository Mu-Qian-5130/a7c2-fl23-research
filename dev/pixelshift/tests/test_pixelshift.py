"""Synthetic RAW contracts and optional original-firmware instruction replays."""
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from raw_group import inspect, validate


def synthetic_raw(order='<', *, group=123, shot=1, count=4, prefixed=False):
    data = bytearray(512)
    data[:8] = (b'II' if order == '<' else b'MM') + struct.pack(order + 'HI', 42, 8)

    def directory(at, entries):
        struct.pack_into(order + 'H', data, at, len(entries))
        for i, entry in enumerate(entries):
            struct.pack_into(order + 'HHII', data, at + 2 + 12 * i, *entry)

    model = b'ILCE-7CM2\0'
    data[48:48 + len(model)] = model
    directory(8, [(272, 2, len(model), 48), (34665, 4, 1, 80)])
    directory(80, [(33434, 5, 1, 160), (33437, 5, 1, 168),
                   (34855, 3, 1, 100), (37500, 7, 128, 200)])
    struct.pack_into(order + 'IIII', data, 160, 1, 125, 28, 10)
    start = 200
    if prefixed:
        data[200:212] = b'SONY DSC \0\0\0'
        start += 12
    directory(start, [(0x202f, 7, 6, 300), (0xb048, 8, 1, 0)])
    struct.pack_into(order + 'IBB', data, 300, group, shot, count)
    return bytes(data)


def rows():
    return [{'file': 'frame' + str(n) + '.ARW', 'model': 'ILCE-7CM2',
             'pixel_shift': {'group_id': 8, 'shot': n, 'count': 4},
             'exposure_fields': {'33434': '01', '33437': '02', '34855': '03'}}
            for n in range(1, 5)]


class RawTests(unittest.TestCase):
    def test_both_byte_orders_and_bare_or_prefixed_makernotes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.ARW'
            for order in ('<', '>'):
                for prefixed in (False, True):
                    path.write_bytes(synthetic_raw(order, prefixed=prefixed))
                    actual = inspect(path)
                    self.assertEqual(actual['model'], 'ILCE-7CM2')
                    self.assertEqual(actual['pixel_shift'], {'group_id': 123, 'shot': 1, 'count': 4})

    def test_normal_zero_metadata_is_not_a_shifted_image(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'burst.ARW'
            path.write_bytes(synthetic_raw(group=0, shot=0, count=0))
            self.assertIsNone(inspect(path)['pixel_shift'])

    def test_truncated_payload_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.ARW'
            path.write_bytes(synthetic_raw()[:302])
            with self.assertRaises(ValueError):
                inspect(path)

    def test_unordered_sources_are_sorted_without_claiming_hardware(self):
        data = rows()[::-1]
        report = validate(data)
        self.assertEqual(report['ordered_files'], [f'frame{n}.ARW' for n in range(1, 5)])
        self.assertFalse(report['physical_shift_verified'])
        self.assertFalse(report['composition_verified'])
        self.assertEqual(data, rows()[::-1])

    def test_normal_burst_cannot_pass_by_merely_having_four_files(self):
        data = rows()
        data[0]['pixel_shift'] = None
        with self.assertRaisesRegex(ValueError, 'Ordinary burst'):
            validate(data)

    def test_missing_duplicate_composite_or_sixteen_shot_sources_fail(self):
        for field, value in [('shot', 0), ('shot', 2), ('count', 16), ('group_id', 99)]:
            data = rows()
            data[0]['pixel_shift'][field] = value
            with self.assertRaises(ValueError):
                validate(data)
        with self.assertRaises(ValueError):
            validate(rows()[:3])

    def test_exposure_changes_missing_fields_mixed_models_and_repeated_paths_fail(self):
        cases = []
        data = rows(); data[0]['exposure_fields']['34855'] = 'different'; cases.append(data)
        data = rows(); del data[0]['exposure_fields']['33434']; cases.append(data)
        data = rows(); data[0]['model'] = 'ILCE-7CR'; cases.append(data)
        data = rows(); data[0]['file'] = data[1]['file']; cases.append(data)
        for case in cases:
            with self.assertRaises(ValueError):
                validate(case)


class DisplacementTests(unittest.TestCase):
    def test_independent_analytic_scene_has_expected_fractional_motion(self):
        import numpy as np
        from displacement import translation, square_evidence
        rng = np.random.default_rng(7)
        fy, fx = rng.uniform(-0.3, 0.3, (2, 60))
        phase = rng.uniform(0, 2 * np.pi, 60)
        yy, xx = np.indices((128, 128))

        def scene(y, x):
            return np.sin(2 * np.pi * ((yy[..., None] - y) * fy +
                                       (xx[..., None] - x) * fx) + phase).sum(axis=2)

        reference = scene(0, 0)
        positions = []
        for dy, dx in [(0, 0), (0.5, 0), (0.5, 0.5), (0, 0.5)]:
            measured = translation(reference, scene(dy, dx))
            np.testing.assert_allclose(measured, [-dy, -dx], atol=0.04)
            positions.append(2 * measured)  # green sampling has two-RAW-pixel spacing
        report = square_evidence(positions)
        self.assertTrue(report['consistent_with_one_pixel_square'])
        self.assertFalse(report['physical_actuator_verified'])
        self.assertFalse(report['settling_verified'])

    def test_no_motion_wrong_spacing_and_bad_frame_do_not_pass(self):
        from displacement import square_evidence
        for positions in [[[0, 0]] * 4,
                          [[0, 0], [0, 2], [2, 2], [2, 0]],
                          [[0, 0], [0, 1], [1, 1], [7, 3]]]:
            self.assertFalse(square_evidence(positions)['consistent_with_one_pixel_square'])


FIRMWARE = os.environ.get('A7C2_PIXELSHIFT_FIRMWARE_ROOT')


@unittest.skipUnless(FIRMWARE, 'Needs private C2/A7CR original firmware, never USB')
class NativeTests(unittest.TestCase):
    def setUp(self):
        self.c2 = Path(FIRMWARE) / 'a7c2-2.01/components'
        self.cr = Path(FIRMWARE) / 'a7cr-support/components'

    def test_rtti_and_direct_sequence_wrapper_builder_chain(self):
        from audit import audit
        for directory, expected in [(self.c2, 'ILCE-7CM2'), (self.cr, 'ILCE-7CR')]:
            report = audit(directory)
            self.assertEqual(report['profile']['model'], expected)
            self.assertEqual(report['generic_capture_command'], '0x4036')
            self.assertTrue(report['generic_command_is_not_proof_of_pixel_shift'])

    def test_original_four_sixteen_selection_has_identical_18_cases(self):
        from native_replay import select_sequence
        for mode, count in [(1, 4), (2, 16)]:
            for interval in range(9):
                c2 = select_sequence(self.c2, mode, interval)
                cr = select_sequence(self.cr, mode, interval)
                self.assertEqual(c2, cr)
                self.assertEqual(c2['shots'], count)
                self.assertEqual(c2['interval_native_value'], [500, 1000, 2000, 3000, 4000, 5000, 10000, 15000, 30000][interval])
                self.assertEqual(c2['external_calls_executed'], 0)

    def test_original_generic_packets_have_identical_44_cases(self):
        from native_replay import packet
        for mode in range(11):
            for ident, aux in [(0, 0), (1, 1), (0x12345678, 0x87654321), (0xffffffff, 0xffffffff)]:
                c2 = packet(self.c2, mode, ident, aux)
                cr = packet(self.cr, mode, ident, aux)
                self.assertEqual(c2['packet'], cr['packet'])
                self.assertFalse(c2['send_executed'])
                self.assertEqual(c2['trace_calls_omitted'], 1)

    def test_original_trinity_setup_and_cp_assignment_match_20_cases(self):
        from trinity_replay import compare
        cases = compare(self.c2, self.cr)
        self.assertEqual(len(cases), 20)
        for case in cases:
            raw = bytes.fromhex(case['ap']['packet'])
            self.assertEqual(struct.unpack_from('<H', raw, 2)[0], 0x40ee)
            self.assertFalse(case['ap']['send_executed'])
            self.assertEqual(case['ap']['trace_calls_omitted'], 1)
            self.assertEqual(case['cp']['external_calls_executed'], 0)
            self.assertFalse(case['cp']['actuator_executed'])
            if case['input'].get('test'):
                self.assertEqual(raw[8:10], b'\x01\x01')
            elif case['input']['mode']:
                self.assertEqual(raw[8], 1)
                self.assertEqual(raw[9], {1: 4, 2: 16}[case['input']['mode']])
            else:
                self.assertEqual(raw[8:], b'\0' * 4)

    def test_original_cp_metadata_matches_63_cases(self):
        from cp_metadata_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 63)
        for case in report['cases']:
            self.assertFalse(case['target']['physical_frame_produced'])
            self.assertEqual(case['target']['external_calls'], 0)

    def test_original_cp_mode_formation_and_consistency_match_63_cases(self):
        from cp_capture_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 63)
        self.assertFalse(report['physical_shift_verified'])
        self.assertFalse(report['settling_verified'])
        for case in report['cases']:
            self.assertEqual(case['target'], case['reference'])
            self.assertEqual(case['target']['hardware_calls'], 0)
            if case['kind'] == 'selection':
                self.assertTrue(case['target']['configuration_inputs_synthetic'])
                if case['input']['mode'] == 2 and case['input']['flag_d88'] and not case['input']['native_state']:
                    self.assertEqual(case['target']['mode'], 23)
            elif case['input']['mode'] == 23:
                self.assertEqual(case['target']['trinity'], case['input']['trinity'])
                self.assertEqual(case['target']['diagnostic_calls_omitted'], 0)

    def test_native_steady_capture_timer_is_a_delay_request_not_a_position_ack(self):
        from cp_timing_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 8)
        self.assertFalse(report['settling_verified'])
        for case in report['cases']:
            self.assertEqual(case['target'], case['reference'])
            expected = max(1, case['exposure_offset_us'] - 9000) if case['exposure_offset_us'] != 9000 else 0
            self.assertEqual(case['target']['delay_us'], expected)
            self.assertFalse(case['target']['timer_api_executed'])
            self.assertFalse(case['target']['actuator_acknowledgement_verified'])

    def test_original_capability_descriptors_match_52_cases(self):
        from capability_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 52)
        change = report['emulated_one_field_change']
        self.assertEqual(change['before']['slot'], 9)
        self.assertFalse(change['before']['support'])
        self.assertTrue(change['after']['support'])
        self.assertFalse(report['installable'])
        for case in report['cases']:
            self.assertFalse(case['reference']['model_identity_inferred'])
            self.assertEqual(case['target']['external_calls_executed'], 0)

    def test_original_sequence_creation_and_clear_boundaries_match_22_cases(self):
        from lifecycle_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 22)
        self.assertFalse(report['installable'])
        self.assertFalse(report['centering_verified'])
        for case in report['cases']:
            result = case['target']
            if case['kind'] == 'enqueue_gate':
                expected = 'request_allocation' if case['enabled'] else 'returned_without_request'
                self.assertEqual(result['boundary'], expected)
                self.assertFalse(result['allocation_executed'])
                self.assertEqual(result['mutex_calls_omitted'], 2)
            elif case['kind'] == 'creator_request':
                self.assertEqual(result['sequence_id'], 0x4bd)
                self.assertTrue(result['native_manager_verified'])
                self.assertFalse(result['construction_executed'])
            elif case['kind'] == 'clear_packet':
                packet = bytes.fromhex(result['packet'])
                self.assertEqual(struct.unpack_from('<H', packet, 2)[0], 0x40ef)
                self.assertFalse(result['transport_executed'])
            else:
                self.assertEqual(result['callback'], 'TrinityShotEnd')
                self.assertFalse(result['service_executed'])
                self.assertFalse(result['callback_executed'])

    def test_original_cp_dispatcher_handles_ap_mode_packets_in_80_paired_cases(self):
        from cp_dispatch_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 80)
        self.assertFalse(report['camera_io'])
        self.assertFalse(report['installable'])
        for case in report['cases']:
            args, result = case['dispatch_input'], case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['check_executed'], args['source_id'] == 0x80020002)
            self.assertTrue(result['handler_executed'])
            self.assertTrue(result['notification_flag_setter_executed'])
            self.assertEqual(result['parameter_changed_flag'], 1)
            self.assertFalse(result['capture_executed'])

    def test_pixel_shift_retains_first_frame_sequence_in_64_paired_cases(self):
        from cp_sequence_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 64)
        self.assertFalse(report['physical_shift_verified'])
        for case in report['cases']:
            args, result = case['input'], case['target']
            if args['mode'] == 23:
                self.assertEqual(result['sequence_index'], 4 if args['first_flag'] else 9)
            self.assertFalse(result['configuration_executed'])
            self.assertFalse(result['callback_executed'])

    def test_dispatched_mode_reaches_capture_snapshot_via_native_memcpy(self):
        from cp_config_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 8)
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertTrue(result['native_copy_executed'])
            self.assertEqual(result['copied_bytes'], 0xd64)
            self.assertTrue(result['configuration_snapshot_equal'])
            self.assertEqual(result['capture_configuration_trinity'], result['mode_dispatch']['mode'])
            self.assertFalse(result['scheduler_between_entries_executed'])
            self.assertFalse(result['capture_executed'])

    def test_individual_option_support_is_separate_from_parent_support(self):
        from option_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 78)
        change = report['emulated_c2_four_shot_options']
        self.assertEqual([r['visible_by_model'] for r in change['before']], [False, False, False])
        self.assertEqual([r['visible_by_model'] for r in change['after']], [True, True, False])
        self.assertFalse(change['strict_value_two']['visible_by_model'])
        self.assertEqual([r['slot'] for r in change['before']], [9, 9, 9])
        self.assertEqual([r['value'] for r in change['before']], [0, 1, 2])
        self.assertFalse(report['installable'])
        self.assertFalse(report['physical_shift_verified'])

    def test_invalid_native_selection_stops_at_unhandled_path(self):
        from native_replay import select_sequence
        for mode, interval in [(1, 9), (2, 99), (0, 0)]:
            with self.assertRaises(ValueError):
                select_sequence(self.c2, mode, interval)

    def test_parameter_definition_is_separate_from_menu_support_and_value_validation(self):
        from eligibility_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['original_instruction_cases'], 26)
        self.assertFalse(report['target']['defined'])
        self.assertEqual(report['reference']['allowed_values'], [1, 1, 1])
        self.assertEqual(report['native_classification'], dict(c2=False, reference=True, emulated_c2=True))
        for case in report['value_cases']:
            self.assertTrue(case['c2'])  # The permissive fallback does not mean the feature exists.
            self.assertEqual(case['reference'], case['value'] in (0, 1, 2))
            self.assertEqual(case['emulated_c2'], case['reference'])
        init = report['initialization_notifications']
        self.assertEqual([r['inhibited_item'] for r in init['original']], ['0x28c', '0x2927', '0x2928', '0x2929'])
        self.assertEqual(init['emulated_definition'], [])
        self.assertFalse(init['notifier_executed'])
        self.assertFalse(report['installable'])

    def test_native_exclusion_rules_allow_pasm_but_inhibit_auto(self):
        from eligibility_replay import c2_rules
        rules = c2_rules(self.c2)
        self.assertEqual(len(rules), 10)
        exposure = next(r for r in rules if r['name'] == 'PRM_exposure_mode')
        by_name = {r['name']: r['effects'] for r in exposure['values']}
        for mode in ('P', 'A', 'S', 'M'):
            self.assertEqual(by_name['VAL_exposure_mode_EXPOSURE_MODE_STILL_' + mode], [])
        self.assertTrue(any(e['kind'] == 6 and e['operand_a'] == '0x28c'
                            for e in by_name['VAL_exposure_mode_EXPOSURE_MODE_STILL_AUTO']))


if __name__ == '__main__':
    unittest.main()
