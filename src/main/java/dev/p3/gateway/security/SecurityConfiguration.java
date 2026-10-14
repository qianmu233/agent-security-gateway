/*
 * Copyright 2025-2025 the original author or authors.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 * https://www.apache.org/licenses/LICENSE-2.0
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and limitations.
 *
 * API-key configuration pattern adapted from mcp-security v0.0.6 sample.
 * P3 changes: environment secrets, fail-closed identity setup, strict header shape,
 * stateless HTTP security and a sanitized tool boundary. See NOTICE.
 */
package dev.p3.gateway.security;

import java.util.HashSet;
import java.util.List;
import java.util.ArrayList;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.p3.gateway.audit.AuditTrail;
import dev.p3.gateway.audit.AuthenticationAuditFilter;
import dev.p3.gateway.mcp.McpBoundaryFilter;
import org.springaicommunity.mcp.security.server.apikey.memory.ApiKeyEntityImpl;
import org.springaicommunity.mcp.security.server.apikey.memory.InMemoryApiKeyEntityRepository;
import org.springaicommunity.mcp.security.server.config.McpApiKeyConfigurer;
import org.springaicommunity.mcp.security.server.apikey.web.ApiKeyAuthenticationConverter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.access.intercept.AuthorizationFilter;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

@Configuration
@EnableMethodSecurity
public class SecurityConfiguration {
    @Bean
    InMemoryApiKeyEntityRepository<ApiKeyEntityImpl> apiKeys() {
        // Read raw secrets only from the process environment, hash through upstream builder.
        var keys = new ArrayList<ApiKeyEntityImpl>();
        var distinct = new HashSet<String>();
        for (var entry : List.of(new String[]{"reader-a", "P3_READER_A_SECRET"},
                new String[]{"buyer-a", "P3_BUYER_A_SECRET"}, new String[]{"buyer-b", "P3_BUYER_B_SECRET"})) {
            String secret = System.getenv(entry[1]);
            if (secret == null || !secret.matches("[A-Za-z0-9_-]{32,64}") || !distinct.add(secret))
                throw new IllegalStateException("Configure three distinct 32-64 character API secrets in P3 environment variables");
            keys.add(ApiKeyEntityImpl.builder().id(entry[0]).name(entry[0]).secret(secret).build());
        }
        return new InMemoryApiKeyEntityRepository<>(keys);
    }

    @Bean
    SecurityFilterChain security(HttpSecurity http, InMemoryApiKeyEntityRepository<ApiKeyEntityImpl> keys,
            ObjectMapper mapper, AuditTrail audit, IdentityDirectory identities) throws Exception {
        return http.authorizeHttpRequests(a -> a.requestMatchers("/mcp").authenticated().anyRequest().denyAll())
            .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .requestCache(c -> c.disable())
            // API-only endpoint uses headers on every request, never cookie authentication.
            .csrf(c -> c.ignoringRequestMatchers("/mcp"))
            .exceptionHandling(e -> e.authenticationEntryPoint((req, res, ex) -> res.setStatus(401)))
            .with(McpApiKeyConfigurer.mcpServerApiKey(), c -> c.apiKeyRepository(keys).authenticationConverter(req -> {
                var headers = req.getHeaders("X-API-Key");
                if (!headers.hasMoreElements()) return null;
                String raw = headers.nextElement();
                // Harden upstream 0.0.6's permissive split; parsing/authentication remain upstream.
                if (headers.hasMoreElements() || !raw.matches("[A-Za-z0-9-]{1,32}\\.[A-Za-z0-9_-]{32,64}")) return null;
                return new ApiKeyAuthenticationConverter().convert(req);
            }))
            .addFilterBefore(new AuthenticationAuditFilter(audit), UsernamePasswordAuthenticationFilter.class)
            .addFilterAfter(new McpBoundaryFilter(mapper, audit, identities), AuthorizationFilter.class)
            .build();
    }
}
