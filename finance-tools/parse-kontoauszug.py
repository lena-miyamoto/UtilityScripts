#!/usr/bin/env python3
from categories import giro_categories, creditcard_categories, FALLBACK, PATTERNS

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass

import argparse
import csv
import os
import re
import sys

# ---------------------------------------------------------------------------
# Category matching
# ---------------------------------------------------------------------------

def _compile_categories(categories):
  return [
    (key, label, [re.compile(pattern, re.IGNORECASE) for pattern in PATTERNS[key]])
    for key, label in categories
  ]
#end def

GIRO_COMPILED = _compile_categories(giro_categories)
CREDITCARD_COMPILED = _compile_categories(creditcard_categories)

GIRO_DISPLAY_CATEGORIES = [(key, label) for key, label in giro_categories] + [FALLBACK]
CREDITCARD_DISPLAY_CATEGORIES = [(key, label) for key, label in creditcard_categories] + [FALLBACK]

def categorize_by_patterns(merchant, compiled_categories):
  merchant = merchant.strip()

  for key, label, regexes in compiled_categories:
    for regex in regexes:
      if regex.search(merchant):
        return key
      #end if
    #end for
  #end for

  return FALLBACK[0]
#end def

def parse_date(value):
  try:
    return datetime.strptime(value.strip(), '%d.%m.%Y').date()
  except ValueError:
    print(f'Could not parse date: {value}')
    return None
  #end try
#end def

def parse_amount(value):
  # Normalize a raw amount string to a signed Decimal. Handles thousand
  # separators ('.'), a decimal comma (','), and an optional leading '+/-'
  # or German trailing '-'.
  cleaned = value.strip().replace('.', '').replace(' ', '')

  if not cleaned:
    print(f'Could not parse amount: {value}')
    return None
  #end if

  sign = 1

  if cleaned.startswith('-'):
    sign = -1
    cleaned = cleaned[1:]
  elif cleaned.startswith('+'):
    cleaned = cleaned[1:]
  elif cleaned.endswith('-'):
    sign = -1
    cleaned = cleaned[:-1]
  #end if

  cleaned = cleaned.replace(',', '.')

  try:
    return Decimal(cleaned) * sign
  except InvalidOperation:
    print(f'Could not parse amount: {value}')
    return None
  #end try
#end def

class Transaction:
  def __init__(self, account_number, kind, merchant, booking_date, transaction_date, amount, currency, description=None):
    self.account_number = account_number
    self.kind = kind
    self.merchant = merchant
    self.description = description if description is not None else [merchant]
    self.booking_date = booking_date
    self.transaction_date = transaction_date
    self.minus = amount < 0
    self.amount = abs(amount)
    self.currency = currency
  #end def

  def __str__(self):
    description_len = len(self.description)
    return f"Transaction(Account: {self.account_number}, Amount: {self.amount} {self.currency}, Transaction date: {self.transaction_date}, Booking date: {self.booking_date}, Description ({description_len}): {self.description})"
  #end def

  def __repr__(self):
    return self.__str__()
  #end def
#end class

def parse_easybank_transactions(csv_file, account_type):
  transactions = []

  with open(csv_file, 'r') as csv_file_handle:
    for line in csv_file_handle:
      normalized_line = line.strip()

      if not normalized_line:
        continue
      #end if

      columns = normalized_line.split(';')

      if len(columns) == 6:
        account_number = columns[0]
        description = columns[1].split('|')
        booking_date = parse_date(columns[2])
        transaction_date = parse_date(columns[3])
        amount = parse_amount(columns[4])
        currency = columns[5].strip()

        if booking_date is None or transaction_date is None or amount is None:
          continue
        #end if

        kind = description[0] if description else ''

        if account_type == 'giro':
          merchant = description[2] if len(description) >= 3 else ''
        else:
          merchant = description[0] if description else ''
        #end if

        transactions.append(Transaction(account_number, kind, merchant, booking_date, transaction_date, amount, currency, description))
      else:
        print(f'Unable to parse transaction: {normalized_line}')
      #end if
    #end for
  #end with

  return transactions
#end def

def parse_sparkasse_transactions(csv_file):
  transactions = []

  # The account number (IBAN) is not part of the export; take it from the
  # filename, e.g. "AT000000000000000000_2025-01-01_2026-07-31.csv".
  account_number = os.path.basename(csv_file).split('_', 1)[0]

  with open(csv_file, 'r', newline='') as csv_file_handle:
    reader = csv.reader(csv_file_handle)
    next(reader, None)  # skip the header row

    for row in reader:
      if not row or (len(row) == 1 and not row[0].strip()):
        continue
      #end if

      if len(row) < 7:
        print(f'Unable to parse transaction: {row}')
        continue
      #end if

      # Sparkasse has no separate valuta date, so booking and transaction
      # date are identical.
      booking_date = parse_date(row[0])
      merchant = row[1].strip()
      amount = parse_amount(row[6])

      if booking_date is None or amount is None:
        continue
      #end if

      transactions.append(Transaction(account_number, '', merchant, booking_date, booking_date, amount, 'EUR'))
    #end for
  #end with

  return transactions
#end def

def categorize_easybank_giro(transaction):
  if len(transaction.description) < 3:
    print(f'Cannot compute transaction: {transaction}')
    return None
  #end if

  return categorize_by_patterns(transaction.merchant, GIRO_COMPILED)
#end def

def categorize_easybank_creditcard(transaction):
  if not transaction.minus:
    print(f'Uncatalogued transaction type: {transaction.merchant}')
    return None
  #end if

  return categorize_by_patterns(transaction.merchant, CREDITCARD_COMPILED)
#end def

def categorize_sparkasse(transaction):
  return categorize_by_patterns(transaction.merchant, GIRO_COMPILED)
#end def

@dataclass
class Source:
  key: str
  display_name: str
  parse: object
  is_expense: object
  categorize: object
  categories: object
  include_account_number: bool = False
#end class

SOURCES = {
  'easybank-giro': Source(
    key='easybank-giro',
    display_name='Giro',
    parse=lambda csv_file: parse_easybank_transactions(csv_file, 'giro'),
    is_expense=lambda transaction: transaction.kind.startswith('Bezahlung Karte') or transaction.kind.startswith('EINZUGSBETRAG'),
    categorize=categorize_easybank_giro,
    categories=GIRO_DISPLAY_CATEGORIES,
  ),
  'easybank-creditcard': Source(
    key='easybank-creditcard',
    display_name='Creditcard',
    parse=lambda csv_file: parse_easybank_transactions(csv_file, 'creditcard'),
    is_expense=lambda transaction: not transaction.kind.startswith('EINZUGSBETRAG'),
    categorize=categorize_easybank_creditcard,
    categories=CREDITCARD_DISPLAY_CATEGORIES,
  ),
  'sparkasse': Source(
    key='sparkasse',
    display_name='Sparkasse',
    parse=parse_sparkasse_transactions,
    is_expense=lambda transaction: transaction.minus,
    categorize=categorize_sparkasse,
    categories=GIRO_DISPLAY_CATEGORIES,
    include_account_number=True,
  ),
}

def regex_escape(text):
  # re.escape over-escapes characters that are literal outside a character
  # class; strip those backslashes (space, '-', '&', '~', '#').
  escaped = re.escape(text)

  for char in ' -&~#':
    escaped = escaped.replace('\\' + char, char)
  #end for

  return escaped
#end def

def print_regex_entries(patterns):
  for pattern in sorted(set(patterns)):
    if "'" in pattern:
      print(f'  {pattern!r},')
    else:
      print(f"  r'{pattern}',")
    #end if
  #end for
#end def

def print_new_merchants(accounts):
  merchants = []

  for name, expenses, categories in accounts:
    for month_transactions in expenses.get('new', {}).values():
      for transaction in month_transactions:
        merchant = transaction.merchant.strip()

        if merchant:
          merchants.append(merchant)
        #end if
      #end for
    #end for
  #end for

  if not merchants:
    return
  #end if

  print()
  print('# New merchants (unrecognized) - regex-escaped, ready to paste into a category list:')
  print_regex_entries([regex_escape(merchant) for merchant in merchants])
#end def

def print_categories_sorted():
  print('#!/usr/bin/env python3')
  print()

  for name, patterns in PATTERNS.items():
    print(f'{name} = [')
    print_regex_entries(patterns)
    print(']')
    print()
  #end for

  print('PATTERNS = {')
  for name in PATTERNS:
    print(f'  {name!r}: {name},')
  #end for
  print('}')
  print()

  print('giro_categories = [')
  for key, label in giro_categories:
    print(f'  ({key!r}, {label!r}),')
  #end for
  print(']')
  print()

  print('creditcard_categories = [')
  for key, label in creditcard_categories:
    print(f'  ({key!r}, {label!r}),')
  #end for
  print(']')
  print()

  print(f'FALLBACK = ({FALLBACK[0]!r}, {FALLBACK[1]!r})')
#end def

def add_transaction(expenses, transaction, category, start_date, end_date):
  if transaction.transaction_date < start_date:
    print(f'Ignore transaction, transaction date is before start date {start_date}: {transaction}')
  elif transaction.transaction_date > end_date:
    print(f'Ignore transaction, transaction date is after end date {end_date}: {transaction}')
  else:
    month_marker = transaction.transaction_date.strftime('%Y-%m')

    if not 'months' in expenses:
      expenses['months'] = [month_marker]
    elif not month_marker in expenses['months']:
      expenses['months'].append(month_marker)
    #end if

    if not category in expenses:
      expenses[category] = {}
    #end if

    if not month_marker in expenses[category]:
      expenses[category][month_marker] = []
    #end if

    expenses[category][month_marker].append(transaction)
  #end if
#end def

def calculate_expenses_for_month(expenses, category, month_marker):
  total = 0

  if category in expenses and month_marker in expenses[category]:
    for transaction in expenses[category][month_marker]:
      if transaction.currency != 'EUR':
        print(f'Non-Euro transaction found: {transaction}')
        print('Abort.')
        sys.exit(1)
      #end if

      total = total + transaction.amount
    #end for
  #end if

  return total
#end def

def analyze_expenses(transactions, source, start_date, end_date):
  expenses = {}

  for transaction in transactions:
    if not source.is_expense(transaction):
      continue
    #end if

    category = source.categorize(transaction)

    if not category is None:
      add_transaction(expenses, transaction, category, start_date, end_date)
    #end if
  #end for

  return expenses
#end def

def print_expenses(accounts):
  months = set()

  for name, expenses, categories in accounts:
    if 'months' in expenses:
      months.update(expenses['months'])
    #end if
  #end for

  if not months:
    print('No transactions found. Abort.')
    return
  #end if

  months = sorted(months)

  label_width = max(len(label) for name, expenses, categories in accounts for category, label in categories)

  totals = {}

  for month_marker in months:
    print(f'[ {month_marker} ]')

    for name, expenses, categories in accounts:
      print(f'  * {name}:')

      for category, label in categories:
        value = calculate_expenses_for_month(expenses, category, month_marker)
        key = (name, category)
        totals[key] = totals.get(key, 0) + value
        print(f'    - {label:<{label_width}}  {value} EUR')
      #end for
    #end for

    print()
  #end for

  month_count = len(months)

  print('--------------------------------------------------------------')
  print()
  print(f'# Total expenses in {month_count} months:')

  for name, expenses, categories in accounts:
    for category, label in categories:
      total = totals[(name, category)]
      average = total / month_count
      print(f'  - Total {name} {label}: {total} EUR (avg of {average:.2f} EUR per month)')
    #end for
  #end for

  print_new_merchants(accounts)
#end def

def main():
  parser = argparse.ArgumentParser(description='Analyze bank account CSV exports (easybank and Sparkasse).')
  parser.add_argument('--start', metavar='YYYY-MM-DD', help='Only consider transactions on or after this date.')
  parser.add_argument('--end', metavar='YYYY-MM-DD', help='Only consider transactions on or before this date.')
  parser.add_argument('--print-categories', action='store_true', help='Print sorted category definitions (to regenerate categories.py) and exit.')
  parser.add_argument('inputs', nargs='*', metavar='FORMAT:PATH', help=f'Input files. FORMAT is one of: {", ".join(SOURCES)}.')

  args = parser.parse_args()

  if args.print_categories:
    print_categories_sorted()
    return
  #end if

  if not args.inputs:
    parser.error('at least one FORMAT:PATH input is required')
  #end if

  start_date = datetime.strptime(args.start, '%Y-%m-%d').date() if args.start else date.min
  end_date = datetime.strptime(args.end, '%Y-%m-%d').date() if args.end else date.max

  accounts = []

  for spec in args.inputs:
    if ':' in spec:
      source_key, csv_file = spec.split(':', 1)
    else:
      print(f'Missing format for input "{spec}" (expected FORMAT:PATH).')
      sys.exit(1)
    #end if

    if source_key not in SOURCES:
      print(f'Unknown format "{source_key}". Available: {", ".join(SOURCES)}.')
      sys.exit(1)
    #end if

    source = SOURCES[source_key]
    transactions = source.parse(csv_file)

    name = source.display_name
    if source.include_account_number and transactions:
      name = f'{name} {transactions[0].account_number}'
    #end if

    expenses = analyze_expenses(transactions, source, start_date, end_date)
    accounts.append((name, expenses, source.categories))
  #end for

  print_expenses(accounts)
#end def

if __name__ == '__main__':
  main()
