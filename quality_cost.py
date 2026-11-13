"""Quality costs: weights in kilograms, repair rates in PLN per minute."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

REPAIR_MINUTES = (15, 30, 45, 60, 90, 120)
WELDING_MINUTES = REPAIR_MINUTES + (180, 240, 300, 360, 420, 500, 560, 620)
REPAIR_RATES = {
    'szlifowanie': '0.70',
    'szpachlowanie': '0.63',
    'poprawa gwintu': '1.30',
    'naprawa gwintu': '1.30',
    'spawanie': '0.60',
}


def calculate_quality_cost(decision, minutes=None, weight_kg=None):
    decision = decision.strip().lower()
    if decision == 'złomować':
        try:
            weight = Decimal(str(weight_kg))
        except InvalidOperation:
            raise ValueError('Brak poprawnej wagi żeliwa produktu.') from None
        if not weight.is_finite() or weight <= 0:
            raise ValueError('Waga żeliwa produktu musi być większa od zera.')
        cost = Decimal('5045') * weight / Decimal('1000')
    elif decision in REPAIR_RATES:
        allowed = WELDING_MINUTES if decision == 'spawanie' else REPAIR_MINUTES
        if str(minutes) not in {str(value) for value in allowed}:
            raise ValueError('Wybierz prawidłowy czas naprawy z listy.')
        cost = Decimal(str(minutes)) * Decimal(REPAIR_RATES[decision])
    else:
        cost = Decimal('0')
    cost = cost.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if cost > Decimal('99999999.99'):
        raise ValueError('Koszt przekracza dopuszczalny zakres kwoty.')
    return cost
