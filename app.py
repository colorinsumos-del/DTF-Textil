
import os
import secrets
import hashlib
import json
from pathlib import Path
from datetime import date, datetime
from io import BytesIO
from urllib.parse import urlparse

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import (
    create_engine, Column, Integer, Float, String, Date, DateTime, Boolean, Text
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import IntegrityError

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)



# =========================================================
# CONFIGURACION GENERAL
# =========================================================

st.set_page_config(
    page_title="DTF Control ROI",
    page_icon="🖨️",
    layout="wide",
    initial_sidebar_state="expanded"
)

APP_NAME = "DTF Control ROI"
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASS = "admin123"

Base = declarative_base()


def get_database_url():
    """
    Railway puede usar DATABASE_URL si agregas PostgreSQL.
    Si no existe, usa SQLite local.
    Nota: SQLite en Railway necesita volumen persistente para no perder datos en redeploys.
    """
    url = os.getenv("DATABASE_URL", "").strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

    if url:
        return url

    data_dir = Path(os.getenv("DATA_DIR", "."))
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{data_dir / 'dtf_roi.db'}"


DATABASE_URL = get_database_url()
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


# =========================================================
# MODELOS
# =========================================================

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    name = Column(String(120), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(30), nullable=False, default="socio")  # admin, socio, empleada
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(80), primary_key=True)
    value = Column(Text, nullable=False)


class Sale(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True)
    sale_date = Column(Date, nullable=False)
    meters = Column(Float, nullable=False)
    notes = Column(Text, default="")
    created_by = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True)
    expense_date = Column(Date, nullable=False)
    category = Column(String(80), nullable=False, default="Servicio técnico")
    amount = Column(Float, nullable=False)
    paid_by = Column(String(80), nullable=False, default="Empresa")
    platform = Column(String(80), default="")
    reference = Column(String(120), default="")
    notes = Column(Text, default="")
    created_by = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    payment_date = Column(Date, nullable=False)
    partner = Column(String(80), nullable=False, default="Javier")
    amount = Column(Float, nullable=False)
    platform = Column(String(80), nullable=False, default="PayPal")
    reference = Column(String(120), default="")
    notes = Column(Text, default="")
    created_by = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class MonthlyClose(Base):
    __tablename__ = "monthly_closes"

    id = Column(Integer, primary_key=True)
    period_key = Column(String(7), unique=True, nullable=False)  # YYYY-MM
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    total_meters = Column(Float, nullable=False, default=0)
    revenue = Column(Float, nullable=False, default=0)
    production_cost = Column(Float, nullable=False, default=0)
    deductible_expenses = Column(Float, nullable=False, default=0)
    net_profit_before_roi = Column(Float, nullable=False, default=0)
    roi_recovery = Column(Float, nullable=False, default=0)
    distributable_profit = Column(Float, nullable=False, default=0)
    partner_share = Column(Float, nullable=False, default=0)
    javier_credit = Column(Float, nullable=False, default=0)
    rene_credit = Column(Float, nullable=False, default=0)
    notes = Column(Text, default="")
    created_by = Column(String(80), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    action_date = Column(DateTime, default=datetime.utcnow)
    username = Column(String(80), nullable=False)
    module = Column(String(80), nullable=False)
    action = Column(String(80), nullable=False)
    record_id = Column(Integer, nullable=True)
    before_data = Column(Text, default="")
    after_data = Column(Text, default="")
    reason = Column(Text, default="")


# =========================================================
# SEGURIDAD
# =========================================================

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"{salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, digest = stored_hash.split("$", 1)
        check = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        return secrets.compare_digest(check, digest)
    except Exception:
        return False


# =========================================================
# DB INIT
# =========================================================

def init_db():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            admin = User(
                username=DEFAULT_ADMIN_USER,
                name="Administrador",
                password_hash=hash_password(DEFAULT_ADMIN_PASS),
                role="admin",
                active=True
            )
            db.add(admin)

        defaults = {
            "price_per_meter": "6.00",
            "cost_per_meter": "2.00",
            "equipment_investment": "0.00",
            "roi_recovery_percent": "20.00",
            "partner_1_name": "Rene",
            "partner_2_name": "Javier",
            "opening_debt_javier": "0.00",
            "opening_debt_notes": "Deuda acumulada previa al sistema.",
        }

        for key, value in defaults.items():
            if not db.query(Setting).filter(Setting.key == key).first():
                db.add(Setting(key=key, value=value))

        db.commit()
    finally:
        db.close()


def get_setting(key: str, default: str = "") -> str:
    db = SessionLocal()
    try:
        item = db.query(Setting).filter(Setting.key == key).first()
        return item.value if item else default
    finally:
        db.close()


def set_setting(key: str, value: str):
    db = SessionLocal()
    try:
        item = db.query(Setting).filter(Setting.key == key).first()
        if item:
            item.value = str(value)
        else:
            db.add(Setting(key=key, value=str(value)))
        db.commit()
    finally:
        db.close()


def get_money_setting(key: str, default: float = 0.0) -> float:
    try:
        return float(get_setting(key, str(default)))
    except Exception:
        return default


# =========================================================
# LOGIN
# =========================================================

def login_user(username, password):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username.strip()).first()
        if user and user.active and verify_password(password, user.password_hash):
            return {
                "id": user.id,
                "username": user.username,
                "name": user.name,
                "role": user.role
            }
        return None
    finally:
        db.close()


def require_login():
    if "user" not in st.session_state:
        st.session_state.user = None

    if st.session_state.user:
        return st.session_state.user

    st.markdown("""
    <style>
    .login-card {
        max-width: 460px;
        margin: 60px auto;
        padding: 28px;
        border-radius: 22px;
        background: white;
        box-shadow: 0 12px 40px rgba(15, 23, 42, .10);
        border: 1px solid #eef2f7;
    }
    </style>
    """, unsafe_allow_html=True)

    st.title("🖨️ DTF Control ROI")
    st.caption("Control de metros vendidos, utilidad, socios y recuperación del equipo.")

    with st.form("login_form"):
        username = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")
        submit = st.form_submit_button("Ingresar", width="stretch")

    if submit:
        user = login_user(username, password)
        if user:
            st.session_state.user = user
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrectos.")

    st.info("Primer acceso: usuario **admin**, clave **admin123**. Cambia esa clave apenas entres.")
    st.stop()


# =========================================================
# CALCULOS
# =========================================================

def sales_dataframe(start=None, end=None):
    db = SessionLocal()
    try:
        q = db.query(Sale)
        if start:
            q = q.filter(Sale.sale_date >= start)
        if end:
            q = q.filter(Sale.sale_date <= end)
        rows = q.order_by(Sale.sale_date.desc(), Sale.id.desc()).all()
        return pd.DataFrame([
            {
                "ID": r.id,
                "Fecha": r.sale_date,
                "Metros": float(r.meters),
                "Notas": r.notes or "",
                "Creado por": r.created_by,
                "Creado": r.created_at,
            }
            for r in rows
        ])
    finally:
        db.close()



def expenses_dataframe(start=None, end=None):
    db = SessionLocal()
    try:
        q = db.query(Expense)
        if start:
            q = q.filter(Expense.expense_date >= start)
        if end:
            q = q.filter(Expense.expense_date <= end)
        rows = q.order_by(Expense.expense_date.desc(), Expense.id.desc()).all()
        return pd.DataFrame([
            {
                "ID": r.id,
                "Fecha": r.expense_date,
                "Categoría": r.category,
                "Monto": float(r.amount),
                "Pagado por": r.paid_by,
                "Plataforma": r.platform or "",
                "Referencia": r.reference or "",
                "Notas": r.notes or "",
                "Creado por": r.created_by,
                "Creado": r.created_at,
            }
            for r in rows
        ])
    finally:
        db.close()


def payments_dataframe(partner="Javier"):
    db = SessionLocal()
    try:
        q = db.query(Payment)
        if partner:
            q = q.filter(Payment.partner == partner)
        rows = q.order_by(Payment.payment_date.desc(), Payment.id.desc()).all()
        return pd.DataFrame([
            {
                "ID": r.id,
                "Fecha": r.payment_date,
                "Socio": r.partner,
                "Monto": float(r.amount),
                "Plataforma": r.platform,
                "Referencia": r.reference or "",
                "Notas": r.notes or "",
                "Creado por": r.created_by,
                "Creado": r.created_at,
            }
            for r in rows
        ])
    finally:
        db.close()




def get_sale_by_id(sale_id: int):
    db = SessionLocal()
    try:
        s = db.query(Sale).filter(Sale.id == int(sale_id)).first()
        if not s:
            return None
        return {
            "id": s.id,
            "sale_date": s.sale_date,
            "meters": float(s.meters),
            "notes": s.notes or "",
            "created_by": s.created_by,
            "created_at": s.created_at,
        }
    finally:
        db.close()


def get_expense_by_id(expense_id: int):
    db = SessionLocal()
    try:
        e = db.query(Expense).filter(Expense.id == int(expense_id)).first()
        if not e:
            return None
        return {
            "id": e.id,
            "expense_date": e.expense_date,
            "category": e.category,
            "amount": float(e.amount),
            "paid_by": e.paid_by,
            "platform": e.platform or "",
            "reference": e.reference or "",
            "notes": e.notes or "",
            "created_by": e.created_by,
            "created_at": e.created_at,
        }
    finally:
        db.close()


def get_payment_by_id(payment_id: int):
    db = SessionLocal()
    try:
        p = db.query(Payment).filter(Payment.id == int(payment_id)).first()
        if not p:
            return None
        return {
            "id": p.id,
            "payment_date": p.payment_date,
            "partner": p.partner,
            "amount": float(p.amount),
            "platform": p.platform,
            "reference": p.reference or "",
            "notes": p.notes or "",
            "created_by": p.created_by,
            "created_at": p.created_at,
        }
    finally:
        db.close()


def closes_dataframe():
    db = SessionLocal()
    try:
        rows = db.query(MonthlyClose).order_by(MonthlyClose.period_key.desc()).all()
        return pd.DataFrame([
            {
                "ID": r.id,
                "Periodo": r.period_key,
                "Desde": r.start_date,
                "Hasta": r.end_date,
                "Metros": float(r.total_meters),
                "Venta bruta": float(r.revenue),
                "Costo producción": float(r.production_cost),
                "Gastos deducibles": float(r.deductible_expenses),
                "Utilidad antes ROI": float(r.net_profit_before_roi),
                "ROI equipo": float(r.roi_recovery),
                "Utilidad a repartir": float(r.distributable_profit),
                "Cada socio": float(r.partner_share),
                "Abono/cargo Javier": float(r.javier_credit),
                "Abono/cargo Rene": float(r.rene_credit),
                "Notas": r.notes or "",
                "Creado por": r.created_by,
                "Creado": r.created_at,
            }
            for r in rows
        ])
    finally:
        db.close()


def javier_account_summary():
    opening = get_money_setting("opening_debt_javier", 0.0)
    df_payments = payments_dataframe("Javier")
    df_closes = closes_dataframe()

    total_payments = 0.0 if df_payments.empty else float(df_payments["Monto"].sum())
    total_monthly_credits = 0.0 if df_closes.empty else float(df_closes["Abono/cargo Javier"].sum())
    balance = opening + total_monthly_credits - total_payments

    return {
        "opening": opening,
        "monthly_credits": total_monthly_credits,
        "payments": total_payments,
        "balance": balance
    }



def calculate_report(df: pd.DataFrame, expenses_df: pd.DataFrame = None):
    price = get_money_setting("price_per_meter", 6.0)
    cost = get_money_setting("cost_per_meter", 2.0)
    investment = get_money_setting("equipment_investment", 0.0)
    roi_percent = get_money_setting("roi_recovery_percent", 20.0)

    total_meters = 0.0 if df.empty else float(df["Metros"].sum())
    revenue = total_meters * price
    production_cost = total_meters * cost
    deductible_expenses = 0.0 if expenses_df is None or expenses_df.empty else float(expenses_df["Monto"].sum())

    # Utilidad real del corte después de costo por metro y gastos deducibles del equipo.
    net_profit_before_roi = revenue - production_cost - deductible_expenses

    # Recuperación del equipo: porcentaje de la utilidad real después de gastos.
    planned_roi = max(net_profit_before_roi, 0) * (roi_percent / 100.0)
    recovered_before = get_recovered_total_from_closed_months()
    remaining_before = max(investment - recovered_before, 0)
    roi_recovery = max(min(planned_roi, remaining_before), 0)

    distributable_profit = net_profit_before_roi - roi_recovery
    partner_share = distributable_profit / 2 if distributable_profit > 0 else 0

    recovered_total_after = min(recovered_before + roi_recovery, investment) if investment > 0 else 0
    roi_progress = (recovered_total_after / investment * 100) if investment > 0 else 0

    return {
        "total_meters": total_meters,
        "revenue": revenue,
        "production_cost": production_cost,
        "deductible_expenses": deductible_expenses,
        "gross_profit": revenue - production_cost,
        "net_profit_before_roi": net_profit_before_roi,
        "roi_recovery": roi_recovery,
        "distributable_profit": distributable_profit,
        "partner_share": partner_share,
        "investment": investment,
        "roi_percent": roi_percent,
        "recovered_before": recovered_before,
        "recovered_total_after": recovered_total_after,
        "roi_progress": roi_progress,
        "price": price,
        "cost": cost,
    }


def get_recovered_total_from_closed_months():
    investment = get_money_setting("equipment_investment", 0.0)
    if investment <= 0:
        return 0.0
    db = SessionLocal()
    try:
        recovered = db.query(MonthlyClose).all()
        total = sum(float(r.roi_recovery or 0) for r in recovered)
        return min(total, investment)
    finally:
        db.close()


def get_recovered_total_from_all_sales(exclude_current_df=None):
    """
    Calcula el ROI acumulado históricamente usando la misma regla:
    utilidad por venta * porcentaje de recuperación, limitado por inversión.
    Para evitar doble conteo en el informe actual, excluye los IDs visibles en el corte actual.
    """
    investment = get_money_setting("equipment_investment", 0.0)
    roi_percent = get_money_setting("roi_recovery_percent", 20.0)
    price = get_money_setting("price_per_meter", 6.0)
    cost = get_money_setting("cost_per_meter", 2.0)

    if investment <= 0:
        return 0.0

    exclude_ids = set()
    if exclude_current_df is not None and not exclude_current_df.empty and "ID" in exclude_current_df.columns:
        exclude_ids = set(exclude_current_df["ID"].tolist())

    db = SessionLocal()
    try:
        rows = db.query(Sale).order_by(Sale.sale_date.asc(), Sale.id.asc()).all()
        recovered = 0.0
        for r in rows:
            if r.id in exclude_ids:
                continue
            profit = float(r.meters) * (price - cost)
            recovered += max(profit * (roi_percent / 100.0), 0)
            recovered = min(recovered, investment)
        return recovered
    finally:
        db.close()


def format_usd(value):
    return f"${value:,.2f}"


def audit_log(username, module, action, record_id=None, before=None, after=None, reason=""):
    db = SessionLocal()
    try:
        item = AuditLog(
            username=username,
            module=module,
            action=action,
            record_id=record_id,
            before_data=json.dumps(before or {}, default=str, ensure_ascii=False),
            after_data=json.dumps(after or {}, default=str, ensure_ascii=False),
            reason=reason or ""
        )
        db.add(item)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def audit_dataframe(limit=200):
    db = SessionLocal()
    try:
        rows = db.query(AuditLog).order_by(AuditLog.action_date.desc()).limit(limit).all()
        return pd.DataFrame([
            {
                "ID": r.id,
                "Fecha": r.action_date,
                "Usuario": r.username,
                "Módulo": r.module,
                "Acción": r.action,
                "Registro": r.record_id,
                "Motivo": r.reason,
                "Antes": r.before_data,
                "Después": r.after_data,
            }
            for r in rows
        ])
    finally:
        db.close()


def build_javier_statement_dataframe():
    opening = get_money_setting("opening_debt_javier", 0.0)
    moves = []

    if opening > 0:
        moves.append({
            "Fecha": date.min,
            "Concepto": "Deuda acumulada inicial",
            "Debe": opening,
            "Haber": 0.0,
            "Referencia": "",
            "Notas": get_setting("opening_debt_notes", "Deuda acumulada previa al sistema.")
        })

    closes = closes_dataframe()
    if not closes.empty:
        for _, row in closes.iterrows():
            moves.append({
                "Fecha": row["Hasta"],
                "Concepto": f"Corte mensual {row['Periodo']}",
                "Debe": float(row["Abono/cargo Javier"]),
                "Haber": 0.0,
                "Referencia": str(row["Periodo"]),
                "Notas": str(row["Notas"])
            })

    payments = payments_dataframe("Javier")
    if not payments.empty:
        for _, row in payments.iterrows():
            moves.append({
                "Fecha": row["Fecha"],
                "Concepto": f"Abono recibido por {row['Plataforma']}",
                "Debe": 0.0,
                "Haber": float(row["Monto"]),
                "Referencia": str(row["Referencia"]),
                "Notas": str(row["Notas"])
            })

    if not moves:
        return pd.DataFrame(columns=["Fecha", "Concepto", "Debe", "Haber", "Saldo", "Referencia", "Notas"])

    df = pd.DataFrame(moves)
    df["FechaOrden"] = pd.to_datetime(df["Fecha"].astype(str).replace("0001-01-01", "1900-01-01"))
    df = df.sort_values(["FechaOrden", "Concepto"]).drop(columns=["FechaOrden"]).reset_index(drop=True)
    saldo = 0.0
    saldos = []
    for _, row in df.iterrows():
        saldo += float(row["Debe"]) - float(row["Haber"])
        saldos.append(saldo)
    df["Saldo"] = saldos
    df["Fecha"] = df["Fecha"].apply(lambda x: "Inicial" if str(x) == "0001-01-01" else str(x))
    return df[["Fecha", "Concepto", "Debe", "Haber", "Saldo", "Referencia", "Notas"]]




# =========================================================
# UI COMPONENTES
# =========================================================

def header(title, subtitle=""):
    st.markdown(f"""
    <div style="
        padding: 22px 24px;
        border-radius: 24px;
        background: linear-gradient(135deg, #101b3b 0%, #2a42ed 55%, #027efc 100%);
        color: white;
        margin-bottom: 20px;
        box-shadow: 0 14px 34px rgba(42,66,237,.20);
    ">
        <h1 style="margin:0;font-size:32px;">{title}</h1>
        <p style="margin:6px 0 0 0;opacity:.92;font-size:16px;">{subtitle}</p>
    </div>
    """, unsafe_allow_html=True)


def metric_card(label, value, help_text=None):
    st.metric(label, value, help=help_text)


def sidebar(user):
    st.sidebar.title("🖨️ DTF Control ROI")
    st.sidebar.caption(f"{user['name']} · {user['role'].upper()}")

    allowed_pages = ["Dashboard", "Cargar venta diaria", "Gastos del equipo", "Cuenta Javier", "Informe mensual", "ROI del equipo"]
    if user["role"] == "admin":
        allowed_pages += ["Cierre mensual", "Auditoría", "Usuarios", "Configuración", "Base de datos"]

    page = st.sidebar.radio("Menú", allowed_pages)

    st.sidebar.divider()
    if st.sidebar.button("Cerrar sesión", width="stretch"):
        st.session_state.user = None
        st.rerun()

    return page


# =========================================================
# MODULOS
# =========================================================

def page_dashboard():
    header("Dashboard DTF", "Resumen general del negocio en tiempo real.")

    today = date.today()
    start_month = today.replace(day=1)
    df_month = sales_dataframe(start_month, today)
    expenses_month = expenses_dataframe(start_month, today)
    report = calculate_report(df_month, expenses_month)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metric_card("Metros vendidos este mes", f"{report['total_meters']:,.2f} m")
    with c2:
        metric_card("Venta bruta", format_usd(report["revenue"]))
    with c3:
        metric_card("Costo producción", format_usd(report["production_cost"]))
    with c4:
        metric_card("Utilidad real antes ROI", format_usd(report["net_profit_before_roi"]))

    c5, c6, c7, c8 = st.columns(4)
    with c5:
        metric_card("Gastos deducibles", format_usd(report["deductible_expenses"]))
    with c6:
        metric_card("Apartado ROI del corte", format_usd(report["roi_recovery"]))
    with c7:
        metric_card(get_setting("partner_1_name", "Rene"), format_usd(report["partner_share"]))
    with c8:
        metric_card(get_setting("partner_2_name", "Javier"), format_usd(report["partner_share"]))

    st.subheader("Progreso de recuperación del equipo")
    investment = report["investment"]
    if investment > 0:
        st.progress(min(report["roi_progress"] / 100, 1.0))
        st.caption(
            f"Recuperado estimado: {format_usd(report['recovered_total_after'])} "
            f"de {format_usd(investment)} · {report['roi_progress']:.2f}%"
        )
    else:
        st.warning("Configura el monto de inversión del equipo para activar el seguimiento de ROI.")

    st.subheader("Ventas recientes")
    df_recent = sales_dataframe()
    if df_recent.empty:
        st.info("Todavía no hay ventas cargadas.")
    else:
        st.dataframe(df_recent.head(20), width="stretch", hide_index=True)

    if not df_month.empty:
        chart_df = df_month.copy()
        chart_df["Fecha"] = pd.to_datetime(chart_df["Fecha"])
        daily = chart_df.groupby("Fecha", as_index=False)["Metros"].sum()
        fig = px.bar(daily, x="Fecha", y="Metros", title="Metros vendidos por día")
        st.plotly_chart(fig, width="stretch")


def page_load_sale(user):
    header("Cargar venta diaria", "Registra, edita o elimina los metros DTF vendidos por fecha.")

    price = get_money_setting("price_per_meter", 6.0)
    cost = get_money_setting("cost_per_meter", 2.0)

    tab1, tab2, tab3 = st.tabs(["Registrar venta", "Editar venta", "Eliminar venta"])

    with tab1:
        with st.form("sale_form"):
            c1, c2 = st.columns(2)
            with c1:
                sale_date = st.date_input("Fecha de venta", value=date.today(), key="sale_new_date")
            with c2:
                meters = st.number_input("Metros vendidos", min_value=0.01, step=0.10, format="%.2f", key="sale_new_meters")

            notes = st.text_area("Notas opcionales", placeholder="Ej: venta mostrador, pedido cliente X, rollo completo, etc.", key="sale_new_notes")
            submitted = st.form_submit_button("Guardar venta", width="stretch")

        if submitted:
            db = SessionLocal()
            try:
                sale = Sale(
                    sale_date=sale_date,
                    meters=float(meters),
                    notes=notes.strip(),
                    created_by=user["username"]
                )
                db.add(sale)
                db.commit()
                audit_log(user["username"], "Ventas", "crear", sale.id, after={"fecha": sale_date, "metros": meters, "notas": notes})
                st.success("Venta guardada correctamente.")
                st.rerun()
            finally:
                db.close()

    df_all = sales_dataframe()

    with tab2:
        if df_all.empty:
            st.info("No hay ventas para editar.")
        else:
            options = {
                f"ID {int(row['ID'])} · {row['Fecha']} · {float(row['Metros']):,.2f} m · {row['Notas']}": int(row["ID"])
                for _, row in df_all.iterrows()
            }
            label = st.selectbox("Selecciona venta", list(options.keys()), key="edit_sale_select")
            sale_id = options[label]
            sale = get_sale_by_id(sale_id)
            if sale:
                with st.form(f"edit_sale_form_{sale_id}"):
                    c1, c2 = st.columns(2)
                    with c1:
                        edit_date = st.date_input("Fecha", value=sale["sale_date"], key=f"sale_edit_date_{sale_id}")
                    with c2:
                        edit_meters = st.number_input("Metros", min_value=0.01, value=sale["meters"], step=0.10, format="%.2f", key=f"sale_edit_meters_{sale_id}")
                    edit_notes = st.text_area("Notas", value=sale["notes"], key=f"sale_edit_notes_{sale_id}")
                    save = st.form_submit_button("Guardar cambios", width="stretch")
                if save:
                    db = SessionLocal()
                    try:
                        s = db.query(Sale).filter(Sale.id == int(sale_id)).first()
                        before = {"fecha": s.sale_date, "metros": s.meters, "notas": s.notes}
                        s.sale_date = edit_date
                        s.meters = float(edit_meters)
                        s.notes = edit_notes.strip()
                        db.commit()
                        audit_log(user["username"], "Ventas", "editar", sale_id, before=before, after={"fecha": edit_date, "metros": edit_meters, "notas": edit_notes})
                        st.success("Venta actualizada.")
                        st.rerun()
                    finally:
                        db.close()

    with tab3:
        if user["role"] != "admin":
            st.warning("Solo un administrador puede eliminar ventas.")
        elif df_all.empty:
            st.info("No hay ventas para eliminar.")
        else:
            options = {
                f"ID {int(row['ID'])} · {row['Fecha']} · {float(row['Metros']):,.2f} m · {row['Notas']}": int(row["ID"])
                for _, row in df_all.iterrows()
            }
            label = st.selectbox("Selecciona venta a eliminar", list(options.keys()), key="delete_sale_select")
            sale_id = options[label]
            reason = st.text_area("Motivo de eliminación", key="delete_sale_reason")
            confirm = st.checkbox("Confirmo que quiero eliminar esta venta", key="delete_sale_confirm")
            if st.button("Eliminar venta", width="stretch", type="primary"):
                if not confirm or not reason.strip():
                    st.error("Debes confirmar y escribir un motivo.")
                else:
                    db = SessionLocal()
                    try:
                        s = db.query(Sale).filter(Sale.id == int(sale_id)).first()
                        if s:
                            before = {"fecha": s.sale_date, "metros": s.meters, "notas": s.notes}
                            db.delete(s)
                            db.commit()
                            audit_log(user["username"], "Ventas", "eliminar", sale_id, before=before, reason=reason.strip())
                            st.success("Venta eliminada.")
                            st.rerun()
                    finally:
                        db.close()

    st.info(
        f"Con la configuración actual, cada metro se vende en **{format_usd(price)}** "
        f"y tiene costo de producción de **{format_usd(cost)}**."
    )

    df = sales_dataframe()
    if not df.empty:
        st.subheader("Últimos registros")
        st.dataframe(df.head(30), width="stretch", hide_index=True)


def page_monthly_report():
    header("Informe mensual", "Corte por rango de fechas con utilidad, socios y ROI.")

    today = date.today()
    start_default = today.replace(day=1)

    c1, c2 = st.columns(2)
    with c1:
        start = st.date_input("Desde", value=start_default)
    with c2:
        end = st.date_input("Hasta", value=today)

    if start > end:
        st.error("La fecha inicial no puede ser mayor que la fecha final.")
        return

    df = sales_dataframe(start, end)
    expenses_df = expenses_dataframe(start, end)
    report = calculate_report(df, expenses_df)

    st.subheader("Resumen del corte")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        metric_card("Metros vendidos", f"{report['total_meters']:,.2f} m")
    with c2:
        metric_card("Venta bruta", format_usd(report["revenue"]))
    with c3:
        metric_card("Costo producción", format_usd(report["production_cost"]))
    with c4:
        metric_card("Gastos deducibles", format_usd(report["deductible_expenses"]))
    with c5:
        metric_card("Utilidad real antes ROI", format_usd(report["net_profit_before_roi"]))

    c6, c7, c8 = st.columns(3)
    with c6:
        metric_card(f"ROI equipo ({report['roi_percent']:.2f}%)", format_usd(report["roi_recovery"]))
    with c7:
        metric_card(get_setting("partner_1_name", "Rene"), format_usd(report["partner_share"]))
    with c8:
        metric_card(get_setting("partner_2_name", "Javier"), format_usd(report["partner_share"]))

    st.markdown("### Fórmula aplicada")
    st.code(
        f"""
Venta bruta = metros vendidos × precio por metro
Venta bruta = {report['total_meters']:.2f} × {report['price']:.2f} = {report['revenue']:.2f}

Costo producción = metros vendidos × costo por metro
Costo producción = {report['total_meters']:.2f} × {report['cost']:.2f} = {report['production_cost']:.2f}

Utilidad bruta = venta bruta - costo producción
Utilidad bruta = {report['revenue']:.2f} - {report['production_cost']:.2f} = {report['gross_profit']:.2f}

Utilidad real antes ROI = utilidad bruta - gastos deducibles
Utilidad real antes ROI = {report['gross_profit']:.2f} - {report['deductible_expenses']:.2f} = {report['net_profit_before_roi']:.2f}

Apartado ROI = utilidad real antes ROI × {report['roi_percent']:.2f}%
Apartado ROI = {report['roi_recovery']:.2f}

Utilidad a repartir = utilidad real antes ROI - apartado ROI
Utilidad a repartir = {report['distributable_profit']:.2f}

Cada socio = utilidad a repartir / 2
Cada socio = {report['partner_share']:.2f}
        """.strip(),
        language="text"
    )

    if not df.empty:
        export_df = df.copy()
        export_df["Venta bruta"] = export_df["Metros"] * report["price"]
        export_df["Costo"] = export_df["Metros"] * report["cost"]
        export_df["Utilidad bruta"] = export_df["Venta bruta"] - export_df["Costo"]

        st.subheader("Detalle de ventas")
        st.dataframe(export_df, width="stretch", hide_index=True)

        st.subheader("Gastos deducibles del corte")
        if expenses_df.empty:
            st.info("No hay gastos del equipo en este rango.")
        else:
            st.dataframe(expenses_df, width="stretch", hide_index=True)

        csv = export_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Descargar CSV del corte",
            data=csv,
            file_name=f"corte_dtf_{start}_a_{end}.csv",
            mime="text/csv",
            width="stretch"
        )

        daily = export_df.copy()
        daily["Fecha"] = pd.to_datetime(daily["Fecha"])
        daily = daily.groupby("Fecha", as_index=False).agg({
            "Metros": "sum",
            "Venta bruta": "sum",
            "Costo": "sum",
            "Utilidad bruta": "sum"
        })

        fig1 = px.line(daily, x="Fecha", y="Metros", markers=True, title="Metros por día")
        st.plotly_chart(fig1, width="stretch")

        fig2 = px.bar(daily, x="Fecha", y="Utilidad bruta", title="Utilidad bruta por día")
        st.plotly_chart(fig2, width="stretch")
    else:
        st.info("No hay ventas en este rango.")


def page_roi():
    header("ROI del equipo", "Seguimiento de recuperación de la inversión.")

    investment = get_money_setting("equipment_investment", 0.0)
    roi_percent = get_money_setting("roi_recovery_percent", 20.0)
    price = get_money_setting("price_per_meter", 6.0)
    cost = get_money_setting("cost_per_meter", 2.0)

    df_all = sales_dataframe()
    if df_all.empty:
        total_meters = 0
        total_profit = 0
    else:
        total_meters = float(df_all["Metros"].sum())
        total_profit = total_meters * (price - cost)

    recovered = 0
    if investment > 0:
        recovered = min(total_profit * (roi_percent / 100.0), investment)

    remaining = max(investment - recovered, 0)
    progress = recovered / investment * 100 if investment > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metric_card("Inversión equipo", format_usd(investment))
    with c2:
        metric_card("Recuperado estimado", format_usd(recovered))
    with c3:
        metric_card("Pendiente por recuperar", format_usd(remaining))
    with c4:
        metric_card("Avance ROI", f"{progress:.2f}%")

    if investment > 0:
        st.progress(min(progress / 100, 1.0))
    else:
        st.warning("Configura la inversión del equipo en el módulo de Configuración.")

    st.subheader("Simulador rápido")
    c1, c2 = st.columns(2)
    with c1:
        avg_daily_meters = st.number_input("Promedio estimado de metros diarios", min_value=0.0, value=10.0, step=1.0)
    with c2:
        working_days = st.number_input("Días de trabajo al mes", min_value=1, value=24, step=1)

    monthly_profit = avg_daily_meters * working_days * (price - cost)
    monthly_roi = monthly_profit * (roi_percent / 100.0)
    months_to_recover = remaining / monthly_roi if monthly_roi > 0 else 0

    st.info(
        f"Con **{avg_daily_meters:.2f} m diarios** durante **{working_days} días**, "
        f"la utilidad estimada mensual sería **{format_usd(monthly_profit)}**. "
        f"El apartado mensual para ROI sería **{format_usd(monthly_roi)}**. "
        f"Tiempo estimado para recuperar lo pendiente: **{months_to_recover:.2f} meses**."
    )



def page_expenses(user):
    header("Gastos del equipo", "Registra, edita o elimina servicios técnicos, piezas, cabezales y otros costos deducibles.")

    st.info("Estos gastos se descuentan en el informe mensual antes de calcular ROI y reparto 50/50.")

    tab1, tab2, tab3 = st.tabs(["Registrar gasto", "Editar gasto", "Eliminar gasto"])

    with tab1:
        with st.form("expense_form"):
            c1, c2, c3 = st.columns(3)
            with c1:
                expense_date = st.date_input("Fecha del gasto", value=date.today(), key="expense_new_date")
                amount = st.number_input("Monto del gasto ($)", min_value=0.01, step=1.0, format="%.2f", key="expense_new_amount")
            with c2:
                category = st.selectbox("Categoría", ["Servicio técnico", "Cabezal", "Pieza/Repuesto", "Tinta/consumible especial", "Mantenimiento", "Otro"], key="expense_new_category")
                paid_by = st.selectbox("Pagado por", ["Empresa", "Rene", "Javier"], key="expense_new_paid_by")
            with c3:
                platform = st.text_input("Plataforma / método", placeholder="PayPal, Zelle, efectivo, transferencia...", key="expense_new_platform")
                reference = st.text_input("Referencia", placeholder="Nro. operación, factura, recibo...", key="expense_new_reference")

            notes = st.text_area("Descripción / notas", placeholder="Ej: cambio de damper, limpieza profunda, compra de cabezal, técnico...", key="expense_new_notes")
            submitted = st.form_submit_button("Guardar gasto", width="stretch")

        if submitted:
            db = SessionLocal()
            try:
                item = Expense(
                    expense_date=expense_date,
                    category=category,
                    amount=float(amount),
                    paid_by=paid_by,
                    platform=platform.strip(),
                    reference=reference.strip(),
                    notes=notes.strip(),
                    created_by=user["username"]
                )
                db.add(item)
                db.commit()
                audit_log(user["username"], "Gastos", "crear", item.id, after={"fecha": expense_date, "categoria": category, "monto": amount, "pagado_por": paid_by})
                st.success("Gasto guardado correctamente.")
                st.rerun()
            finally:
                db.close()

    df_all = expenses_dataframe()

    with tab2:
        if df_all.empty:
            st.info("No hay gastos para editar.")
        else:
            options = {
                f"ID {int(row['ID'])} · {row['Fecha']} · {row['Categoría']} · {format_usd(float(row['Monto']))}": int(row["ID"])
                for _, row in df_all.iterrows()
            }
            label = st.selectbox("Selecciona gasto", list(options.keys()), key="edit_expense_select")
            expense_id = options[label]
            exp = get_expense_by_id(expense_id)
            if exp:
                with st.form(f"edit_expense_form_{expense_id}"):
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        edit_date = st.date_input("Fecha", value=exp["expense_date"], key=f"expense_edit_date_{expense_id}")
                        edit_amount = st.number_input("Monto ($)", min_value=0.01, value=exp["amount"], step=1.0, format="%.2f", key=f"expense_edit_amount_{expense_id}")
                    with c2:
                        cats = ["Servicio técnico", "Cabezal", "Pieza/Repuesto", "Tinta/consumible especial", "Mantenimiento", "Otro"]
                        edit_category = st.selectbox("Categoría", cats, index=cats.index(exp["category"]) if exp["category"] in cats else 0, key=f"expense_edit_category_{expense_id}")
                        payers = ["Empresa", "Rene", "Javier"]
                        edit_paid_by = st.selectbox("Pagado por", payers, index=payers.index(exp["paid_by"]) if exp["paid_by"] in payers else 0, key=f"expense_edit_paid_by_{expense_id}")
                    with c3:
                        edit_platform = st.text_input("Plataforma / método", value=exp["platform"], key=f"expense_edit_platform_{expense_id}")
                        edit_reference = st.text_input("Referencia", value=exp["reference"], key=f"expense_edit_reference_{expense_id}")
                    edit_notes = st.text_area("Descripción / notas", value=exp["notes"], key=f"expense_edit_notes_{expense_id}")
                    save = st.form_submit_button("Guardar cambios", width="stretch")
                if save:
                    db = SessionLocal()
                    try:
                        e = db.query(Expense).filter(Expense.id == int(expense_id)).first()
                        before = {"fecha": e.expense_date, "categoria": e.category, "monto": e.amount, "pagado_por": e.paid_by, "referencia": e.reference}
                        e.expense_date = edit_date
                        e.category = edit_category
                        e.amount = float(edit_amount)
                        e.paid_by = edit_paid_by
                        e.platform = edit_platform.strip()
                        e.reference = edit_reference.strip()
                        e.notes = edit_notes.strip()
                        db.commit()
                        audit_log(user["username"], "Gastos", "editar", expense_id, before=before, after={"fecha": edit_date, "categoria": edit_category, "monto": edit_amount, "pagado_por": edit_paid_by, "referencia": edit_reference})
                        st.success("Gasto actualizado.")
                        st.rerun()
                    finally:
                        db.close()

    with tab3:
        if user["role"] != "admin":
            st.warning("Solo un administrador puede eliminar gastos.")
        elif df_all.empty:
            st.info("No hay gastos para eliminar.")
        else:
            options = {
                f"ID {int(row['ID'])} · {row['Fecha']} · {row['Categoría']} · {format_usd(float(row['Monto']))}": int(row["ID"])
                for _, row in df_all.iterrows()
            }
            label = st.selectbox("Selecciona gasto a eliminar", list(options.keys()), key="delete_expense_select")
            expense_id = options[label]
            reason = st.text_area("Motivo de eliminación", key="delete_expense_reason")
            confirm = st.checkbox("Confirmo que quiero eliminar este gasto", key="delete_expense_confirm")
            if st.button("Eliminar gasto", width="stretch", type="primary"):
                if not confirm or not reason.strip():
                    st.error("Debes confirmar y escribir un motivo.")
                else:
                    db = SessionLocal()
                    try:
                        e = db.query(Expense).filter(Expense.id == int(expense_id)).first()
                        if e:
                            before = {"fecha": e.expense_date, "categoria": e.category, "monto": e.amount, "pagado_por": e.paid_by, "referencia": e.reference}
                            db.delete(e)
                            db.commit()
                            audit_log(user["username"], "Gastos", "eliminar", expense_id, before=before, reason=reason.strip())
                            st.success("Gasto eliminado.")
                            st.rerun()
                    finally:
                        db.close()

    st.subheader("Historial de gastos")
    df = expenses_dataframe()
    if df.empty:
        st.info("Todavía no hay gastos registrados.")
    else:
        st.dataframe(df.head(50), width="stretch", hide_index=True)


def page_javier_account(user):
    header("Cuenta Javier", "Control de deuda acumulada, abonos realizados y cortes mensuales pendientes.")

    summary = javier_account_summary()

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metric_card("Deuda acumulada inicial", format_usd(summary["opening"]))
    with c2:
        metric_card("Cortes acumulados", format_usd(summary["monthly_credits"]))
    with c3:
        metric_card("Abonos pagados", format_usd(summary["payments"]))
    with c4:
        metric_card("Saldo actual con Javier", format_usd(summary["balance"]))

    st.caption("Saldo actual = deuda inicial + cortes cerrados que le corresponden a Javier - abonos pagados.")

    try:
        pdf_bytes = build_javier_account_pdf()
        st.download_button(
            "Descargar estado de cuenta PDF",
            data=pdf_bytes,
            file_name=f"estado_cuenta_javier_{date.today().isoformat()}.pdf",
            mime="application/pdf",
            width="stretch"
        )
    except Exception as e:
        st.warning(f"No se pudo generar el PDF de Cuenta Javier en este momento: {e}")


    st.subheader("Estado de cuenta tipo banco")
    statement_df = build_javier_statement_dataframe()
    if statement_df.empty:
        st.info("Todavía no hay movimientos en la cuenta de Javier.")
    else:
        show_df = statement_df.copy()
        for col in ["Debe", "Haber", "Saldo"]:
            show_df[col] = show_df[col].apply(format_usd)
        st.dataframe(show_df, width="stretch", hide_index=True)

        csv_statement = statement_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Descargar movimientos CSV",
            data=csv_statement,
            file_name=f"movimientos_javier_{date.today().isoformat()}.csv",
            mime="text/csv",
            width="stretch"
        )


    tab1, tab2, tab3 = st.tabs(["Registrar abono", "Editar abono", "Eliminar abono"])

    with tab1:
        st.subheader("Registrar abono a Javier")
        with st.form("payment_form"):
            c1, c2, c3 = st.columns(3)
            with c1:
                payment_date = st.date_input("Fecha del abono", value=date.today(), key="new_payment_date")
                amount = st.number_input("Monto abonado ($)", min_value=0.01, step=1.0, format="%.2f", key="new_payment_amount")
            with c2:
                platform = st.selectbox("Plataforma", ["PayPal", "Zelle", "Binance", "Zinli", "Efectivo", "Transferencia", "Otro"], key="new_payment_platform")
                reference = st.text_input("Referencia", key="new_payment_reference")
            with c3:
                notes = st.text_area("Notas", placeholder="Ej: abono parcial deuda vieja, pago corte marzo...", key="new_payment_notes")

            submitted = st.form_submit_button("Guardar abono", width="stretch")

        if submitted:
            db = SessionLocal()
            try:
                p = Payment(
                    payment_date=payment_date,
                    partner="Javier",
                    amount=float(amount),
                    platform=platform,
                    reference=reference.strip(),
                    notes=notes.strip(),
                    created_by=user["username"]
                )
                db.add(p)
                db.commit()
                audit_log(user["username"], "Cuenta Javier", "crear abono", p.id, after={"fecha": payment_date, "monto": amount, "plataforma": platform, "referencia": reference})
                st.success("Abono registrado correctamente.")
                st.rerun()
            finally:
                db.close()

    payments = payments_dataframe("Javier")

    with tab2:
        st.subheader("Editar abono existente")

        # Recargamos la lista justo antes de editar para tener la data más fresca.
        payments_edit = payments_dataframe("Javier")

        if payments_edit.empty:
            st.info("Todavía no hay abonos para editar.")
        else:
            options = {
                f"ID {int(row['ID'])} · {row['Fecha']} · {format_usd(float(row['Monto']))} · {row['Plataforma']} · Ref: {row['Referencia']}": int(row["ID"])
                for _, row in payments_edit.iterrows()
            }

            selected_label = st.selectbox("Selecciona el abono a editar", list(options.keys()), key="edit_payment_select")
            selected_id = options[selected_label]
            selected_payment = get_payment_by_id(selected_id)

            if selected_payment:
                st.caption(
                    f"Editando abono ID {selected_payment['id']} · "
                    f"{selected_payment['payment_date']} · {format_usd(selected_payment['amount'])}"
                )

                # Importante:
                # Las keys incluyen el ID del abono para que Streamlit refresque automáticamente
                # los valores al seleccionar otro registro.
                dynamic_key = f"payment_{selected_id}"

                with st.form(f"edit_payment_form_{selected_id}"):
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        edit_date = st.date_input(
                            "Fecha del abono",
                            value=selected_payment["payment_date"],
                            key=f"edit_payment_date_{dynamic_key}"
                        )
                        edit_amount = st.number_input(
                            "Monto abonado ($)",
                            min_value=0.01,
                            value=float(selected_payment["amount"]),
                            step=1.0,
                            format="%.2f",
                            key=f"edit_payment_amount_{dynamic_key}"
                        )
                    with c2:
                        platforms = ["PayPal", "Zelle", "Binance", "Zinli", "Efectivo", "Transferencia", "Otro"]
                        current_platform = selected_payment["platform"] if selected_payment["platform"] in platforms else "Otro"
                        edit_platform = st.selectbox(
                            "Plataforma",
                            platforms,
                            index=platforms.index(current_platform),
                            key=f"edit_payment_platform_{dynamic_key}"
                        )
                        edit_reference = st.text_input(
                            "Referencia",
                            value=selected_payment["reference"],
                            key=f"edit_payment_reference_{dynamic_key}"
                        )
                    with c3:
                        edit_notes = st.text_area(
                            "Notas",
                            value=selected_payment["notes"],
                            key=f"edit_payment_notes_{dynamic_key}"
                        )

                    save_edit = st.form_submit_button("Guardar cambios del abono", width="stretch")

                if save_edit:
                    db = SessionLocal()
                    try:
                        p = db.query(Payment).filter(Payment.id == int(selected_id)).first()
                        if p:
                            before = {"fecha": p.payment_date, "monto": p.amount, "plataforma": p.platform, "referencia": p.reference, "notas": p.notes}
                            p.payment_date = edit_date
                            p.amount = float(edit_amount)
                            p.platform = edit_platform
                            p.reference = edit_reference.strip()
                            p.notes = edit_notes.strip()
                            db.commit()
                            audit_log(user["username"], "Cuenta Javier", "editar abono", selected_id, before=before, after={"fecha": edit_date, "monto": edit_amount, "plataforma": edit_platform, "referencia": edit_reference, "notas": edit_notes})
                            st.success("Abono actualizado correctamente.")
                            st.rerun()
                        else:
                            st.error("No se encontró el abono seleccionado.")
                    finally:
                        db.close()

    with tab3:
        st.subheader("Eliminar abono")

        if payments.empty:
            st.info("Todavía no hay abonos para eliminar.")
        else:
            delete_options = {
                f"ID {int(row['ID'])} · {row['Fecha']} · {format_usd(float(row['Monto']))} · {row['Plataforma']} · Ref: {row['Referencia']}": int(row["ID"])
                for _, row in payments.iterrows()
            }

            delete_label = st.selectbox("Selecciona el abono a eliminar", list(delete_options.keys()), key="delete_payment_select")
            delete_id = delete_options[delete_label]

            st.warning("Eliminar un abono aumenta nuevamente el saldo pendiente con Javier. Usa esta opción solo si el registro fue cargado por error.")
            confirm_delete = st.checkbox("Confirmo que quiero eliminar este abono", key="confirm_delete_payment")

            if st.button("Eliminar abono seleccionado", width="stretch", type="primary"):
                if not confirm_delete:
                    st.error("Debes marcar la confirmación antes de eliminar.")
                else:
                    db = SessionLocal()
                    try:
                        p = db.query(Payment).filter(Payment.id == int(delete_id)).first()
                        if p:
                            before = {"fecha": p.payment_date, "monto": p.amount, "plataforma": p.platform, "referencia": p.reference, "notas": p.notes}
                            db.delete(p)
                            db.commit()
                            audit_log(user["username"], "Cuenta Javier", "eliminar abono", delete_id, before=before, reason="Eliminado desde Cuenta Javier")
                            st.success("Abono eliminado correctamente.")
                            st.rerun()
                        else:
                            st.error("No se encontró el abono seleccionado.")
                    finally:
                        db.close()

    st.subheader("Cortes mensuales cargados a Javier")
    closes = closes_dataframe()
    if closes.empty:
        st.info("Todavía no hay cierres mensuales registrados.")
    else:
        st.dataframe(closes, width="stretch", hide_index=True)

    st.subheader("Abonos realizados")
    payments = payments_dataframe("Javier")
    if payments.empty:
        st.info("Todavía no hay abonos registrados.")
    else:
        st.dataframe(payments, width="stretch", hide_index=True)


def page_monthly_close(user):
    header("Cierre mensual", "Cierra un mes y carga automáticamente el monto correspondiente a la cuenta de Javier.")

    today = date.today()
    year = st.number_input("Año", min_value=2020, max_value=2100, value=today.year, step=1)
    month = st.number_input("Mes", min_value=1, max_value=12, value=today.month, step=1)

    start = date(int(year), int(month), 1)
    if int(month) == 12:
        end = date(int(year) + 1, 1, 1) - pd.Timedelta(days=1)
    else:
        end = date(int(year), int(month) + 1, 1) - pd.Timedelta(days=1)
    end = end.date() if hasattr(end, "date") else end

    period_key = f"{int(year):04d}-{int(month):02d}"

    df = sales_dataframe(start, end)
    expenses_df = expenses_dataframe(start, end)
    report = calculate_report(df, expenses_df)

    st.subheader(f"Previsualización del cierre {period_key}")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metric_card("Metros", f"{report['total_meters']:,.2f} m")
    with c2:
        metric_card("Venta bruta", format_usd(report["revenue"]))
    with c3:
        metric_card("Gastos deducibles", format_usd(report["deductible_expenses"]))
    with c4:
        metric_card("Le toca a Javier", format_usd(report["partner_share"]))

    st.write(
        f"Al cerrar este mes, se sumará **{format_usd(report['partner_share'])}** "
        f"a la cuenta de Javier como monto pendiente de pago del corte."
    )

    monthly_pdf = build_monthly_close_pdf(period_key, start, end, report, expenses_df, df, javier_account_summary())
    st.download_button(
        "Descargar PDF preliminar del cierre",
        data=monthly_pdf,
        file_name=f"cierre_mensual_dtf_{period_key}.pdf",
        mime="application/pdf",
        width="stretch"
    )

    notes = st.text_area("Notas del cierre", placeholder="Ej: corte mensual revisado con Javier, pendiente abonar por PayPal...")

    db = SessionLocal()
    try:
        exists = db.query(MonthlyClose).filter(MonthlyClose.period_key == period_key).first()
    finally:
        db.close()

    if exists:
        st.warning("Este mes ya fue cerrado. Para evitar duplicados, no se puede cerrar dos veces desde aquí.")
    else:
        if st.button("Cerrar mes y cargar monto a Javier", width="stretch"):
            db = SessionLocal()
            try:
                close = MonthlyClose(
                    period_key=period_key,
                    start_date=start,
                    end_date=end,
                    total_meters=report["total_meters"],
                    revenue=report["revenue"],
                    production_cost=report["production_cost"],
                    deductible_expenses=report["deductible_expenses"],
                    net_profit_before_roi=report["net_profit_before_roi"],
                    roi_recovery=report["roi_recovery"],
                    distributable_profit=report["distributable_profit"],
                    partner_share=report["partner_share"],
                    javier_credit=report["partner_share"],
                    rene_credit=report["partner_share"],
                    notes=notes.strip(),
                    created_by=user["username"]
                )
                db.add(close)
                db.commit()
                st.success("Cierre mensual guardado y monto cargado a la cuenta de Javier.")
            except IntegrityError:
                db.rollback()
                st.error("Este periodo ya fue cerrado.")
            finally:
                db.close()




def page_audit():
    header("Auditoría", "Historial de cambios importantes del sistema.")

    st.info("Aquí se registran creaciones, ediciones y eliminaciones de ventas, gastos y abonos.")
    df = audit_dataframe()
    if df.empty:
        st.info("Todavía no hay movimientos de auditoría.")
    else:
        st.dataframe(df, width="stretch", hide_index=True)
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Descargar auditoría CSV",
            data=csv,
            file_name=f"auditoria_dtf_{date.today().isoformat()}.csv",
            mime="text/csv",
            width="stretch"
        )


def page_users():
    header("Usuarios", "Crea usuarios para socios, administradores y empleadas.")

    st.subheader("Crear usuario")
    with st.form("create_user"):
        c1, c2 = st.columns(2)
        with c1:
            username = st.text_input("Usuario")
            name = st.text_input("Nombre")
        with c2:
            password = st.text_input("Contraseña", type="password")
            role = st.selectbox("Rol", ["admin", "socio", "empleada"])

        submit = st.form_submit_button("Crear usuario", width="stretch")

    if submit:
        if not username.strip() or not name.strip() or not password:
            st.error("Completa usuario, nombre y contraseña.")
        else:
            db = SessionLocal()
            try:
                user = User(
                    username=username.strip(),
                    name=name.strip(),
                    password_hash=hash_password(password),
                    role=role,
                    active=True
                )
                db.add(user)
                db.commit()
                st.success("Usuario creado correctamente.")
            except IntegrityError:
                db.rollback()
                st.error("Ese usuario ya existe.")
            finally:
                db.close()

    st.subheader("Usuarios existentes")
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.id.asc()).all()
        data = [{
            "ID": u.id,
            "Usuario": u.username,
            "Nombre": u.name,
            "Rol": u.role,
            "Activo": u.active,
            "Creado": u.created_at
        } for u in users]
        st.dataframe(pd.DataFrame(data), width="stretch", hide_index=True)
    finally:
        db.close()

    st.subheader("Cambiar clave / activar / desactivar")
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.username.asc()).all()
        choices = {f"{u.username} · {u.name}": u.id for u in users}
    finally:
        db.close()

    if choices:
        selected = st.selectbox("Selecciona usuario", list(choices.keys()))
        new_pass = st.text_input("Nueva contraseña", type="password")
        c1, c2, c3 = st.columns(3)
        if c1.button("Cambiar contraseña", width="stretch"):
            if new_pass:
                db = SessionLocal()
                try:
                    u = db.query(User).filter(User.id == choices[selected]).first()
                    u.password_hash = hash_password(new_pass)
                    db.commit()
                    st.success("Contraseña actualizada.")
                finally:
                    db.close()
            else:
                st.warning("Escribe una nueva contraseña.")

        if c2.button("Activar", width="stretch"):
            db = SessionLocal()
            try:
                u = db.query(User).filter(User.id == choices[selected]).first()
                u.active = True
                db.commit()
                st.success("Usuario activado.")
            finally:
                db.close()

        if c3.button("Desactivar", width="stretch"):
            db = SessionLocal()
            try:
                u = db.query(User).filter(User.id == choices[selected]).first()
                u.active = False
                db.commit()
                st.success("Usuario desactivado.")
            finally:
                db.close()


def page_settings():
    header("Configuración", "Ajusta precios, costos, socios y recuperación del equipo.")

    with st.form("settings_form"):
        c1, c2 = st.columns(2)
        with c1:
            price = st.number_input("Precio de venta por metro DTF ($)", min_value=0.0, value=get_money_setting("price_per_meter", 6.0), step=0.10)
            cost = st.number_input("Costo de producción por metro ($)", min_value=0.0, value=get_money_setting("cost_per_meter", 2.0), step=0.10)
            investment = st.number_input("Inversión total del equipo DTF ($)", min_value=0.0, value=get_money_setting("equipment_investment", 0.0), step=10.0)
        with c2:
            roi_percent = st.number_input(
                "% de utilidad bruta que se aparta para recuperar equipo",
                min_value=0.0,
                max_value=100.0,
                value=get_money_setting("roi_recovery_percent", 20.0),
                step=1.0
            )
            partner_1 = st.text_input("Nombre socio 1", value=get_setting("partner_1_name", "Rene"))
            partner_2 = st.text_input("Nombre socio 2", value=get_setting("partner_2_name", "Javier"))
            opening_debt = st.number_input("Deuda acumulada inicial con Javier ($)", min_value=0.0, value=get_money_setting("opening_debt_javier", 0.0), step=10.0)

        submitted = st.form_submit_button("Guardar configuración", width="stretch")

    if submitted:
        set_setting("price_per_meter", price)
        set_setting("cost_per_meter", cost)
        set_setting("equipment_investment", investment)
        set_setting("roi_recovery_percent", roi_percent)
        set_setting("partner_1_name", partner_1.strip() or "Rene")
        set_setting("partner_2_name", partner_2.strip() or "Javier")
        set_setting("opening_debt_javier", opening_debt)
        st.success("Configuración guardada.")


def page_database():
    header("Base de datos", "Herramientas administrativas.")

    st.warning("Usa estas opciones con cuidado.")

    df = sales_dataframe()
    st.subheader("Ventas registradas")
    if df.empty:
        st.info("No hay ventas.")
    else:
        st.dataframe(df, width="stretch", hide_index=True)

        sale_id = st.number_input("ID de venta a eliminar", min_value=1, step=1)
        confirm = st.checkbox("Confirmo que quiero eliminar esta venta")
        if st.button("Eliminar venta", width="stretch"):
            if confirm:
                db = SessionLocal()
                try:
                    sale = db.query(Sale).filter(Sale.id == int(sale_id)).first()
                    if sale:
                        db.delete(sale)
                        db.commit()
                        st.success("Venta eliminada.")
                    else:
                        st.error("No existe una venta con ese ID.")
                finally:
                    db.close()
            else:
                st.warning("Marca la confirmación antes de eliminar.")


# =========================================================
# MAIN
# =========================================================

def main():
    init_db()
    user = require_login()
    page = sidebar(user)

    if page == "Dashboard":
        page_dashboard()
    elif page == "Cargar venta diaria":
        page_load_sale(user)
    elif page == "Gastos del equipo":
        page_expenses(user)
    elif page == "Cuenta Javier":
        page_javier_account(user)
    elif page == "Informe mensual":
        page_monthly_report()
    elif page == "ROI del equipo":
        page_roi()
    elif page == "Cierre mensual" and user["role"] == "admin":
        page_monthly_close(user)
    elif page == "Auditoría" and user["role"] == "admin":
        page_audit()
    elif page == "Usuarios" and user["role"] == "admin":
        page_users()
    elif page == "Configuración" and user["role"] == "admin":
        page_settings()
    elif page == "Base de datos" and user["role"] == "admin":
        page_database()
    else:
        st.error("No tienes permisos para ver este módulo.")


if __name__ == "__main__":
    main()
