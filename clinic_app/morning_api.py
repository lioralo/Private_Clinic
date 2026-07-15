import requests
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

MORNING_AUTH_URL = 'https://api.morning.co/idp/v1/oauth/token'
MORNING_DEFAULT_BASE_URL = 'https://api.greeninvoice.co.il/api/v1'


class MorningAPIClient:
    """Client for the Morning (Green Invoice) digital invoicing API using OAuth 2.0."""

    def __init__(self, client_id=None, client_secret=None, base_url=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = (base_url or MORNING_DEFAULT_BASE_URL).rstrip('/')
        self._token = None
        self._token_expiry = None
        self.session = requests.Session()

    def _ensure_token(self):
        """Obtain or refresh the OAuth access token."""
        now = datetime.utcnow()
        if self._token and self._token_expiry and now < self._token_expiry - timedelta(seconds=30):
            return

        if not self.client_id or not self.client_secret:
            raise ValueError('Morning client_id and client_secret are required')

        resp = self.session.post(
            MORNING_AUTH_URL,
            json={
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'grant_type': 'client_credentials',
            },
            headers={'Content-Type': 'application/json'},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data['accessToken']
        # Tokens are valid for 1 hour
        self._token_expiry = now + timedelta(seconds=3600)
        logger.debug('Morning token obtained, expires %s', self._token_expiry)

    def _request(self, method, path, **kwargs):
        """Make an authenticated API request."""
        self._ensure_token()
        headers = kwargs.pop('headers', {})
        headers['Authorization'] = f'Bearer {self._token}'
        headers.setdefault('Content-Type', 'application/json')
        headers.setdefault('Accept', 'application/json')
        kwargs.setdefault('timeout', 30)
        return self.session.request(method, f'{self.base_url}{path}', headers=headers, **kwargs)

    # ── Documents (Invoices / Receipts) ────────────────────────

    def search_documents(self, page=1, page_size=50, doc_type=None, from_date=None,
                         to_date=None, client_name=None, status=None):
        """Search documents. Returns (items: list, total: int)."""
        body = {'page': page, 'pageSize': page_size}
        if doc_type is not None:
            body['type'] = doc_type
        if from_date:
            body['fromDate'] = from_date if isinstance(from_date, str) else from_date.isoformat()
        if to_date:
            body['toDate'] = to_date if isinstance(to_date, str) else to_date.isoformat()
        if client_name:
            body['clientName'] = client_name
        if status is not None:
            body['status'] = status
        resp = self._request('POST', '/documents/search', json=body)
        resp.raise_for_status()
        data = resp.json()
        return data.get('items', []), data.get('total', 0)

    def get_document(self, doc_id):
        """Get a single document by ID."""
        resp = self._request('GET', f'/documents/{doc_id}')
        resp.raise_for_status()
        return resp.json()

    def get_document_download_links(self, doc_id):
        """Get download links for a document PDF."""
        resp = self._request('GET', f'/documents/{doc_id}/download/links')
        resp.raise_for_status()
        return resp.json()

    def create_document(self, client_name, items, client_email=None, client_phone=None,
                        doc_type=305, notes=None, vat_type=0, currency='ILS', lang='he'):
        """Create an invoice/receipt in Morning. doc_type: 305=invoice/receipt, 320=receipt."""
        payload = {
            'type': doc_type,
            'lang': lang,
            'currency': currency,
            'vatType': vat_type,
            'clientName': client_name,
            'income': items,
        }

        if client and isinstance(client, dict) and client.get('id'):
            payload['client'] = client

        if client_email:
            payload['clientEmail'] = client_email
        if phone:
            payload['clientPhone'] = phone
        if notes:
            payload['description'] = notes
        if date:
            payload['date'] = date
        if due_date:
            payload['dueDate'] = due_date
        if remarks:
            payload['remarks'] = remarks
        if footer:
            payload['footer'] = footer
        if signed:
            payload['signed'] = True
        if attachment:
            payload['attachment'] = True
        if email_content:
            payload['emailContent'] = email_content
        if rounding:
            payload['rounding'] = True

        resp = self._request('POST', '/documents', json=payload)
        resp.raise_for_status()
        return resp.json()

    def create_document_with_client(self, client_name, items, client_email=None, client_phone=None,
                                     doc_type=305, notes=None, date=None, signed=True, rounding=True):
        """Create a document, auto-creating the client in Morning if needed.

        Returns (document_dict, morning_client_id)."""
        client = self.get_or_create_client(client_name, client_email, client_phone)
        result = self.create_document(
            client_name=client_name,
            items=items,
            client=client,
            client_email=client_email,
            client_phone=client_phone,
            doc_type=doc_type,
            notes=notes,
            date=date,
            signed=signed,
            rounding=rounding,
        )
        return result, client.get('id') if isinstance(client, dict) else None

    # ── Clients ───────────────────────────────────────────────

    def search_clients(self, page=1, page_size=50):
        """Search clients. Returns (items: list, total: int)."""
        resp = self._request('POST', '/clients/search', json={'page': page, 'pageSize': page_size})
        resp.raise_for_status()
        data = resp.json()
        return data.get('items', []), data.get('total', 0)

    def create_client(self, name, email=None, phone=None, address=None):
        """Create a client in Morning."""
        payload = {'clientName': name}
        if email:
            payload['emails'] = [email]
        if phone:
            payload['phone'] = phone
        if address:
            payload['address'] = address
        resp = self._request('POST', '/clients', json=payload)
        resp.raise_for_status()
        return resp.json()

    def find_client(self, name=None, email=None, page_size=10):
        """Search for a client in Morning by name or email. Returns matched dict or None."""
        body = {'pageSize': min(page_size, 100), 'page': 1}
        if name:
            body['clientName'] = name
        resp = self._request('POST', '/clients/search', json=body)
        resp.raise_for_status()
        items = resp.json().get('items', [])
        if not items:
            return None
        if name:
            for item in items:
                if item.get('name', '').strip().lower() == name.strip().lower():
                    return item
        return items[0] if items else None

    def get_or_create_client(self, name, email=None, phone=None):
        """Find existing client by name, or create a new one. Returns client dict."""
        existing = self.find_client(name=name, email=email)
        if existing:
            return existing
        return self.create_client(name, email, phone, address=None)

    # ── Payment Form (real Morning endpoint) ──────────────────

    def create_payment_form(self, amount, description, client_name=None, client_email=None,
                            currency='ILS', items=None, doc_type=320, redirect_url=None):
        """Create a payment form URL via POST /payments/form.
        Returns a URL to present as an iframe or redirect for customer payment."""
        payload = {
            'amount': float(amount),
            'currency': currency,
            'description': description,
            'type': doc_type,
        }
        if client_name:
            payload['clientName'] = client_name
        if client_email:
            payload['clientEmail'] = client_email
        if items:
            payload['income'] = items
        else:
            payload['income'] = [{'description': description, 'price': float(amount), 'quantity': 1}]
        if redirect_url:
            payload['redirectUrl'] = redirect_url

        resp = self._request('POST', '/payments/form', json=payload)
        resp.raise_for_status()
        return resp.json()

    def create_payment_request(self, client_name, amount, description,
                               client_email=None, currency='ILS'):
        """Legacy wrapper — creates a payment form (preferred)."""
        return self.create_payment_form(amount, description, client_name, client_email, currency=currency)

    # ── Health / Test ─────────────────────────────────────────

    def test_connection(self):
        """Test full OAuth flow + API connectivity. Returns (success: bool, message: str)."""
        try:
            self._ensure_token()
        except requests.ConnectionError:
            return False, 'Cannot reach auth server — check network/DNS'
        except Exception as e:
            return False, f'Authentication failed: {str(e)[:100]}'
        try:
            resp = self._request('POST', '/documents/search', json={'pageSize': 1})
            if resp.status_code == 200:
                data = resp.json()
                total = data.get('total', 0)
                return True, f'Connected — {total} documents in account'
            return False, f'API error: {resp.status_code}'
        except requests.ConnectionError:
            return False, 'Cannot reach API server — check network/DNS'
        except Exception as e:
            return False, f'API error: {str(e)[:100]}'


def get_morning_client(db):
    """Factory: build a MorningAPIClient from site_settings in the DB."""
    from app import get_site_settings
    settings = get_site_settings(db)
    client_id = settings.get('morning_api_key', '')
    client_secret = settings.get('morning_api_secret', '')
    base_url = settings.get('morning_api_url', MORNING_DEFAULT_BASE_URL)
    if not client_id or not client_secret:
        return None
    return MorningAPIClient(client_id=client_id, client_secret=client_secret, base_url=base_url)
