package dev.p3.gateway.support;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.p3.gateway.GatewayApplication;
import dev.p3.gateway.audit.AuditTrail;
import dev.p3.gateway.erp.ErpStore;
import dev.p3.gateway.security.TrustedIntentConsole;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.web.servlet.context.ServletWebServerApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;

/** Test-classpath ONLY. stdin belongs to the trusted pytest driver, never to an Agent.
 * No REST/MCP fixture, token-issuer tool or production security changes.
 */
public final class PythonGatewayHarness {
    public static final class TestClock extends Clock {
        private final AtomicReference<Instant> now = new AtomicReference<>(Instant.now());
        public ZoneId getZone() { return ZoneOffset.UTC; }
        public Clock withZone(ZoneId zone) { return this; }
        public Instant instant() { return now.get(); }
        public void advance(long seconds) {
            if (seconds < 0 || seconds > 120) throw new IllegalArgumentException();
            now.updateAndGet(value -> value.plusSeconds(seconds));
        }
    }
    @TestConfiguration(proxyBeanMethods = false)
    public static class FixtureConfiguration {
        @Bean @Primary TestClock fixtureClock() { return new TestClock(); }
    }
    public static void main(String[] args) throws Exception {
        var app = new SpringApplication(GatewayApplication.class, FixtureConfiguration.class);
        app.setDefaultProperties(Map.of("p3.intent-console.enabled", "false",
            "spring.main.banner-mode", "off", "logging.level.root", "OFF"));
        try (var context = app.run(args);
             var input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
            var mapper = context.getBean(ObjectMapper.class);
            var store = context.getBean(ErpStore.class);
            int port = ((ServletWebServerApplicationContext) context).getWebServer().getPort();
            System.out.println(mapper.writeValueAsString(Map.of("fixture", "ready", "port", port)));
            for (String line; (line = input.readLine()) != null;) {
                try {
                    var command = mapper.readTree(line);
                    Object value = switch (command.path("op").asText()) {
                        case "snapshot" -> store.snapshot();
                        case "note" -> {
                            store.setInventoryNote("sku-a1", command.path("note").asText());
                            yield Map.of("updated", true);
                        }
                        case "authorize" -> Map.of("intentId", TrustedUser.confirm(
                            context.getBean(TrustedIntentConsole.class), command.path("caller").asText(),
                            command.path("order").asText(), command.path("quantity").asInt()));
                        case "advance" -> {
                            context.getBean(TestClock.class).advance(command.path("seconds").asLong());
                            yield Map.of("advanced", true);
                        }
                        case "audit" -> context.getBean(AuditTrail.class).snapshot();
                        default -> throw new IllegalArgumentException();
                    };
                    // Captured in memory by the trusted driver. Do not redirect this pipe to logs.
                    System.out.println(mapper.writeValueAsString(Map.of("fixture", "reply", "value", value)));
                } catch (Exception ex) {
                    System.out.println("{\"fixture\":\"error\"}");
                }
            }
        }
    }
}
