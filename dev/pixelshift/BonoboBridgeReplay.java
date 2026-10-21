// Requires a local H8 research language module; see the Pixel Shift guide.
// This is a bounded p-code replay, not a complete H8/SX hardware model.
// Execute only the original H8 receive getters and target-register writer.
// Register addresses are EMULATED RAM cells; no device/peripheral is accessed.
import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import java.io.*;
import java.math.BigInteger;
import java.nio.*;
import java.nio.file.*;

public class BonoboBridgeReplay extends GhidraScript {
    byte[] hex(String value) {
        byte[] result=new byte[value.length()/2];
        for(int i=0;i<result.length;i++) result[i]=(byte)Integer.parseInt(value.substring(2*i,2*i+2),16);
        return result;
    }
    int run(EmulatorHelper e,long start,long... ends) throws Exception {
        return runBound(e,start,1200,ends);
    }
    int runBound(EmulatorHelper e,long start,int limit,long... ends) throws Exception {
        e.writeRegister(e.getPCRegister(),BigInteger.valueOf(start));
        for(int steps=0;steps<limit;steps++) {
            long pc=e.getExecutionAddress().getOffset();
            for(long end:ends) if(pc==end) return steps;
            if(!e.step(monitor)) throw new IOException("PC="+Long.toHexString(pc)+": "+e.getLastError());
        }
        throw new IOException("Native H8 instruction bound reached");
    }
    long reg(EmulatorHelper e,String name) {return e.readRegister(name).longValue();}
    String hexBytes(byte[] bytes) {
        StringBuilder s=new StringBuilder();
        for(byte value:bytes) s.append(String.format("%02x",value&255));
        return s.toString();
    }
    byte[] nativeZeroState() throws Exception {
        EmulatorHelper e=new EmulatorHelper(currentProgram);
        try {
            for(int i=0;i<8;i++) e.writeRegister("er"+i,BigInteger.ZERO);
            e.writeRegister("er7",BigInteger.valueOf(0x13e00));
            byte[] dirty=new byte[0x85a];java.util.Arrays.fill(dirty,(byte)0x6b);
            byte[] left=e.readMemory(toAddr(0xcdf8),4),right=e.readMemory(toAddr(0xd656),4);
            e.writeMemory(toAddr(0xcdfc),dirty);
            runBound(e,0xb36c,20000,0xb390); // Original zero-init table/loop only.
            byte[] zeros=e.readMemory(toAddr(0xcdfc),dirty.length);
            for(byte value:zeros) if(value!=0) throw new IOException("Native BSS initialization did not clear its range");
            if(!java.util.Arrays.equals(left,e.readMemory(toAddr(0xcdf8),4)) ||
               !java.util.Arrays.equals(right,e.readMemory(toAddr(0xd656),4)))
                throw new IOException("Native BSS initialization changed neighboring data");
            // Check the exact multi-register stack forms on distinctive values.
            long[] values={0x11223344L,0x55667788L,0x99aabbccL};
            for(int i=0;i<3;i++) e.writeRegister("er"+(4+i),BigInteger.valueOf(values[i]));
            run(e,0x3444,0x3448);
            ByteBuffer stack=ByteBuffer.wrap(e.readMemory(toAddr(0x13df4),12)).order(ByteOrder.BIG_ENDIAN);
            for(int i=0;i<3;i++) if((stack.getInt(4*i)&0xffffffffL)!=values[2-i])
                throw new IOException("Native STM stack order differs");
            for(int i=0;i<3;i++) e.writeRegister("er"+(4+i),BigInteger.ZERO);
            run(e,0x34da,0x34de);
            for(int i=0;i<3;i++) if(reg(e,"er"+(4+i))!=values[i]) throw new IOException("Native LDM restore differs");
            if(reg(e,"er7")!=0x13e00) throw new IOException("Native stack forms did not restore SP");
            return zeros;
        } finally {e.dispose();}
    }
    void seedReceive(EmulatorHelper e,byte[] first,byte[] second,int bank) throws Exception {
        for(int i=0;i<8;i++) e.writeRegister("er"+i,BigInteger.ZERO);
        e.writeRegister("er7",BigInteger.valueOf(0x13e00));
        e.writeMemory(toAddr(0x13700),new byte[192]);
        e.writeMemory(toAddr(0x13700+bank*96),first);
        e.writeMemory(toAddr(0x13730+bank*96),second);
        e.writeMemory(toAddr(0xd790),new byte[16]);
        e.writeMemory(toAddr(0xd799),new byte[]{(byte)bank,1,(byte)(1-bank)});
        e.writeMemory(toAddr(0xce8e),new byte[]{0,40});
        e.writeMemory(toAddr(0x13102),new byte[]{0});
        e.writeRegister("er5",BigInteger.valueOf(0xd790));
    }
    public void run() throws Exception {
        String[] args=getScriptArgs();
        if(currentProgram.getMemory().getBlock(toAddr(0xff3fb000L))==null)
            currentProgram.getMemory().createInitializedBlock("EMULATED_REGISTERS",toAddr(0xff3fb000L),0x400,(byte)0,monitor,false);
        byte[] bootZeros=nativeZeroState();
        try(FileWriter out=new FileWriter(args[1])) {
            out.write("{\"camera_io\":false,\"physical_peripherals_executed\":false,\"peripheral_reply_inputs_synthetic\":true,\"full_receive_irq_executed\":false,\"native_zero_init_slice_executed\":true,\"later_board_configuration_executed\":false,\"cases\":[");
            boolean first=true;
            for(String row:Files.readAllLines(Paths.get(args[0]))) {
                String[] parts=row.split("\\t");
                if(parts[0].endsWith("-bad")) continue;
                boolean prefix=parts.length>2;
                byte[] firstPacket=prefix?hex(parts[1]):null;
                byte[] packet=hex(parts[prefix?2:1]);
                for(int bank=0;bank<2;bank++) {
                    int errorBoundaries=0;
                    if(prefix) for(int phase=0;phase<2;phase++) {
                        EmulatorHelper bad=new EmulatorHelper(currentProgram);
                        try {
                            byte[] a=firstPacket.clone(),b=packet.clone();
                            (phase==0?a:b)[38]^=1;
                            seedReceive(bad,a,b,bank);
                            run(bad,0x2bf8,0x2d34,0x2dfc);
                            if(bad.getExecutionAddress().getOffset()!=0x2d34 ||
                               (bad.readMemory(toAddr(0xd79b),1)[0]&255)==bank)
                                throw new IOException("Corrupt packet did not reach original checksum-error boundary");
                            errorBoundaries++;
                        } finally {bad.dispose();}
                    }
                    EmulatorHelper e=new EmulatorHelper(currentProgram);
                    try {
                        for(int i=0;i<8;i++) e.writeRegister("er"+i,BigInteger.ZERO);
                        e.writeRegister("er7",BigInteger.valueOf(0x13e00));
                        e.writeMemory(toAddr(0xcdfc),bootZeros);
                        e.writeMemory(toAddr(0x13880),packet);
                        e.writeRegister("er0",BigInteger.valueOf(0x13880));
                        e.writeRegister("er1",BigInteger.valueOf(20));
                        run(e,0x249a,0x24aa);
                        if(reg(e,"r0")!=0xf0f) throw new IOException("Input packet did not pass original H8 checksum");
                        int receiveSteps=0;
                        if(prefix) {
                            seedReceive(e,firstPacket,packet,bank);
                            receiveSteps=run(e,0x2bf8,0x2dfc);
                            if((e.readMemory(toAddr(0xd79b),1)[0]&255)!=bank ||
                               (e.readMemory(toAddr(0xd799),1)[0]&255)!=1-bank)
                                throw new IOException("Native type/checksum prefix did not select the received bank");
                        } else e.writeMemory(toAddr(0xd79b),new byte[]{(byte)bank});
                        long source=0x13730+bank*96;
                        if(!prefix) e.writeMemory(toAddr(source),packet);
                        else if(!java.util.Arrays.equals(e.readMemory(toAddr(source),40),packet))
                            throw new IOException("Native receive prefix changed the accepted packet");
                        int steps=run(e,0x3194,0x31a8);
                        int mode=(int)reg(e,"r0l");
                        if(mode!=(packet[3]&255)) throw new IOException("Native mode getter differs");
                        int[] vector=new int[3];
                        long[] getters={0x31aa,0x31fa,0x324a},ends={0x31f8,0x3248,0x3298};
                        ByteBuffer input=ByteBuffer.wrap(packet).order(ByteOrder.LITTLE_ENDIAN);
                        for(int i=0;i<3;i++) {
                            steps+=run(e,getters[i],ends[i]);
                            vector[i]=(int)reg(e,"er0");
                            if(vector[i]!=input.getInt(4+4*i)) throw new IOException("Native vector getter differs: "+i);
                        }
                        steps+=run(e,0x33ae,0x33c2);
                        int trinity=(int)reg(e,"r0l");
                        if(trinity!=(packet[28]&255)) throw new IOException("Native TRINITY getter differs");
                        steps+=run(e,0xa46c,0xa474,0xa4d8);
                        boolean selected=e.getExecutionAddress().getOffset()==0xa474;
                        if(selected!=(trinity==1)) throw new IOException("Native TRINITY branch differs");
                        // Override/reference defaults came from the original BSS loop.
                        if(e.readMemory(toAddr(0xd32a),1)[0]!=0) throw new IOException("Native boot override was changed");
                        // This separate parameter remains a synthetic fixture, not body calibration.
                        e.writeMemory(toAddr(0x1356e),new byte[]{0,18});
                        byte[] cells=new byte[0x400];java.util.Arrays.fill(cells,(byte)0x6b);
                        e.writeMemory(toAddr(0xff3fb000L),cells);
                        steps+=run(e,0x514a,0x51c0,0x5212,0x5230);
                        long[] addresses={0xff3fb010L,0xff3fb014L,0xff3fb018L,0xff3fb354L,0xff3fb358L,0xff3fb35cL};
                        int[] values=new int[6];
                        int[] expected=mode==1 ? new int[]{vector[0],vector[1],-(vector[2]+(18<<16)),0,0,0}
                            : mode==2 ? new int[]{0,0,-(18<<16),vector[0],vector[1],vector[2]}
                            : new int[]{0,0,-(18<<16),0,0,0};
                        for(int i=0;i<6;i++) {
                            values[i]=ByteBuffer.wrap(e.readMemory(toAddr(addresses[i]),4)).order(ByteOrder.BIG_ENDIAN).getInt();
                            if(values[i]!=expected[i]) throw new IOException("Native emulated register differs: "+Long.toHexString(addresses[i]));
                        }
                        byte[] after=e.readMemory(toAddr(0xff3fb000L),0x400);
                        for(int i=0;i<after.length;i++) {
                            boolean allowed=(i>=0x10&&i<0x1c)||(i>=0x354&&i<0x360);
                            if(!allowed&&after[i]!=(byte)0x6b) throw new IOException("Unexpected emulated register write");
                        }
                        // Returned register inputs are independent of desired targets.
                        int[] returned=bank==0 ? new int[]{0x01234567,0xfedcba98,0x80007fff}
                            : new int[]{0x7fffffff,0x0001ffff,0xffff0001};
                        for(int i=0;i<3;i++) e.writeMemory(toAddr(0xff3fb070L+4*i),
                            ByteBuffer.allocate(4).order(ByteOrder.BIG_ENDIAN).putInt(returned[i]).array());
                        byte[] blankReply=new byte[40];blankReply[0]=(byte)0xa5;blankReply[1]=0x5a;
                        e.writeMemory(toAddr(0x137f0),blankReply); // SIO framing is outside this replay.
                        int replySteps=run(e,0x52ac,0x52de); // Native reads and three formatter calls.
                        e.writeRegister("er4",BigInteger.valueOf(0x137f0));
                        replySteps+=run(e,0x2f22,0x2f54); // Native type8 header/checksum builder.
                        byte[] reply=e.readMemory(toAddr(0x137f0),40);
                        int[] words=new int[3];
                        for(int i=0;i<3;i++) {
                            words[i]=ByteBuffer.wrap(reply).order(ByteOrder.LITTLE_ENDIAN).getShort(4+2*i);
                            if(words[i]!=(returned[i]>>16)) throw new IOException("Native reply did not retain peripheral high word");
                        }
                        if(reply[2]!=8||reply[3]!=0) throw new IOException("Native reply type differs");
                        e.writeMemory(toAddr(0x13880),reply);
                        e.writeRegister("er0",BigInteger.valueOf(0x13882));
                        e.writeRegister("er1",BigInteger.valueOf(19));
                        replySteps+=run(e,0x249a,0x24aa);
                        if(reg(e,"r0")!=0xf0f) throw new IOException("Native reply XOR differs");
                        if(reg(e,"er7")!=0x13e00 || !java.util.Arrays.equals(e.readMemory(toAddr(source),40),packet))
                            throw new IOException("Native H8 getter/writer changed stack or input");
                        if(!first) out.write(",");first=false;
                        out.write("{\"label\":\""+parts[0]+"\",\"bank\":"+bank+",\"receive_prefix_executed\":"+prefix+
                            ",\"receive_prefix_steps\":"+receiveSteps+",\"mode\":"+mode+
                            ",\"corrupt_checksum_error_boundaries\":"+errorBoundaries+
                            ",\"trinity\":"+trinity+",\"native_trinity_branch\":"+selected+
                            ",\"vector\":"+java.util.Arrays.toString(vector)+",\"emulated_register_values\":"+
                            java.util.Arrays.toString(values)+",\"native_steps\":"+steps+
                            ",\"peripheral_reply_inputs_raw\":"+java.util.Arrays.toString(returned)+
                            ",\"reply_words\":"+java.util.Arrays.toString(words)+
                            ",\"native_reply_payload\":\""+hexBytes(reply)+"\",\"native_reply_steps\":"+replySteps+
                            ",\"framing_bytes_synthetic\":true}");
                        out.flush();
                    } finally {e.dispose();}
                }
            }
            out.write("]}");
        }
        println("BONOBO NATIVE FIELD/REGISTER REPLAY DONE");
    }
}
