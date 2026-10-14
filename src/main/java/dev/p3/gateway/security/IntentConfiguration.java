package dev.p3.gateway.security;

import java.time.Clock;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class IntentConfiguration {
    @Bean Clock intentClock() { return Clock.systemUTC(); }
}
