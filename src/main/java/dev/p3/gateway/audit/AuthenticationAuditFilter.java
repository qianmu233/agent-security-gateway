package dev.p3.gateway.audit;

import java.io.IOException;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.web.filter.OncePerRequestFilter;

/** Observe the upstream authentication result without parsing credentials/body. */
public class AuthenticationAuditFilter extends OncePerRequestFilter {
    private final AuditTrail audit;
    public AuthenticationAuditFilter(AuditTrail audit) { this.audit = audit; }
    @Override protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
            throws ServletException, IOException {
        chain.doFilter(req, res);
        if ("/mcp".equals(req.getServletPath()) && res.getStatus() == 401)
            audit.record("anonymous", "http.authentication", "AUTHENTICATION_FAILED");
    }
}
