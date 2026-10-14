package dev.p3.gateway.support;

import java.io.BufferedReader;
import java.io.PrintWriter;
import java.io.StringReader;
import java.io.StringWriter;
import dev.p3.gateway.security.TrustedIntentConsole;

/** Test-side trusted operator input, deliberately separate from MockAgent. */
public final class TrustedUser {
    private TrustedUser() {}
    public static String confirm(TrustedIntentConsole console, String caller, String order, int quantity) throws Exception {
        StringWriter output = new StringWriter();
        console.process(new BufferedReader(new StringReader("authorize " + caller + " " + order + " " + quantity + "\nCONFIRM\nexit\n")),
            new PrintWriter(output, true));
        String token = output.toString().lines().filter(line -> line.startsWith("intentId="))
            .map(line -> line.substring("intentId=".length())).findFirst().orElse(null);
        if (token == null) throw new AssertionError("Trusted confirmation did not issue an intent");
        return token;
    }
}
