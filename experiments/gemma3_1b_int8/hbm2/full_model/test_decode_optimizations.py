"""Storage relocation, head scheduling and stream-resource regression checks."""
import copy
import io
import math
import unittest
from dataclasses import replace
from pathlib import Path
import numpy as np
from config import Architecture
from workload import Graph
from intermediate_sram import plan_residency
from scalesim.scale_config import scale_config
from scalesim.compute.systolic_compute_os import systolic_compute_os

HERE=Path(__file__).resolve().parent

class OptimizationChecks(unittest.TestCase):
    def test_full_graph_storage_preserves_arbitrary_byte_values(self):
        arch=Architecture.read(HERE/'configs/decode_f2_stream.json')
        stream=io.StringIO();manifest=Graph(stream,steps=3,architecture=arch).run()
        original=copy.deepcopy(manifest)
        commands,report=plan_residency(stream.getvalue(),manifest,arch.intermediate_sram_bytes,arch.vector_lanes*4)
        self.assertLessEqual(report['peak_live_bytes'],arch.intermediate_sram_bytes)
        self.assertGreater(report['avoided_logical_HBM_bytes'],50_000_000)
        before=stream.getvalue().splitlines();after=commands.splitlines()
        self.assertEqual(len(before),len(after))
        reference={};local=np.zeros(arch.intermediate_sram_bytes,dtype=np.uint8)
        by_tensor={a['tensor']:a for a in report['allocations']}
        for index,line in enumerate(before):
            access=report['local_accesses'].get(str(index))
            if access is None:
                self.assertEqual(line,after[index]);continue
            tensor=original['tensors'][access['tensor']];allocation=by_tensor[access['tensor']]
            self.assertNotEqual(tensor['name'],'selected_token')
            self.assertGreaterEqual(allocation['first_command'],0)
            self.assertTrue(allocation['first_command']<=index<=allocation['last_command'])
            self.assertLessEqual(allocation['sram_offset']+allocation['allocated_bytes'],len(local))
            expected=reference.setdefault(access['tensor'],np.zeros(tensor['size']*tensor['width'],dtype=np.uint8))
            for row in range(access['count']):
                start=access['address']-tensor['address']+row*access['stride'];end=start+access['bytes']
                slot=access['sram_offset']+row*access['stride'];dest=slot+access['bytes']
                if access['action']=='W':
                    payload=((np.arange(access['bytes'],dtype=np.uint32)+index*17)%251).astype(np.uint8)
                    expected[start:end]=payload;local[slot:dest]=payload
                else:np.testing.assert_array_equal(local[slot:dest],expected[start:end])
            converted=after[index].split()
            self.assertEqual(converted[3],'C')
            self.assertEqual(int(converted[4]),math.ceil(access['bytes']*access['count']/(arch.vector_lanes*4)))
        self.assertEqual(sum(o['read_bytes']+o['write_bytes'] for o in original['ops'])-
                         sum(o['read_bytes']+o['write_bytes'] for o in manifest['ops']),report['avoided_logical_HBM_bytes'])

    def test_no_space_is_byte_identical_and_unsafe_users_bypass(self):
        tensors=[dict(address=i*64,size=64,width=1,name='t'+str(i)) for i in range(4)]
        manifest=dict(tensors=tensors,preallocated_parameter_and_cache_bytes=64,
                      ops=[dict(read_bytes=160,write_bytes=128,compute_cycles=0)])
        commands='0 0 test R 64 32 1 0\n0 0 test W 64 64 1 0\n0 0 test W 128 64 1 0\n0 0 test P0 128 64 1 0\n0 0 test R 192 64 1 0\n'
        same,report=plan_residency(commands,copy.deepcopy(manifest),0,64)
        self.assertEqual(same,commands);self.assertFalse(report['allocations'])
        same,report=plan_residency(commands,copy.deepcopy(manifest),1024,64)
        self.assertEqual(same,commands);self.assertFalse(report['allocations'])

    def test_parallel_rows_match_native_independent_arrays(self):
        for physical_rows in (1,2):
            arch=Architecture(array_rows=physical_rows,array_cols=8,array_partitions=8,
                              operand_staging_bytes=4096,dataflow='os',parallel_head_rows=True)
            for m,k,n in [(4,31,16),(7,17,9),(4,33,65),(1,19,3)]:
                total=0
                for first in range(0,n,arch.output_tile_cols):
                    nt=min(arch.output_tile_cols,n-first);columns=math.ceil(nt/arch.array_cols)
                    workers=min(math.ceil(m/physical_rows),arch.array_partitions//columns);times=[]
                    for worker in range(workers):
                        rows=sum(min(physical_rows,m-start) for start in range(worker*physical_rows,m,workers*physical_rows))
                        for start in range(0,nt,arch.array_cols):
                            width=min(arch.array_cols,nt-start);cfg=scale_config();cfg.valid_conf_flag=True
                            cfg.array_rows=physical_rows;cfg.array_cols=arch.array_cols
                            engine=systolic_compute_os();engine.set_params(config_obj=cfg,
                                ifmap_op_mat=np.arange(rows*k).reshape(rows,k),filter_op_mat=np.arange(k*width).reshape(k,width),
                                ofmap_op_mat=np.arange(rows*width).reshape(rows,width))
                            times.append(len(engine.get_demand_matrices()[0]))
                    total+=max(times)
                self.assertEqual(arch.demand_cycles(m,n,k),total)

    def test_streaming_retains_nonzero_resource_costs_and_same_traffic(self):
        arch=Architecture.read(HERE/'configs/decode_f2_stream.json');ops=[]
        for enabled in (False,True):
            graph=Graph(io.StringIO(),steps=1,architecture=replace(arch,stream_value_cache=enabled))
            graph.fused_value_cache('v',graph.tensor('v',515*256,1),graph.tensor('s',515),515);ops.append(graph.op)
        self.assertEqual(ops[0]['read_bytes'],ops[1]['read_bytes']);self.assertEqual(ops[0]['write_bytes'],ops[1]['write_bytes'])
        self.assertLess(ops[1]['compute_cycles'],ops[0]['compute_cycles'])
        self.assertGreater(ops[1]['compute_cycles'],515*256/arch.sfu_lanes)
        self.assertGreater(arch.describe()['stream_pipeline_register_bytes'],0)

    def test_invalid_optimization_configuration(self):
        for args in [dict(intermediate_sram_bytes=-32),dict(intermediate_sram_bytes=True),dict(intermediate_sram_bytes=3),
                     dict(parallel_head_rows=True),dict(parallel_head_rows=1),dict(stream_value_cache=True),dict(stream_value_cache=1)]:
            with self.assertRaises(ValueError):Architecture(**args)

if __name__=='__main__':unittest.main()
