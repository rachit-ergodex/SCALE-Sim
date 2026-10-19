"""Production-size decode tiles against an independent NumPy integer oracle.

These tests exercise the full 64 x 64 compute component at a 5 ns period.
They intentionally do not model HBM, the vector/SFU engine, or a token loop.
The reported cycle counts are component measurements, not end-to-end TPS.
"""
import json
import math
import os
from pathlib import Path

import cocotb
from cocotb.triggers import Timer
import numpy as np

PARTITIONS = 64
COLS = 64
LANES = PARTITIONS * COLS
CORE_HZ = 200_000_000
PARTITION = np.arange(PARTITIONS)
LANE = np.arange(LANES)
LANE_COLUMN = LANE % COLS


def packed(values, dtype):
    return int.from_bytes(np.asarray(values).astype(dtype).tobytes(), 'little')


def unsigned_words(signal, count):
    return np.frombuffer(int(signal.value).to_bytes(count * 4, 'little'), dtype='<u4')


def bits(signal, count):
    raw = int(signal.value).to_bytes((count + 7) // 8, 'little')
    return np.unpackbits(np.frombuffer(raw, dtype=np.uint8), bitorder='little')[:count].astype(bool)


def int32_wrap(values):
    values = np.asarray(values, dtype=np.int64)
    return ((values + (1 << 31)) % (1 << 32)) - (1 << 31)


async def edge(d):
    d.clk.value = 0
    await Timer(2500, unit='ps')
    d.clk.value = 1
    await Timer(2500, unit='ps')


async def reset(d):
    d.clk.value = 0
    d.rst.value = 1
    d.cmd_valid.value = 0
    d.cycle_ready.value = 0
    d.a_data.value = 0
    d.b_data.value = 0
    d.seed_data.value = 0
    await edge(d)
    d.rst.value = 0
    await Timer(1, unit='ps')
    assert not int(d.busy.value) and int(d.cmd_ready.value)


def save_case(name, commands, outputs):
    path = Path(os.environ['DECODE_REAL_TILES_METRICS'])
    cases = json.loads(path.read_text()) if path.exists() else []
    cases.append({'name': name, 'commands': commands, 'checked_final_outputs': outputs})
    path.write_text(json.dumps(cases, indent=2) + '\n')


async def command(d, a, b, *, seed=None, random_seed=1, parallel=True):
    """Check every accepted result and every requested operand address.

    The schedule below is derived from matrix coordinates, independently of
    RTL counters and SCALE-Sim. Stalled outputs are observed but never retired.
    Unused input lanes contain nonzero poison values to catch accidental use.
    """
    m, k = a.shape
    assert b.shape[0] == k
    n = b.shape[1]
    parts = math.ceil(n / COLS)
    workers = min(m, PARTITIONS // parts) if parallel else 1
    cycles = math.ceil(m / workers) * (k + COLS - 1)
    golden = a.astype(np.int64) @ b.astype(np.int64)
    if seed is not None:
        golden += seed
    golden = int32_wrap(golden)
    output = np.empty((m, n), dtype=np.int64)
    writes = np.zeros(m * n, dtype=np.uint8)
    rng = np.random.default_rng(random_seed)
    committed = stalled = 0
    burst_remaining = 0
    injected_bursts = set()

    d.cmd_m.value = m
    d.cmd_k.value = k
    d.cmd_n.value = n
    d.cmd_parallel_rows.value = parallel
    d.cmd_accumulate.value = seed is not None
    d.cmd_valid.value = 1
    await edge(d)
    d.cmd_valid.value = 0
    assert int(d.busy.value) and not int(d.command_error.value)

    while int(d.busy.value):
        d.clk.value = 0
        await Timer(250, unit='ps')
        wave, phase = divmod(committed, k + COLS - 1)
        rows = wave * workers + PARTITION // parts
        used = (PARTITION // parts < workers) & (rows < m)
        lane_rows = np.repeat(rows, COLS)
        columns = (LANE // COLS % parts) * COLS + LANE_COLUMN
        inner = phase - LANE_COLUMN
        active = np.repeat(used, COLS) & (columns < n) & (inner >= 0) & (inner < k)
        av_expected = used & (phase < k)
        sv_expected = active & (phase == LANE_COLUMN) & (seed is not None)
        cv_expected = active & (phase == k - 1 + LANE_COLUMN)
        av = bits(d.a_valid, PARTITIONS)
        bv = bits(d.b_valid, LANES)
        sv = bits(d.seed_valid, LANES)
        cv = bits(d.c_valid, LANES)
        np.testing.assert_array_equal(av, av_expected)
        np.testing.assert_array_equal(bv, active)
        np.testing.assert_array_equal(sv, sv_expected)
        np.testing.assert_array_equal(cv, cv_expected)
        aa = unsigned_words(d.a_address, PARTITIONS)
        ba = unsigned_words(d.b_address, LANES)
        ca = unsigned_words(d.c_address, LANES)
        np.testing.assert_array_equal(aa[av], (rows * k + phase)[av])
        np.testing.assert_array_equal(ba[bv], (inner * n + columns)[bv])
        np.testing.assert_array_equal(ca[active], (lane_rows * n + columns)[active])

        a_values = np.full(PARTITIONS, -91, dtype=np.int8)
        b_values = np.full(LANES, -107, dtype=np.int8)
        seed_values = np.full(LANES, 0x6BADF00D, dtype=np.uint32)
        if np.any(av):
            a_values[av] = a[rows[av], phase]
        b_values[active] = b[inner[active], columns[active]]
        if seed is not None:
            seed_values[sv] = (seed[lane_rows[sv], columns[sv]] % (1 << 32)).astype(np.uint32)
        d.a_data.value = packed(a_values, '<u1')
        d.b_data.value = packed(b_values, '<u1')
        d.seed_data.value = packed(seed_values, '<u4')
        # Long backpressure at the first output of every wave exercises the
        # final-MAC combinational result and prevents double retirement.
        marker = (wave, phase)
        if phase == k - 1 and marker not in injected_bursts:
            injected_bursts.add(marker)
            burst_remaining = 11
        ready = burst_remaining == 0 and rng.random() >= 0.15
        if burst_remaining:
            burst_remaining -= 1
        d.cycle_ready.value = ready
        await Timer(2250, unit='ps')
        if ready:
            indices = ca[cv].astype(np.int64)
            assert not np.any(writes[indices]), 'duplicate accepted output'
            values = unsigned_words(d.c_data, LANES)[cv].astype(np.int64)
            values = np.where(values >= (1 << 31), values - (1 << 32), values)
            np.testing.assert_array_equal(values, golden.flat[indices])
            output.flat[indices] = values
            writes[indices] += 1
            committed += 1
        else:
            stalled += 1
            snapshot = tuple(int(signal.value) for signal in
                             (d.a_address, d.b_address, d.c_address, d.c_valid, d.c_data))
        d.clk.value = 1
        await Timer(2500, unit='ps')
        if not ready:
            assert snapshot == tuple(int(signal.value) for signal in
                                     (d.a_address, d.b_address, d.c_address, d.c_valid, d.c_data))
        assert committed <= cycles and stalled < cycles * 2 + 100

    assert int(d.done.value) and int(d.cmd_ready.value)
    assert committed == cycles == int(d.logical_cycles.value)
    assert int(d.elapsed_cycles.value) == committed + stalled
    assert int(d.stall_cycles.value) == stalled
    assert np.all(writes == 1), 'missing or repeated output'
    np.testing.assert_array_equal(output, golden)
    return output, {'m': m, 'k': k, 'n': n, 'parallel_rows': parallel,
                    'accumulate': seed is not None, 'row_workers': workers,
                    'waves': math.ceil(m / workers), 'logical_cycles': committed,
                    'stall_cycles': stalled, 'elapsed_cycles': committed + stalled,
                    'ideal_compute_us_at_200mhz': committed / 200,
                    'checked_outputs': m * n}


def random_operands(m, k, n, seed):
    rng = np.random.default_rng(seed)
    a = rng.integers(-128, 128, (m, k), dtype=np.int8)
    b = rng.integers(-128, 128, (k, n), dtype=np.int8)
    # Dense signed random values plus explicit minimum/maximum signed bytes.
    a[:, ::31] = -128
    b[::29, ::17] = 127
    b[::37, ::19] = -128
    return a, b


@cocotb.test()
async def gemma_ffn_up_output_tiles_and_k_partials(d):
    await reset(d)
    a, b = random_operands(1, 1152, 6912, 0xF001)
    output = np.empty((1, 6912), dtype=np.int64)
    commands = []
    for left, right in ((0, 4096), (4096, 6912)):
        partial = None
        for low, high in ((0, 576), (576, 1152)):
            partial, report = await command(d, a[:, low:high], b[low:high, left:right],
                                             seed=partial, random_seed=left + low + 1)
            commands.append(report)
        output[:, left:right] = partial
    np.testing.assert_array_equal(output, a.astype(np.int64) @ b.astype(np.int64))
    save_case('gemma_ffn_up_1x1152x6912_output_and_k_tiles', commands, output.size)


@cocotb.test()
async def gemma_ffn_down_seven_accumulated_k_tiles(d):
    await reset(d)
    a, b = random_operands(1, 6912, 1152, 0xF002)
    partial = None
    commands = []
    for number, indices in enumerate(np.array_split(np.arange(6912), 7)):
        partial, report = await command(d, a[:, indices], b[indices], seed=partial,
                                         random_seed=100 + number)
        commands.append(report)
    np.testing.assert_array_equal(partial, a.astype(np.int64) @ b.astype(np.int64))
    save_case('gemma_ffn_down_1x6912x1152_seven_k_tiles', commands, partial.size)


@cocotb.test()
async def gemma_attention_four_rows_context_515(d):
    await reset(d)
    commands = []
    outputs = 0
    for number, (m, k, n) in enumerate(((4, 256, 515), (4, 515, 256))):
        a, b = random_operands(m, k, n, 0xA000 + number)
        result, report = await command(d, a, b, random_seed=200 + number)
        commands.append(report)
        outputs += result.size
    save_case('gemma_attention_qk_and_av_four_rows_context515', commands, outputs)


@cocotb.test()
async def ragged_two_wave_partials_signed_wrap(d):
    await reset(d)
    m, k, n = 4, 257, 1153
    a = np.full((m, k), -128, dtype=np.int8)
    b = np.tile(np.array([-128, 127], dtype=np.int8), (k, (n + 1) // 2))[:, :n]
    seed = np.resize(np.array([(1 << 31) - 16, -(1 << 31) + 16, -1, 0], dtype=np.int64), (m, n))
    result, report = await command(d, a, b, seed=seed, random_seed=300)
    assert report['row_workers'] == 3 and report['waves'] == 2
    save_case('ragged_4x257x1153_two_waves_int32_wrap', [report], result.size)
