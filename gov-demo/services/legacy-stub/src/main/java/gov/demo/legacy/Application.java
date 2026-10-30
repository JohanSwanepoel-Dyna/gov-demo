package gov.demo.legacy;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.Executors;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@SpringBootApplication
@RestController
public class Application {
    private static final ObjectMapper JSON = new ObjectMapper();

    public static void main(String[] args) throws IOException {
        ConfigurableApplicationContext ctx = SpringApplication.run(Application.class, args);
        startControlServer(Integer.parseInt(System.getenv().getOrDefault("HEALTH_PORT", "8301")), ctx.getBean(ToggleApi.class));
    }

    /**
     * Health and the toggle API on their own port and threads. The slow mode and a small pool saturate the Tomcat
     * workers on purpose, and probes and scenario resets must still get through.
     */
    private static void startControlServer(int port, ToggleApi api) throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress(port), 0);
        server.createContext("/healthz", exchange -> send(exchange, 200, Map.of("status", "ok")));
        server.createContext("/control/toggles", exchange -> {
            String header = exchange.getRequestHeaders().getFirst("X-Demo-Control");
            ToggleApi.Result r = switch (exchange.getRequestMethod()) {
                case "GET" -> api.get(header);
                case "PUT" -> api.put(header, new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
                default -> new ToggleApi.Result(405, Map.of("detail", "method not allowed"));
            };
            send(exchange, r.status(), r.body());
        });
        server.setExecutor(Executors.newFixedThreadPool(2));
        server.start();
    }

    private static void send(HttpExchange exchange, int status, Map<String, Object> body) throws IOException {
        byte[] bytes = JSON.writeValueAsBytes(body);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }

    @GetMapping("/healthz")
    public Map<String, String> healthz() {
        return Map.of("status", "ok");
    }
}
