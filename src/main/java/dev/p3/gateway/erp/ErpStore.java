package dev.p3.gateway.erp;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Component;

@Component
public class ErpStore {
    /** The note is untrusted ERP content, never an authorization attribute. */
    public record Inventory(String productId, String tenant, int available, String note, String noteTrust) {}
    public record PurchaseOrder(String orderId, String tenant, int quantity, int version) {}
    private final Map<String, Inventory> inventory = new ConcurrentHashMap<>(Map.of(
        "sku-a1", new Inventory("sku-a1", "tenant-a", 120, "Supplier stock note", "UNTRUSTED_DATA"),
        "sku-a2", new Inventory("sku-a2", "tenant-a", 30, "Supplier stock note", "UNTRUSTED_DATA"),
        "sku-b1", new Inventory("sku-b1", "tenant-b", 80, "Supplier stock note", "UNTRUSTED_DATA")));
    // No MCP/REST setter: tests can simulate contaminated source data in-process.
    public void setInventoryNote(String productId, String note) {
        if (note == null || note.length() > 2048) throw new IllegalArgumentException("Invalid note length");
        inventory.computeIfPresent(productId, (id, old) ->
            new Inventory(id, old.tenant(), old.available(), note, "UNTRUSTED_DATA"));
    }
    private final Map<String, PurchaseOrder> orders = new ConcurrentHashMap<>(Map.of(
        "po-a1", new PurchaseOrder("po-a1", "tenant-a", 10, 0),
        "po-a2", new PurchaseOrder("po-a2", "tenant-a", 20, 0),
        "po-b1", new PurchaseOrder("po-b1", "tenant-b", 30, 0)));
    public Inventory inventory(String id) { return inventory.get(id); }
    public PurchaseOrder order(String id) { return orders.get(id); }
    public PurchaseOrder update(String id, int quantity) {
        return orders.computeIfPresent(id, (key, old) -> new PurchaseOrder(key, old.tenant(), quantity, old.version() + 1));
    }
    public Map<String, PurchaseOrder> snapshot() { return Map.copyOf(orders); }
}
