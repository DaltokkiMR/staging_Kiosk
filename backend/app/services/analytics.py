"""사장님 매출 통계."""
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from ..models import PAY_TYPE_LABELS, Order, OrderStatus, Payment, PayType, Store

DONE = [OrderStatus.PAID.value, OrderStatus.SERVED.value]


def sales_summary(db: Session, store: Store, start: date, end: date) -> dict:
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end + timedelta(days=1), datetime.min.time())
    orders = (
        db.query(Order)
        .filter(Order.store_id == store.id, Order.status.in_(DONE),
                Order.paid_at >= start_dt, Order.paid_at < end_dt)
        .all()
    )

    daily = defaultdict(lambda: {"revenue": 0, "orders": 0})
    hourly = defaultdict(int)
    by_menu = defaultdict(lambda: {"quantity": 0, "revenue": 0})
    customers = defaultdict(int)
    for o in orders:
        d = o.paid_at.date().isoformat()
        daily[d]["revenue"] += o.total_amount
        daily[d]["orders"] += 1
        hourly[o.paid_at.hour] += o.total_amount
        if o.user_id:
            customers[o.user_id] += 1
        for it in o.items:
            by_menu[it.name]["quantity"] += it.quantity
            by_menu[it.name]["revenue"] += it.unit_price * it.quantity

    payments = (
        db.query(Payment)
        .filter(Payment.order_id.in_([o.id for o in orders] or [-1]), Payment.status == "approved")
        .all()
    )
    by_pay = defaultdict(int)
    for p in payments:
        by_pay[p.pay_type] += p.amount

    total = sum(o.total_amount for o in orders)
    returning = sum(1 for c in customers.values() if c >= 2)
    return {
        "store_id": store.id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "total_revenue": total,
        "order_count": len(orders),
        "average_order_value": round(total / len(orders)) if orders else 0,
        "member_customers": len(customers),
        "returning_customers": returning,
        "daily": [{"date": d, **v} for d, v in sorted(daily.items())],
        "hourly": [{"hour": h, "revenue": hourly[h]} for h in sorted(hourly)],
        "by_menu": sorted(({"name": n, **v} for n, v in by_menu.items()), key=lambda x: -x["revenue"]),
        "by_payment_type": [
            {"pay_type": t, "label": PAY_TYPE_LABELS.get(PayType(t), t), "amount": a}
            for t, a in sorted(by_pay.items(), key=lambda x: -x[1])
        ],
    }
