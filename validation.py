"""
INPUT VALIDATION
Checks on transactions arriving through the API

Transaction and customer ids are stored and later shown in the dashboard, so
they are restricted to a short, plain set of characters. That keeps markup and
other unexpected text out of the database, whatever the page does with it.
(The dashboard also escapes everything it displays; this is the second layer.)
"""

import math
import re

# 1 to 64 characters: letters, digits, hyphen, underscore (e.g. CUST001, TXN4F2A9C1B, LIVE8D3E21AA)
ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,64}$')

ID_RULE = 'must be 1 to 64 characters: letters, digits, hyphen or underscore'
MAX_AMOUNT = 1e12
REQUIRED_FIELDS = ('customer_id', 'amount', 'transaction_id')


def valid_id(value):
    """True if value is a string of the allowed form"""
    return isinstance(value, str) and bool(ID_PATTERN.match(value))


def validate_transaction(txn):
    """None if the transaction is acceptable, otherwise a short message saying why not"""
    if not isinstance(txn, dict):
        return 'Transaction must be a JSON object'

    missing = [field for field in REQUIRED_FIELDS if field not in txn]
    if missing:
        return 'Missing ' + ', '.join(missing)

    if not valid_id(txn['transaction_id']):
        return f'transaction_id {ID_RULE}'
    if not valid_id(txn['customer_id']):
        return f'customer_id {ID_RULE}'

    amount = txn['amount']
    if (isinstance(amount, bool) or not isinstance(amount, (int, float))
            or not math.isfinite(amount) or amount < 0 or amount > MAX_AMOUNT):
        return 'amount must be a number between 0 and 1000000000000'

    return None
