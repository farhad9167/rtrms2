import json
import threading

try:
    import win32print
except ImportError:
    win32print = None


def send_to_printer(printer_name, text_bytes, on_result=None):
    """
    Fires the print job in a background thread so a slow/offline printer never
    delays order confirmation. If on_result is given, it's called with True/False
    once the job finishes (or immediately with False if no printer is configured
    or pywin32 isn't available, e.g. when testing off Windows).
    """
    if not win32print or not printer_name:
        if on_result:
            on_result(False)
        return

    def _do_print():
        success = False
        try:
            hPrinter = win32print.OpenPrinter(printer_name)
            try:
                hJob = win32print.StartDocPrinter(hPrinter, 1, ("RTRMS Order", None, "RAW"))
                win32print.StartPagePrinter(hPrinter)
                win32print.WritePrinter(hPrinter, text_bytes)
                win32print.EndPagePrinter(hPrinter)
                win32print.EndDocPrinter(hPrinter)
                success = True
            finally:
                win32print.ClosePrinter(hPrinter)
        except Exception as e:
            print(f"❌ Print Error: {e}")
            success = False
        finally:
            if on_result:
                on_result(success)

    threading.Thread(target=_do_print, daemon=True).start()


def generate_receipt(order, restaurant, currency_symbol, ticket_type="KITCHEN", payment_method="N/A"):
    """
    ticket_type: "KITCHEN" | "COUNTER" | "CUSTOMER" — all three now carry the
    same core info (items, prices, table, time, date, daily serial number) per
    the unified-bill design. Only the footer message (and payment method, once
    known) is skipped on the kitchen copy.
    """
    from utils.timezones import get_local_time

    try:
        items = json.loads(order.items)
    except Exception:
        items = []

    local_dt = get_local_time(order.created_at, restaurant.country_code) or order.created_at

    INIT = b'\x1b\x40'
    CENTER = b'\x1b\x61\x01'
    LEFT = b'\x1b\x61\x00'
    BOLD_ON = b'\x1b\x45\x01'
    BOLD_OFF = b'\x1b\x45\x00'
    LARGE_ON = b'\x1d\x21\x11'
    LARGE_OFF = b'\x1d\x21\x00'
    CUT = b'\x1d\x56\x41'

    content = INIT + CENTER + BOLD_ON + LARGE_ON
    content += f"{restaurant.name}\n".encode('utf-8', errors='replace')
    content += f"{ticket_type} TICKET\n".encode('utf-8')
    content += LARGE_OFF + BOLD_OFF + b"================================\n"
    content += LEFT + BOLD_ON
    content += f"Table: {order.table_no} | {order.dining_mode}\n".encode('utf-8', errors='replace')
    content += BOLD_OFF
    if order.daily_serial:
        content += f"Order # {order.daily_serial} (today)\n".encode('utf-8')
    content += f"{local_dt.strftime('%Y-%m-%d %H:%M')}\n".encode('utf-8')
    content += b"--------------------------------\n"
    for item in items:
        line_total = item.get('price', 0) * item.get('count', 1)
        content += f"{item['count']} x {item['name']}".encode('utf-8', errors='replace')
        content += f" - {currency_symbol}{line_total:g}\n".encode('utf-8', errors='replace')
    if getattr(order, "special_instructions", None):
        content += b"--------------------------------\n"
        content += BOLD_ON + f"Note: {order.special_instructions}\n".encode('utf-8', errors='replace') + BOLD_OFF
    content += b"--------------------------------\n"
    content += BOLD_ON + f"TOTAL: {currency_symbol}{order.total_price:g}\n".encode('utf-8') + BOLD_OFF
    # The user was explicit: PAID/pay-at-counter status shows on all three
    # copies (kitchen included), only the payment-method line + footer
    # message are counter/customer-only.
    if getattr(order, "is_paid", False):
        content += BOLD_ON + LARGE_ON + b"*** PAID ***\n" + LARGE_OFF + BOLD_OFF
    elif restaurant.bank_payment_enabled:
        content += b"Please pay at the counter after your meal.\n"
    if ticket_type != "KITCHEN":
        content += f"Payment: {order.payment_method or payment_method}\n".encode('utf-8', errors='replace')
        if restaurant.bill_footer_message:
            content += b"--------------------------------\n"
            content += f"{restaurant.bill_footer_message}\n".encode('utf-8', errors='replace')
    else:
        content += f"Payment: {order.payment_method or payment_method}\n".encode('utf-8', errors='replace')
    content += b"\n\n\n\n" + CUT
    return content
