from typing import Any, TYPE_CHECKING

# Mock Class for Linter
class MockModule:
    def __getattr__(self, _) -> Any: return MockModule()
    def __call__(self, *args, **kwargs) -> Any: return MockModule()
    def __iter__(self) -> Any: return iter([])
    def __bool__(self) -> bool: return False

if TYPE_CHECKING:
    requests: Any = MockModule()
else:
    try:
        import requests
    except ImportError:
        requests = MockModule()

API_URL = "http://localhost:8000/api/documents/"
API_TOKEN = "2051eaf6a446d1bbb6a034588604ac9a5e20b1ee"  # Hier dein Token einfügen

# Optional: Startwert der ASN (z.B. 1000)
asn_start = 1000

headers = {
    "Authorization": f"Token {API_TOKEN}",
    "Content-Type": "application/json"
}

def get_documents():
    """Alle Dokumente holen. Bei vielen Dokumenten ggf. Pagination beachten."""
    docs = []
    url = API_URL
    while url:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        docs.extend(data['results'])
        url = data.get('next')
    return docs

def set_asn(doc_id, asn):
    """ASN für ein Dokument setzen."""
    response = requests.patch(
        f"{API_URL}{doc_id}/",
        headers=headers,
        json={"archive_serial_number": str(asn)}
    )
    response.raise_for_status()

def update_all_documents():
    docs = get_documents()
    for idx, doc in enumerate(docs):
        if not doc['archive_serial_number']:
            asn_value = asn_start + idx
            set_asn(doc['id'], asn_value)
            print(f"Dokument {doc['id']} → ASN gesetzt auf: {asn_value}")

if __name__ == "__main__":
    update_all_documents()
