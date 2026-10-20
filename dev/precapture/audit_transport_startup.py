"""Original transport GPIO startup guards; no native service success is supplied.

Module GPIO/thread/IRQ calls stop before execution. Distinct post-getter slices
take explicit synthetic status/data inputs. Optional kernel checks use synthetic
resource tables and stop before the hardware load, then audit the pure bit mask.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn import arm64_const as R
from support.kernel import Module, PCIE_SHA
from support.boundaries import BoundaryRunner
from support.memory import MEM, STACK, STOP

KERNEL_SHA = '620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
ORIGIN, CODE = 0xffffff8008080000, 0x50000000


def put(cpu, at, value, size=4):
    cpu.mem_write(at, value.to_bytes(size, 'little'))


def module_audit(raw):
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    module = Module(cpu, raw, PCIE_SHA, 0x10000000)
    for at, size in ((MEM, 0x20000), (STACK, 0x10000), (STOP, 4096)):
        cpu.mem_map(at, size)
    run = BoundaryRunner(cpu, (module,), stop=STOP, stack=STACK)
    at = lambda offset: module.at('.text', offset)
    cases = []
    assert module.rel[module.at('.init.text', 0x2c)]['addend'] == 0
    assert module.rel[at(0x1c)]['name'] == 'gpio_get_data_bit'
    for call in (0x38, 0x3cf8):
        assert module.rel[at(call)]['name'] == 'pcieif_snd_init_done'
    got = run.call(at(0), ())
    assert got['call'] == 'pcieif_set_interrupt' and got['args'][0] == 0
    cases.append(dict(case='startup-first-stops-at-interrupt-output', native_write_executed=False))
    # Independent post-output slice. No output result is consumed here.
    got = run.run(at(0x10))
    assert got['call'] == 'gpio_get_data_bit' and got['args'][:2] == [17, 4]
    destination = got['args'][2]
    assert destination == cpu.reg_read(R.UC_ARM64_REG_X29) + 0x1c
    cases.append(dict(case='startup-reads-port17-bit4', getter_executed=False))
    for status in (0, 1, -22):
        for value in (0, 1, 2, 0xffffffff):
            # Enter at the original conditional AFTER the omitted getter.
            # These are explicit independent inputs, not native GPIO evidence.
            frame = STACK + 0x7000
            cpu.reg_write(R.UC_ARM64_REG_SP, frame)
            cpu.reg_write(R.UC_ARM64_REG_X29, frame)
            put(cpu, frame + 8, STOP, 8)
            put(cpu, frame + 0x1c, value)
            got = run.run(at(0x20), inputs=((R.UC_ARM64_REG_X0, status),))
            admitted = status == 0 and value == 1
            assert got['at'] == (at(0x38) if admitted else STOP)
            cases.append(dict(case='post-getter-startup-guard', status=status,
                              data=value, init_done_reached=admitted,
                              getter_and_init_done_executed=False))
    for entry, expected in ((0x3cf0, 'pcieif_snd_init_done'), (0x3cc8, 'pcieif_rcv_int')):
        got = run.call(at(entry), ())
        assert got['call'] == expected
        cases.append(dict(case='IRQ-first-boundary', entry=hex(entry), first=expected,
                          handler_service_executed=False))
    got = run.call(at(0x3d18), ())
    assert got['call'] == 'pcieif_irq_clear' and got['args'][0] == 92
    for entry, irq in ((0x3d28, 92), (0x3d54, 91)):
        got = run.run(at(entry))
        assert got['call'] == 'pcieif_irq_request'
        descriptor = bytes(cpu.mem_read(got['args'][0], 40))
        number, = struct.unpack_from('<I', descriptor)
        assert number == irq
        handler, thread = struct.unpack_from('<QQ', descriptor, 8)
        assert handler == at(0x3cf0 if irq == 92 else 0x3cc8)
        cases.append(dict(case='IRQ-descriptor', IRQ=irq, handler=hex(handler-at(0)),
                          thread_present=bool(thread), IRQ_request_executed=False))
    return dict(cases=cases, startup_GPIO=dict(port=17, bit=4, required_getter_status=0,
                required_data=1), init_done_flag_is_not_CP_receipt=True)


def kernel_audit(raw):
    if hashlib.sha256(raw).hexdigest() != KERNEL_SHA:
        raise ValueError('Unsupported original kernel image')
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.mem_map(CODE, 0x800000)
    cpu.mem_write(CODE, raw)
    for at, size in ((MEM, 0x20000), (STACK, 0x10000), (STOP, 4096)):
        cpu.mem_map(at, size)
    at = lambda address: CODE + address - ORIGIN
    getter, hardware, table = map(at, (0xffffff80082f7608, 0xffffff80082f7598, 0xffffff80086ab600))
    class Boundaries:
        calls = {getter+0x54: 'hw_gpio_get_data_bit'}
    run = BoundaryRunner(cpu, (Boundaries(),), stop=STOP, stack=STACK)
    output, registers = MEM+0x1000, MEM+0x4000
    cases = []
    for port, bit, pointer, destination, admitted in (
            (17,4,0xffff8000,output,False), (17,4,registers,output,True),
            (17,32,registers,output,False), (19,4,registers,output,False),
            (17,4,registers,0,False)):
        if port < 19:
            put(cpu, table+port*96, pointer, 8)
        put(cpu, output, 0xa5a5a5a5)
        got = run.call(getter, (port, bit, destination))
        assert bytes(cpu.mem_read(output,4)) == b'\xa5'*4
        assert got['at'] == (getter+0x54 if admitted else STOP)
        if not admitted:
            assert got['args'][0] & 0xffffffff == (-22) & 0xffffffff
        cases.append(dict(case='kernel-getter-admission', port=port, bit=bit,
                          hardware_boundary_reached=admitted, hardware_executed=False))
    put(cpu, table+17*96, registers, 8)
    got = run.call(hardware, (17,4,output), targets=(hardware+0x20,))
    assert got['at'] == hardware+0x20 and cpu.reg_read(R.UC_ARM64_REG_X3) == registers+0x10
    cases.append(dict(case='hardware-input-register-address', offset='0x10', load_executed=False))
    for value in (0, 0x10, 0x20, 0xffffffff):
        put(cpu, output, 0xa5a5a5a5)
        cpu.reg_write(R.UC_ARM64_REG_LR, STOP)
        got = run.run(hardware+0x24, inputs=((R.UC_ARM64_REG_X1,4),
                      (R.UC_ARM64_REG_X2,output), (R.UC_ARM64_REG_X3,value)))
        assert got['at'] == STOP and got['args'][0] == 0
        assert int.from_bytes(cpu.mem_read(output,4),'little') == ((value>>4)&1)
        cases.append(dict(case='post-load-bit-extraction', synthetic_sample=hex(value),
                          bit4=(value>>4)&1, native_load_executed=False))
    return dict(cases=cases, table_link_address='0xffffff80086ab600',
                table_stride=96, register_input_offset=16, native_kernel_services_executed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pcie', type=Path, required=True)
    parser.add_argument('--kernel', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.pcie.read_bytes()
    report = dict(schema='OFFLINE_TRANSPORT_STARTUP_GUARDS/1', camera_io=False,
                  PCIe_sha256=hashlib.sha256(raw).hexdigest(), module=module_audit(raw),
                  limits=['Separate synthetic slices do not establish continuous native startup',
                          'GPIO status/data/IRQ presence cannot prove CP firmware or DMA execution',
                          'No hardware, GPIO setter, IRQ handler or thread service is run'])
    if args.kernel:
        report.update(kernel_sha256=KERNEL_SHA, kernel=kernel_audit(args.kernel.read_bytes()))
    paths=[Path(__file__),Path(__file__).with_name('support')/'kernel.py',
           Path(__file__).with_name('support')/'boundaries.py']
    report['sources']={str(p.relative_to(Path(__file__).parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(report,stream,indent=2);stream.write('\n')
    count=len(report['module']['cases'])+len(report.get('kernel',{}).get('cases',[]))
    print(f'{count} original startup/GPIO guard contracts; no CP readiness established.')


if __name__ == '__main__':
    main()
