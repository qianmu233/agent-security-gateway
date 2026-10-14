package dev.p3.gateway.mcp;

import java.util.List;
import java.util.Map;
import io.modelcontextprotocol.server.McpStatelessServerFeatures.SyncToolSpecification;
import io.modelcontextprotocol.spec.McpSchema;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class ToolConfiguration {
    @Bean
    List<SyncToolSpecification> tools(ToolGateway gateway) {
        var inventory = schema(Map.of("productId", Map.of("type", "string", "pattern", "^sku-[ab][12]$")), List.of("productId"));
        var update = schema(Map.of("orderId", Map.of("type", "string", "pattern", "^po-[ab][12]$"),
            "quantity", Map.of("type", "integer", "minimum", 1, "maximum", 1000),
            "intentId", Map.of("type", "string", "pattern", "^[A-Za-z0-9_-]{43}$")), List.of("orderId", "quantity", "intentId"));
        return List.of(spec("inventory.read", "Read authorized virtual ERP inventory", inventory, gateway),
            spec("purchase_order.update", "Update virtual order quantity with a trusted single-use write intent", update, gateway));
    }
    private SyncToolSpecification spec(String name, String description, McpSchema.JsonSchema schema, ToolGateway gateway) {
        return new SyncToolSpecification(McpSchema.Tool.builder().name(name).description(description).inputSchema(schema).build(),
            (context, request) -> gateway.call(name, request.arguments()));
    }
    private McpSchema.JsonSchema schema(Map<String, Object> properties, List<String> required) {
        return new McpSchema.JsonSchema("object", properties, required, false, null, null);
    }
}
