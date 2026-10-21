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

    def test_capture_activation_is_separate_from_trigger_preparation(self):
        from native_replay import capture_packet
        for mode, wire_mode in enumerate((2, 10, 12, 8, 9, 3)):
            for ident, auxiliary in ((0, 0), (1, 1), (0x12345678, 0x87654321),
                                     (0xffffffff, 0xffffffff)):
                a = capture_packet(self.c2, mode, ident, auxiliary)
                b = capture_packet(self.cr, mode, ident, auxiliary)
                self.assertEqual(a['packet'], b['packet'])
                self.assertEqual(a['routing'], 0x90040193)
                self.assertEqual(a['routing'], b['routing'])
                raw = bytes.fromhex(a['packet'])
                self.assertEqual(struct.unpack('<BBHIB3xI', raw),
                                 (5, 0, 0x4038, ident, wire_mode, auxiliary))
                self.assertEqual(a['trace_calls_omitted'], 2)
                self.assertEqual(b['trace_calls_omitted'], 2)
                self.assertFalse(a['send_executed'])
                self.assertFalse(b['send_executed'])
        for directory in (self.c2, self.cr):
            with self.assertRaisesRegex(ValueError, 'bounded instruction/memory model'):
                capture_packet(directory, 6, 0, 0)

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

    def test_mode23_callbacks_dispatch_stages_before_child_execution(self):
        from cp_stage_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 19)
        self.assertTrue(report['separate_callback_invocations'])
        for index, count in ((4, 7), (9, 8)):
            rows = [c['target'] for c in report['cases'] if c['index'] == index]
            self.assertEqual([r['child_index'] for r in rows[:count]], list(range(count)))
            self.assertTrue(all(r['rejected'] and r['native_return'] == 5 for r in rows[count:]))
            self.assertTrue(all(not r['child_executed'] and not r['scheduler_executed'] for r in rows))
        self.assertFalse(report['exposure_or_centering_executed'])
        self.assertFalse(report['installable'])

    def test_complete_control_producer_and_explicit_off_preserve_native_semantics(self):
        from cp_control_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 16)
        self.assertEqual(report['paired_frame_steps'], 8)
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['additional_native_parameter_ids'], [0xf0028, 0xf0029, 0xf002c])
            self.assertEqual(len(result['shots']), 4)
            for shot in result['shots']:
                self.assertTrue(shot['complete_producer_executed'])
                self.assertFalse(shot['precomputed_vector_supplied'])
            for request in result['post_requests']:
                self.assertEqual(request['vector_raw'], result['shots'][-1]['vector_raw'])
                self.assertTrue(request['trinity_still_enabled'])
                self.assertFalse(request['gpio_executed'])
            self.assertEqual(result['off_next_frame']['trinity'], 0)
            self.assertEqual(result['off_next_frame']['native_vector_mode'], 1)
            self.assertEqual(result['off_next_frame']['vector_raw'], [123456, -654321, 65536])
            self.assertFalse(result['automatic_completion_or_abort_executed'])
        self.assertFalse(report['installable'])

    def test_h8_generated_reply_golden_payloads_reach_original_cp_signed_getters(self):
        from cp_controller_reply_replay import decode_reply
        # Golden payloads from original H8 sampling/encoding, independent register
        # inputs and synthetic post-SIO framing; no host-side checksum repair.
        samples = [
            ('a55a08002301dcfe008000000000000000000000000000000000000000000000000000000000f870',
             [291, -292, -32768]),
            ('a55a0800ff7f0100ffff00000000000000000000000000000000000000000000000000000000068f',
             [32767, 1, -1]),
        ]
        for payload, expected in samples:
            a = decode_reply(self.c2, bytes.fromhex(payload))
            b = decode_reply(self.cr, bytes.fromhex(payload))
            self.assertEqual(a, b)
            self.assertEqual(a['values'], expected)
            self.assertTrue(a['complete_40_byte_copy'])
            self.assertTrue(a['bad_checksum_rejected'])
            self.assertFalse(a['payload_reencoded_by_host'])
            self.assertFalse(a['physical_feedback_verified'])

    def test_original_alternate_formatters_build_first_then_second_packets(self):
        from cp_phase_pair_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 8)
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertTrue(result['native_first_then_second_formatters'])
            self.assertTrue(result['host_selected_stage_invocations'])
            for shot in result['shots']:
                first, second = bytes.fromhex(shot['first']), bytes.fromhex(shot['second'])
                self.assertEqual(first[:4], bytes([0x39, 7, 7, 3]))
                self.assertEqual(second[:4], bytes([0x39, 8, 8, 2]))
                for packet in (first, second):
                    self.assertEqual(len(packet), 40)
                    check = 0
                    for word in struct.unpack('<20H', packet):
                        check ^= word
                    self.assertEqual(check, 0xf0f)
                self.assertEqual(list(struct.unpack_from('<3i', second, 4)), shot['vector_raw'])
                self.assertEqual(second[28], shot['trinity'])
        self.assertFalse(report['installable'])

    def test_complete_native_control_producer_feeds_both_formatters_without_replacing_its_vector(self):
        from cp_phase_pair_replay import compare
        report = compare(self.c2, self.cr, full_control=True)
        self.assertEqual(report['paired_cases'], 8)
        for case in report['cases']:
            a = case['target']
            self.assertEqual(a, case['reference'])
            self.assertTrue(a['full_control_producer_executed'])
            self.assertFalse(a['precomputed_vector_supplied'])
            self.assertTrue(all(s['native_vector_and_frame_preserved'] for s in a['shots']))
            expected = ([[0, 0, 0]] * 4 if case['scales'] is None else
                        [[0, 0, 0], [49152, 81920, 0], [49152, 81920, 114688], [0, 0, 114688]])
            self.assertEqual([s['vector_raw'] for s in a['shots']], expected)
            for shot in a['shots']:
                self.assertEqual(list(struct.unpack_from('<3i', bytes.fromhex(shot['second']), 4)),
                                 shot['vector_raw'])
        self.assertFalse(report['physical_shift_verified'])

    def test_native_controller_parameter_queue_carries_source_words_and_updates_its_cache(self):
        from cp_parameter_wire_replay import parameter_packets
        for words in (None, bytes.fromhex('1234fedc89abcdef1357fdb9')):
            a = parameter_packets(self.c2, synthetic_words=words)
            self.assertEqual(a, parameter_packets(self.cr, synthetic_words=words))
            self.assertEqual(a['parameter_id'], 0x170006)
            self.assertTrue(a['native_loader_and_cache_scanner_executed'])
            self.assertTrue(a['source_bytes_preserved_by_emission'])
            self.assertTrue(a['prior_cache_synthetic'])
            self.assertEqual(a['source_words_synthetic'], words is not None)
            for index, row in enumerate(a['packets']):
                packet = bytes.fromhex(row['packet'])
                self.assertEqual(packet[7:10], bytes([6, (0x60, 0x64, 0x6c)[index], 255]))
                if words is not None:
                    self.assertEqual(packet[10:14], words[index * 4:index * 4 + 4])
            self.assertFalse(a['physical_configuration_verified'])

    def test_native_adjustment_arithmetic_supplies_full_vectors_and_retains_invalid_range_behavior(self):
        from cp_scale_calculation_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 10)
        self.assertEqual(report['paired_vector_steps'], 40)
        expected = [([4, 8, 8], 0)] * 3 + [([0, 8, 8], 1), ([4, 0, 8], 1),
                    ([4, 8, 0], 1), ([200, 8, 8], 0), ([0, 26, 26], 1),
                    ([0, 26, 26], 1), ([0, 41, 41], 0)]
        for case, (scales, error) in zip(report['cases'], expected):
            a = case['target']
            self.assertEqual(a, case['reference'])
            result = a['scale_calculation']
            self.assertEqual(result['scale_bytes'], scales)
            self.assertEqual(result['native_error_flag'], error)
            self.assertEqual(result['native_scale_store_offsets'], [0, 1, 2])
            self.assertTrue(result['native_measurement_pointer_binding_executed'])
            self.assertEqual(result['native_diagnostic_record_bytes'], 72)
            self.assertFalse(result['host_assigned_scale_bytes'])
            self.assertFalse(result['notification_executed'])
            self.assertTrue(a['same_ram'])
            self.assertTrue(a['full_native_consumer_and_producer_executed'])
            self.assertTrue(a['native_both_packet_formatters_executed'])
            self.assertEqual([s['vector_raw'] for s in a['shots']], [
                [0, 0, 0], [scales[0] * 16384, scales[1] * 16384, 0],
                [scales[0] * 16384, scales[1] * 16384, scales[2] * 16384],
                [0, 0, scales[2] * 16384]])
            for shot in a['shots']:
                self.assertTrue(shot['native_vector_and_frame_preserved'])
                self.assertEqual(list(struct.unpack_from('<3i', bytes.fromhex(shot['second']), 4)),
                                 shot['vector_raw'])
        self.assertFalse(report['physical_shift_verified'])

    def test_native_group_end_uses_reference_cleanup_and_stops_before_unmodeled_resources(self):
        from cp_group_end_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 14)
        for case in report['cases']:
            args, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['next_ordinal'], 0)
            self.assertEqual(result['end_marker'], 1)
            self.assertTrue(result['synthetic_cp_enable_word_unchanged'])
            self.assertEqual(result['void_reference_semaphore_calls_omitted'], [])
            self.assertTrue(result['native_lock_ownership_released'])
            self.assertFalse(result['host_assigned_lock_return_value'])
            self.assertFalse(result['pool_return_executed'])
            self.assertFalse(result['pending_callback_executed'])
            self.assertFalse(result['resource_release_executed'])
            self.assertFalse(result['centering_verified'])
            references = args['references']
            if references == 1:
                self.assertTrue(result['native_constructor_executed'])
                self.assertTrue(result['native_cleanup_started'])
                self.assertEqual(result['reference_count'], 0)
                self.assertTrue(result['group_pointer_retained'])
                self.assertEqual(result['native_empty_resource_cleanup_finished'], not args.get('resource', False))
                self.assertEqual(result['boundary'], 'resource_release' if args.get('resource') else 'pool_return')
            else:
                self.assertFalse(result['native_cleanup_started'])
                self.assertFalse(result['group_pointer_retained'])
                self.assertFalse(result['pending_callback_retained'])
                self.assertEqual(result['reference_count'], 1 if references == 2 else None)
                self.assertEqual(result['boundary'], 'pending_callback' if args['pending_callback'] else 'returned')
        self.assertFalse(report['installable'])

    def test_original_atomic_reference_lock_apis_handle_success_rejection_and_contention(self):
        from cp_native_lock_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 16)
        for case in report['cases']:
            args, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            self.assertFalse(result['host_assigned_return_value'])
            self.assertFalse(result['wake_or_cross_core_effect_verified'])
            calls = result['calls']
            if args['kind'] == 'cycle':
                self.assertEqual([c['status'] for c in calls], [0, 0])
                self.assertEqual(calls[0]['owner'], 0x36)
                self.assertEqual(calls[1]['owner'], 0)
                self.assertEqual(result['original_atomic_instructions'], ['ldrex', 'strex'])
                self.assertEqual(result['original_barriers'], ['dmb', 'dmb', 'dsb', 'sev'])
            elif args['kind'] == 'busy':
                self.assertEqual(calls[0]['boundary'], 'wait_for_event')
                self.assertIsNone(calls[0]['status'])
                self.assertEqual(result['original_atomic_instructions'], ['ldrex'])
            else:
                self.assertEqual(calls[0]['status'], args['expected'])
                self.assertEqual(result['original_atomic_instructions'], [])

    def test_original_pool_recycling_requires_actual_list_update_beyond_validator_return(self):
        from cp_pool_recycle_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 12)
        for case in report['cases']:
            args, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            valid = args['pointer'] == 'valid'
            recycled = valid and not args.get('masked', False)
            self.assertEqual(result['range_validator_return'], int(valid))
            self.assertEqual(result['actual_list_update'], recycled)
            self.assertEqual(result['free_count'], 2 if recycled else 1)
            self.assertFalse(result['host_assigned_return_value'])
            self.assertFalse(result['complete_pool_return_wrapper_executed'])
            self.assertFalse(result['group_completion_executed'])
            if args.get('masked'):
                self.assertEqual(result['range_validator_return'], 1)
                self.assertEqual(result['checked_lock_status'], -25)
                self.assertEqual(result['recycle_helper_return'], 0)
                self.assertFalse(result['actual_list_update'])

    def test_native_pool_entry_mutex_and_same_task_vfp_save_restore_do_not_need_host_returns(self):
        from cp_native_mutex_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 14)
        statuses = [[0, 0], [0, -41, 0], [-25], [-25], [-25], [-18], [-18],
                    [-41], [-25], [-25], [-18], [-18], [None], [None]]
        for index, case in enumerate(report['cases']):
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual([c['status'] for c in result['calls']], statuses[index])
            self.assertEqual(result['native_scheduler_save_restore_pairs'], int(index < 2))
            self.assertTrue(result['vfp_values_preserved'])
            self.assertFalse(result['host_assigned_api_or_scheduler_return'])
            self.assertFalse(result['host_restored_registers'])
            self.assertFalse(result['task_switch_to_different_task_executed'])
            self.assertFalse(result['wait_enqueue_or_wakeup_executed'])

    def test_complete_native_outer_pool_return_preserves_status_and_actual_recycle_distinction(self):
        from cp_pool_return_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 7)
        acquisitions = [0, 0, 0, -25, -25, -25, None]
        releases = [0, 0, 0, -25, -41, -25, None]
        counts = [1, 2, 0, 0, 1, 1, 0]
        updates = [True, True, False, False, True, True, False]
        for index, case in enumerate(report['cases']):
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['entry_mutex_status'], acquisitions[index])
            self.assertEqual(result['entry_mutex_release_status'], releases[index])
            self.assertEqual(result['node_recycled'], updates[index])
            self.assertEqual(result['free_count'], counts[index])
            self.assertEqual(result['same_task_scheduler_entries'], int(index < 3))
            self.assertEqual(result['complete_outer_pool_function_returned'], index != 6)
            self.assertEqual(result['outer_return'], 0 if index != 6 else None)
            self.assertFalse(result['host_assigned_api_or_scheduler_return'])
            self.assertFalse(result['host_restored_registers'])
            self.assertFalse(result['physical_allocation_deletion_executed'])
            self.assertFalse(result['camera_group_completion_executed'])

    def test_group_end_recycles_final_empty_object_and_detaches_before_pending_callback(self):
        from cp_group_end_replay import compare
        report = compare(self.c2, self.cr, full_pool=True)
        self.assertEqual(report['paired_cases'], 7)
        self.assertTrue(report['full_pool_requested'])
        for case in report['cases']:
            args, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            resource = args.get('resource', False)
            recycled = args['references'] == 1 and not resource
            self.assertEqual(result['pool_return_executed'], recycled)
            self.assertEqual(result['whole_pool']['free_count'], int(recycled))
            self.assertEqual(result['whole_pool']['outer_pool_return_status'], 0 if recycled else None)
            self.assertEqual(result['scheduler_executed'], recycled)
            self.assertEqual(result['group_pointer_retained'], resource)
            self.assertEqual(result['boundary'], 'resource_release' if resource else
                             'pending_callback' if args['pending_callback'] else 'returned')
            self.assertFalse(result['pending_callback_executed'])
            self.assertFalse(result['resource_release_executed'])
            self.assertFalse(result['capture_scheduler_executed'])
            self.assertTrue(result['native_lock_ownership_released'])
            self.assertTrue(result['synthetic_cp_enable_word_unchanged'])
        self.assertFalse(report['centering_verified'])

    def test_original_client_records_and_post_dequeue_invocation_register_actual_completion_event(self):
        from cp_completion_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 7)
        bits = [0, 0x204, 0x10000, 0x10204, 0, 0, 0]
        statuses = [[], [], [0], [0], [-25], [-25], []]
        for index, case in enumerate(report['cases']):
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['native_client_categories'], [0, 2])
            self.assertEqual(result['event_id'], 0x35)
            self.assertEqual(result['event_mask'], 0x10000)
            self.assertEqual(result['event_bits'], bits[index])
            self.assertEqual(result['event_statuses'], statuses[index])
            self.assertEqual(result['completion_pending'], index < 2)
            self.assertEqual(result['worker_messages_completed'], 1 if index == 6 else 2)
            self.assertTrue(result['sender_bytes_preserved'])
            self.assertTrue(result['unrelated_start_callback_preserved'])
            self.assertFalse(result['actor_queue_transport_executed'])
            self.assertFalse(result['complete_sender_function_executed'])
            self.assertFalse(result['host_assigned_callback_or_api_return'])
            self.assertFalse(result['waiting_capture_task_woken'])

    def test_group_end_uses_native_registered_callback_after_pool_return_to_set_completion_flag(self):
        from cp_group_end_replay import compare
        report = compare(self.c2, self.cr, native_completion=True)
        self.assertEqual(report['paired_cases'], 4)
        self.assertTrue(report['native_completion_requested'])
        for case in report['cases']:
            args, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            resource = args.get('resource', False)
            self.assertEqual(result['pending_callback_executed'], not resource)
            self.assertEqual(result['completion_event_bits'], 0x204 if resource else 0x10204)
            self.assertEqual(result['native_completion']['event_statuses'], [] if resource else [0])
            self.assertEqual(result['native_completion']['event_arguments'], [] if resource else [[0x35, 0x10000]])
            self.assertEqual(result['group_pointer_retained'], resource)
            self.assertEqual(result['pending_callback_retained'], resource)
            self.assertEqual(result['boundary'], 'resource_release' if resource else 'returned')
            self.assertEqual(result['pool_return_executed'], args['references'] == 1 and not resource)
            self.assertTrue(result['native_client_registration']['sender_bytes_preserved'])
            self.assertFalse(result['actor_queue_transport_executed'])
            self.assertFalse(result['waiting_capture_task_woken'])
            self.assertFalse(result['capture_scheduler_executed'])
            self.assertTrue(result['synthetic_cp_enable_word_unchanged'])
        self.assertFalse(report['physical_shift_verified'])

    def test_dispatched_mode_reaches_current_settings_and_native_tc_input(self):
        from cp_mode_source_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 6)
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['copied_settings_mode'], int(result['mode'] != 0))
            self.assertEqual(result['published_trinity_flag'], int(result['mode'] != 0))
            self.assertEqual(result['native_copy_lengths'], [0xd64, 340, 192, 192])
            self.assertTrue(result['native_first_pointer_bound'])
            self.assertFalse(result['host_reassigned_mode'])
            self.assertFalse(result['semaphore_admission_executed'])
            self.assertFalse(result['scheduler_executed'])
            self.assertFalse(result['capture_end_executed'])
        self.assertFalse(report['installable'])

    def test_steady_timer_callback_and_waiter_use_the_same_native_event(self):
        from cp_steady_event_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 8)
        self.assertTrue(report['separate_callback_and_waiter_invocations'])
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual((result['event_id'], result['event_mask']), (0x2e, 0x80000000))
            self.assertEqual(result['timeout_argument'], 10000)
            self.assertTrue(result['original_arm_context_detector_executed'])
            self.assertTrue(result['native_predicate_and_inhibitions_verified'])
            self.assertTrue(result['native_bypass_verified'])
            self.assertFalse(result['rtos_event_api_executed'])
            self.assertFalse(result['wait_completed'])
            self.assertFalse(result['motor_settling_verified'])

    def test_alternate_reply_reaches_its_own_decoder_and_signed_getters(self):
        from cp_feedback_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 24)
        shots = report['target']['shots']
        self.assertEqual(len(shots), 4)
        for ordinal, shot in enumerate(shots):
            self.assertFalse(shot['settling_verified'])
            self.assertFalse(shot['physical_units_verified'])
            self.assertEqual(len(shot['cases']), 6)
            for case in shot['cases']:
                self.assertEqual(case['signed_values'], [-17 - ordinal, 31 + ordinal, -5])
                self.assertEqual(case['native_history_copy_bytes'], 16)
                self.assertEqual(case['next_index'], 1 if case['initial_index'] == 0 else 0)
                self.assertEqual(case['history_source'], 'previous_entry'
                                 if case['source_kind'] == 1 else 'context')
        self.assertFalse(report['target']['hardware_acknowledgment_verified'])
        self.assertFalse(report['installable'])

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

    def test_native_frame_mapping_carries_trinity_to_later_control_flag(self):
        from cp_frame_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 24)
        self.assertFalse(report['installable'])
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['control_flag'], result['frame_mode'])
            self.assertTrue(result['mode_never_reassigned_by_host'])
            self.assertFalse(result['full_preparation_executed'])
            self.assertFalse(result['transport_executed'])
            self.assertFalse(result['physical_shift_verified'])

    def test_trinity_index_reaches_serial_extension_without_host_reassignment(self):
        from cp_serial_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 56)
        for case in report['cases']:
            args, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            index = args['ordinal'] & 127
            packed = index | (args['trinity'] << 7)
            extended = int(args['interface_mode'] in (4, 5))
            raw = bytes.fromhex(result['packet'])
            self.assertEqual(result['native_index'], index)
            self.assertEqual(result['packed_index'], packed)
            self.assertEqual(result['extended'], extended)
            self.assertEqual(result['tc_first_frame'], int(args['ordinal'] == 0))
            self.assertEqual(raw[:3], b'\x39\x05\x05')
            self.assertEqual(raw[0x6e], packed if extended else 0xa5)
            self.assertEqual(result['transmitted_bytes'], 128 if args['long_packet'] else 100)
            self.assertEqual(result['total_bytes'], result['transmitted_bytes'])
            self.assertEqual(result['repeat_count'], 1)
            self.assertEqual(result['rx_buffer_offset'], 128)
            primary, extension = 0x0f0f, 0
            for value in struct.unpack('<49H', raw[:98]):
                primary ^= value
            for value in struct.unpack('<13H', raw[100:126]):
                extension ^= value
            self.assertEqual(struct.unpack_from('<H', raw, 98)[0], primary)
            self.assertEqual(struct.unpack_from('<H', raw, 126)[0], extension)
            self.assertTrue(result['native_slices_only'])
            self.assertTrue(result['synthetic_frame_and_interface'])
            self.assertFalse(result['full_tc_calculation_executed'])
            self.assertFalse(result['serial_transport_executed'])
            self.assertFalse(result['serial_peer_identified'])
            self.assertFalse(result['physical_shift_verified'])

    def test_factory_tc_defaults_use_native_lookup_copy_and_branch_selection(self):
        from cp_defaults_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 2)
        for case in report['cases']:
            for result in (case['target'], case['reference']):
                self.assertEqual(result['sio_channel'], 4)
                self.assertEqual(result['sio_rate_code'], 24)
                self.assertEqual(result['interface_parameter'], '0x000f0001')
                self.assertEqual(result['native_copied_bytes'], 256)
                self.assertEqual(result['raw_interface_word'], 0x66)
                self.assertEqual(result['decoded_interface_type'], 6)
                self.assertTrue(result['alternate_tc_if_defaults_retained'])
                self.assertTrue(result['native_memcpy_executed'])
                self.assertEqual(result['mutex_calls_omitted'], 5)
                self.assertFalse(result['runtime_overrides_executed'])
                self.assertFalse(result['live_state_verified'])
                self.assertFalse(result['camera_io'])
                self.assertFalse(result['physical_shift_verified'])

    def test_darwin_native_receive_and_parser_prefix_preserve_all_34_bytes(self):
        from darwin_capture_replay import compare
        c2, cr = self.c2 / 'darwin_core.bin', self.cr / 'darwin_core.bin'
        if not c2.is_file() or not cr.is_file():
            self.skipTest('Needs privately extracted 0640_darwin/darwin_core.bin beside each CP image')
        report = compare(c2, cr)
        self.assertEqual(report['paired_cases'], 276)
        self.assertFalse(report['camera_io'])
        self.assertFalse(report['installable'])
        for case in report['cases']:
            self.assertEqual(case['target'], case['reference'])
            result = case['target']
            self.assertEqual(result['message_id'], 12)
            self.assertEqual(result['code'], '03/01/02')
            self.assertEqual(result['received_bytes'], 34)
            self.assertEqual(result['native_snapshot_bytes'], 34)
            self.assertEqual(result['native_fetch_bytes'], 34)
            self.assertEqual(result['external_calls_omitted'], 0)
            self.assertTrue(result['parser_prefix_only'])
            self.assertFalse(result['serial_transport_executed'])
            self.assertFalse(result['capture_preparation_executed'])
            self.assertFalse(result['physical_shift_verified'])

    def test_factory_selected_alternate_tc_retains_ordinal_across_both_banks(self):
        from cp_alternate_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_sequences'], 8)
        self.assertEqual(report['paired_cases'], 32)
        for case in report['cases']:
            args, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['official_interface_type'], 6)
            self.assertTrue(result['official_selector_preserved'])
            self.assertTrue(result['native_alternate_entry_executed'])
            self.assertEqual([shot['bank'] for shot in result['shots']], [1, 0, 1, 0])
            mode = 4 if not args['gate'] else 1 if args['shared_flag'] else 2
            for index, shot in enumerate(result['shots']):
                self.assertEqual(shot['ordinal'], index)
                self.assertEqual(shot['control_mode'], mode)
                self.assertEqual(shot['request_category'], 3 if index == 0 and args['first'] else 7)
            self.assertEqual(result['gpio_port'], 255)
            self.assertEqual(result['gpio_native_invalid_port_returns'],
                             ['set' if mode == 1 else 'clear'] * 4)
            self.assertFalse(result['gpio_hardware_access_executed'])
            self.assertFalse(result['serial_transport_executed'])
            self.assertFalse(result['physical_shift_verified'])

    def test_native_ordinal_vector_uses_factory_scales_and_real_flag_copy(self):
        from cp_vector_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_sequences'], 3)
        self.assertEqual(report['paired_cases'], 12)
        for case in report['cases']:
            self.assertEqual(case['target'], case['reference'])
            result = case['target']
            self.assertEqual(result['original_scale_bytes'], [0, 0, 0])
            self.assertTrue(result['interface_selector_preserved'])
            factor = 1 << (case['exponent'] or 13)
            scales = case['scales'] or [0, 0, 0]
            for index, shot in enumerate(result['shots']):
                x, y = [(0, 0), (2, 0), (2, 2), (0, 2)][index]
                self.assertEqual(shot['vector_raw'],
                                 [x * scales[0] * factor, x * scales[1] * factor, y * scales[2] * factor])
                self.assertEqual(shot['native_pattern_mode'], 2)
                self.assertTrue(shot['native_frame_flag_exported'])
                self.assertEqual(shot['native_shared_copy_bytes'], 192)
                self.assertTrue(shot['ordinal_unchanged'])
                self.assertEqual(shot['sensitivity_scales_synthetic'], case['scales'] is not None)
                self.assertFalse(shot['physical_units_verified'])
                self.assertFalse(shot['serial_transport_executed'])
                self.assertFalse(shot['physical_shift_verified'])

    def test_alternate_wire_retains_vector_and_rejects_bad_synthetic_replies(self):
        from cp_alternate_wire_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_packets'], 8)
        self.assertEqual(report['paired_reply_cases'], 24)
        self.assertFalse(report['hardware_acknowledgment_verified'])
        self.assertFalse(report['installable'])
        for case in report['cases']:
            self.assertEqual(case['target'], case['reference'])
            self.assertEqual(case['target']['original_scale_bytes'], [0, 0, 0])
            for shot in case['target']['shots']:
                packet = bytes.fromhex(shot['packet'])
                self.assertEqual(len(packet), 40)
                self.assertEqual(packet[:4], bytes([0x39, 8, 8, 2]))
                self.assertEqual(list(struct.unpack_from('<3i', packet, 4)), shot['packet_vector_raw'])
                self.assertEqual(packet[28], 1)
                checksum = 0x0f0f
                for word in struct.unpack('<19H', packet[:38]):
                    checksum ^= word
                self.assertEqual(struct.unpack_from('<H', packet, 38)[0], checksum)
                self.assertEqual([r['native_validation_branch'] for r in shot['reply_cases']],
                                 ['accepted', 'rejected', 'rejected'])
                self.assertEqual([r['complete_40_byte_copy'] for r in shot['reply_cases']],
                                 [True, False, False])
                self.assertTrue(shot['synthetic_reply_bytes'])
                self.assertFalse(shot['transport_executed'])
                self.assertFalse(shot['hardware_acknowledgment_verified'])
                self.assertFalse(shot['exposure_or_centering_executed'])

    def test_capture_status_exchange_retains_native_request_failure_gate(self):
        from capture_gate_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 102)
        self.assertFalse(report['physical_readiness_verified'])
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['event'], 0x1000212 if result['software_gate_passed'] else 0x1000213)
            self.assertEqual(result['ap_status'], int(not result['software_gate_passed']))
            self.assertTrue(result['status_provider_synthetic'])
            self.assertFalse(result['cp_refresh_executed'])
            self.assertFalse(result['transport_executed'])
            self.assertFalse(result['event_dispatcher_executed'])

    def test_trigger_arbitration_distinguishes_af_awbl_and_capture_start(self):
        from cp_trigger_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 72)
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertFalse(result['physical_shift_verified'])
            self.assertFalse(result['transport_executed'])
            if case['stage'] == 'arbitration':
                args = case['input']
                self.assertFalse(result['sender_bodies_executed'])
                if args == dict(active=[20], previous=(0, 0, 0), af_enabled=1):
                    self.assertEqual(result['selected'], [20, 20, 20])
                    self.assertEqual([r['command'] for r in result['requests']],
                                     ['0x3021', '0x300e', '0x302e'])
                if args['active'] == [20] and args['previous'] == (20, 20, 20):
                    self.assertEqual(result['requests'], [])
                continue
            messages = [bytes.fromhex(m) for m in result['messages']]
            commands = [struct.unpack_from('<I', m, 4)[0] for m in messages]
            command = case['input']['command']
            expected = {0x300c: [0x8202, 0x100], 0x300e: [0x102],
                        0x300f: [0x8204, 0x104], 0x3010: [0x8201, 0x103],
                        0x3021: [0x8301], 0x3022: [0x8302],
                        0x302e: [0x8307], 0x302f: [0x8308]}
            self.assertEqual(commands, expected[command])
            for message in messages:
                self.assertEqual(struct.unpack_from('<II', message, 8),
                                 (case['input']['capture_id'], 0x90040193))
            if 'route' in result:
                route = result['route']
                self.assertFalse(route['capture_handler_executed'])
                self.assertFalse(route['capture_executed'])
                self.assertFalse(route['queue_and_scheduler_executed'])
                if command == 0x300c:
                    self.assertEqual(route['boundary'], 'capture-start-handler')
                    self.assertEqual(route['trigger'], 20)
                    self.assertEqual(struct.unpack_from('<I', messages[1], 20)[0], 0x87654321)
                elif command == 0x300e:
                    self.assertEqual(route['boundary'], 'af-prepare-helper')
                    self.assertEqual(route['awbl_flag'], 0xa5)
                else:
                    self.assertEqual(route['boundary'], 'post-handler')
                    self.assertEqual(route['awbl_flag'], int(command == 0x302e))

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
