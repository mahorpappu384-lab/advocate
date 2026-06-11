"""
MSG91 Phone OTP Utility
------------------------
MSG91 se phone number par OTP bhejo aur verify karo.

Settings required (settings.py / .env mein):
    MSG91_AUTH_KEY     = '<your_production_auth_key>'
    MSG91_TEMPLATE_ID  = '<your_template_id>'
    MSG91_SENDER_ID    = 'EXVAKL'   (ya apna sender ID)
    MSG91_COUNTRY_CODE = '91'        (India default)
"""

import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

MSG91_SEND_URL   = "https://control.msg91.com/api/v5/otp"
MSG91_VERIFY_URL = "https://control.msg91.com/api/v5/otp/verify"
MSG91_RESEND_URL = "https://control.msg91.com/api/v5/otp/retry"


def _get_e164(phone: str) -> str:
    """
    Phone number ko E.164 format mein convert karo (leading + ke bina).
    Accepted formats:
        +919876543210  →  919876543210
        09876543210    →  919876543210
        9876543210     →  919876543210
        919876543210   →  919876543210  (already correct)
    """
    country_code = getattr(settings, 'MSG91_COUNTRY_CODE', '91')
    phone = phone.strip().replace(' ', '').replace('-', '').replace('(', '').replace(')', '')

    if phone.startswith('+'):
        phone = phone[1:]
    elif phone.startswith('0'):
        phone = country_code + phone[1:]
    elif len(phone) == 10 and phone.isdigit():
        phone = country_code + phone
    # Already 12-digit with country code (e.g. 919876543210) — no change

    return phone


def _auth_key() -> str:
    key = getattr(settings, 'MSG91_AUTH_KEY', '')
    if not key:
        logger.critical("MSG91_AUTH_KEY settings/env mein set nahi hai!")
    return key


def send_phone_otp(phone: str) -> dict:
    """
    MSG91 se phone number par OTP bhejo.

    Returns:
        {'success': True}
        {'success': False, 'error': '<user-facing message>'}
    """
    auth_key    = _auth_key()
    template_id = getattr(settings, 'MSG91_TEMPLATE_ID', '').strip()
    sender_id   = getattr(settings, 'MSG91_SENDER_ID', 'EXVAKL')

    if not auth_key:
        return {'success': False, 'error': 'SMS service is not configured. Please contact support.'}

    if not template_id:
        logger.critical(
            "MSG91_TEMPLATE_ID settings/env mein set nahi hai! "
            ".env mein MSG91_TEMPLATE_ID=<your_template_id> add karo."
        )
        return {'success': False, 'error': 'SMS service is not configured. Please contact support.'}

    e164_phone = _get_e164(phone)

    params = {
        'template_id':       template_id,
        'mobile':            e164_phone,
        'authkey':           auth_key,
        'realTimeResponse':  '1',
    }

    try:
        response = requests.get(MSG91_SEND_URL, params=params, timeout=15)
        data = response.json()
        logger.info(f"MSG91 send_otp → {e164_phone}: HTTP {response.status_code} | {data}")

        # MSG91 success response: {"type": "success", ...}
        if data.get('type') == 'success':
            return {'success': True}

        # Kuch providers HTTP 200 pe bhi error dete hain — message check karo
        error_msg = data.get('message', 'OTP send karne mein problem aayi. Dobara try karo.')
        logger.warning(f"MSG91 send_otp failed for {e164_phone}: {error_msg}")
        return {'success': False, 'error': _clean_error(error_msg)}

    except requests.Timeout:
        logger.error(f"MSG91 send_otp TIMEOUT for {e164_phone}")
        return {'success': False, 'error': 'OTP send nahi ho paaya (timeout). Thodi der baad try karo.'}
    except requests.ConnectionError:
        logger.error(f"MSG91 send_otp CONNECTION ERROR for {e164_phone}")
        return {'success': False, 'error': 'SMS service se connect nahi ho paaya. Internet check karo.'}
    except Exception as e:
        logger.exception(f"MSG91 send_otp unexpected error for {e164_phone}: {e}")
        return {'success': False, 'error': 'OTP bhejne mein koi problem aayi. Dobara try karo.'}


def verify_phone_otp(phone: str, otp: str) -> dict:
    """
    MSG91 se OTP verify karo.

    Returns:
        {'success': True}
        {'success': False, 'error': '<user-facing message>'}
    """
    auth_key = _auth_key()
    if not auth_key:
        return {'success': False, 'error': 'SMS service is not configured. Please contact support.'}

    e164_phone = _get_e164(phone)

    # Basic client-side sanity check
    otp = str(otp).strip()
    if not otp.isdigit() or len(otp) != 6:
        return {'success': False, 'error': 'Invalid OTP format. Please enter the 6-digit code.'}

    params = {
        'authkey': auth_key,
        'mobile':  e164_phone,
        'otp':     otp,
    }

    try:
        response = requests.get(MSG91_VERIFY_URL, params=params, timeout=15)
        data = response.json()
        logger.info(f"MSG91 verify_otp → {e164_phone}: HTTP {response.status_code} | {data}")

        if data.get('type') == 'success':
            return {'success': True}

        error_msg = data.get('message', 'OTP verify nahi ho paaya.')
        return {'success': False, 'error': _clean_error(error_msg)}

    except requests.Timeout:
        logger.error(f"MSG91 verify_otp TIMEOUT for {e164_phone}")
        return {'success': False, 'error': 'Verification timeout. Dobara try karo.'}
    except requests.ConnectionError:
        logger.error(f"MSG91 verify_otp CONNECTION ERROR for {e164_phone}")
        return {'success': False, 'error': 'SMS service se connect nahi ho paaya.'}
    except Exception as e:
        logger.exception(f"MSG91 verify_otp unexpected error for {e164_phone}: {e}")
        return {'success': False, 'error': 'OTP verification mein problem aayi. Dobara try karo.'}


def resend_phone_otp(phone: str, retry_type: str = 'text') -> dict:
    """
    OTP resend karo (same MSG91 session mein retry).
    retry_type: 'text' (default) ya 'voice'

    Agar MSG91 retry fail kare toh fresh OTP bhejne ki koshish karo.

    Returns:
        {'success': True}
        {'success': False, 'error': '<message>'}
    """
    auth_key = _auth_key()
    if not auth_key:
        return {'success': False, 'error': 'SMS service is not configured.'}

    e164_phone = _get_e164(phone)

    params = {
        'authkey':   auth_key,
        'mobile':    e164_phone,
        'retrytype': retry_type,
    }

    try:
        response = requests.get(MSG91_RESEND_URL, params=params, timeout=15)
        data = response.json()
        logger.info(f"MSG91 resend_otp → {e164_phone}: HTTP {response.status_code} | {data}")

        if data.get('type') == 'success':
            return {'success': True}

        # Retry fail → fresh OTP bhejo as fallback
        logger.warning(f"MSG91 resend failed for {e164_phone}, trying fresh send. Response: {data}")
        return send_phone_otp(phone)

    except requests.Timeout:
        logger.error(f"MSG91 resend_otp TIMEOUT for {e164_phone}, falling back to fresh send")
        return send_phone_otp(phone)
    except Exception as e:
        logger.exception(f"MSG91 resend_otp error for {e164_phone}: {e}, falling back to fresh send")
        return send_phone_otp(phone)


def _clean_error(msg: str) -> str:
    """
    MSG91 ke technical error messages ko user-friendly banao.
    """
    msg_lower = str(msg).lower()

    if 'expired' in msg_lower or 'expire' in msg_lower:
        return 'OTP expire ho gaya. Naya OTP maangein.'
    if 'invalid' in msg_lower and 'otp' in msg_lower:
        return 'Galat OTP. Dobara check karke try karo.'
    if 'not found' in msg_lower or 'no active' in msg_lower:
        return 'OTP session nahi mila. Pehle OTP bhejne ki request karo.'
    if 'already verified' in msg_lower:
        return 'Yeh number pehle se verified hai.'
    if 'limit' in msg_lower or 'exceed' in msg_lower:
        return 'Bahut zyada OTP requests. Kuch der baad try karo.'
    if 'template' in msg_lower:
        return 'OTP bhejne mein configuration error. Support se contact karo.'
    if 'authkey' in msg_lower or 'auth' in msg_lower:
        return 'SMS service authentication error. Support se contact karo.'

    # Fallback — original message return karo agar already clean hai
    return msg if len(msg) < 120 else 'OTP process mein koi problem aayi. Dobara try karo.'