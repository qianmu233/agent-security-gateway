package dev.p3.gateway.audit;

import java.util.ArrayDeque;
import java.util.List;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

@Component
public class AuditTrail {
    public record Event(String requestId, String caller, String tool, String decision, String reason) {}
    private static final Logger LOG = LoggerFactory.getLogger(AuditTrail.class);
    private final ArrayDeque<Event> events = new ArrayDeque<>();
    public synchronized String record(String caller, String tool, String reason) {
        String requestId = UUID.randomUUID().toString();
        var event = new Event(requestId, caller, tool, "ALLOW".equals(reason) ? "ALLOW" : "DENY", reason);
        if (events.size() == 200) events.removeFirst();
        events.addLast(event);
        LOG.info("requestId={} caller={} tool={} decision={} reason={}", event.requestId(), event.caller(), event.tool(), event.decision(), event.reason());
        return requestId;
    }
    public synchronized List<Event> snapshot() { return List.copyOf(events); }
}
