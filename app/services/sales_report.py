from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any

PAID_STATUSES = {'paid', 'approved', 'completed'}


def _money(value: int | float | None) -> str:
    return f"{int(value or 0):,}"


def _display_text(value: Any) -> str:
    raw = str(value if value is not None else '-')
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        if any('\u0600' <= ch <= '\u06ff' for ch in raw):
            return get_display(arabic_reshaper.reshape(raw))
    except Exception:
        pass
    return raw


async def collect_sales_report(start_dt: datetime, end_dt: datetime) -> dict[str, Any]:
    """Collect completed sales and accounting-friendly summaries for a period."""
    from sqlalchemy import select
    from app.database.models import Order, Plan, User
    from app.database.session import SessionLocal

    async with SessionLocal() as session:
        orders = (
            await session.execute(
                select(Order)
                .where(
                    Order.status.in_(PAID_STATUSES),
                    Order.created_at >= start_dt,
                    Order.created_at < end_dt,
                )
                .order_by(Order.created_at.asc(), Order.id.asc())
            )
        ).scalars().all()
        user_ids = sorted({int(o.user_id) for o in orders if o.user_id})
        plan_ids = sorted({int(o.plan_id) for o in orders if o.plan_id})
        users = {u.id: u for u in (await session.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()} if user_ids else {}
        plans = {p.id: p for p in (await session.execute(select(Plan).where(Plan.id.in_(plan_ids)))).scalars().all()} if plan_ids else {}

    rows: list[dict[str, Any]] = []
    plan_stats: dict[str, dict[str, Any]] = {}
    payment_stats: dict[str, dict[str, Any]] = {}
    daily_sales: dict[str, int] = defaultdict(int)
    total_revenue = 0

    for order in orders:
        amount = int(order.amount_irt or 0)
        total_revenue += amount
        user = users.get(order.user_id)
        plan = plans.get(order.plan_id)
        user_name = (user.full_name or user.username or str(user.telegram_id)) if user else f'User #{order.user_id}'
        if plan:
            plan_title = plan.title or f'Plan #{plan.id}'
            volume_gb = int(plan.volume_gb or 0)
            duration_days = int(plan.duration_days or 0)
        elif order.plan_id:
            plan_title = f'Deleted plan #{order.plan_id}'
            volume_gb = 0
            duration_days = 0
        else:
            plan_title = 'Wallet / Custom sale'
            volume_gb = 0
            duration_days = 0

        payment = str(order.payment_method or '-').strip() or '-'
        created_at = order.created_at or start_dt
        daily_sales[created_at.date().isoformat()] += amount

        bucket = plan_stats.setdefault(plan_title, {
            'plan': plan_title, 'count': 0, 'revenue': 0,
            'volume_gb': volume_gb, 'duration_days': duration_days,
        })
        bucket['count'] += 1
        bucket['revenue'] += amount

        pay_bucket = payment_stats.setdefault(payment, {'payment': payment, 'count': 0, 'revenue': 0})
        pay_bucket['count'] += 1
        pay_bucket['revenue'] += amount

        rows.append({
            'order': f'#{order.id}',
            'date': created_at.strftime('%Y-%m-%d %H:%M'),
            'user': user_name,
            'plan': plan_title,
            'payment': payment,
            'status': order.status or '-',
            'amount_irt': amount,
            'amount': f'{_money(amount)} Toman',
        })

    days = max(1, (end_dt.date() - start_dt.date()).days)
    daily = []
    for index in range(days):
        day = (start_dt + timedelta(days=index)).date()
        daily.append({'date': day.isoformat(), 'label': day.strftime('%b %d'), 'sales': int(daily_sales.get(day.isoformat(), 0))})

    plan_summary = sorted(plan_stats.values(), key=lambda item: (-int(item['revenue']), -int(item['count']), item['plan']))
    payment_summary = sorted(payment_stats.values(), key=lambda item: (-int(item['revenue']), item['payment']))
    avg_order = int(total_revenue / len(rows)) if rows else 0
    return {
        'title': 'D BOT 30-Day Sales Accounting Report',
        'range_label': f"{start_dt.date().isoformat()} to {(end_dt - timedelta(seconds=1)).date().isoformat()}",
        'total_revenue': int(total_revenue),
        'order_count': len(rows),
        'avg_order': avg_order,
        'rows': rows,
        'plan_summary': plan_summary,
        'payment_summary': payment_summary,
        'daily': daily,
    }


def build_accounting_sales_pdf(payload: dict[str, Any]) -> bytes:
    """Create a dark accounting-style PDF with KPI cards, 3-day chart and detailed tables."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    page_w, page_h = landscape(A4)
    margin = 12 * mm
    content_w = page_w - 2 * margin
    font_name, bold_name = 'Helvetica', 'Helvetica-Bold'
    normal = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    bold = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    if os.path.exists(normal):
        try:
            pdfmetrics.registerFont(TTFont('DBotReport', normal)); font_name = 'DBotReport'
        except Exception:
            pass
    if os.path.exists(bold):
        try:
            pdfmetrics.registerFont(TTFont('DBotReportBold', bold)); bold_name = 'DBotReportBold'
        except Exception:
            pass

    navy = colors.HexColor('#06111f'); panel = colors.HexColor('#0b1a2d'); panel2 = colors.HexColor('#10233b')
    line = colors.HexColor('#28425f'); blue = colors.HexColor('#72aefc'); blue2 = colors.HexColor('#3f7fd8')
    green = colors.HexColor('#47c59a'); text = colors.HexColor('#edf5ff'); muted = colors.HexColor('#9fb2ca'); amber = colors.HexColor('#e2b86b')

    buff = BytesIO(); c = canvas.Canvas(buff, pagesize=(page_w, page_h)); c.setTitle(str(payload.get('title') or 'D BOT Sales Report'))
    range_label = str(payload.get('range_label') or '-')
    total = int(payload.get('total_revenue') or 0); count = int(payload.get('order_count') or 0); avg = int(payload.get('avg_order') or 0)
    plans = list(payload.get('plan_summary') or []); payments = list(payload.get('payment_summary') or []); daily = list(payload.get('daily') or []); rows = list(payload.get('rows') or [])

    def fit(value: Any, n: int) -> str:
        raw = str(value if value is not None else '-')
        return raw if len(raw) <= n else raw[:max(1, n-1)] + '…'

    def bg() -> None:
        c.setFillColor(navy); c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

    def header(title: str, subtitle: str, page_no: int) -> float:
        bg(); c.setFillColor(panel); c.roundRect(margin, page_h-31*mm, content_w, 20*mm, 4*mm, fill=1, stroke=0)
        c.setStrokeColor(line); c.roundRect(margin, page_h-31*mm, content_w, 20*mm, 4*mm, fill=0, stroke=1)
        c.setFillColor(text); c.setFont(bold_name, 16); c.drawString(margin+6*mm, page_h-19*mm, _display_text(title))
        c.setFillColor(muted); c.setFont(font_name, 8.5); c.drawString(margin+6*mm, page_h-25*mm, _display_text(subtitle))
        c.drawRightString(page_w-margin-6*mm, page_h-19*mm, datetime.utcnow().strftime('Generated %Y-%m-%d %H:%M UTC'))
        c.setStrokeColor(line); c.line(margin, 9*mm, page_w-margin, 9*mm); c.setFont(font_name, 7.5)
        c.drawString(margin, 5.2*mm, 'D BOT automated accounting report'); c.drawRightString(page_w-margin, 5.2*mm, f'Page {page_no}')
        return page_h-38*mm

    def kpi(x, y, w, label, value, accent):
        c.setFillColor(panel); c.roundRect(x,y,w,15*mm,3*mm,fill=1,stroke=0); c.setStrokeColor(line); c.roundRect(x,y,w,15*mm,3*mm,fill=0,stroke=1)
        c.setFillColor(accent); c.roundRect(x+3*mm,y+3*mm,2.2*mm,9*mm,1*mm,fill=1,stroke=0)
        c.setFillColor(muted); c.setFont(font_name,7.5); c.drawString(x+8*mm,y+9.5*mm,_display_text(label))
        c.setFillColor(text); c.setFont(bold_name,11); c.drawString(x+8*mm,y+4.2*mm,_display_text(fit(value,34)))

    # Page 1: accounting overview and 3-day revenue buckets.
    page = 1; y = header('D BOT 30-Day Sales Accounting Report', f'Period: {range_label}', page)
    gap=4*mm; cw=(content_w-3*gap)/4; cy=y-16*mm
    kpi(margin,cy,cw,'Total revenue',f'{_money(total)} Toman',blue); kpi(margin+cw+gap,cy,cw,'Completed sales',str(count),green)
    kpi(margin+2*(cw+gap),cy,cw,'Average order',f'{_money(avg)} Toman',amber); kpi(margin+3*(cw+gap),cy,cw,'Plans sold',str(len(plans)),blue2)

    chart_x=margin; chart_y=28*mm; chart_w=content_w*.61; chart_h=72*mm
    c.setFillColor(panel); c.roundRect(chart_x,chart_y,chart_w,chart_h,3*mm,fill=1,stroke=0); c.setStrokeColor(line); c.roundRect(chart_x,chart_y,chart_w,chart_h,3*mm,fill=0,stroke=1)
    c.setFillColor(text); c.setFont(bold_name,9.5); c.drawString(chart_x+5*mm,chart_y+chart_h-8*mm,'Revenue trend - 3 day buckets')
    buckets=[]
    for i in range(0,len(daily),3):
        chunk=daily[i:i+3]
        if chunk:
            label=f"{chunk[0].get('label','-')} - {chunk[-1].get('label','-')}" if len(chunk)>1 else str(chunk[0].get('label','-'))
            buckets.append({'label':label,'sales':sum(int(x.get('sales') or 0) for x in chunk)})
    buckets=buckets[-10:]; maxv=max([int(x['sales']) for x in buckets]+[1]); px=chart_x+10*mm; py=chart_y+17*mm; pw=chart_w-17*mm; ph=chart_h-31*mm
    c.setStrokeColor(colors.HexColor('#213750'))
    for gi in range(5):
        gy=py+ph*gi/4; c.line(px,gy,px+pw,gy)
    if buckets:
        slot=pw/len(buckets); bw=max(3*mm,min(11*mm,slot*.55))
        for i,item in enumerate(buckets):
            val=int(item['sales']); bh=(val/maxv)*(ph-4*mm); bx=px+i*slot+(slot-bw)/2
            c.setFillColor(blue2); c.roundRect(bx,py,bw,max(1,bh),1.2*mm,fill=1,stroke=0)
            c.setFillColor(muted); c.setFont(font_name,5.7); c.saveState(); c.translate(bx+bw/2,py-1.8*mm); c.rotate(28); c.drawCentredString(0,0,fit(item['label'],16)); c.restoreState()
            if val:
                c.setFillColor(text); c.setFont(font_name,5.8); c.drawCentredString(bx+bw/2,py+bh+2*mm,_money(val))
    else:
        c.setFillColor(muted); c.setFont(font_name,9); c.drawCentredString(chart_x+chart_w/2,chart_y+chart_h/2,'No completed sales in this period')

    sx=chart_x+chart_w+gap; sw=content_w-chart_w-gap
    c.setFillColor(panel); c.roundRect(sx,chart_y,sw,chart_h,3*mm,fill=1,stroke=0); c.setStrokeColor(line); c.roundRect(sx,chart_y,sw,chart_h,3*mm,fill=0,stroke=1)
    c.setFillColor(text); c.setFont(bold_name,9.5); c.drawString(sx+5*mm,chart_y+chart_h-8*mm,'Top plans by revenue')
    sy=chart_y+chart_h-16*mm; c.setFont(font_name,7.1)
    for idx,item in enumerate(plans[:8],1):
        c.setFillColor(panel2 if idx%2 else panel); c.roundRect(sx+4*mm,sy-6.5*mm,sw-8*mm,8*mm,1.5*mm,fill=1,stroke=0)
        c.setFillColor(text); c.drawString(sx+7*mm,sy-2*mm,_display_text(f'{idx}. {fit(item.get("plan"),27)}'))
        c.setFillColor(muted); c.drawRightString(sx+sw-7*mm,sy-2*mm,_display_text(f'{item.get("count",0)} sales | {_money(item.get("revenue"))} T')); sy-=8.6*mm
    if not plans:
        c.setFillColor(muted); c.drawString(sx+6*mm,sy,'No plan sales found.')

    # Page 2: plan and payment totals.
    c.showPage(); page+=1; y=header('Accounting Summary',f'Period: {range_label}',page)
    cols=[74*mm,22*mm,30*mm,31*mm,31*mm,40*mm]; heads=['Plan','Sales','Volume','Duration','Share','Revenue']; tw=sum(cols)
    def summary_header(ypos):
        c.setFillColor(blue2); c.roundRect(margin,ypos-7*mm,tw,8*mm,1.8*mm,fill=1,stroke=0); c.setFillColor(colors.white); c.setFont(bold_name,7.2); x=margin
        for i,h in enumerate(heads): c.drawString(x+2*mm,ypos-4.4*mm,h); x+=cols[i]
        return ypos-8.5*mm
    c.setFillColor(text); c.setFont(bold_name,10); c.drawString(margin,y,'Sales by plan'); y=summary_header(y-7*mm); c.setFont(font_name,7.1)
    plan_rows=plans or [{'plan':'No completed sales','count':0,'volume_gb':0,'duration_days':0,'revenue':0}]
    for idx,item in enumerate(plan_rows):
        if y<38*mm:
            c.showPage(); page+=1; y=header('Accounting Summary - Plans',f'Period: {range_label}',page)-4*mm; y=summary_header(y); c.setFont(font_name,7.1)
        share=(int(item.get('revenue') or 0)/total*100) if total else 0
        vals=[fit(item.get('plan'),38),str(item.get('count',0)),f"{item.get('volume_gb',0)} GB",f"{item.get('duration_days',0)} days",f'{share:.1f}%',f"{_money(item.get('revenue'))} Toman"]
        c.setFillColor(panel2 if idx%2==0 else panel); c.rect(margin,y-7.5*mm,tw,7.5*mm,fill=1,stroke=0); c.setFillColor(text); x=margin
        for j,val in enumerate(vals): c.drawString(x+2*mm,y-5*mm,_display_text(val)); x+=cols[j]
        y-=7.5*mm
    y-=6*mm
    if y<55*mm: c.showPage(); page+=1; y=header('Accounting Summary - Payments',f'Period: {range_label}',page)
    c.setFillColor(text); c.setFont(bold_name,10); c.drawString(margin,y,'Sales by payment method'); y-=7*mm
    pcols=[86*mm,28*mm,45*mm,45*mm]; pheads=['Payment method','Sales','Share','Revenue']; ptw=sum(pcols)
    c.setFillColor(blue2); c.roundRect(margin,y-7*mm,ptw,8*mm,1.8*mm,fill=1,stroke=0); c.setFillColor(colors.white); c.setFont(bold_name,7.2); x=margin
    for i,h in enumerate(pheads): c.drawString(x+2*mm,y-4.4*mm,h); x+=pcols[i]
    y-=8.5*mm; c.setFont(font_name,7.1)
    for idx,item in enumerate(payments or [{'payment':'-','count':0,'revenue':0}]):
        share=(int(item.get('revenue') or 0)/total*100) if total else 0; vals=[fit(item.get('payment'),45),str(item.get('count',0)),f'{share:.1f}%',f"{_money(item.get('revenue'))} Toman"]
        c.setFillColor(panel2 if idx%2==0 else panel); c.rect(margin,y-7.5*mm,ptw,7.5*mm,fill=1,stroke=0); c.setFillColor(text); x=margin
        for j,val in enumerate(vals): c.drawString(x+2*mm,y-5*mm,_display_text(val)); x+=pcols[j]
        y-=7.5*mm

    # Detail pages.
    detail_cols=[20*mm,34*mm,47*mm,69*mm,42*mm,43*mm]; detail_heads=['Order','Date','User','Plan','Payment','Amount']; dtw=sum(detail_cols)
    def detail_page(page_no):
        yy=header('Completed Sales Detail',f'Period: {range_label}',page_no)-4*mm; c.setFillColor(blue2); c.roundRect(margin,yy-7*mm,dtw,8*mm,1.8*mm,fill=1,stroke=0); c.setFillColor(colors.white); c.setFont(bold_name,7.2); x=margin
        for i,h in enumerate(detail_heads): c.drawString(x+2*mm,yy-4.4*mm,h); x+=detail_cols[i]
        return yy-8.5*mm
    c.showPage(); page+=1; y=detail_page(page); c.setFont(font_name,7.0)
    detail_rows=rows or [{'order':'-','date':'-','user':'No completed sales','plan':'-','payment':'-','amount':'0 Toman'}]
    for idx,row in enumerate(detail_rows):
        if y<18*mm:
            c.showPage(); page+=1; y=detail_page(page); c.setFont(font_name,7.0)
        vals=[fit(row.get('order'),12),fit(row.get('date'),20),fit(row.get('user'),28),fit(row.get('plan'),42),fit(row.get('payment'),24),fit(row.get('amount'),24)]
        c.setFillColor(panel2 if idx%2==0 else panel); c.rect(margin,y-7.5*mm,dtw,7.5*mm,fill=1,stroke=0); c.setFillColor(text); x=margin
        for j,val in enumerate(vals): c.drawString(x+2*mm,y-5*mm,_display_text(val)); x+=detail_cols[j]
        y-=7.5*mm

    c.save(); return buff.getvalue()
