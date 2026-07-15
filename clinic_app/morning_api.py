import requests
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

MORNING_DEFAULT_BASE_URL = 'https://api.greeninvoice.co.il/api/v1'


class MorningAPIClient:
    """Client for the Green Invoice (Morning / מרנינג) digital invoicing API."""

    def __init__(self, api_key=None, api_secret=None, base_url=None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = (base_url or MORNING_DEFAULT_BASE_URL).rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key or ""}',
        })

    # ── Documents (Invoices / Receipts) ────────────────────────

    def get_documents(self, from_date=None, to_date=None, doc_type=None, limit=100, offset=0):
        """Pull documents from Morning. Returns list of dicts."""
        params = {'limit': limit, 'offset': offset}
        if from_date:
            params['from_date'] = from_date if isinstance(from_date, str) else from_date.isoformat()
        if to_date:
            params['to_date'] = to_date if isinstance(to_date, str) else to_date.isoformat()
        if doc_type:
            params['type'] = doc_type
        resp = self.session.get(f'{self.base_url}/documents', params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get('data', data.get('documents', []))

    def get_document(self, doc_id):
        """Get a single document by ID."""
        resp = self.session.get(f'{self.base_url}/documents/{doc_id}', timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_document_pdf(self, doc_id):
        """Download a document PDF. Returns bytes."""
        resp = self.session.get(f'{self.base_url}/documents/{doc_id}/pdf', timeout=30)
        resp.raise_for_status()
        return resp.content

    def create_document(self, client_name, items, client_email=None, client_phone=None,
                        doc_type='invoice', notes=None, payment_request=False):
        """Create an invoice/receipt in Morning. Returns created document dict."""
        payload = {
            'type': doc_type,
            'client_name': client_name,
            'items': items,
        }
        if client_email:
            payload['client_email'] = client_email
        if client_phone:
            payload['client_phone'] = client_phone
        if notes:
            payload['notes'] = notes
        if payment_request:
            payload['payment_request'] = True

        resp = self.session.post(
            f'{self.base_url}/documents',
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Payment Requests ──────────────────────────────────────

    def create_payment_request(self, client_name, amount, description,
                               client_email=None, client_phone=None):
        """Send a payment request link to a client."""
        payload = {
            'client_name': client_name,
            'amount': amount,
            'description': description,
        }
        if client_email:
            payload['client_email'] = client_email
        if client_phone:
            payload['client_phone'] = client_phone

        resp = self.session.post(
            f'{self.base_url}/payment-requests',
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def get_payment_request_status(self, payment_id):
        """Check payment request status."""
        resp = self.session.get(
            f'{self.base_url}/payment-requests/{payment_id}',
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Clients ───────────────────────────────────────────────

    def get_clients(self, limit=100, offset=0):
        """List clients from Morning."""
        resp = self.session.get(
            f'{self.base_url}/clients',
            params={'limit': limit, 'offset': offset},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get('data', data.get('clients', []))

    def create_client(self, name, email=None, phone=None, address=None):
        """Create a client in Morning."""
        payload = {'name': name}
        if email:
            payload['email'] = email
        if phone:
            payload['phone'] = phone
        if address:
            payload['address'] = address
        resp = self.session.post(
            f'{self.base_url}/clients',
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Health / Test ─────────────────────────────────────────

    def test_connection(self):
        """Test API connectivity. Returns (success: bool, message: str)."""
        try:
            r = self.session.post(
                f'{self.base_url}/documents',
                json={'type': 'receipt'},
                timeout=15,
            )
            if r.status_code == 401:
                return False, 'Authentication failed — check that your API token is valid. Generate it from the Green Invoice developer dashboard.'
            if r.status_code == 200 or r.status_code == 201:
                return True, 'Connected successfully'
            if r.status_code == 405:
                return True, f'Connected (endpoint reached, status {r.status_code})'
            return False, f'Unexpected response: {r.status_code}'
        except requests.ConnectionError:
            return False, 'Cannot reach Green Invoice API — check network/DNS'
        except Exception as e:
            logger.warning('Morning API test connection failed: %s', e)
            return False, f'Connection error: {str(e)[:80]}'


def get_morning_client(db):
    """Factory: build a MorningAPIClient from site_settings in the DB."""
    from app import get_site_settings
    settings = get_site_settings(db)
    api_key = settings.get('morning_api_key', '')
    api_secret = settings.get('morning_api_secret', '')
    base_url = settings.get('morning_api_url', MORNING_DEFAULT_BASE_URL)
    if not api_key:
        return None
    return MorningAPIClient(api_key=api_key, api_secret=api_secret, base_url=base_url)
