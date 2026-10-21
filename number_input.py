from constants import NUMBER_INPUT_RE


def is_number_input(value, max_value):
    if not NUMBER_INPUT_RE.fullmatch(value):
        return False
    number = parse_number(value)
    return number is None or number <= max_value


def parse_number(value):
    # Returns the field value as a number, or None if it isn't a number yet
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def format_number(number):
    # 50.0 -> "50", 12.50 -> "12.5"
    return f"{number:.2f}".rstrip("0").rstrip(".")


def valid_number_or(value, default, max_value, allow_zero=False):
    # Use a saved value only if it is still valid: above zero, or zero too with allow_zero
    value = str(value) if value is not None else ""
    number = parse_number(value)
    if not is_number_input(value, max_value) or number is None:
        return default
    return value if number > 0 or (allow_zero and number == 0) else default
