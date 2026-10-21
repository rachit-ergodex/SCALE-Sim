"""Directed limits and command-protocol checks for the compact decode core."""
import os
import sys
from pathlib import Path

import cocotb
from cocotb.triggers import Timer
import numpy as np

# The override permits isolated runs without touching an in-flight main build.
sys.path.insert(0, str(Path(os.environ.get('DECODE_RTL_ROOT', Path(__file__).resolve().parents[1])) / 'tests'))
from test_os_core import C, P, edge, pack, reset, run, words


@cocotb.test()
async def maximum_k_and_signed_wrap(d):
    await reset(d)
    for k, n, av, bv, initial in [
        (8191, C + 1, -128, -128, (1 << 31) - 17),
        (8192, C - 1, -128, 127, -(1 << 31) + 17),
    ]:
        m = 4
        a = np.full((m, k), av, dtype=np.int8)
        b = np.full((k, n), bv, dtype=np.int8)
        seed = np.full((m, n), initial, dtype=np.int64)
        await run(d, a, b, True, seed)

    # Small sign quadrants include the asymmetric -128 signed INT8 endpoint.
    for av, bv in [(-128, -1), (-1, -128), (127, 127), (127, -128), (-128, 0)]:
        await run(d, np.full((1, 1), av, dtype=np.int8),
                  np.full((1, 1), bv, dtype=np.int8), False)


@cocotb.test()
async def unsigned_command_limits_and_pending_command(d):
    await reset(d)
    # Command fields are unsigned; upper-bit values must never masquerade as
    # small dimensions after intermediate addition/division or signed casts.
    for field in range(3):
        for value in (0x80000000, 0xffffffff):
            dims = [1, 1, 1]
            dims[field] = value
            d.cmd_m.value, d.cmd_k.value, d.cmd_n.value = dims
            d.cmd_valid.value = 1
            d.cmd_parallel_rows.value = 1
            d.cmd_accumulate.value = 0
            await edge(d)
            assert int(d.command_error.value) == 1
            assert int(d.busy.value) == 0 and int(d.cmd_ready.value) == 1
            d.cmd_valid.value = 0
            await edge(d)
            assert int(d.command_error.value) == 0

    # Offer a different command throughout an active operation. The command
    # must wait for ready and be accepted on the first available following edge.
    d.cmd_m.value = 1
    d.cmd_k.value = 5
    d.cmd_n.value = 1
    d.cmd_parallel_rows.value = 0
    d.cmd_accumulate.value = 0
    d.cmd_valid.value = 1
    d.cycle_ready.value = 0
    await edge(d)
    assert int(d.busy.value) == 1
    d.cmd_m.value = 1
    d.cmd_k.value = 1
    d.cmd_n.value = 1
    d.cmd_parallel_rows.value = 1
    d.cmd_accumulate.value = 0
    d.cycle_ready.value = 1
    seen = []
    for cycle in range(5 + C - 1):
        d.clk.value = 0
        d.a_data.value = pack([3] * P, 8)
        d.b_data.value = pack([-2] * (P * C), 8)
        d.seed_data.value = 0
        await Timer(1, unit='ns')
        assert int(d.busy.value) == 1 and int(d.cmd_ready.value) == 0
        assert int(d.command_error.value) == 0
        cv = int(d.c_valid.value)
        if cv:
            assert cv == 1
            seen.append(words(d.c_data, P * C, 32)[0])
        await edge(d)
    assert seen == [(-30) & 0xffffffff]
    assert int(d.busy.value) == 0 and int(d.done.value) == 1
    assert int(d.cmd_ready.value) == 1
    assert int(d.logical_cycles.value) == 5 + C - 1

    # The held command is accepted here without needing valid to be reasserted.
    await edge(d)
    assert int(d.busy.value) == 1 and int(d.done.value) == 0
    assert int(d.logical_cycles.value) == 0
    d.cmd_valid.value = 0
    seen = []
    for cycle in range(C):
        d.clk.value = 0
        d.a_data.value = pack([-128] * P, 8)
        d.b_data.value = pack([127] * (P * C), 8)
        await Timer(1, unit='ns')
        cv = int(d.c_valid.value)
        if cv:
            assert cv == 1
            seen.append(words(d.c_data, P * C, 32)[0])
        await edge(d)
    assert seen == [(-16256) & 0xffffffff]
    assert int(d.busy.value) == 0 and int(d.done.value) == 1
    assert int(d.logical_cycles.value) == C
    await edge(d)
    assert int(d.done.value) == 0 and int(d.busy.value) == 0
