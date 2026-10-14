package dev.p3.gateway.erp;

import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.stereotype.Service;
import dev.p3.gateway.security.WriteIntentService;
import org.springframework.security.core.context.SecurityContextHolder;

@Service
public class ErpService {
    private final ErpStore store;
    private final WriteIntentService intents;
    public ErpService(ErpStore store, WriteIntentService intents) { this.store = store; this.intents = intents; }
    @PreAuthorize("@policy.allows(authentication, 'inventory.read', #resource.tenant(), #resource.productId())")
    public ErpStore.Inventory read(ErpStore.Inventory resource) { return resource; }
    @PreAuthorize("@policy.allows(authentication, 'purchase_order.update', #resource.tenant(), #resource.orderId())")
    public ErpStore.PurchaseOrder update(ErpStore.PurchaseOrder resource, int quantity, String intentId) {
        return intents.execute(SecurityContextHolder.getContext().getAuthentication(), "purchase_order.update",
            resource, quantity, intentId, () -> store.update(resource.orderId(), quantity));
    }
}
