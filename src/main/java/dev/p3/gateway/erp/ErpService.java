package dev.p3.gateway.erp;

import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.stereotype.Service;

@Service
public class ErpService {
    private final ErpStore store;
    public ErpService(ErpStore store) { this.store = store; }
    @PreAuthorize("@policy.allows(authentication, 'inventory.read', #resource.tenant(), #resource.productId())")
    public ErpStore.Inventory read(ErpStore.Inventory resource) { return resource; }
    @PreAuthorize("@policy.allows(authentication, 'purchase_order.update', #resource.tenant(), #resource.orderId())")
    public ErpStore.PurchaseOrder update(ErpStore.PurchaseOrder resource, int quantity) {
        return store.update(resource.orderId(), quantity);
    }
}
