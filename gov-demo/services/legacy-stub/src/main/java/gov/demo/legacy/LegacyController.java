package gov.demo.legacy;

import java.util.UUID;
import java.util.concurrent.ThreadLocalRandom;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class LegacyController {
    // Log4j 2.14.1 is deliberately old. It is initialised on every call so it is loaded at runtime.
    // Only server-generated values are passed to it.
    private static final Logger AUDIT = LogManager.getLogger("legacy.audit");
    private static final Pattern CUSTOMER_ID = Pattern.compile("<(?:\\w+:)?CustomerId>\\s*(\\d{1,9})\\s*<");
    private static final Pattern CLAIM_ID = Pattern.compile("<(?:\\w+:)?ClaimId>\\s*([0-9a-fA-F-]{36})\\s*<");
    private static final Pattern AMOUNT = Pattern.compile("<(?:\\w+:)?AmountCents>\\s*(\\d{1,9})\\s*<");

    private final int minMs;
    private final int maxMs;
    private final Toggles toggles;

    public LegacyController(@Value("${legacy.latency.min-ms}") int minMs, @Value("${legacy.latency.max-ms}") int maxMs,
                            Toggles toggles) {
        this.minMs = minMs;
        this.maxMs = maxMs;
        this.toggles = toggles;
    }

    @PostMapping(value = "/legacy/CustomerService", produces = MediaType.TEXT_XML_VALUE)
    public ResponseEntity<String> customer(@RequestBody String body) throws InterruptedException {
        delay();
        if (brownout()) return ResponseEntity.status(500).body(fault("Simulated brownout"));
        Matcher m = CUSTOMER_ID.matcher(body);
        if (!m.find()) {
            return ResponseEntity.badRequest().body(fault("CustomerId missing"));
        }
        long id = Long.parseLong(m.group(1));
        AUDIT.warn("customer lookup {}", id);
        String residency = id % 20 == 0 ? "NON_RESIDENT" : "RESIDENT";
        return ResponseEntity.ok(envelope("<CustomerResponse><CustomerId>%d</CustomerId><CustomerRef>LC-%06d</CustomerRef>"
                + "<ResidencyStatus>%s</ResidencyStatus></CustomerResponse>", id, id, residency));
    }

    @PostMapping(value = "/legacy/PaymentService", produces = MediaType.TEXT_XML_VALUE)
    public ResponseEntity<String> payment(@RequestBody String body) throws InterruptedException {
        delay();
        if (brownout()) return ResponseEntity.status(500).body(fault("Simulated brownout"));
        Matcher claim = CLAIM_ID.matcher(body);
        Matcher amount = AMOUNT.matcher(body);
        if (!claim.find() || !amount.find()) {
            return ResponseEntity.badRequest().body(fault("ClaimId or AmountCents missing"));
        }
        String ref = "LGY-" + UUID.randomUUID().toString().substring(0, 8).toUpperCase();
        AUDIT.warn("payment posted {}", ref);
        return ResponseEntity.ok(envelope("<PaymentResponse><PaymentReference>%s</PaymentReference>"
                + "<Status>POSTED</Status></PaymentResponse>", ref));
    }

    private void delay() throws InterruptedException {
        boolean slow = !"normal".equals(toggles.mode());  // slow and brownout both add 2 to 5 s
        Thread.sleep(slow ? ThreadLocalRandom.current().nextInt(2000, 5001) : ThreadLocalRandom.current().nextInt(minMs, maxMs + 1));
    }

    private boolean brownout() {
        return "brownout".equals(toggles.mode()) && ThreadLocalRandom.current().nextInt(100) < 15;
    }

    private static String envelope(String format, Object... args) {
        return "<soap:Envelope xmlns:soap=\"http://schemas.xmlsoap.org/soap/envelope/\"><soap:Body>"
                + format.formatted(args) + "</soap:Body></soap:Envelope>";
    }

    private static String fault(String reason) {
        return envelope("<soap:Fault><faultcode>soap:Client</faultcode><faultstring>%s</faultstring></soap:Fault>", reason);
    }
}
