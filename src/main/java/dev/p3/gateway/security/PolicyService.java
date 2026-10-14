package dev.p3.gateway.security;

import java.util.Set;
import org.springframework.security.core.Authentication;
import org.springframework.stereotype.Service;

@Service("policy")
public class PolicyService {
    private static final Set<String> REGISTERED = Set.of("inventory.read", "purchase_order.update");
    private final IdentityDirectory directory;
    public PolicyService(IdentityDirectory directory) { this.directory = directory; }
    public boolean allows(Authentication authentication, String tool, String tenant, String resource) {
        var identity = directory.resolve(authentication);
        return identity != null && REGISTERED.contains(tool) && identity.permissions().contains(tool)
            && identity.tenant().equals(tenant) && identity.resources().contains(resource);
    }
}
