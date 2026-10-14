package dev.p3.gateway.security;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

/** Local OS operator channel. Do not expose its stdin or output to an Agent. */
@Component
public class TrustedIntentConsole implements ApplicationRunner {
    private final WriteIntentService intents;
    private final boolean enabled;
    public TrustedIntentConsole(WriteIntentService intents, @Value("${p3.intent-console.enabled:false}") boolean enabled) {
        this.intents = intents; this.enabled = enabled;
    }
    @Override public void run(ApplicationArguments arguments) {
        if (!enabled) return;
        Thread console = new Thread(() -> {
            try {
                process(new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8)),
                    new PrintWriter(System.out, true));
            } catch (IOException ex) { /* EOF/disconnect: no authorization issued. */ }
        }, "trusted-intent-console");
        console.setDaemon(true);
        console.start();
    }

    /** Test harness may supply trusted operator input; this is not a network API. */
    public void process(BufferedReader input, PrintWriter output) throws IOException {
        output.println("Trusted console: authorize <callerId> <orderId> <quantity>, then CONFIRM; exit to close.");
        for (String line; (line = input.readLine()) != null;) {
            if (line.equals("exit")) return;
            String[] parts = line.trim().split("\\s+");
            if (parts.length != 4 || !parts[0].equals("authorize") || !parts[1].matches("(reader|buyer)-[ab]")
                    || !parts[2].matches("po-[ab][12]") || !parts[3].matches("[0-9]{1,4}")) {
                output.println("REJECTED INVALID_CONFIRMATION"); continue;
            }
            output.printf("Confirm caller=%s tool=purchase_order.update order=%s quantity=%s TTL=60s with CONFIRM:%n",
                parts[1], parts[2], parts[3]);
            output.flush();
            if (!"CONFIRM".equals(input.readLine())) { output.println("CANCELLED"); continue; }
            try {
                String token = intents.issueForConfirmedUser(parts[1], parts[2], Integer.parseInt(parts[3]));
                // Returned only over this local trusted channel, never through a tool.
                output.println("intentId=" + token);
            } catch (IntentRejectedException ex) { output.println("REJECTED " + ex.code()); }
        }
    }
}
