package dev.p3.gateway.security;

import java.security.SecureRandom;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;
import java.util.function.Supplier;
import dev.p3.gateway.audit.AuditTrail;
import dev.p3.gateway.erp.ErpStore;
import org.springframework.security.core.Authentication;
import org.springframework.stereotype.Service;

/** Single-use server grants. Issuance is package-private and has no HTTP/MCP route. */
@Service
public class WriteIntentService {
    public static final Duration LIFETIME = Duration.ofSeconds(60);
    private static final String TOOL = "purchase_order.update";
    private final Map<String, Grant> grants = new HashMap<>();
    private final SecureRandom random = new SecureRandom();
    private final Clock clock;
    private final IdentityDirectory identities;
    private final PolicyService policy;
    private final ErpStore store;
    private final AuditTrail audit;
    private static class Grant {
        final String caller, tool, tenant, order;
        final int quantity;
        final Instant expiresAt;
        boolean consumed;
        Grant(String caller, String tenant, String order, int quantity, Instant expiresAt) {
            this.caller = caller; this.tool = TOOL; this.tenant = tenant; this.order = order;
            this.quantity = quantity; this.expiresAt = expiresAt;
        }
    }
    public WriteIntentService(Clock clock, IdentityDirectory identities, PolicyService policy, ErpStore store, AuditTrail audit) {
        this.clock = clock; this.identities = identities; this.policy = policy; this.store = store; this.audit = audit;
    }

    // Called only after local operator confirmation; never from model/tool output.
    synchronized String issueForConfirmedUser(String caller, String orderId, int quantity) {
        var identity = identities.findById(caller);
        var order = store.order(orderId);
        if (order == null || quantity < 1 || quantity > 1000
                || !policy.allows(identity, TOOL, order.tenant(), orderId))
            throw new IntentRejectedException("FORBIDDEN");
        Instant now = clock.instant();
        grants.values().removeIf(grant -> !now.isBefore(grant.expiresAt));
        if (grants.size() >= 200) throw new IntentRejectedException("INTENT_CAPACITY");
        byte[] bytes = new byte[32];
        String token;
        do {
            random.nextBytes(bytes);
            token = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        } while (grants.containsKey(token));
        grants.put(token, new Grant(identity.id(), order.tenant(), orderId, quantity, now.plus(LIFETIME)));
        audit.record(identity.id(), "intent.authorize", "ALLOW");
        return token;
    }

    /** Verification, consumption and the in-memory mutation share one lock. */
    public synchronized <T> T execute(Authentication authentication, String tool, ErpStore.PurchaseOrder order,
                                      int quantity, String token, Supplier<T> mutation) {
        var identity = identities.resolve(authentication);
        if (!policy.allows(identity, tool, order.tenant(), order.orderId()))
            throw new IntentRejectedException("FORBIDDEN");
        if (token == null) throw new IntentRejectedException("INTENT_REQUIRED");
        Grant grant = grants.get(token);
        if (grant == null) throw new IntentRejectedException("INTENT_INVALID");
        if (!clock.instant().isBefore(grant.expiresAt)) throw new IntentRejectedException("INTENT_EXPIRED");
        if (!grant.caller.equals(identity.id()) || !grant.tool.equals(tool) || !grant.tenant.equals(order.tenant())
                || !grant.order.equals(order.orderId()) || grant.quantity != quantity)
            throw new IntentRejectedException("INTENT_MISMATCH");
        if (grant.consumed) throw new IntentRejectedException("INTENT_REPLAY");
        grant.consumed = true;
        return mutation.get();
    }
}
