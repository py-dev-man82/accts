from datetime import datetime
from handlers.reports import ReportEngine


def parse_date(input_str):
    """Helper to parse DDMMYYYY input to datetime"""
    try:
        return datetime.strptime(input_str, "%d%m%Y")
    except ValueError:
        print("❌ Invalid date format. Use DDMMYYYY.")
        exit(1)


# ──────────────────────────────────────────────
# 📄 Customer Report Pretty Printer
# ──────────────────────────────────────────────
def print_customer_report(report):
    cust = report['customer']
    print(f"\n📄 Customer Report: {cust['name']}")
    print(f"Currency: {cust['currency']}")
    print("──────────────────────────────")
    print("🛒 Sales:")
    if report['sales']:
        for s in report['sales']:
            print(f"• {s['date']}: {s['item']} x{s['quantity']} @ {s['unit_price']} {s['currency']} "
                  f"= {s['total_value']} {s['currency']} (Store: {s['store']})")
            if s['note']:
                print(f"  📝 Note: {s['note']}")
    else:
        print("  (No sales in this period)")

    print("\n💵 Payments:")
    if report['payments']:
        for p in report['payments']:
            print(f"• {p['date']}: {p['local_amt']} (fee: {p['fee_amt']}) → {p['usd_amt']} USD @ {p['fx_rate']:.4f}")
            if p['note']:
                print(f"  📝 Note: {p['note']}")
    else:
        print("  (No payments in this period)")

    print("\n📊 Totals:")
    print(f"  Sales: {report['totals']['sales_local']:.2f} {cust['currency']}")
    print(f"  Payments: {report['totals']['payments_local']:.2f} {cust['currency']}")
    print(f"  USD Received: {report['totals']['payments_usd']:.2f} USD")
    print(f"  Fees: {report['totals']['fees_total']:.2f} {cust['currency']}")
    print(f"  Balance: {report['balance_local']:.2f} {cust['currency']}")
    print("──────────────────────────────\n")


# ──────────────────────────────────────────────
# 📄 Partner Report Pretty Printer
# ──────────────────────────────────────────────
def print_partner_report(report):
    partner = report['partner']
    print(f"\n📄 Partner Report: {partner['name']}")
    print(f"Currency: {partner['currency']}")
    print("──────────────────────────────")
    print("🛒 Sales:")
    if report['sales']:
        for s in report['sales']:
            print(f"• {s['date']}: {s['item']} x{s['quantity']} @ {s['unit_price']} {s['currency']} "
                  f"= {s['total_value']} {s['currency']}")
            if s['note']:
                print(f"  📝 Note: {s['note']}")
    else:
        print("  (No sales in this period)")

    print("\n💵 Payouts:")
    if report['payouts']:
        for p in report['payouts']:
            print(f"• {p['date']}: {p['local_amt']} (fee: {p['fee_amt']}) → {p['usd_amt']} USD @ {p['fx_rate']:.4f}")
            if p['note']:
                print(f"  📝 Note: {p['note']}")
    else:
        print("  (No payouts in this period)")

    print("\n📦 Inventory:")
    if report['inventory']:
        for i in report['inventory']:
            print(f"• {i['item']}: {i['quantity']} units @ {i['purchase_cost']} = {i['market_value']} USD")
            if i['note']:
                print(f"  📝 Note: {i['note']}")
    else:
        print("  (No inventory records)")

    print("\n📊 Totals:")
    print(f"  Sales: {report['totals']['sales_local']:.2f} {partner['currency']}")
    print(f"  Payouts: {report['totals']['payouts_local']:.2f} {partner['currency']}")
    print(f"  USD Paid: {report['totals']['payouts_usd']:.2f} USD")
    print(f"  Inventory Market Value: {report['inventory_value_usd']:.2f} USD")
    print(f"  Balance: {report['balance_local']:.2f} {partner['currency']}")
    if report['reconciliation_flag']:
        print("⚠️ Inventory is NOT reconciled!")
    else:
        print("✅ Inventory reconciled.")
    print("──────────────────────────────\n")


# ──────────────────────────────────────────────
# 📄 Store Report Pretty Printer
# ──────────────────────────────────────────────
def print_store_report(report):
    store = report['store']
    print(f"\n📄 Store Report: {store['name']}")
    print(f"Currency: {store['currency']}")
    print("──────────────────────────────")
    print("🏪 Direct Sales:")
    if report['direct_sales']:
        for s in report['direct_sales']:
            print(f"• {s['date']}: {s['item']} x{s['quantity']} @ {s['unit_price']} {s['currency']} "
                  f"= {s['total_value']} {s['currency']}")
            if s['note']:
                print(f"  📝 Note: {s['note']}")
    else:
        print("  (No direct sales in this period)")

    print("\n🤝 Owner Sales Fees:")
    if report['owner_sales_fees']:
        for f in report['owner_sales_fees']:
            print(f"• {f['date']}: Fee {f['fee_amt']} {f['currency']}")
    else:
        print("  (No owner sales fees in this period)")

    print("\n📊 Totals:")
    print(f"  Handling Fees Collected: {report['handling_fees_total']:.2f} {store['currency']}")
    print("──────────────────────────────\n")


# ──────────────────────────────────────────────
# 📄 Owner Report Pretty Printer
# ──────────────────────────────────────────────
def print_owner_report(report):
    print("\n📄 Owner (POT) Summary Report")
    print("──────────────────────────────")
    print("📈 Sales & Payments:")
    print(f"  Total Sales (local): {report['total_sales_local']:.2f}")
    print(f"  Total Payments (USD): {report['total_payments_usd']:.2f} USD")
    print(f"  Total Payouts (USD): {report['total_payouts_usd']:.2f} USD")
    print(f"  POT Balance (USD): {report['pot_balance_usd']:.2f} USD")

    print("\n📦 Inventory Summary:")
    if report['inventory_summary']:
        for inv in report['inventory_summary']:
            print(f"• {inv['item']}: {inv['quantity']} units @ {inv['market_price']} USD = {inv['total_value']} USD")
    else:
        print("  (No inventory summary)")

    print("\n⚠️ Reconciliation Flags:")
    if report['reconciliation_flags']:
        for flag in report['reconciliation_flags']:
            print(f"• {flag}")
    else:
        print("✅ All inventories reconciled.")
    print("──────────────────────────────\n")


# ──────────────────────────────────────────────
# 🚀 Main Runner
# ──────────────────────────────────────────────
def main():
    print("=== Report Test Tool ===")
    engine = ReportEngine()
    report_type = input("Report type (customer/partner/store/owner): ").strip().lower()

    start_str = input("Start date (DDMMYYYY): ").strip()
    start_date = parse_date(start_str)
    end_date = datetime.now()

    scope = input("Scope (full/sales/payments) [default: full]: ").strip().lower() or "full"

    try:
        if report_type == "customer":
            customer_id = int(input("Enter Customer ID: ").strip())
            report = engine.get_customer_report(customer_id, start_date, end_date, scope)
            print_customer_report(report)

        elif report_type == "partner":
            partner_id = int(input("Enter Partner ID: ").strip())
            report = engine.get_partner_report(partner_id, start_date, end_date, scope)
            print_partner_report(report)

        elif report_type == "store":
            store_id = int(input("Enter Store ID: ").strip())
            report = engine.get_store_report(store_id, start_date, end_date, scope)
            print_store_report(report)

        elif report_type == "owner":
            report = engine.get_owner_report(start_date, end_date, scope)
            print_owner_report(report)

        else:
            print("❌ Invalid report type.")
    except Exception as e:
        print(f"⚠️ Error: {e}")


if __name__ == "__main__":
    main()