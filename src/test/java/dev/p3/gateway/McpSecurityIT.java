package dev.p3.gateway;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;
import java.util.Set;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.p3.gateway.audit.AuditTrail;
import dev.p3.gateway.erp.ErpStore;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.boot.test.web.server.LocalServerPort;
import static org.junit.jupiter.api.Assertions.*;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
    properties = {"debug=false", "logging.level.root=INFO", "logging.level.org.springframework.web=WARN"})
@ExtendWith(OutputCaptureExtension.class)
class McpSecurityIT {
    @LocalServerPort int port;
    @Autowired ObjectMapper mapper;
    @Autowired ErpStore store;
    @Autowired AuditTrail audit;
    private final HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    private String key(String identity) {
        return identity + "." + System.getenv(switch (identity) {
            case "reader-a" -> "P3_READER_A_SECRET";
            case "buyer-a" -> "P3_BUYER_A_SECRET";
            case "buyer-b" -> "P3_BUYER_B_SECRET";
            default -> throw new IllegalArgumentException("Unknown test identity");
        });
    }
    private String wrongKey(String identity) {
        String valid = key(identity);
        char replacement = valid.charAt(valid.length() - 1) == 'a' ? 'b' : 'a';
        return valid.substring(0, valid.length() - 1) + replacement;
    }
    private HttpResponse<String> rpc(String method, Map<String, Object> params, String credential) throws Exception {
        var request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/mcp"))
            .timeout(Duration.ofSeconds(10)).header("Content-Type", "application/json")
            .header("Accept", "application/json, text/event-stream").header("MCP-Protocol-Version", "2025-06-18")
            .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(Map.of("jsonrpc", "2.0", "id", 1, "method", method, "params", params))));
        if (credential != null) request.header("X-API-Key", credential);
        var response = client.send(request.build(), HttpResponse.BodyHandlers.ofString());
        assertNoSecrets(response.body());
        return response;
    }
    private JsonNode call(String identity, String tool, Map<String, Object> arguments) throws Exception {
        var response = rpc("tools/call", Map.of("name", tool, "arguments", arguments), key(identity));
        assertEquals(200, response.statusCode());
        return mapper.readTree(response.body());
    }
    private JsonNode payload(JsonNode response) throws Exception {
        return mapper.readTree(response.path("result").path("content").get(0).path("text").asText());
    }
    private void denied(String identity, String tool, Map<String, Object> arguments, String code) throws Exception {
        var before = store.snapshot();
        JsonNode response = call(identity, tool, arguments);
        assertTrue(response.path("result").path("isError").asBoolean());
        assertEquals(code, payload(response).path("code").asText());
        assertEquals(before, store.snapshot(), "Denied request must preserve every order");
    }
    private void assertNoSecrets(String text) {
        for (String name : Set.of("P3_READER_A_SECRET", "P3_BUYER_A_SECRET", "P3_BUYER_B_SECRET")) {
            String secret = System.getenv(name);
            assertNotNull(secret, "Run scripts/verify.ps1 or provide P3 secret environment variables");
            assertFalse(text.contains(secret), "Secret must never appear in responses or logs");
        }
    }

    @Test void initializeAndDiscoverExactlyTwoTools() throws Exception {
        var response = rpc("initialize", Map.of("protocolVersion", "2025-06-18", "capabilities", Map.of(),
            "clientInfo", Map.of("name", "p3-http-test", "version", "1")), key("reader-a"));
        assertEquals(200, response.statusCode());
        assertEquals("2025-06-18", mapper.readTree(response.body()).path("result").path("protocolVersion").asText());
        var list = rpc("tools/list", Map.of(), key("reader-a"));
        assertEquals(200, list.statusCode());
        var names = new java.util.HashSet<String>();
        mapper.readTree(list.body()).path("result").path("tools").forEach(t -> names.add(t.path("name").asText()));
        assertEquals(Set.of("inventory.read", "purchase_order.update"), names);
    }
    @Test void credentialsRequiredForEveryMcpMethod() throws Exception {
        for (String method : Set.of("initialize", "tools/list", "tools/call")) {
            var before = store.snapshot();
            assertEquals(401, rpc(method, Map.of(), null).statusCode());
            assertEquals(401, rpc(method, Map.of(), wrongKey("reader-a")).statusCode());
            assertEquals(401, rpc(method, Map.of(), "malformed").statusCode());
            assertEquals(401, rpc(method, Map.of(), key("reader-a") + ".suffix").statusCode());
            assertEquals(401, rpc(method, Map.of(), "reader-a.").statusCode());
            assertEquals(before, store.snapshot());
        }
    }
    @Test void readerReadsAuthorizedInventory() throws Exception {
        var result = call("reader-a", "inventory.read", Map.of("productId", "sku-a1"));
        assertFalse(result.path("result").path("isError").asBoolean());
        assertEquals(120, payload(result).path("data").path("available").asInt());
    }
    @Test void buyerUpdatesOwnOrderWithObservableMutation() throws Exception {
        int before = store.order("po-a1").version();
        var result = call("buyer-a", "purchase_order.update", Map.of("orderId", "po-a1", "quantity", 25));
        assertFalse(result.path("result").path("isError").asBoolean());
        assertEquals(25, payload(result).path("data").path("quantity").asInt());
        assertEquals(before + 1, store.order("po-a1").version());
        assertEquals(25, store.order("po-a1").quantity());
    }
    @Test void readerCannotWrite() throws Exception {
        denied("reader-a", "purchase_order.update", Map.of("orderId", "po-a1", "quantity", 99), "FORBIDDEN");
    }
    @Test void bothTenantsCannotCrossReadOrWrite() throws Exception {
        denied("buyer-a", "inventory.read", Map.of("productId", "sku-b1"), "FORBIDDEN");
        denied("buyer-a", "purchase_order.update", Map.of("orderId", "po-b1", "quantity", 99), "FORBIDDEN");
        denied("buyer-b", "inventory.read", Map.of("productId", "sku-a1"), "FORBIDDEN");
        denied("buyer-b", "purchase_order.update", Map.of("orderId", "po-a1", "quantity", 99), "FORBIDDEN");
        assertFalse(call("buyer-b", "inventory.read", Map.of("productId", "sku-b1")).path("result").path("isError").asBoolean());
    }
    @Test void sameTenantUnassignedResourcesDenied() throws Exception {
        denied("buyer-a", "inventory.read", Map.of("productId", "sku-a2"), "FORBIDDEN");
        denied("buyer-a", "purchase_order.update", Map.of("orderId", "po-a2", "quantity", 99), "FORBIDDEN");
    }
    @Test void unknownToolDeniedWithoutReflectingUntrustedName() throws Exception {
        var before = store.snapshot();
        var response = call("buyer-a", key("buyer-a"), Map.of("quantity", 99));
        assertEquals("UNKNOWN_TOOL", response.path("error").path("message").asText());
        assertEquals(before, store.snapshot());
    }
    @Test void invalidParametersDenied() throws Exception {
        for (Object value : java.util.List.of(0, 1001, "25", 2.5, true, 999999999999L))
            denied("buyer-a", "purchase_order.update", Map.of("orderId", "po-a1", "quantity", value), "INVALID_ARGUMENTS");
        denied("buyer-a", "purchase_order.update", Map.of("orderId", "po-a1"), "INVALID_ARGUMENTS");
        denied("buyer-a", "inventory.read", Map.of("productId", "../etc/passwd"), "INVALID_ARGUMENTS");
    }
    @Test void agentForgedRoleAndTenantCannotBypassPolicy() throws Exception {
        // Simulated Agent plan is sent through the actual HTTP endpoint.
        denied("reader-a", "purchase_order.update", Map.of("orderId", "po-a1", "quantity", 99,
            "role", "ADMIN", "tenantId", "tenant-a"), "INVALID_ARGUMENTS");
        denied("buyer-a", "purchase_order.update", Map.of("orderId", "po-b1", "quantity", 99,
            "role", "ADMIN", "tenantId", "tenant-b"), "INVALID_ARGUMENTS");
        denied("buyer-a", "purchase_order.update", Map.of("orderId", "po-b1", "quantity", 99), "FORBIDDEN");
    }
    @Test void errorsAndAuditDoNotLeakSecrets(CapturedOutput output) throws Exception {
        denied("buyer-a", "purchase_order.update", Map.of("orderId", "po-a1", "quantity", key("buyer-a")), "INVALID_ARGUMENTS");
        var events = audit.snapshot();
        assertFalse(events.isEmpty());
        var last = events.get(events.size() - 1);
        assertEquals("buyer-a", last.caller());
        assertEquals("DENY", last.decision());
        assertEquals("INVALID_ARGUMENTS", last.reason());
        assertTrue(last.requestId().matches("[a-f0-9-]{36}"));
        assertNoSecrets(mapper.writeValueAsString(events));
        assertNoSecrets(output.getAll());
    }
}
