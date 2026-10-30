import os
import re
import urllib.request

LEGACY_URL = os.environ.get("LEGACY_URL", "http://legacy-stub:8300")
TIMEOUT_S = float(os.environ.get("LEGACY_TIMEOUT_S", "15"))

ENVELOPE = ('<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
            "{body}</soap:Body></soap:Envelope>")


def _post(path, body):
    req = urllib.request.Request(LEGACY_URL + path, data=ENVELOPE.format(body=body).encode(),
                                 headers={"Content-Type": "text/xml"}, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return resp.read().decode()


def _field(xml, name):
    m = re.search(rf"<(?:\w+:)?{name}>(.*?)</(?:\w+:)?{name}>", xml)
    if not m:
        raise ValueError(f"legacy response missing {name}")
    return m.group(1)


def lookup_customer(citizen_id):
    xml = _post("/legacy/CustomerService", f"<CustomerRequest><CustomerId>{int(citizen_id)}</CustomerId></CustomerRequest>")
    return {"residency": _field(xml, "ResidencyStatus"), "legacy_customer_ref": _field(xml, "CustomerRef")}
