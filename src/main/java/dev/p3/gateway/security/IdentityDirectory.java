package dev.p3.gateway.security;

import java.util.Map;
import java.util.Set;
import org.springaicommunity.mcp.security.server.apikey.ApiKeyEntity;
import org.springframework.security.core.Authentication;
import org.springframework.stereotype.Component;

/** Authorization attributes are server-owned; key IDs are public identifiers. */
@Component
public class IdentityDirectory {
    public record Identity(String id, String role, String tenant, Set<String> permissions, Set<String> resources) {}
    private final Map<String, Identity> identities = Map.of(
        "reader-a", new Identity("reader-a", "READER", "tenant-a", Set.of("inventory.read"), Set.of("sku-a1")),
        "buyer-a", new Identity("buyer-a", "BUYER", "tenant-a", Set.of("inventory.read", "purchase_order.update"), Set.of("sku-a1", "po-a1")),
        "buyer-b", new Identity("buyer-b", "BUYER", "tenant-b", Set.of("inventory.read", "purchase_order.update"), Set.of("sku-b1", "po-b1"))
    );
    public Identity resolve(Authentication authentication) {
        if (authentication == null || !authentication.isAuthenticated()
                || !(authentication.getPrincipal() instanceof ApiKeyEntity principal)) return null;
        return identities.get(principal.getId());
    }
}
