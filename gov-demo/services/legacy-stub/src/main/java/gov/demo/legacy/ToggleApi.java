package gov.demo.legacy;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.security.MessageDigest;
import java.util.LinkedHashMap;
import java.util.Map;
import org.apache.coyote.AbstractProtocol;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.embedded.tomcat.TomcatWebServer;
import org.springframework.boot.web.servlet.context.ServletWebServerApplicationContext;
import org.springframework.stereotype.Component;

/** Toggle logic shared by the Spring controller (port 8300) and the independent control server (port 8301). */
@Component
public class ToggleApi {
    public record Result(int status, Map<String, Object> body) {}

    private static final ObjectMapper JSON = new ObjectMapper();
    private final Toggles toggles;
    private final ServletWebServerApplicationContext context;
    private final String token;

    public ToggleApi(Toggles toggles, ServletWebServerApplicationContext context, @Value("${CONTROL_TOKEN:}") String token) {
        this.toggles = toggles;
        this.context = context;
        this.token = token;
    }

    public Result get(String header) {
        Result denied = check(header);
        return denied != null ? denied : new Result(200, state());
    }

    public Result put(String header, String body) {
        Result denied = check(header);
        if (denied != null) return denied;
        Map<String, Object> changes;
        try {
            changes = JSON.readValue(body == null || body.isBlank() ? "{}" : body, new TypeReference<>() {});
        } catch (Exception e) {
            return error(422, "body must be a JSON object");
        }
        String mode = null;
        Integer threads = null;
        for (Map.Entry<String, Object> e : changes.entrySet()) {
            String value = String.valueOf(e.getValue());
            switch (e.getKey()) {
                case "mode" -> {
                    if (!Toggles.MODES.contains(value)) return error(422, "mode must be one of normal, slow, brownout");
                    mode = value;
                }
                case "pool_threads" -> {
                    try { threads = Integer.parseInt(value); } catch (NumberFormatException ex) { threads = -1; }
                    if (threads < 1 || threads > 64) return error(422, "pool_threads must be 1 to 64");
                }
                default -> { return error(422, "unknown toggle " + e.getKey()); }
            }
        }
        if (threads != null) {
            // Tomcat resizes its worker pool at runtime. The maximum may not drop below the minimum spare threads.
            TomcatWebServer web = (TomcatWebServer) context.getWebServer();
            AbstractProtocol<?> protocol = (AbstractProtocol<?>) web.getTomcat().getConnector().getProtocolHandler();
            protocol.setMinSpareThreads(Math.min(threads, protocol.getMinSpareThreads()));
            protocol.setMaxThreads(threads);
            toggles.poolThreads(threads);
        }
        if (mode != null) toggles.mode(mode);
        return new Result(200, state());
    }

    private Map<String, Object> state() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("mode", toggles.mode());
        m.put("pool_threads", toggles.poolThreads());
        return m;
    }

    private Result check(String header) {
        if (token.isEmpty()) return error(503, "control API disabled: CONTROL_TOKEN not set");
        boolean ok = header != null && MessageDigest.isEqual(header.getBytes(), token.getBytes());
        return ok ? null : error(401, "bad control token");
    }

    private static Result error(int status, String detail) {
        return new Result(status, Map.of("detail", detail));
    }
}
