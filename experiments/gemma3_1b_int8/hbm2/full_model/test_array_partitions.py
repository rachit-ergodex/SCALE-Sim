"""Independent checks for parallel OS partitions and bijective HBM interleaving."""
import csv
import json
import tempfile
import io
import random
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
import numpy as np
import torch
from config import Architecture
from workload import Graph
from experiments.gemma3_1b_int8.hbm2.f2_config import make_f2_config
from tiled_gemm_reference import execute_tiled
from scalesim.scale_config import scale_config
from scalesim.compute.systolic_compute_os import systolic_compute_os

HERE=Path(__file__).resolve().parent

class PartitionChecks(unittest.TestCase):
    def test_parallel_schedule_matches_maximum_of_native_arrays(self):
        for partitions in (1,2,4,8):
            arch=Architecture(array_rows=1,array_cols=8,array_partitions=partitions,
                              operand_staging_bytes=partitions*256,dataflow='os',balance_k_tiles=True)
            for m,k,n in ((1,67,129),(4,31,65),(1,17,3)):
                scheduled=0
                for n0 in range(0,n,arch.output_tile_cols):
                    nt=min(arch.output_tile_cols,n-n0)
                    for k0,kt in arch.k_tiles(k):
                        durations=[]
                        for sub in range(0,nt,arch.array_cols):
                            width=min(arch.array_cols,nt-sub)
                            cfg=scale_config();cfg.valid_conf_flag=True;cfg.array_rows=1;cfg.array_cols=8
                            engine=systolic_compute_os();engine.set_params(config_obj=cfg,
                                ifmap_op_mat=np.arange(m*kt).reshape(m,kt),
                                filter_op_mat=np.arange(kt*width).reshape(kt,width),
                                ofmap_op_mat=np.arange(m*width).reshape(m,width))
                            durations.append(len(engine.get_demand_matrices()[0]))
                        self.assertEqual(arch.demand_cycles(m,nt,kt),max(durations))
                        scheduled+=max(durations)
                g=Graph(io.StringIO(),steps=1,architecture=arch)
                g.gemm('test',g.tensor('a',m*k,1),m,k,n,g.tensor('b',k*n,1))
                self.assertEqual(g.op['native_array_cycles'],scheduled)

    def test_partitioned_packing_and_integer_results(self):
        torch.set_num_threads(2);torch.manual_seed(319)
        for partitions in (2,4,8):
            arch=Architecture(array_rows=1,array_cols=8,array_partitions=partitions,
                operand_staging_bytes=partitions*256,vector_staging_bytes=32768,
                dataflow='os',gemm_prefetch=True,balance_k_tiles=True)
            for layout,m,k,n in [('packed',1,1152,137),('key_transpose',4,256,515),('row_major',4,515,256)]:
                a=torch.randint(-127,128,(m,k),dtype=torch.int8)
                b=torch.randint(-127,128,(k,n),dtype=torch.int8)
                result=execute_tiled(a,b,arch,layout)
                np.testing.assert_array_equal(result.numpy(),a.numpy().astype(np.int64)@b.numpy().astype(np.int64))

    def test_physical_mapping_preserves_bits_and_round_trips(self):
        # Independent scalar oracle tests the compiled production mapping.
        destinations=[14,16,17,9,10,11,12,13,15]
        samples=[0,(1<<34)-1]+[1<<bit for bit in range(34)]
        rng=random.Random(92);samples += [rng.randrange(1<<34) for _ in range(64)]
        for address in samples:
            mapped=int(subprocess.check_output([str(HERE/'build/runner'),'--map-address',str(address)],text=True))
            self.assertEqual(mapped&511,address&511)
            self.assertEqual(mapped>>18,address>>18)
            inverse=mapped&~(511<<9)
            for bit,destination in enumerate(destinations):inverse|=((mapped>>destination)&1)<<(9+bit)
            self.assertEqual(inverse,address)
            self.assertLess(mapped,1<<34)

    def test_native_ragged_contiguous_output_has_one_request_per_line(self):
        arch=Architecture(array_rows=1,array_cols=256,array_partitions=4,
            operand_staging_bytes=1048576,vector_staging_bytes=131072,
            dataflow='os',gemm_prefetch=True,balance_k_tiles=True)
        stream=io.StringIO();g=Graph(stream,steps=1,architecture=arch)
        g.gemm('qk',g.tensor('a',4*256,1),4,256,513,g.tensor('b',256*513,1),'key_transpose')
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);commands=folder/'commands';report=folder/'report'
            commands.write_text(stream.getvalue())
            config=folder/'hbm2.json';config.write_text(json.dumps(make_f2_config(16)[0]))
            subprocess.run([str(HERE/'build/runner'),str(config),
                str(commands),str(report),'1000000000','16','10000','512','1'],check=True,stdout=subprocess.DEVNULL)
            with report.open() as f:r=next(csv.DictReader(f))
            self.assertEqual(int(r['writes']),(4*513*4+31)//32)

    def test_invalid_partition_configuration(self):
        for config in ({'array_partitions':0},{'array_partitions':True},
                       {'array_partitions':4},{'hbm_address_mapping':'unknown'},
                       {'max_inflight_requests':0},{'hbm_read_queue':0}):
            with self.assertRaises(ValueError):Architecture(**config)

if __name__=='__main__':unittest.main()
