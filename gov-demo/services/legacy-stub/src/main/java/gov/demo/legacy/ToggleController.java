package gov.demo.legacy;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

/** The toggle API on the main port. The same API is also served on the independent port, see Application. */
@RestController
public class ToggleController {
    private final ToggleApi api;

    public ToggleController(ToggleApi api) {
        this.api = api;
    }

    @GetMapping("/control/toggles")
    public ResponseEntity<?> get(@RequestHeader(value = "X-Demo-Control", required = false) String header) {
        ToggleApi.Result r = api.get(header);
        return ResponseEntity.status(r.status()).body(r.body());
    }

    @PutMapping("/control/toggles")
    public ResponseEntity<?> put(@RequestHeader(value = "X-Demo-Control", required = false) String header,
                                 @RequestBody String body) {
        ToggleApi.Result r = api.put(header, body);
        return ResponseEntity.status(r.status()).body(r.body());
    }
}
