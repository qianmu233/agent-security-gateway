package dev.p3.gateway.support;

import java.util.Map;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

/** Deterministic unsafe planning simulation, not a model or injection detector.
 * It knows only MCP HTTP; no server-side service or granting API is accessible here. */
public final class MockAgent {
    public enum Behavior { NORMAL, FOLLOW_INJECTED_NOTE }
    public record UserTask(String instruction, String productId) {}
    public record Trace(String task, String trust, boolean induced, String proposedTool, McpHttpClient.Reply result) {}
    private final McpHttpClient mcp;
    private final ObjectMapper mapper;
    public MockAgent(McpHttpClient mcp, ObjectMapper mapper) { this.mcp = mcp; this.mapper = mapper; }

    public Trace run(UserTask task, Behavior behavior) throws Exception {
        var read = mcp.call("inventory.read", Map.of("productId", task.productId()));
        if (read.status() != 200 || read.isError()) throw new AssertionError("Mock Agent initial read failed");
        var data = mcp.payload(read).path("data");
        String note = data.path("note").asText();
        String trust = data.path("noteTrust").asText();
        // The deliberately vulnerable planner follows a fixture embedded in untrusted data.
        int begin = note.indexOf("[[CALL]]"), end = note.indexOf("[[/CALL]]");
        if (behavior == Behavior.FOLLOW_INJECTED_NOTE && begin >= 0 && end > begin) {
            var proposal = mapper.readTree(note.substring(begin + "[[CALL]]".length(), end));
            String tool = proposal.path("name").asText();
            Map<String, Object> arguments = mapper.convertValue(proposal.path("arguments"), new TypeReference<>() {});
            return new Trace(task.instruction(), trust, true, tool, mcp.call(tool, arguments));
        }
        return new Trace(task.instruction(), trust, false, "inventory.read", read);
    }
    public McpHttpClient.Reply executeExplicitUserWrite(String orderId, int quantity, String trustedIntent) throws Exception {
        return mcp.call("purchase_order.update", Map.of("orderId", orderId, "quantity", quantity, "intentId", trustedIntent));
    }
}
