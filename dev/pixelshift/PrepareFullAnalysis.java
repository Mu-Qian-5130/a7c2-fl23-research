// Schedule all enabled analyzers across the entire existing private program.
import ghidra.app.script.GhidraScript;
import ghidra.app.plugin.core.analysis.AutoAnalysisManager;

public class PrepareFullAnalysis extends GhidraScript {
    public void run() throws Exception {
        // Retain architecture context, existing labels and project-specific options.
        // Do not use aggressive linear disassembly over strings, tables or other data.
        AutoAnalysisManager.getAnalysisManager(currentProgram).reAnalyzeAll(null);
        println("FULL ANALYSIS SCHEDULED " + currentProgram.getName());
    }
}
