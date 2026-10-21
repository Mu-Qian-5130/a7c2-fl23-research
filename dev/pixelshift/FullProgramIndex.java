// Export every decoded instruction/function/reference, not only Pixel Shift matches.
// Run on a private copy of a firmware project. Never accesses a physical device.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;

public class FullProgramIndex extends GhidraScript {
    private String field(Object value) {
        return String.valueOf(value).replace("\\", "\\\\").replace("\t", "\\t")
            .replace("\n", "\\n").replace("\r", "\\r");
    }
    private PrintWriter writer(String prefix, String suffix) throws IOException {
        return new PrintWriter(new BufferedWriter(new FileWriter(prefix + suffix)));
    }
    public void run() throws Exception {
        String prefix = getScriptArgs()[0];
        long instructions = 0, functions = 0, references = 0, strings = 0;
        try (PrintWriter out = writer(prefix, ".instructions.tsv")) {
            out.println("address\tlength\tfunction_entry\tflow_type\tinstruction");
            for (Instruction ins : currentProgram.getListing().getInstructions(true)) {
                monitor.checkCancelled();
                Function fn = getFunctionContaining(ins.getAddress());
                out.println(ins.getAddress() + "\t" + ins.getLength() + "\t"
                    + (fn == null ? "" : fn.getEntryPoint()) + "\t" + ins.getFlowType() + "\t" + field(ins));
                instructions++;
            }
        }
        try (PrintWriter out = writer(prefix, ".functions.tsv")) {
            out.println("entry\tname\tbody_bytes\tbody_ranges\tthunk\tsignature");
            for (Function fn : currentProgram.getFunctionManager().getFunctions(true)) {
                monitor.checkCancelled();
                out.println(fn.getEntryPoint() + "\t" + field(fn.getName(true)) + "\t"
                    + fn.getBody().getNumAddresses() + "\t" + field(fn.getBody()) + "\t"
                    + fn.isThunk() + "\t" + field(fn.getSignature()));
                functions++;
            }
        }
        try (PrintWriter out = writer(prefix, ".references.tsv")) {
            out.println("from\tto\ttype\toperand\tsource\tprimary");
            ReferenceIterator it = currentProgram.getReferenceManager().getReferenceIterator(currentProgram.getMinAddress());
            while (it.hasNext()) {
                monitor.checkCancelled();
                Reference ref = it.next();
                out.println(ref.getFromAddress() + "\t" + ref.getToAddress() + "\t" + ref.getReferenceType()
                    + "\t" + ref.getOperandIndex() + "\t" + ref.getSource() + "\t" + ref.isPrimary());
                references++;
            }
        }
        try (PrintWriter out = writer(prefix, ".strings.tsv")) {
            out.println("address\tbytes\tvalue");
            for (Data data : currentProgram.getListing().getDefinedData(true)) {
                monitor.checkCancelled();
                if (!data.hasStringValue()) continue;
                out.println(data.getAddress() + "\t" + data.getLength() + "\t" + field(data.getValue())); strings++;
            }
        }
        println("WHOLE INDEX " + currentProgram.getName() + " instructions=" + instructions
            + " functions=" + functions + " references=" + references + " strings=" + strings);
    }
}
