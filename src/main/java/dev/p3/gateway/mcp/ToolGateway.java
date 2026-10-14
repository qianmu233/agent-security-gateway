package dev.p3.gateway.mcp;

import java.util.Map;
import java.util.Set;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.p3.gateway.audit.AuditTrail;
import dev.p3.gateway.erp.ErpService;
import dev.p3.gateway.erp.ErpStore;
import dev.p3.gateway.security.IdentityDirectory;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import jakarta.validation.Validator;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;

/** The registered SDK call handlers enter this gateway before any ERP mutation. */
@Component
public class ToolGateway {
    public static final Set<String> TOOLS = Set.of("inventory.read", "purchase_order.update");
    public record InventoryInput(@NotNull @Pattern(regexp = "sku-[ab][12]") String productId) {}
    public record UpdateInput(@NotNull @Pattern(regexp = "po-[ab][12]") String orderId,
                              @NotNull @Min(1) @Max(1000) Integer quantity) {}
    private final ErpStore store;
    private final ErpService service;
    private final Validator validator;
    private final ObjectMapper mapper;
    private final IdentityDirectory identities;
    private final AuditTrail audit;
    public ToolGateway(ErpStore store, ErpService service, Validator validator, ObjectMapper mapper,
                       IdentityDirectory identities, AuditTrail audit) {
        this.store = store; this.service = service; this.validator = validator; this.mapper = mapper;
        this.identities = identities; this.audit = audit;
    }

    public CallToolResult call(String tool, Map<String, Object> arguments) {
        var identity = identities.resolve(SecurityContextHolder.getContext().getAuthentication());
        String caller = identity == null ? "anonymous" : identity.id();
        String reason = "ALLOW";
        Object data = null;
        try {
            if (!TOOLS.contains(tool)) throw new Rejected("UNKNOWN_TOOL");
            if (identity == null) throw new Rejected("FORBIDDEN");
            if (tool.equals("inventory.read")) {
                exactFields(arguments, Set.of("productId"));
                var input = new InventoryInput(string(arguments.get("productId")));
                validate(input);
                var resource = store.inventory(input.productId());
                if (resource == null) throw new Rejected("FORBIDDEN");
                data = service.read(resource);
            } else {
                exactFields(arguments, Set.of("orderId", "quantity"));
                Object quantity = arguments.get("quantity");
                // No coercion from strings, floats, booleans, or oversized integers.
                if (!(quantity instanceof Integer)) throw new Rejected("INVALID_ARGUMENTS");
                var input = new UpdateInput(string(arguments.get("orderId")), (Integer) quantity);
                validate(input);
                var resource = store.order(input.orderId());
                if (resource == null) throw new Rejected("FORBIDDEN");
                data = service.update(resource, input.quantity());
            }
        } catch (Rejected ex) {
            reason = ex.code;
        } catch (AccessDeniedException ex) {
            reason = "FORBIDDEN";
        } catch (RuntimeException ex) {
            // Never expose exception messages, credentials, or raw arguments.
            reason = "INTERNAL_ERROR";
        }
        String requestId = audit.record(caller, TOOLS.contains(tool) ? tool : "unregistered", reason);
        var body = reason.equals("ALLOW") ? Map.of("requestId", requestId, "data", data)
            : Map.of("requestId", requestId, "code", reason);
        try {
            return CallToolResult.builder().addTextContent(mapper.writeValueAsString(body))
                .isError(!reason.equals("ALLOW")).build();
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("Response serialization failed");
        }
    }
    private void validate(Object input) {
        if (!validator.validate(input).isEmpty()) throw new Rejected("INVALID_ARGUMENTS");
    }
    private static void exactFields(Map<String, Object> args, Set<String> fields) {
        if (args == null || !args.keySet().equals(fields)) throw new Rejected("INVALID_ARGUMENTS");
    }
    private static String string(Object value) {
        if (!(value instanceof String text)) throw new Rejected("INVALID_ARGUMENTS");
        return text;
    }
    private static class Rejected extends RuntimeException {
        private final String code;
        Rejected(String code) { super(code); this.code = code; }
    }
}
