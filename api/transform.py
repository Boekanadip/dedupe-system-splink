"""Transform functions for customer data standardization."""
import re
from datetime import datetime

def standardize_name(name):
    """Standardize name: lowercase, strip, title case."""
    if not name:
        return ""
    return name.strip().lower().title()

def standardize_email(email):
    """Standardize email: lowercase, strip."""
    if not email:
        return ""
    return email.strip().lower()

def extract_email_domain(email):
    """Extract domain from email."""
    if not email or '@' not in email:
        return ""
    return email.split('@')[1].strip().lower()

def standardize_phone(phone):
    """Standardize phone: digits only."""
    if not phone:
        return ""
    return re.sub(r'\D', '', str(phone))

def extract_phone_last4(phone):
    """Extract last 4 digits from phone."""
    digits = standardize_phone(phone)
    return digits[-4:] if digits else ""

def standardize_address(address):
    """Standardize address: lowercase, strip."""
    if not address:
        return ""
    return address.strip().lower()

def standardize_city(city):
    """Standardize city: lowercase, strip, title case."""
    if not city:
        return ""
    return city.strip().lower().title()

def standardize_state(state):
    """Standardize state: uppercase, strip."""
    if not state:
        return ""
    return state.strip().upper()

def standardize_dob(dob):
    """Standardize date of birth to YYYY-MM-DD string."""
    if not dob:
        return ""
    if isinstance(dob, datetime):
        return dob.strftime('%Y-%m-%d')
    if isinstance(dob, str):
        # Try parsing common formats
        for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y%m%d']:
            try:
                return datetime.strptime(dob, fmt).strftime('%Y-%m-%d')
            except ValueError:
                continue
        return dob  # Return as-is if cannot parse
    return str(dob)

def transform_customer(customer):
    """Transform raw customer to standardized format."""
    return {
        'customer_id': customer.get('customer_id', ''),
        'first_name_std': standardize_name(customer.get('first_name', '')),
        'last_name_std': standardize_name(customer.get('last_name', '')),
        'email_std': standardize_email(customer.get('email', '')),
        'email_domain': extract_email_domain(customer.get('email', '')),
        'phone_std': standardize_phone(customer.get('phone', '')),
        'phone_last4': extract_phone_last4(customer.get('phone', '')),
        'address_std': standardize_address(customer.get('address', '')),
        'city_std': standardize_city(customer.get('city', '')),
        'state_std': standardize_state(customer.get('state', '')),
        'dob_std': standardize_dob(customer.get('dob', '')),
    }