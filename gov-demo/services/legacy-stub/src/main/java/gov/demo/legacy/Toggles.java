package gov.demo.legacy;

import java.util.Set;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/** In-memory toggle state. Resets on restart, defaults come from env. */
@Component
public class Toggles {
    static final Set<String> MODES = Set.of("normal", "slow", "brownout");

    private volatile String mode;
    private volatile int poolThreads;

    public Toggles(@Value("${legacy.mode}") String mode, @Value("${server.tomcat.threads.max}") int poolThreads) {
        this.mode = MODES.contains(mode) ? mode : "normal";
        this.poolThreads = poolThreads;
    }

    public String mode() { return mode; }
    public int poolThreads() { return poolThreads; }
    public void mode(String value) { this.mode = value; }
    public void poolThreads(int value) { this.poolThreads = value; }
}
