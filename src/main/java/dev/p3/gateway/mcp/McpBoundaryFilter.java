package dev.p3.gateway.mcp;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.util.LinkedHashMap;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.p3.gateway.audit.AuditTrail;
import dev.p3.gateway.security.IdentityDirectory;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ReadListener;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletInputStream;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletRequestWrapper;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

/** Preflight rejects unregistered tool names without reflecting untrusted text.
 * The SDK still implements initialize, discovery, dispatch and MCP transport. */
public class McpBoundaryFilter extends OncePerRequestFilter {
    private final ObjectMapper mapper;
    private final AuditTrail audit;
    private final IdentityDirectory identities;
    public McpBoundaryFilter(ObjectMapper mapper, AuditTrail audit, IdentityDirectory identities) {
        this.mapper = mapper; this.audit = audit; this.identities = identities;
    }
    @Override
    protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
            throws ServletException, IOException {
        if (!"/mcp".equals(req.getServletPath()) || !"POST".equals(req.getMethod())) {
            chain.doFilter(req, res); return;
        }
        byte[] body = req.getInputStream().readNBytes(16385);
        if (body.length > 16384) { res.setStatus(413); return; }
        JsonNode root;
        try { root = mapper.readTree(body); }
        catch (IOException ex) { reject(res, null, "INVALID_REQUEST"); return; }
        if (root == null || !root.isObject()) { reject(res, null, "INVALID_REQUEST"); return; }
        if ("tools/call".equals(root.path("method").asText())
                && !ToolGateway.TOOLS.contains(root.path("params").path("name").asText())) {
            reject(res, root.get("id"), "UNKNOWN_TOOL"); return;
        }
        chain.doFilter(new HttpServletRequestWrapper(req) {
            @Override public ServletInputStream getInputStream() {
                var input = new ByteArrayInputStream(body);
                return new ServletInputStream() {
                    public int read() { return input.read(); }
                    public boolean isFinished() { return input.available() == 0; }
                    public boolean isReady() { return true; }
                    public void setReadListener(ReadListener listener) { throw new UnsupportedOperationException(); }
                };
            }
        }, res);
    }
    private void reject(HttpServletResponse res, JsonNode id, String reason) throws IOException {
        var identity = identities.resolve(SecurityContextHolder.getContext().getAuthentication());
        String requestId = audit.record(identity == null ? "anonymous" : identity.id(), "unregistered", reason);
        var response = new LinkedHashMap<String, Object>();
        response.put("jsonrpc", "2.0");
        response.put("id", id);
        response.put("error", java.util.Map.of("code", -32602, "message", reason,
            "data", java.util.Map.of("requestId", requestId)));
        res.setStatus(200);
        res.setContentType("application/json");
        mapper.writeValue(res.getOutputStream(), response);
    }
}
