package dev.p3.gateway.support;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/** Holds a fixed credential chosen by the trusted test setup, never by tool text. */
public final class McpHttpClient {
    public record Reply(int status, JsonNode body, double latencyMillis) {
        public boolean isError() { return status < 200 || status >= 300 || body.has("error") || body.path("result").path("isError").asBoolean(); }
    }
    private final HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    private final ObjectMapper mapper;
    private final URI uri;
    private final String credential;
    public McpHttpClient(int port, ObjectMapper mapper, String credential) {
        this.uri = URI.create("http://127.0.0.1:" + port + "/mcp");
        this.mapper = mapper; this.credential = credential;
    }
    public Reply rpc(String method, Map<String, Object> params) throws Exception {
        var request = HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(10))
            .header("Content-Type", "application/json").header("Accept", "application/json, text/event-stream")
            .header("MCP-Protocol-Version", "2025-06-18")
            .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(Map.of("jsonrpc", "2.0", "id", 2, "method", method, "params", params))));
        if (credential != null) request.header("X-API-Key", credential);
        long start = System.nanoTime();
        var response = client.send(request.build(), HttpResponse.BodyHandlers.ofString());
        double elapsed = (System.nanoTime() - start) / 1_000_000.0;
        for (String name : java.util.List.of("P3_READER_A_SECRET", "P3_BUYER_A_SECRET", "P3_BUYER_B_SECRET")) {
            String secret = System.getenv(name);
            if (secret != null && response.body().contains(secret)) throw new AssertionError("API secret reflected in response");
        }
        return new Reply(response.statusCode(), response.body().isEmpty() ? mapper.createObjectNode() : mapper.readTree(response.body()), elapsed);
    }
    public Reply call(String name, Map<String, Object> arguments) throws Exception {
        return rpc("tools/call", Map.of("name", name, "arguments", arguments));
    }
    public JsonNode payload(Reply reply) throws Exception {
        return mapper.readTree(reply.body().path("result").path("content").get(0).path("text").asText());
    }
    public String code(Reply reply) throws Exception {
        if (reply.status() == 401) return "AUTHENTICATION_FAILED";
        if (reply.status() != 200) return "HTTP_ERROR";
        if (!reply.body().has("result") && !reply.body().has("error")) return "MALFORMED_RESPONSE";
        return reply.body().has("error") ? reply.body().path("error").path("message").asText()
            : reply.isError() ? payload(reply).path("code").asText() : "ALLOW";
    }
}
