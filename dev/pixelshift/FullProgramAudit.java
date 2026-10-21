// Offline Ghidra coverage inventory. Outputs belong in a private research directory.
import ghidra.app.util.headless.HeadlessScript;
import ghidra.framework.options.Options;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.MemoryBlock;
import java.io.*;

public class FullProgramAudit extends HeadlessScript {
    private String q(Object value) {
        String s = String.valueOf(value);
        return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"")
            .replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t") + "\"";
    }
    public void run() throws Exception {
        String path = getScriptArgs()[0];
        AddressSet decoded = new AddressSet();
        long instructions = 0, functions = 0, indirect = 0, flows = 0;
        for (Instruction ins : currentProgram.getListing().getInstructions(true)) {
            monitor.checkCancelled();
            decoded.add(ins.getMinAddress(), ins.getMaxAddress());
            instructions++;
            if (ins.getFlowType().isComputed()) indirect++;
            flows += ins.getFlows().length;
        }
        AddressSet bodies = new AddressSet();
        for (Function fn : currentProgram.getFunctionManager().getFunctions(true)) {
            bodies.add(fn.getBody()); functions++;
        }
        try (PrintWriter out = new PrintWriter(new BufferedWriter(new FileWriter(path)))) {
            out.println("{\"program\":" + q(currentProgram.getName())
                + ",\"language\":" + q(currentProgram.getLanguageID())
                + ",\"image_base\":" + q(currentProgram.getImageBase())
                + ",\"analysis_timeout\":" + analysisTimeoutOccurred()
                + ",\"instructions\":" + instructions
                + ",\"instruction_bytes\":" + decoded.getNumAddresses()
                + ",\"functions\":" + functions + ",\"function_body_bytes\":" + bodies.getNumAddresses()
                + ",\"computed_flow_instructions\":" + indirect + ",\"direct_flow_targets\":" + flows + ",\"blocks\":[");
            boolean comma = false;
            for (MemoryBlock block : currentProgram.getMemory().getBlocks()) {
                if (comma) out.println(","); comma = true;
                AddressSet range = new AddressSet(block.getStart(), block.getEnd());
                out.print("{\"name\":" + q(block.getName()) + ",\"start\":" + q(block.getStart())
                    + ",\"bytes\":" + block.getSize() + ",\"initialized\":" + block.isInitialized()
                    + ",\"executable\":" + block.isExecute()
                    + ",\"instruction_bytes\":" + decoded.intersect(range).getNumAddresses()
                    + ",\"function_body_bytes\":" + bodies.intersect(range).getNumAddresses() + "}");
            }
            out.println("],\"analysis_options\":{"); comma = false;
            Options options = currentProgram.getOptions("Analyzers");
            for (String name : options.getOptionNames()) {
                if (comma) out.println(","); comma = true;
                out.print(q(name) + ":" + q(options.getValueAsString(name)));
            }
            out.println("}}");
        }
        println("COVERAGE " + currentProgram.getName() + " instructions=" + instructions
            + " bytes=" + decoded.getNumAddresses() + " functions=" + functions + " output=" + path);
    }
}
