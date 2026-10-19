// SPDX-License-Identifier: MIT
// Switchboard transports test inputs/results to an actual Verilated RTL model.
// Host memory adapters provide operands; no GEMM arithmetic is done here.
#include "Vdecode_os_core.h"
#include "verilated.h"
#include "switchboard.hpp"
#include <array>
#include <cstring>
#include <iostream>
#include <random>
#include <vector>
#include <sys/stat.h>

static constexpr unsigned P=4,C=8;
static void tick(Vdecode_os_core& d) { d.clk=0;d.eval();d.clk=1;d.eval();d.clk=0;d.eval(); }
static uint32_t word(const sb_packet& p,unsigned i) { uint32_t v;std::memcpy(&v,p.data+4*i,4);return v; }
static void put(sb_packet& p,unsigned i,uint32_t v) { std::memcpy(p.data+4*i,&v,4); }
int main(int argc,char** argv) {
    if(argc!=3) return 2;
    Verilated::commandArgs(argc,argv);
    // A Rosetta Verilator executable and native Python can have different page
    // sizes. Use the already-created queue file capacity on both endpoints.
    struct stat incoming{},outgoing{};
    if(stat(argv[1],&incoming) || stat(argv[2],&outgoing)) return 2;
    SBRX rx;SBTX tx;
    rx.init(argv[1],spsc_capacity(incoming.st_size));
    tx.init(argv[2],spsc_capacity(outgoing.st_size));
    Vdecode_os_core d;d.rst=1;d.cmd_valid=0;d.cycle_ready=0;tick(d);d.rst=0;tick(d);
    std::vector<uint8_t> a(4*8192),b(8192*P*C);
    std::vector<uint32_t> seed(4*P*C),out(4*P*C);
    sb_packet pkt{};
    try {
        for(;;) {
            rx.recv_blocking(pkt);
            unsigned op=pkt.destination;
            if(op==0) break;
            if(op==1 || op==2) {
                auto& dst=(op==1)?a:b;
                unsigned offset=word(pkt,0),count=word(pkt,1);
                if(count>44 || offset+count>dst.size()) throw std::runtime_error("invalid byte transfer");
                std::memcpy(dst.data()+offset,pkt.data+8,count);
            } else if(op==3) {
                unsigned offset=word(pkt,0),count=word(pkt,1);
                if(count>11 || offset+count>seed.size()) throw std::runtime_error("invalid seed transfer");
                for(unsigned i=0;i<count;i++) seed[offset+i]=word(pkt,i+2);
            } else if(op==4) {
                unsigned m=word(pkt,0),k=word(pkt,1),n=word(pkt,2),flags=word(pkt,3);
                d.cmd_m=m;d.cmd_k=k;d.cmd_n=n;d.cmd_parallel_rows=flags&1;d.cmd_accumulate=(flags>>1)&1;
                d.cmd_valid=1;tick(d);d.cmd_valid=0;
                if(d.command_error || !d.busy) throw std::runtime_error("command rejected");
                std::fill(out.begin(),out.end(),0);
                std::mt19937 rng(word(pkt,4));unsigned cycles=0,count=0;
                while(d.busy) {
                    if(++cycles>1000000) throw std::runtime_error("RTL timeout");
                    d.eval();d.a_data=0;
                    for(unsigned p=0;p<P;p++) if((d.a_valid>>p)&1) d.a_data|=uint32_t(a.at(d.a_address[p]))<<(p*8);
                    for(unsigned i=0;i<P*C/4;i++) d.b_data[i]=0;
                    for(unsigned i=0;i<P*C;i++) {
                        if((d.b_valid>>i)&1) d.b_data[i/4]|=uint32_t(b.at(d.b_address[i]))<<((i%4)*8);
                        d.seed_data[i]=((d.seed_valid>>i)&1)?seed.at(d.c_address[i]):0;
                    }
                    d.cycle_ready=(rng()%4)!=0;d.eval();
                    if(d.cycle_ready) for(unsigned i=0;i<P*C;i++) if((d.c_valid>>i)&1) {
                        out.at(d.c_address[i])=d.c_data[i];count++;
                    }
                    tick(d);
                }
                if(count!=m*n) throw std::runtime_error("wrong result count");
                for(unsigned offset=0;offset<m*n;offset+=11) {
                    sb_packet result{};result.destination=0;unsigned length=std::min(11U,m*n-offset);
                    put(result,0,offset);put(result,1,length);
                    for(unsigned i=0;i<length;i++) put(result,i+2,out[offset+i]);
                    tx.send_blocking(result);
                }
                sb_packet status{};status.destination=1;status.last=1;
                put(status,0,uint32_t(d.logical_cycles));put(status,1,uint32_t(d.elapsed_cycles));
                put(status,2,uint32_t(d.stall_cycles));tx.send_blocking(status);
            } else throw std::runtime_error("unknown operation");
        }
    } catch(const std::exception& e) { std::cerr<<e.what()<<'\n';return 1; }
    d.final();return 0;
}
