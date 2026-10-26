"""Shartnoma (DOCX, shablon asosida) va to'lov kvitansiyasi (chop etiladigan HTML)."""
import html
import io
from datetime import date
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "shartnoma.docx"

MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr",
          "noyabr", "dekabr"]


def money(n) -> str:
    return f"{int(n):,}".replace(",", " ") + " so‘m"


def num(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def dmy(d) -> str:
    return d.strftime("%d.%m.%Y") if d else ""


def long_date(d: date) -> str:
    return f"{d.year}-yil {d.day}-{MONTHS[d.month - 1]}"


_ONES = ["", "bir", "ikki", "uch", "to‘rt", "besh", "olti", "yetti", "sakkiz", "to‘qqiz"]
_TENS = ["", "o‘n", "yigirma", "o‘ttiz", "qirq", "ellik", "oltmish", "yetmish", "sakson", "to‘qson"]
_SCALES = [(10 ** 12, "trillion"), (10 ** 9, "milliard"), (10 ** 6, "million"), (10 ** 3, "ming")]


def _tri(n):
    out = []
    if n >= 100:
        out += [_ONES[n // 100], "yuz"]
        n %= 100
    if n >= 10:
        out.append(_TENS[n // 10])
        n %= 10
    if n:
        out.append(_ONES[n])
    return out


def words(n: int) -> str:
    """Summani so'z bilan: 412500000 → "to‘rt yuz o‘n ikki million besh yuz ming"."""
    n = int(n)
    if n == 0:
        return "nol"
    out = []
    for v, name in _SCALES:
        if n >= v:
            out += _tri(n // v) + [name]
            n %= v
    out += _tri(n)
    return " ".join(w for w in out if w)


def render_contract(c: dict, client: dict, st: dict) -> bytes:
    from docxtpl import DocxTemplate
    comp = st["company"]
    sched = []
    for it in c["schedule"]:
        sched.append({"n": "Boshlang‘ich" if it["n"] == 0 else it["n"], "date": dmy(it["due_date"]),
                      "amount": num(it["amount"])})
    rest = c["price"] - c["down_payment"]
    ctx = {
        "number": c["number"], "date": dmy(c["contract_date"]), "date_long": long_date(c["contract_date"]),
        "city": comp.get("city") or "", "company": comp, "object": comp.get("object") or "",
        "client": {
            "name": client.get("full_name") or "", "passport": client.get("passport") or "________",
            "passport_issued": client.get("passport_issued") or "________________",
            "pinfl": client.get("pinfl") or "______________", "address": client.get("address") or "________________",
            "phone": client.get("phone") or "", "birth_date": dmy(client.get("birth_date")),
        },
        "unit": {"id": c["unit_id"], "block": c["block"], "floor": c["floor"], "n": c["unit_n"],
                 "rooms": c["rooms"], "area": f"{c['area']:g}".replace(".", ",")},
        "price": num(c["price"]), "price_words": words(c["price"]),
        "down": num(c["down_payment"]), "down_words": words(c["down_payment"]),
        "rest": num(rest), "months": c["months"], "markup": f"{c['markup_pct']:g}".replace(".", ","),
        "total": num(c["total"]), "total_words": words(c["total"]),
        "installment_total": num(c["total"] - c["down_payment"]),
        "monthly": num(next((i["amount"] for i in c["schedule"] if i["n"] == 1), 0)),
        "first_due": dmy(next((i["due_date"] for i in c["schedule"] if i["n"] == 1), None)),
        "last_due": dmy(c["schedule"][-1]["due_date"]) if c["schedule"] else "",
        "schedule": sched, "installment": c["months"] > 0,
    }
    tpl = DocxTemplate(str(TEMPLATE))
    tpl.render(ctx, autoescape=True)
    buf = io.BytesIO()
    tpl.save(buf)
    return buf.getvalue()


def receipt_html(p: dict, c: dict, st: dict, methods: dict) -> str:
    comp = st["company"]
    e = html.escape
    status = "Bekor qilingan to‘lov" if p.get("deleted_at") else ""
    one = f"""
    <section class="r">
      <header><div><b>{e(comp.get('name') or '')}</b><br><small>{e(comp.get('address') or '')}
        {(' · ' + e(comp['phone'])) if comp.get('phone') else ''}</small></div>
        <div class="no">KVITANSIYA № {p['id']}<br><small>{dmy(p['paid_at'])}</small></div></header>
      {f'<p class="void">{status}</p>' if status else ''}
      <table>
        <tr><th>To‘lovchi</th><td>{e(c['client_name'])}</td></tr>
        <tr><th>Shartnoma</th><td>№ {e(c['number'])} ({dmy(c['contract_date'])}), uy {e(c['unit_id'])}</td></tr>
        <tr><th>Summa</th><td class="sum">{money(p['amount'])}</td></tr>
        <tr><th>So‘z bilan</th><td>{e(words(p['amount']).capitalize())} so‘m</td></tr>
        <tr><th>To‘lov usuli</th><td>{e(methods.get(p['method'], p['method']))}</td></tr>
        {f"<tr><th>Izoh</th><td>{e(p['note'])}</td></tr>" if p.get('note') else ''}
        <tr><th>Jami to‘langan</th><td>{money(c['paid'])} / {money(c['total'])}</td></tr>
        <tr><th>Qolgan qarz</th><td>{money(c['remaining'])}</td></tr>
      </table>
      <footer><span>Qabul qildi: {e(p.get('created_by_name') or '')} ____________</span>
        <span>To‘lovchi: ____________</span></footer>
    </section>"""
    return f"""<!doctype html><html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kvitansiya № {p['id']}</title>
<style>
body{{font:14px/1.45 Arial,Helvetica,sans-serif;color:#111;margin:0;background:#eef1f5}}
.wrap{{max-width:760px;margin:24px auto;padding:0 16px}}
.r{{background:#fff;border:1px solid #cfd6df;border-radius:8px;padding:22px 26px;margin-bottom:18px}}
header{{display:flex;justify-content:space-between;gap:16px;border-bottom:2px solid #111;padding-bottom:10px;margin-bottom:12px}}
.no{{text-align:right;font-weight:700}}
small{{color:#555;font-weight:400}}
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;width:34%;color:#444;font-weight:600;padding:6px 8px 6px 0;vertical-align:top}}
td{{padding:6px 0;border-bottom:1px dotted #bbb}}
.sum{{font-size:18px;font-weight:700}}
.void{{color:#b00020;font-weight:700;text-transform:uppercase}}
footer{{display:flex;justify-content:space-between;gap:16px;margin-top:26px;flex-wrap:wrap}}
.cut{{border-top:1px dashed #888;margin:6px 0 18px;text-align:center;color:#888;font-size:12px}}
.bar{{display:flex;gap:10px;justify-content:flex-end;margin-bottom:12px}}
button{{font:inherit;padding:8px 16px;border-radius:8px;border:0;background:#2448a6;color:#fff;cursor:pointer}}
@media print{{body{{background:#fff}}.bar{{display:none}}.wrap{{margin:0;max-width:none}}.r{{border-radius:0}}}}
</style></head><body><div class="wrap">
<div class="bar"><button onclick="print()">Chop etish</button></div>
{one}<div class="cut">✂ kesish chizig‘i (ikkinchi nusxa kompaniyada qoladi)</div>{one}
</div></body></html>"""
