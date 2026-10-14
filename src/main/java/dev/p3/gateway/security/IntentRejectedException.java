package dev.p3.gateway.security;

/** Contains only a fixed reason code, never a token or raw argument. */
public class IntentRejectedException extends RuntimeException {
    public IntentRejectedException(String code) { super(code); }
    public String code() { return getMessage(); }
}
